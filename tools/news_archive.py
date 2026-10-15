"""Build a local SQLite newsroom index and a path-safe public JSON export.

Source reports, batch manifests, and production-state remain the canonical data.
This command only rebuilds derived indexes; it never edits those source records.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from edition_contract import navigation_story_order


DEFAULT_ROOT = Path(__file__).resolve().parents[1]


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE editions (
  id TEXT PRIMARY KEY, date TEXT NOT NULL, kind TEXT NOT NULL,
  title TEXT NOT NULL, headline TEXT, summary TEXT, headline_source_story_id TEXT,
  scheduled_at TEXT, bulletin_url TEXT, video_story_count INTEGER,
  window_start TEXT, window_end TEXT, url TEXT, video_url TEXT,
  poster_url TEXT, video_status TEXT NOT NULL,
  coverage_status TEXT NOT NULL, status TEXT NOT NULL,
  report_path TEXT, source_fingerprint TEXT
);
CREATE TABLE stories (
  id TEXT PRIMARY KEY, event_id TEXT, content_version TEXT,
  title TEXT NOT NULL, summary TEXT, url TEXT, published_at TEXT,
  sources_json TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'reviewed'
);
CREATE TABLE edition_stories (
  edition_id TEXT NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
  story_id TEXT NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
  ordinal INTEGER NOT NULL DEFAULT 0, relation TEXT NOT NULL DEFAULT 'reported',
  PRIMARY KEY (edition_id, story_id, relation)
);
CREATE TABLE batches (
  id TEXT PRIMARY KEY, date TEXT NOT NULL, slot TEXT NOT NULL,
  window_start TEXT, window_end TEXT, status TEXT NOT NULL,
  coverage_status TEXT NOT NULL, story_count INTEGER NOT NULL DEFAULT 0, url TEXT,
  source_run_ids_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE edition_batches (
  edition_id TEXT NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
  batch_id TEXT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
  PRIMARY KEY (edition_id,batch_id)
);
CREATE TABLE story_batches (
  story_id TEXT NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
  batch_id TEXT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
  PRIMARY KEY (story_id,batch_id)
);
CREATE TABLE assets (
  id TEXT PRIMARY KEY, edition_id TEXT REFERENCES editions(id) ON DELETE CASCADE,
  story_id TEXT REFERENCES stories(id) ON DELETE CASCADE,
  role TEXT NOT NULL, url TEXT, source_url TEXT, sha256 TEXT, media_type TEXT
);
CREATE INDEX idx_editions_date_kind ON editions(date,kind);
CREATE INDEX idx_stories_event ON stories(event_id,content_version);
CREATE INDEX idx_stories_published ON stories(published_at);
"""


def read_json(path: Path, warnings: list[str]):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        warnings.append(f"invalid_json:{path.as_posix()}:{type(exc).__name__}")
        return None


def stable_id(prefix: str, *parts: object) -> str:
    raw = "\x1f".join(str(x or "") for x in parts)
    return prefix + "_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def clean_public_url(value, root: Path) -> str | None:
    """Return a site-relative path or public http(s) URL, never a local path."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    value = value.replace("\\", "/")
    parsed = urlparse(value)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        if parsed.username or parsed.password or any(k.lower() in {"token", "access_token", "api_key", "apikey", "signature", "sig"} for k, _ in parse_qsl(parsed.query, keep_blank_values=True)):
            return None
        return value
    if parsed.scheme or value.startswith("//"):
        return None
    if value.startswith("/"):
        candidate = Path(value)
        if candidate.is_absolute():
            try:
                rel = candidate.resolve().relative_to((root / "research/evidence").resolve()).as_posix()
                return "/" + rel
            except (ValueError, OSError):
                # Existing site routes are rooted, while absolute local paths
                # outside evidence are private and must never pass through.
                if value.startswith("/bulletins/") or re.match(r"/\d{4}-\d{2}-\d{2}/", value):
                    pass
                else:
                    return None
        if any(part == ".." for part in value.split("/")):
            return None
        return value
    if value.startswith("research/evidence/"):
        candidate = (root / value).resolve()
        try:
            rel = candidate.relative_to((root / "research/evidence").resolve()).as_posix()
        except ValueError:
            return None
        return "/" + rel
    if any(part == ".." for part in value.split("/")):
        return None
    # A relative asset path is exported only if it resolves inside the evidence
    # tree; local filesystem paths are never serialized.
    candidate = (root / "research/evidence" / value).resolve()
    evidence = (root / "research/evidence").resolve()
    try:
        rel = candidate.relative_to(evidence).as_posix()
    except ValueError:
        return None
    return "/" + rel


TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref_src", "s", "si"}


def canonical_source_url(value) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = urlparse(value.strip())
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        return None
    host = parsed.netloc.lower()
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
             if not (k.lower().startswith("utm_") or k.lower() in TRACKING_QUERY_KEYS)]
    path = parsed.path or "/"
    return urlunparse((parsed.scheme.lower(), host, path, "", urlencode(query, doseq=True), ""))


def truthy_status(entry: dict, path: str | None, root: Path) -> tuple[str, str | None]:
    if not path:
        return "missing", None
    public = clean_public_url(path, root)
    if not public or not public.startswith("/"):
        return "missing", None
    # State stores public route paths like /2026-.../clip.mp4. Check the
    # corresponding evidence file without exposing its local path.
    candidate = (root / "research/evidence" / public.lstrip("/")).resolve()
    try:
        candidate.relative_to((root / "research/evidence").resolve())
    except ValueError:
        return "missing", None
    if not candidate.is_file():
        return "missing", None
    status = entry.get("status") or "rendered"
    if status == "verified" and entry.get("video_sha256"):
        return "verified", public
    if status == "verified":
        # Older receipts may put the hash in own-video.json instead.
        return "verified", public
    return "rendered", public


def story_identity(story: dict) -> tuple[str, str, str | None, str | None]:
    event = story.get("event_id") or story.get("eventId")
    version = story.get("content_version") or story.get("contentVersion")
    source_url = story.get("primary_url") or story.get("url") or story.get("source_url")
    if not source_url and isinstance(story.get("sources"), list):
        first_source = next((item for item in story["sources"] if isinstance(item, dict) and (item.get("url") or item.get("source_url"))), None)
        if first_source:
            source_url = first_source.get("url") or first_source.get("source_url")
    canonical = canonical_source_url(source_url)
    natural = canonical or event or story.get("id") or story.get("title") or json.dumps(story, sort_keys=True, ensure_ascii=False)
    if version:
        sid = stable_id("story", event or canonical or natural, version)
    else:
        sid = stable_id("story", canonical or event or natural)
    return sid, str(event) if event else None, str(version) if version else None, source_url


def make_story(story: dict, root: Path):
    if not isinstance(story, dict):
        return None
    sid, event, version, source_url = story_identity(story)
    sources = []
    for field in ("sources", "related"):
        value = story.get(field)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    u = item.get("url") or item.get("source_url")
                    if u:
                        sources.append({"label": item.get("label"), "url": clean_public_url(u, root)})
    for item in story.get("source_captures", []) if isinstance(story.get("source_captures"), list) else []:
        if isinstance(item, dict) and item.get("source_url"):
            sources.append({"label": item.get("label"), "url": clean_public_url(item["source_url"], root)})
    if source_url:
        sources.insert(0, {"label": story.get("source_name") or story.get("author"), "url": clean_public_url(source_url, root)})
    seen = set()
    deduped = []
    for source in sources:
        if source.get("url") and source["url"] not in seen:
            seen.add(source["url"])
            deduped.append(source)
    return {
        "id": sid, "event_id": event, "content_version": version,
        "title": str(story.get("title") or story.get("headline") or "未命名资讯"),
        "summary": story.get("summary") or story.get("description"),
        "url": clean_public_url(source_url, root),
        "published_at": story.get("published_at") or story.get("publishedAt"),
        "sources": deduped,
        "_canonical_url": canonical_source_url(source_url),
        "status": str(story.get("status") or "reviewed"),
    }


def clean_headline(value):
    return re.sub(r"\s+", " ", value).strip() if isinstance(value, str) and value.strip() else None


def batch_bulletin_url(batch: dict, root: Path) -> str | None:
    """Resolve legacy string and current object-shaped batch bulletin refs."""
    value = batch.get("bulletin")
    if isinstance(value, dict):
        value = value.get("path") or value.get("url")
    return clean_public_url(value, root)


def cover_story_raw_id(report: dict):
    presentation = report.get("presentation") if isinstance(report.get("presentation"), dict) else {}
    lead = presentation.get("lead_story_id")
    if isinstance(lead, str) and lead:
        return lead
    ids = presentation.get("cover_story_ids") or report.get("cover_story_ids") or []
    wanted = ids[0] if isinstance(ids, list) and ids else None
    return wanted


def cover_story_raw_ids(report: dict):
    """Return editorial lead candidates before legacy cover-story candidates."""
    presentation = report.get("presentation") if isinstance(report.get("presentation"), dict) else {}
    candidates = []
    lead = presentation.get("lead_story_id")
    if isinstance(lead, str) and lead:
        candidates.append(lead)
    ids = presentation.get("cover_story_ids") or report.get("cover_story_ids") or []
    if isinstance(ids, list):
        candidates.extend(item for item in ids if isinstance(item, str) and item)
    return list(dict.fromkeys(candidates))


def cover_headline(report: dict, fallback: str) -> str:
    presentation = report.get("presentation") if isinstance(report.get("presentation"), dict) else {}
    explicit = clean_headline(presentation.get("cover_headline"))
    if explicit:
        return explicit
    wanted = cover_story_raw_id(report)
    for story in report.get("stories", []) if isinstance(report.get("stories"), list) else []:
        if isinstance(story, dict) and (story.get("id") == wanted or wanted is None and story.get("title")):
            return clean_headline(story.get("title")) or fallback
    return fallback


def batch_files(root: Path, warnings: list[str]):
    base = root / "research/news-batches"
    result = []
    if not base.exists():
        warnings.append("missing_news_batches_directory")
        return result
    for path in sorted(base.glob("????-??-??/????/batch.json")):
        data = read_json(path, warnings)
        if not isinstance(data, dict) or not data.get("batch_id"):
            if data is not None:
                warnings.append(f"invalid_batch:{path.relative_to(root).as_posix()}")
            continue
        result.append((path, data))
    return result


def build(root: Path):
    root = root.resolve()
    warnings: list[str] = []
    # Load batch manifests once. Source-version links on long-form editions
    # must resolve to an actual story in the named batch, and the same cached
    # manifests are reused by the normal batch-ingest pass below.
    batch_records = batch_files(root, warnings)
    batch_data_by_id = {str(data["batch_id"]): data for _, data in batch_records}
    source_version_index: dict[tuple[str, str, str, str], list[dict]] = {}
    for _, batch_data in batch_records:
        batch_id = str(batch_data["batch_id"])
        for batch_story in batch_data.get("stories", []) if isinstance(batch_data.get("stories"), list) else []:
            if not isinstance(batch_story, dict):
                continue
            event_id = batch_story.get("event_id") or batch_story.get("eventId")
            content_version = batch_story.get("content_version") or batch_story.get("contentVersion")
            source_url = batch_story.get("primary_url") or batch_story.get("url") or batch_story.get("source_url")
            if all(isinstance(value, str) and value for value in (event_id, content_version, source_url)):
                source_version_index.setdefault((batch_id, event_id, content_version, source_url), []).append(batch_story)
    state_path = root / "research/editions/production-state.json"
    state = read_json(state_path, warnings)
    if not isinstance(state, dict):
        state = {}
        warnings.append("missing_or_invalid_production_state")
    editions: dict[str, dict] = {}
    stories: dict[str, dict] = {}
    batches: dict[str, dict] = {}
    edition_story_links: set[tuple[str, str, int, str]] = set()
    edition_batch_links: set[tuple[str, str]] = set()
    story_batch_links: set[tuple[str, str]] = set()
    assets: dict[str, dict] = {}
    url_aliases: dict[str, set[str]] = {}
    event_aliases: dict[str, set[str]] = {}
    story_id_remaps: dict[str, str] = {}
    special_identity_to_eid: dict[str, str] = {}

    def validate_source_event_versions(item: dict, report_path: Path):
        """Resolve refs only when all identity fields match the named batch story."""
        if "source_event_versions" not in item:
            return None  # Legacy reports retain their existing ingestion behavior.
        refs = item.get("source_event_versions")
        location = report_path.relative_to(root).as_posix()
        item_id = str(item.get("id") or "unknown")
        if not isinstance(refs, list) or not refs:
            warnings.append(f"invalid_source_event_versions:{location}:{item_id}:not_a_nonempty_list")
            return {"primary": None, "valid": []}
        valid = []
        for ref_idx, ref in enumerate(refs):
            if not isinstance(ref, dict):
                warnings.append(f"invalid_source_event_version_ref:{location}:{item_id}:{ref_idx}:not_an_object")
                continue
            required = (ref.get("batch_id"), ref.get("event_id"), ref.get("content_version"), ref.get("url"))
            if not all(isinstance(value, str) and value for value in required):
                warnings.append(f"invalid_source_event_version_ref:{location}:{item_id}:{ref_idx}:missing_identity_field")
                continue
            batch_id, event_id, content_version, source_url = required
            manifest = batch_data_by_id.get(batch_id)
            if manifest is None or manifest.get("batch_id") != batch_id:
                warnings.append(f"invalid_source_event_version_ref:{location}:{item_id}:{ref_idx}:unknown_batch")
                continue
            if manifest.get("status") != "reviewed":
                warnings.append(f"invalid_source_event_version_ref:{location}:{item_id}:{ref_idx}:unreviewed_batch")
                continue
            matches = source_version_index.get((batch_id, event_id, content_version, source_url), [])
            if len(matches) != 1:
                reason = "no_exact_batch_story_match" if not matches else "ambiguous_batch_story_match"
                warnings.append(f"invalid_source_event_version_ref:{location}:{item_id}:{ref_idx}:{reason}")
                continue
            valid.append((ref, matches[0]))

        primary_url = item.get("primary_url") or item.get("url")
        report_event_id = item.get("event_id") or item.get("eventId")
        primary_candidates = [(ref, batch_story) for ref, batch_story in valid
                              if ref.get("event_id") == report_event_id and ref.get("url") == primary_url]
        if len(primary_candidates) != 1:
            reason = "primary_source_ref_missing" if not primary_candidates else "ambiguous_primary_source_ref"
            warnings.append(f"invalid_source_event_versions:{location}:{item_id}:{reason}")
            return {"primary": None, "valid": valid}
        return {"primary": primary_candidates[0], "valid": valid}

    def merge_story(raw: dict):
        """Resolve stable event/version identity and URL aliases across files."""
        incoming = make_story(raw, root)
        if not incoming:
            return None
        canonical = incoming.pop("_canonical_url", None)
        event, version = incoming.get("event_id"), incoming.get("content_version")
        candidates = set(url_aliases.get(canonical, set())) if canonical else set()
        matching = [sid for sid in candidates
                    if (not event or not stories[sid].get("event_id") or stories[sid].get("event_id") == event)
                    and (not version or not stories[sid].get("content_version") or stories[sid].get("content_version") == version)]
        sid = None
        if event and version:
            target = stable_id("story", event, version)
            if target in stories:
                sid = target
            elif len(matching) == 1:
                sid = matching[0]
                # A versionless earlier report is upgraded to the stable
                # event/version key once richer evidence arrives.
                if not stories[sid].get("content_version"):
                    old = sid
                    sid = target
                    story_id_remaps[old] = sid
                    previous = stories.pop(old)
                    previous["id"] = sid
                    stories[sid] = previous
                    for alias, ids in url_aliases.items():
                        if old in ids:
                            ids.discard(old)
                            ids.add(sid)
                    if previous.get("event_id"):
                        event_aliases.setdefault(previous["event_id"], set()).discard(old)
                    for existing in list(edition_story_links):
                        if existing[1] == old:
                            edition_story_links.discard(existing)
                            edition_story_links.add((existing[0], sid, existing[2], existing[3]))
                    for existing in list(story_batch_links):
                        if existing[0] == old:
                            story_batch_links.discard(existing)
                            story_batch_links.add((sid, existing[1]))
            else:
                sid = target
        elif len(matching) == 1:
            sid = matching[0]
        elif candidates and event:
            same_event = [candidate for candidate in candidates if stories[candidate].get("event_id") == event]
            if len(same_event) == 1:
                sid = same_event[0]
        if sid is None and event and not version:
            same_event = set(event_aliases.get(event, set()))
            if len(same_event) == 1:
                sid = next(iter(same_event))
        if sid is None and len(candidates) > 1:
            warnings.append("ambiguous_story_url_alias_preserved_versions")
        if sid is None:
            sid = incoming["id"]
        incoming["id"] = sid
        existing = stories.get(sid)
        if existing:
            merged_sources = existing.get("sources", []) + incoming.get("sources", [])
            unique = []
            seen_urls = set()
            for source in merged_sources:
                if source.get("url") and source["url"] not in seen_urls:
                    seen_urls.add(source["url"])
                    unique.append(source)
            # Prefer the version-bearing, more explicit record when aliases
            # collide, while retaining already captured source links.
            for key in ("event_id", "content_version", "title", "summary", "url", "published_at", "status"):
                if incoming.get(key) is not None and (existing.get(key) is None or key in ("title", "summary") and len(str(incoming.get(key))) > len(str(existing.get(key)))):
                    existing[key] = incoming[key]
            existing["sources"] = unique
        else:
            stories[sid] = incoming
        if canonical:
            url_aliases.setdefault(canonical, set()).add(sid)
        if event:
            event_aliases.setdefault(event, set()).add(sid)
        return stories[sid]

    def ingest_report(stable_key: str, date: str, kind: str, report_path: Path, state_entry: dict | None, status_override: str | None = None):
        report = read_json(report_path, warnings)
        if not isinstance(report, dict):
            return None
        state_entry = state_entry or {}
        eid = stable_id("edition", stable_key)
        presentation = report.get("presentation") if isinstance(report.get("presentation"), dict) else {}
        column = {"morning": "AI早报", "evening": "AI晚报", "briefing": "AI资讯"}.get(kind, "AI资讯")
        date_label = f"{date[:4]}年{int(date[5:7])}月{int(date[8:10])}日"
        published_title = presentation.get("issue_title") or state_entry.get("title") or report.get("title") or report.get("headline")
        title = str(published_title or f"{date_label} {column}")
        if presentation.get("issue_title") and not str(published_title).startswith(date_label):
            title = f"{date_label} {title}"
        out_url = clean_public_url(state_entry.get("url") or state_entry.get("web_url"), root)
        if not out_url:
            out_url = "/" + date + "/" + report_path.parent.name + "/"
        video_status, video_url = truthy_status(state_entry, state_entry.get("video"), root)
        poster_url = clean_public_url(state_entry.get("poster"), root)
        coverage = state_entry.get("coverage_status") or report.get("coverage_status")
        if not coverage:
            coverage = "partial" if isinstance(report.get("coverage"), dict) and report["coverage"].get("gaps") else "unknown"
        status = status_override or state_entry.get("status") or "indexed"
        source_batches = report.get("source_batch_ids") or state_entry.get("source_batch_ids") or []
        scheduled = report.get("scheduled_at") or report.get("window_end")
        report_story_map = {}
        report_merged_progress_map = {}
        report_stories = report.get("stories", []) if isinstance(report.get("stories"), list) else []
        for ordinal, item in enumerate(report_stories):
            if not isinstance(item, dict):
                warnings.append(f"invalid_story:{report_path.relative_to(root).as_posix()}:{ordinal}")
                continue
            source_refs = validate_source_event_versions(item, report_path)
            if source_refs is not None:
                primary = source_refs.get("primary")
                if not primary:
                    # A fabricated or incomplete ref must not mint a summary
                    # story/version or relationships to unrelated batches.
                    continue
                primary_ref, primary_batch_story = primary
                primary_raw = dict(primary_batch_story)
                # Keep the reviewed editorial text while anchoring identity,
                # source URL, publication time, and content version to the
                # matched source record from batch.json.
                primary_raw["title"] = item.get("title") or primary_batch_story.get("title")
                primary_raw["summary"] = item.get("summary") or primary_batch_story.get("summary")
                primary_raw["related"] = item.get("related", primary_batch_story.get("related", []))
                primary_raw["source_captures"] = item.get("source_captures", primary_batch_story.get("source_captures", []))
                story = merge_story(primary_raw)
                if story:
                    story["title"] = str(item.get("title") or story.get("title") or "未命名资讯")
                    if item.get("summary") is not None:
                        story["summary"] = item.get("summary")
                    linked_progress = []
                    for ref, batch_story in source_refs["valid"]:
                        source_story = merge_story(batch_story)
                        if not source_story:
                            continue
                        source_batch_id = ref["batch_id"]
                        story_batch_links.add((source_story["id"], source_batch_id))
                        if ref is not primary_ref:
                            linked_progress.append(source_story["id"])
                    if item.get("id"):
                        report_story_map[item["id"]] = story["id"]
                        report_merged_progress_map[item["id"]] = list(dict.fromkeys(linked_progress))
                if not story:
                    warnings.append(f"invalid_story:{report_path.relative_to(root).as_posix()}:{ordinal}")
                continue

            story = merge_story(item)
            if not story:
                warnings.append(f"invalid_story:{report_path.relative_to(root).as_posix()}:{ordinal}")
                continue
            if item.get("id"):
                report_story_map[item["id"]] = story["id"]
        try:
            ordered_raw_ids = navigation_story_order(report)
        except (ValueError, TypeError):
            ordered_raw_ids = [item.get("id") for item in report_stories if isinstance(item, dict)]
            warnings.append(f"invalid_navigation_order:{report_path.relative_to(root).as_posix()}")
        for ordinal, raw_id in enumerate(ordered_raw_ids):
            if raw_id in report_story_map:
                edition_story_links.add((eid, report_story_map[raw_id], ordinal, "reported"))
                for progress_story_id in report_merged_progress_map.get(raw_id, []):
                    edition_story_links.add((eid, progress_story_id, ordinal, "merged_progress"))
        cover_raw_id = next((raw_id for raw_id in cover_story_raw_ids(report) if raw_id in report_story_map), None)
        cover_story_id = report_story_map.get(cover_raw_id)
        cover_story = stories.get(cover_story_id) if cover_story_id else None
        if cover_story is None and report_story_map:
            cover_story = stories.get(next(iter(report_story_map.values())))
            cover_story_id = cover_story.get("id") if cover_story else None
        editions[eid] = {
            "id": eid, "date": date, "kind": kind, "title": title,
            "headline": clean_headline(presentation.get("cover_headline")) or clean_headline((cover_story or {}).get("title")) or cover_headline(report, title),
            "summary": (cover_story or {}).get("summary"), "headline_source_story_id": cover_story_id,
            "video_story_count": len(set(report_story_map.values())) if state_entry.get("video") else None,
            "scheduled_at": scheduled, "window_start": report.get("window_start") or state_entry.get("window_start"),
            "window_end": report.get("window_end") or state_entry.get("window_end"),
            "url": out_url, "video_url": video_url, "poster_url": poster_url,
            "video_status": video_status, "coverage_status": str(coverage),
            "status": str(status), "report_path": report_path.relative_to(root).as_posix(),
            "source_fingerprint": state_entry.get("fingerprint") or state_entry.get("source_report_fingerprint"),
            "story_ids": [], "batch_ids": [],
        }
        for item in report_stories:
            story = stories.get(report_story_map.get(item.get("id"))) if isinstance(item, dict) else None
            if story:
                if "source_event_versions" in item:
                    # Valid refs above add only each matched story's true batch
                    # membership. Never apply an editorial row's broad batch list.
                    continue
                item_batches = item.get("source_batch_ids") or ([item.get("source_batch_id")] if item.get("source_batch_id") else [])
                if isinstance(item_batches, list):
                    for item_batch in item_batches:
                        if isinstance(item_batch, str):
                            story_batch_links.add((story["id"], item_batch))
        # Persist assets as metadata only; never expose machine paths.
        for field, role in (("image_assets", "image"), ("video_assets", "video"), ("videos", "video")):
            for idx, item in enumerate(report.get(field, []) if isinstance(report.get(field), list) else []):
                if not isinstance(item, dict):
                    continue
                public_path = clean_public_url(item.get("path") or item.get("url"), root)
                if not public_path:
                    continue
                aid = stable_id("asset", eid, role, item.get("sha256") or public_path, idx)
                assets[aid] = {"id": aid, "edition_id": eid, "story_id": None, "role": role, "url": public_path,
                               "source_url": clean_public_url(item.get("original_url") or item.get("source_url"), root),
                               "sha256": item.get("sha256"), "media_type": item.get("type") or item.get("mime_type")}
        for bid in source_batches:
            if isinstance(bid, str):
                edition_batch_links.add((eid, bid))
        return eid

    # Canonical, scheduled editions and separate supplemental reports.
    for state_group in ("completed", "supplemental_completed", "in_progress"):
        entries = state.get(state_group, {})
        if not isinstance(entries, dict):
            warnings.append(f"invalid_state_group:{state_group}")
            continue
        for key, entry in sorted(entries.items()):
            if not isinstance(entry, dict):
                warnings.append(f"invalid_state_entry:{state_group}")
                continue
            match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})/(.+)", key)
            if not match:
                warnings.append(f"invalid_edition_key:{state_group}")
                continue
            date, slug = match.groups()
            report_rel = entry.get("report")
            if not isinstance(report_rel, str):
                if state_group == "in_progress":
                    eid = stable_id("edition", key)
                    editions[eid] = {"id": eid, "date": date, "kind": slug if slug in ("morning", "evening") else "briefing",
                        "title": str(entry.get("title") or f"{date} {slug}"), "headline": entry.get("headline"),
                        "scheduled_at": entry.get("scheduled_at"), "window_start": entry.get("window_start"),
                        "window_end": entry.get("window_end"), "url": None, "video_url": None, "poster_url": None,
                        "video_status": "missing", "coverage_status": str(entry.get("coverage_status") or "unknown"),
                        "status": str(entry.get("status") or "in_progress"), "report_path": None,
                        "source_fingerprint": None, "story_ids": [], "batch_ids": []}
                    warnings.append(f"in_progress_without_report:{date}/{slug}")
                    continue
                warnings.append(f"missing_report_reference:{date}/{slug}")
                continue
            report_path = (root / report_rel).resolve()
            try:
                report_path.relative_to(root)
            except ValueError:
                warnings.append(f"unsafe_report_reference:{date}/{slug}")
                continue
            if state_group == "in_progress":
                status = str(entry.get("status") or "in_progress")
            else:
                status = str(entry.get("status") or state_group)
            if slug in ("morning", "evening"):
                kind = slug
            else:
                kind = "briefing"
            # Supplementary videos tied to a batch are linked to the batch
            # edition below, preventing an extra pseudo-scheduled issue.
            report = read_json(report_path, warnings)
            source_ids = report.get("source_batch_ids", []) if isinstance(report, dict) else []
            matching_batch = source_ids[0] if len(source_ids) == 1 and isinstance(source_ids[0], str) else None
            if state_group == "in_progress" and kind == "briefing" and matching_batch:
                batch_date, _, batch_slot = matching_batch.partition("/")
                if batch_date == date and batch_slot not in ("0800", "2000"):
                    # A one-batch in-progress briefing is the reader-facing
                    # view for that batch, not a second edition. Digest slots
                    # remain their own morning/evening editions.
                    eid = ingest_report(key, date, kind, report_path, entry, status)
                    if eid:
                        editions[eid]["_supplemental_batch_id"] = matching_batch
                    continue
            if state_group == "supplemental_completed" and matching_batch and matching_batch.rsplit("/", 1)[-1] in ("0800", "2000"):
                # These trigger slots now produce the 12-hour digest; an older
                # one-batch video must not reappear as an extra issue.
                continue
            if state_group == "supplemental_completed" and matching_batch:
                # Keep this report as an attachment for the matching batch row.
                eid = ingest_report(key, date, "briefing", report_path, entry, status)
                if eid:
                    editions[eid]["_supplemental_batch_id"] = matching_batch
                continue
            ingested = ingest_report(key, date, kind, report_path, entry, status)
            if state_group == "in_progress" and not ingested:
                eid = stable_id("edition", key)
                editions[eid] = {"id": eid, "date": date, "kind": slug if slug in ("morning", "evening") else "briefing",
                    "title": str(entry.get("title") or f"{date} {slug}"), "headline": clean_headline(entry.get("headline")),
                    "scheduled_at": entry.get("scheduled_at"), "window_start": entry.get("window_start"),
                    "window_end": entry.get("window_end"), "url": None, "video_url": None, "poster_url": None,
                    "video_status": "missing", "coverage_status": str(entry.get("coverage_status") or "unknown"),
                    "status": str(entry.get("status") or "failed"), "report_path": None,
                    "source_fingerprint": None, "story_ids": [], "batch_ids": []}
                warnings.append(f"in_progress_report_unavailable:{date}/{slug}")

    # Ingest batch records and their short bulletin pages.
    for path, data in batch_records:
        bid = str(data["batch_id"])
        date, _, slot = bid.partition("/")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or not re.fullmatch(r"\d{4}", slot):
            warnings.append(f"invalid_batch_id:{path.relative_to(root).as_posix()}")
            continue
        batch_stories = []
        pending_story_ids = []
        for ordinal, item in enumerate(data.get("stories", []) if isinstance(data.get("stories"), list) else []):
            story = merge_story(item)
            if not story:
                warnings.append(f"invalid_story:{path.relative_to(root).as_posix()}:{ordinal}")
                continue
            batch_stories.append((story["id"], ordinal))
            story_batch_links.add((story["id"], bid))
        for pending_idx, pending in enumerate(data.get("pending_editorial", []) if isinstance(data.get("pending_editorial"), list) else []):
            if not isinstance(pending, dict):
                continue
            queue_label = Path(str(pending.get("queue_file") or "")).name
            pending_item = {"event_id": pending.get("event_id"), "content_version": pending.get("content_version"),
                "id": pending.get("id") or pending.get("event_id") or f"{bid}-pending-{pending_idx}",
                "title": pending.get("title") or (f"待核线索 · {pending.get('event_id')}" if pending.get("event_id") else f"待核线索 · {queue_label}" if queue_label else "待核线索"),
                "summary": pending.get("reason") or pending.get("note"), "url": pending.get("url"),
                "published_at": pending.get("published_at"), "status": "pending"}
            story = merge_story(pending_item)
            if story:
                pending_story_ids.append((story["id"], pending_idx))
                story_batch_links.add((story["id"], bid))
        status = str(data.get("status") or "unknown")
        coverage = str(data.get("coverage_status") or ("partial" if data.get("coverage_gaps") else "unknown"))
        batches[bid] = {"id": bid, "date": date, "slot": slot,
                        "window_start": data.get("window_start"), "window_end": data.get("window_end"),
                        "status": status, "coverage_status": coverage,
                        "story_count": len({s for s, _ in batch_stories}),
                        "url": batch_bulletin_url(data, root),
                        "source_run_ids": data.get("source_run_ids") if isinstance(data.get("source_run_ids"), list) else []}
        # One public edition per batch. Its bulletin page and any supplemental
        # briefing video share this row.
        eid = stable_id("edition", bid)
        bulletin_path = batch_bulletin_url(data, root)
        report_path = None
        supplemental = None
        for other_id, other in editions.items():
            if other.get("_supplemental_batch_id") == bid:
                supplemental = other
                break
        batch_entry = state.get("batches", {}).get(bid, {}) if isinstance(state.get("batches"), dict) else {}
        title = (supplemental or {}).get("title") or f"{date[:4]}年{int(date[5:7])}月{int(date[8:10])}日 {int(slot[:2])}点资讯"
        report_story_ids = []
        if supplemental:
            report_story_ids = list(supplemental.get("story_ids", []))
            video_url = supplemental.get("video_url")
            poster_url = supplemental.get("poster_url")
            video_status = supplemental.get("video_status", "missing")
            coverage = supplemental.get("coverage_status") or coverage
            # Fold the source references and window into the canonical batch row.
            report_path = supplemental.get("report_path")
            old_eid = supplemental["id"]
            edition_story_links.update((eid, sid, ordinal, relation) for link_eid, sid, ordinal, relation in list(edition_story_links) if link_eid == old_eid)
            edition_story_links = {link for link in edition_story_links if link[0] != old_eid}
            edition_batch_links.update((eid, linked_bid) for link_eid, linked_bid in list(edition_batch_links) if link_eid == old_eid)
            edition_batch_links = {link for link in edition_batch_links if link[0] != old_eid}
            for asset in assets.values():
                if asset.get("edition_id") == old_eid:
                    asset["edition_id"] = eid
            editions.pop(old_eid, None)
        else:
            video_url = poster_url = None
            video_status = "missing"
        first_batch_story = stories.get(batch_stories[0][0]) if batch_stories else None
        make_bulletin_edition = slot not in ("0800", "2000")
        if make_bulletin_edition:
            editions[eid] = {"id": eid, "date": date, "kind": "bulletin", "title": title,
                         "headline": (supplemental or {}).get("headline") or (first_batch_story or {}).get("title") or title,
                         "summary": (supplemental or {}).get("summary") or (first_batch_story or {}).get("summary"),
                         "headline_source_story_id": (supplemental or {}).get("headline_source_story_id") or (first_batch_story or {}).get("id"),
                         "video_story_count": (supplemental or {}).get("video_story_count"),
                         "scheduled_at": data.get("window_end"),
                         "window_start": data.get("window_start"), "window_end": data.get("window_end"),
                         "url": (supplemental or {}).get("url") or bulletin_path or f"/bulletins/{date}/{slot}/index.html",
                         "bulletin_url": bulletin_path or f"/bulletins/{date}/{slot}/index.html",
                         "video_url": video_url, "poster_url": poster_url,
                         "video_status": video_status, "coverage_status": coverage,
                         "status": status, "report_path": report_path,
                         "source_fingerprint": (supplemental or {}).get("source_fingerprint"),
                         "story_ids": [], "batch_ids": [bid]}
            edition_batch_links.add((eid, bid))
            for story_id, pending_idx in pending_story_ids:
                edition_story_links.add((eid, story_id, 100000 + pending_idx, "pending"))
            for story_id, ordinal in batch_stories:
                edition_story_links.add((eid, story_id, ordinal, "reported"))
            for story_id in report_story_ids:
                edition_story_links.add((eid, story_id, 10000, "reported"))
        # A special is its own retrievable editorial item, kept linked to its
        # owning batch and event where available.
        for special_idx, special in enumerate(data.get("special_reports", []) if isinstance(data.get("special_reports"), list) else []):
            if not isinstance(special, dict):
                continue
            special_type = str(special.get("type") or "")
            special_path = special.get("path") or special.get("url")
            # Batch metadata may list a companion video under special_reports;
            # its source_batch_ids already caused it to merge into the bulletin.
            if "video" in special_type.lower():
                continue
            if not special_path and special.get("report"):
                continue
            canonical_special_url = canonical_source_url(special_path)
            sid_key = special.get("event_id") or canonical_special_url or clean_public_url(special_path, root) or f"{bid}/special/{special_idx}"
            special_identity = str(sid_key)
            special_eid = special_identity_to_eid.get(special_identity) or stable_id("edition", "special", special_identity)
            event_story = next((st for st in stories.values() if special.get("event_id") and st.get("event_id") == special.get("event_id") and st.get("status") != "pending"), None)
            title_s = str(special.get("title") or (event_story or {}).get("title") or "特别报道")
            special_url = clean_public_url(special.get("path") or special.get("url"), root)
            if special_eid not in editions:
                editions[special_eid] = {"id": special_eid, "date": date, "kind": "special", "title": title_s,
                "headline": title_s, "summary": (event_story or {}).get("summary"), "headline_source_story_id": (event_story or {}).get("id"),
                "scheduled_at": data.get("window_end"), "window_start": data.get("window_start"),
                "window_end": data.get("window_end"), "url": special_url, "video_url": None, "poster_url": None,
                "video_status": "missing", "coverage_status": coverage, "status": str(special.get("status") or status),
                "report_path": None, "source_fingerprint": None, "story_ids": [], "batch_ids": [bid]}
                special_identity_to_eid[special_identity] = special_eid
            elif (not editions[special_eid].get("url") or editions[special_eid].get("title") == "特别报道") and special_url:
                editions[special_eid]["url"] = special_url
            editions[special_eid]["status"] = "verified" if "verified" in (editions[special_eid].get("status"), special.get("status")) else editions[special_eid].get("status")
            edition_batch_links.add((special_eid, bid))
            event = special.get("event_id")
            matched_special_stories = []
            if event:
                for stid, st in stories.items():
                    if st.get("event_id") == event and st.get("status") != "pending":
                        edition_story_links.add((special_eid, stid, 0, "special"))
                        matched_special_stories.append(stid)
            editions[special_eid]["story_count"] = len(set(matched_special_stories)) if matched_special_stories else None
        # Batch row itself can own a poster or media path in later schema versions.

    # Story associations from reports can identify batches even if the batch
    # has zero bulletins or missing source files.
    known_batches = set(batches)
    for eid, bid in sorted(edition_batch_links):
        if bid not in known_batches:
            warnings.append(f"missing_batch_record:{bid}")
    # Remove internal merge metadata and derive public relationships.
    def final_story_id(sid):
        seen_ids = set()
        while sid in story_id_remaps and sid not in seen_ids:
            seen_ids.add(sid)
            sid = story_id_remaps[sid]
        return sid
    collapsed_links = {}
    for eid, sid, ordinal, relation in edition_story_links:
        sid = final_story_id(sid)
        key = (eid, sid, relation)
        collapsed_links[key] = min(ordinal, collapsed_links.get(key, ordinal))
    edition_story_links = {(eid, sid, ordinal, relation) for (eid, sid, relation), ordinal in collapsed_links.items()}
    story_batch_links = {(final_story_id(sid), bid) for sid, bid in story_batch_links}
    for row in editions.values():
        row.pop("_supplemental_batch_id", None)
        if row.get("headline_source_story_id"):
            row["headline_source_story_id"] = final_story_id(row["headline_source_story_id"])
    for eid, sid, _, _ in sorted(edition_story_links, key=lambda x: (x[0], x[2], x[3], x[1])):
        if eid in editions and sid in stories and sid not in editions[eid]["story_ids"]:
            editions[eid]["story_ids"].append(sid)
    for eid, bid in sorted(edition_batch_links):
        if eid in editions and bid not in editions[eid]["batch_ids"]:
            editions[eid]["batch_ids"].append(bid)
    for row in editions.values():
        if row.get("kind") != "special" or row.get("story_count") is None:
            reported_ids = {sid for eid, sid, _, relation in edition_story_links if eid == row["id"] and relation == "reported"}
            row["story_count"] = len(reported_ids) if row.get("kind") != "special" else None
        row["batch_ids"].sort()

    return root, editions, stories, batches, edition_story_links, edition_batch_links, story_batch_links, assets, warnings


def export_data(root: Path, editions, stories, batches, edition_story_links, edition_batch_links, story_batch_links, assets):
    story_editions: dict[str, list[str]] = {sid: [] for sid in stories}
    story_batches: dict[str, list[str]] = {sid: [] for sid in stories}
    public_story_ids = {sid for sid, story in stories.items() if story.get("status") != "pending"}
    for eid, sid, _, relation in edition_story_links:
        if relation in ("reported", "special", "merged_progress") and eid in editions and sid in public_story_ids and eid not in story_editions[sid]:
            story_editions[sid].append(eid)
    for sid, bid in story_batch_links:
        if sid in public_story_ids and bid in batches and bid not in story_batches[sid]:
            story_batches[sid].append(bid)
    public_editions = []
    for row in sorted(editions.values(), key=lambda x: (x.get("scheduled_at") or "", x["kind"], x["id"])):
        public_row = {k: row.get(k) for k in ("id", "date", "kind", "title", "headline", "summary", "headline_source_story_id", "scheduled_at", "window_start", "window_end", "url", "bulletin_url", "video_story_count", "video_url", "poster_url", "video_status", "coverage_status", "story_count", "story_ids", "batch_ids", "status")}
        ordered_links = sorted((x for x in edition_story_links if x[0] == row["id"] and x[3] in ("reported", "special") and x[1] in public_story_ids), key=lambda x: (x[2], x[1]))
        public_row["story_ids"] = list(dict.fromkeys(sid for _, sid, _, _ in ordered_links))
        public_row["story_count"] = len(public_row["story_ids"]) if row.get("kind") != "special" or row.get("story_count") is not None else None
        public_editions.append(public_row)
    public_stories = []
    for row in sorted((x for x in stories.values() if x["id"] in public_story_ids and (story_editions[x["id"]] or story_batches[x["id"]])), key=lambda x: (x.get("published_at") or "", x["id"])):
        public_stories.append({k: v for k, v in {**row, "edition_ids": sorted(story_editions[row["id"]]), "batch_ids": sorted(story_batches[row["id"]])}.items() if not k.startswith("_")})
    public_batches = []
    for row in sorted(batches.values(), key=lambda x: (x["date"], x["slot"])):
        eds = sorted((eid for eid, bid in edition_batch_links if bid == row["id"]), key=lambda eid: (editions[eid].get("scheduled_at") or "", editions[eid].get("kind") or "", eid))
        batch_story_ids = sorted({sid for sid, bid in story_batch_links if bid == row["id"] and sid in public_story_ids})
        public_batches.append({"id": row["id"], "date": row["date"], "slot": row["slot"],
            "window_start": row["window_start"], "window_end": row["window_end"],
            "status": row["status"], "coverage_status": row["coverage_status"], "url": row.get("url"),
            "story_count": row["story_count"], "story_ids": batch_story_ids, "edition_ids": eds})
    return {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "editions": public_editions, "stories": public_stories, "batches": public_batches,
            "assets": sorted(assets.values(), key=lambda x: x["id"]),
            "stats": {"editions": len(public_editions), "stories": len(public_stories),
                      "batches": len(public_batches), "assets": len(assets),
                      "verified_videos": sum(1 for x in public_editions if x["video_status"] == "verified"),
                      "partial_coverage": sum(1 for x in public_editions if x["coverage_status"] == "partial")}}


def write_db(path: Path, editions, stories, batches, edition_story_links, edition_batch_links, story_batch_links, assets):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with sqlite3.connect(temp_path) as con:
            con.executescript(SCHEMA)
            con.executemany("INSERT INTO editions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
                (x["id"], x["date"], x["kind"], x["title"], x["headline"], x.get("summary"), x.get("headline_source_story_id"), x["scheduled_at"], x.get("bulletin_url"), x.get("video_story_count"), x["window_start"], x["window_end"], x["url"], x["video_url"], x["poster_url"], x["video_status"], x["coverage_status"], x["status"], x["report_path"], x["source_fingerprint"]) for x in editions.values()])
            con.executemany("INSERT INTO stories VALUES (?,?,?,?,?,?,?,?,?)", [
                (x["id"], x["event_id"], x["content_version"], x["title"], x["summary"], x["url"], x["published_at"], json.dumps(x["sources"], ensure_ascii=False), x.get("status", "reviewed")) for x in stories.values()])
            con.executemany("INSERT INTO batches VALUES (?,?,?,?,?,?,?,?,?,?)", [
                (x["id"], x["date"], x["slot"], x["window_start"], x["window_end"], x["status"], x["coverage_status"], x["story_count"], x.get("url"), json.dumps(x["source_run_ids"], ensure_ascii=False)) for x in batches.values()])
            con.executemany("INSERT INTO edition_stories VALUES (?,?,?,?)", sorted(edition_story_links))
            con.executemany("INSERT INTO edition_batches VALUES (?,?)", sorted(edition_batch_links))
            con.executemany("INSERT INTO story_batches VALUES (?,?)", sorted(story_batch_links))
            con.executemany("INSERT INTO assets VALUES (?,?,?,?,?,?,?,?)", [
                (x["id"], x["edition_id"], x["story_id"], x["role"], x["url"], x["source_url"], x["sha256"], x["media_type"]) for x in assets.values()])
            violations = list(con.execute("PRAGMA foreign_key_check"))
            if violations:
                raise sqlite3.IntegrityError(f"foreign key violations: {violations[:3]}")
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def rebuild(root: Path):
    root, editions, stories, batches, story_links, batch_links, story_batch_links, assets, warnings = build(root)
    db_path = root / "research/newsroom/newsroom.sqlite"
    json_path = root / "research/evidence/archive/data.json"
    write_db(db_path, editions, stories, batches, story_links, batch_links, story_batch_links, assets)
    data = export_data(root, editions, stories, batches, story_links, batch_links, story_batch_links, assets)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=json_path.name + ".", suffix=".tmp", dir=json_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        os.replace(temp_name, json_path)
    finally:
        Path(temp_name).unlink(missing_ok=True)
    counts = {"editions": len(editions), "stories": len(data["stories"]), "pending_stories": sum(1 for x in stories.values() if x.get("status") == "pending"), "batches": len(batches), "assets": len(assets)}
    return {"status": "completed", "counts": counts, "warnings": warnings,
            "database": db_path.relative_to(root).as_posix(), "public_json": json_path.relative_to(root).as_posix()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("rebuild", help="rebuild the SQLite newsroom index and public JSON")
    cmd.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="project root (useful for isolated fixtures)")
    args = parser.parse_args()
    result = rebuild(args.root)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
