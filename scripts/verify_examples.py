#!/usr/bin/env python3
"""Verify the unchanged public examples locally; never fetch, synthesize or publish."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from media_runtime import resolve_media_tools


def main():
    examples = ROOT / "examples"
    manifest = json.loads((examples / "cases.json").read_text())
    probe = resolve_media_tools(ROOT / "prototypes/daily-brief-video").get("ffprobe")
    results = []
    for case in manifest["cases"]:
        folder = examples / case["directory"]
        for kind, expected in case["sha256"].items():
            file = folder / case["files"][kind]
            actual = hashlib.sha256(file.read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError(f"File hash mismatch: {file.relative_to(ROOT)}")
        srt = (folder / case["files"]["subtitles"]).read_text(encoding="utf-8-sig")
        cues = len(re.findall(r"\d\d:\d\d:\d\d,\d{3} -->", srt))
        if not cues:
            raise ValueError(f"No subtitles: {case['directory']}")
        row = {"case": case["directory"], "sha256": "passed", "subtitle_cues": cues,
               "media_probe": "skipped; install FFmpeg or npm ci for media inspection"}
        if probe:
            media = json.loads(subprocess.check_output(
                [probe, "-v", "error", "-show_streams", "-show_format", "-of", "json",
                 str(folder / case["files"]["video"])], text=True, cwd=Path(probe).parent))
            video = next(s for s in media["streams"] if s["codec_type"] == "video")
            assert any(s["codec_type"] == "audio" for s in media["streams"]), "Audio missing"
            assert (video["width"], video["height"]) == (1920, 1080), "Unexpected dimensions"
            assert abs(float(media["format"]["duration"]) - case["duration_seconds"]) < .5, "Duration mismatch"
            row["media_probe"] = "passed"
        results.append(row)
    print(json.dumps({"status": "passed", "cases": results, "external_publication": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
