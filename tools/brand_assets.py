#!/usr/bin/env python3
"""Resolve unchanged first-party brand assets from the local cache."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import shutil
import struct
import sys
import urllib.request
from urllib.parse import urlparse
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "research/brand-assets/manifest.json"
EVIDENCE_ROOT = ROOT / "research/evidence/brand-assets"
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ALIASES = {
    "openai": "openai", "codex": "codex", "claude code": "claude-code",
    "cloud code": "claude-code", "claudecode": "claude-code",
    "claude": "claude", "cloudflare": "cloudflare", "腾讯优图": "tencent",
    "tencent youtu": "tencent", "deepseek": "deepseek", "灵光": "lingguang",
    "lingguang": "lingguang", "stepfun": "stepfun", "阶跃星辰": "stepfun",
    "elevenlabs": "elevenlabs", "eleven labs": "elevenlabs", "qoder": "qoder",
    "nous portal": "nous-portal", "nous": "nous",
}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dimensions(data: bytes, suffix: str):
    """Read raster dimensions with stdlib parsers, or parse SVG geometry."""
    suffix = suffix.lower()
    if suffix == ".svg":
        root = ElementTree.fromstring(data)
        def number(value):
            match = re.match(r"\s*([0-9]+(?:\.[0-9]+)?)", value or "")
            return float(match.group(1)) if match else None
        width, height = number(root.attrib.get("width")), number(root.attrib.get("height"))
        viewbox = root.attrib.get("viewBox", "").replace(",", " ").split()
        if (not width or not height) and len(viewbox) == 4:
            width, height = float(viewbox[2]), float(viewbox[3])
        if not width or not height:
            raise ValueError("SVG has no usable width/height or viewBox")
        return width, height
    if suffix == ".png":
        if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
            raise ValueError("invalid PNG signature or IHDR")
        return struct.unpack(">II", data[16:24])
    if suffix in (".jpg", ".jpeg"):
        if len(data) < 4 or data[:2] != b"\xff\xd8":
            raise ValueError("invalid JPEG signature")
        i = 2
        sof = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
        while i < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            while i < len(data) and data[i] == 0xFF:
                i += 1
            if i >= len(data):
                break
            marker = data[i]
            i += 1
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7 or marker == 0x01:
                continue
            if i + 2 > len(data):
                break
            seglen = struct.unpack(">H", data[i:i+2])[0]
            if seglen < 2 or i + seglen > len(data):
                raise ValueError("invalid JPEG segment length")
            if marker in sof:
                if seglen < 7:
                    raise ValueError("invalid JPEG frame header")
                height, width = struct.unpack(">HH", data[i+3:i+7])
                return width, height
            i += seglen
        raise ValueError("JPEG frame dimensions not found")
    if suffix == ".webp":
        if len(data) < 20 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
            raise ValueError("invalid WebP RIFF header")
        kind, chunk = data[12:16], data[20:]
        if kind == b"VP8X" and len(chunk) >= 10:
            return 1 + int.from_bytes(chunk[4:7], "little"), 1 + int.from_bytes(chunk[7:10], "little")
        if kind == b"VP8L" and len(chunk) >= 5 and chunk[0] == 0x2F:
            b1, b2, b3, b4 = chunk[1:5]
            return 1 + b1 + ((b2 & 0x3F) << 8), 1 + (b2 >> 6) + (b3 << 2) + ((b4 & 0x0F) << 10)
        if kind == b"VP8 " and len(chunk) >= 10 and chunk[3:6] == b"\x9d\x01\x2a":
            return int.from_bytes(chunk[6:8], "little") & 0x3FFF, int.from_bytes(chunk[8:10], "little") & 0x3FFF
        raise ValueError("unsupported or invalid WebP image chunk")
    raise ValueError(f"unsupported image extension: {suffix}")


def measured_asset(entry):
    file_value = entry.get("file")
    if not file_value:
        raise ValueError(f"{entry.get('id')}: manifest entry has no file")
    source = (ROOT / file_value).resolve()
    source.relative_to((ROOT / "research/brand-assets").resolve())
    if not source.is_file():
        raise ValueError(f"{entry.get('id')}: missing asset {file_value}")
    actual_sha = digest(source)
    if actual_sha != entry.get("sha256"):
        raise ValueError(f"{entry.get('id')}: SHA-256 mismatch for {file_value}")
    width, height = dimensions(source.read_bytes(), source.suffix)
    for key, actual in (("width", width), ("height", height)):
        declared = entry.get(key)
        if declared is not None and not math.isclose(float(declared), float(actual), rel_tol=0, abs_tol=0.02):
            raise ValueError(f"{entry.get('id')}: declared {key}={declared}, measured {actual}")
    resolution = entry.get("resolution", "")
    declared_dims = re.match(r"\s*([0-9]+(?:\.[0-9]+)?)\s*[×x]\s*([0-9]+(?:\.[0-9]+)?)", resolution)
    if declared_dims and (not math.isclose(float(declared_dims.group(1)), float(width), abs_tol=0.02)
                          or not math.isclose(float(declared_dims.group(2)), float(height), abs_tol=0.02)):
        raise ValueError(f"{entry.get('id')}: resolution metadata {resolution!r} differs from measured {width}×{height}")
    return source, width, height


def manifest_assets(manifest):
    for entry in manifest.get("assets", []):
        yield entry, None
        for variant in entry.get("variants", []):
            yield variant, entry


def verify_and_copy_assets(manifest):
    verified = []
    copied, reused = [], []
    # Validate the entire master library before making any evidence copies.
    for entry, parent in manifest_assets(manifest):
        source, width, height = measured_asset(entry)
        verified.append((entry, parent, source, width, height))
    for entry, parent, source, width, height in verified:
        relative = source.relative_to(ROOT / "research/brand-assets")
        destination = EVIDENCE_ROOT / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if digest(destination) != entry["sha256"]:
                raise ValueError(f"refusing to overwrite different evidence copy: {destination}")
            reused.append(str(destination.relative_to(ROOT)))
        else:
            shutil.copy2(source, destination)
            copied.append(str(destination.relative_to(ROOT)))
    return verified, copied, reused


def evidence_record(entry, width=None, height=None):
    record = copy.deepcopy(entry)
    source_file = record.get("file")
    if source_file:
        rel = (ROOT / source_file).resolve().relative_to((ROOT / "research/brand-assets").resolve())
        record["file"] = (Path("research/evidence/brand-assets") / rel).as_posix()
        if record.get("path"):
            record["path"] = "/brand-assets/" + rel.as_posix()
    if width is not None:
        record["width"], record["height"] = width, height
    if record.get("variants"):
        for variant in record["variants"]:
            rel = (ROOT / variant["file"]).resolve().relative_to((ROOT / "research/brand-assets").resolve())
            variant["file"] = (Path("research/evidence/brand-assets") / rel).as_posix()
            if variant.get("path"):
                variant["path"] = "/brand-assets/" + rel.as_posix()
            checked = next((v for v in _VERIFIED if v[0].get("file") == str(Path("research/brand-assets") / rel)), None)
            if checked:
                variant["width"], variant["height"] = checked[3], checked[4]
    return record


_VERIFIED = []


def sync_report(report_path):
    report_path = Path(report_path).resolve()
    report_path.relative_to(ROOT.resolve())
    report = json.loads(report_path.read_text())
    manifest = json.loads(MANIFEST.read_text())
    verified, copied, reused = verify_and_copy_assets(manifest)
    global _VERIFIED
    _VERIFIED = verified
    by_id = {}
    for entry, parent, source, width, height in verified:
        if parent is None:
            by_id[entry["id"]] = (entry, width, height)
    pending = []
    synced = []
    updated = []
    for current in report.get("brand_assets", []):
        key = current.get("id")
        match = by_id.get(key)
        if not match:
            # Allow old entries to be recognized by file or digest when id is absent.
            for candidate_id, candidate in by_id.items():
                candidate_entry = candidate[0]
                if current.get("sha256") == candidate_entry.get("sha256") or current.get("file") == candidate_entry.get("file"):
                    key, match = candidate_id, candidate
                    break
        if not match:
            record = copy.deepcopy(current)
            record["cache_status"] = "pending"
            record["cache_note"] = "No matching first-party master manifest record; verify official source page and resource URL before adding."
            pending.append(record.get("id", record.get("name", "unknown")))
            updated.append(record)
            continue
        master, width, height = match
        display_name = current.get("name") or master.get("name") or key
        record = evidence_record(master, width, height)
        record["original_asset_name"] = current.get("original_asset_name") or master.get("name") or display_name
        record["name"] = display_name
        record["cache_status"] = "cache_hit"
        updated.append(record)
        synced.append(key)
    # Newly cached official assets become available to the next episode automatically.
    present_ids = {entry.get('id') for entry in updated}
    for key, (master, width, height) in by_id.items():
        if key in present_ids:
            continue
        record = evidence_record(master, width, height)
        record['original_asset_name'] = master.get('name') or key
        record['name'] = master.get('display_name') or master.get('name') or key
        record['cache_status'] = 'cache_hit'
        updated.append(record)
        synced.append(key)
    report["brand_assets"] = updated
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    receipt = {"status": "completed_with_pending" if pending else "completed", "synced_at_utc": now(),
               "report": str(report_path.relative_to(ROOT)), "master_manifest": str(MANIFEST.relative_to(ROOT)),
               "verified_assets": len(verified), "copied_files": copied, "reused_files": reused,
               "report_asset_ids_synced": synced, "pending_report_assets": pending,
               "evidence_root": str(EVIDENCE_ROOT.relative_to(ROOT)),
               "note": "No network fetch was performed. Evidence copies are byte-for-byte copies of verified master files."}
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    public_manifest = copy.deepcopy(manifest)
    public_manifest['assets'] = [entry for entry in updated if entry.get('cache_status') == 'cache_hit']
    (EVIDENCE_ROOT / 'manifest.json').write_text(json.dumps(public_manifest, ensure_ascii=False, indent=2) + '\n')
    (EVIDENCE_ROOT / "cache-sync-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(receipt, ensure_ascii=False))
    return 0


def all_entries(manifest):
    for entry in manifest["assets"]:
        yield entry
        for variant in entry.get("variants", []):
            # Variants inherit the parent brand id while keeping their own paths.
            yield {**variant, "id": entry["id"]}


def dims(data: bytes, suffix: str):
    return dimensions(data, suffix)


def result(entry, status):
    return {"id": entry["id"], "path": entry["path"], "file": entry["file"], "cache_status": status,
            "kind": entry.get("kind", entry.get("asset_type")), "width": entry.get("width"),
            "height": entry.get("height"), "variants": entry.get("variants", [])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list cached brand assets")
    p = sub.add_parser("resolve", help="resolve a local asset; fetch only with explicit first-party URLs")
    p.add_argument("brand")
    p.add_argument("--source-url", help="user-verified official resource URL")
    p.add_argument("--source-page", help="official page documenting the resource")
    p.add_argument("--refresh", action="store_true", help="explicitly fetch a new immutable variant")
    p.add_argument("--kind", help="asset category, e.g. official-logo, app-icon, favicon, avatar")
    p.add_argument("--name", help="display name for a newly cached source")
    sync = sub.add_parser("sync", help="verify and sync local manifest assets into a report")
    sync.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text())
    if args.command == "sync":
        return sync_report(args.report)
    if args.command == "list":
        print(json.dumps([result(e, "cache_hit" if (ROOT / e["file"]).is_file() and digest(ROOT / e["file"]) == e["sha256"] else "invalid") for e in all_entries(manifest)], ensure_ascii=False, indent=2))
        return 0
    normalized = args.brand.strip().casefold()
    bid = ALIASES.get(normalized, re.sub(r"\s+", "-", normalized))
    if not ID_RE.fullmatch(bid):
        raise ValueError("invalid brand id; use lowercase letters, digits and single hyphens")
    matches = [e for e in all_entries(manifest) if e["id"] == bid]
    for e in matches:
        f = ROOT / e["file"]
        if f.is_file() and digest(f) == e["sha256"] and not args.refresh:
            print(json.dumps(result(e, "cache_hit"), ensure_ascii=False))
            return 0
    if not args.source_url or not args.source_page:
        print(json.dumps({"id": bid, "cache_status": "pending", "reason": "no valid cached asset; pass verified --source-url and --source-page"}, ensure_ascii=False))
        return 2
    # Never infer source URLs from brand names. A refresh gets a new immutable filename.
    req = urllib.request.Request(args.source_url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"})
    with urllib.request.urlopen(req, timeout=30) as response:
        data = response.read(20 * 1024 * 1024 + 1)
        mime = response.headers.get_content_type()
        final_url = response.geturl()
    if len(data) > 20 * 1024 * 1024:
        raise ValueError("asset exceeds 20 MiB limit")
    suffix = Path(urlparse(final_url).path).suffix.lower()
    if not suffix:
        suffix = ".svg" if "svg" in mime else ".png" if "png" in mime else ".jpg" if "jpeg" in mime else ""
    if suffix not in (".svg", ".png", ".jpg", ".jpeg", ".webp"):
        raise ValueError(f"unsupported MIME/type: {mime}")
    allowed_mimes = {".svg": {"image/svg+xml", "text/xml", "application/xml"},
                     ".png": {"image/png"}, ".jpg": {"image/jpeg"},
                     ".jpeg": {"image/jpeg"}, ".webp": {"image/webp"}}
    if mime not in allowed_mimes[suffix]:
        raise ValueError(f"MIME {mime} does not match {suffix}")
    width, height = dims(data, suffix)
    sha = hashlib.sha256(data).hexdigest()
    stem = bid + ("-refresh-" + sha[:10] if args.refresh or matches else "")
    filename = stem + suffix
    out = ROOT / "research/brand-assets/assets" / filename
    if out.exists():
        raise FileExistsError(f"refusing to overwrite existing asset: {out}")
    out.write_bytes(data)
    entry = {"id": bid, "name": args.name or bid, "path": "/brand-assets/assets/" + filename,
             "file": "research/brand-assets/assets/" + filename, "source_page_url": args.source_page,
             "source_url": args.source_page, "resource_url": args.source_url, "first_cached_at": now(),
             "last_validated_at": now(), "downloaded_at_utc": now(), "sha256": sha,
             "kind": args.kind or "official-logo", "asset_type": args.kind or "official-logo",
             "width": width, "height": height, "resolution": f"{width:g}×{height:g} {suffix[1:].upper()}",
             "source_note": "Resource URL explicitly supplied by the caller; page provenance retained.",
             "usage_notes": "Unchanged first-party resource. Follow the source brand terms; no general trademark license is implied."}
    manifest["assets"].append(entry)
    manifest["updated_at_utc"] = now()
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result(entry, "downloaded"), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"cache_status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
