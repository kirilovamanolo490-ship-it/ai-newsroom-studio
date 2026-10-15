#!/usr/bin/env python3
"""Generate per-scene Chinese narration with the existing Seed TTS adapter.

Credentials are loaded from the existing AIgpt workbench .env via its adapter.
Only successful local receipts are cached; API errors are deliberately sanitized.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
import io
import time
import datetime as dt
from urllib.error import HTTPError
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from media_runtime import resolve_media_tools  # noqa: E402
from seed_tts_adapter import (  # noqa: E402
    VolcengineTTSConfig,
    VolcengineTTSError,
    _request_payload,
    default_env_path,
    load_env_file,
    synthesize_to_file,
)

RESOURCE = "seed-tts-2.0"
SPEAKER = "zh_female_vv_uranus_bigtts"
DIRECTOR = (
    "请用自然、明快、亲切的中文女性科技解说口吻。像一位聪明的同事在讲清楚一件新鲜事："
    "开头轻快吸引注意，解释部分稳而清楚，转折前稍作蓄势，关键结论有明确重音，"
    "结尾从容收住。根据语义自然改变节奏和语调，不要逐字播报，不要夸张播音腔；"
    "英文品牌名按常见英语读法清楚说出。"
)
MODEL = "Seed TTS 2.0"


class SeedVoiceFailure(RuntimeError):
    """Machine-readable failure without credentials or provider response text."""
    def __init__(self, info):
        self.info = info
        super().__init__(info["reason"])


def classify_http_failure(status: int, body: bytes) -> dict[str, Any]:
    code = None
    try:
        data = json.loads(body)
        header = data.get("header", data)
        candidate = header.get("code", header.get("status_code"))
        if isinstance(candidate, int):
            code = candidate
    except (ValueError, AttributeError, TypeError):
        pass
    if code == 45000030:
        reason, retryable = "resource_not_granted", False
    elif status in (401, 403):
        reason, retryable = "authorization_rejected", False
    elif status == 429:
        reason, retryable = "rate_limited", True
    elif status >= 500:
        reason, retryable = "provider_temporarily_unavailable", True
    else:
        reason, retryable = "provider_request_rejected", False
    return {"http_status": status, "provider_code": code, "reason": reason,
            "retryable": retryable, "resource_id": RESOURCE, "speaker": SPEAKER}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def narration_scenes(data: Any) -> list[dict[str, str]]:
    if isinstance(data, dict):
        scenes = data.get("scenes")
    elif isinstance(data, list):
        scenes = data
    else:
        scenes = None
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("旁白JSON需要包含非空 scenes 数组")

    result: list[dict[str, str]] = []
    for index, scene in enumerate(scenes, 1):
        if not isinstance(scene, dict):
            raise ValueError(f"第{index}场不是对象")
        lines = scene.get("lines")
        if lines is None:
            lines = [scene.get("spoken", scene.get("text", ""))]
        if not isinstance(lines, list):
            lines = [lines]
        spoken: list[str] = []
        for line in lines:
            if isinstance(line, str):
                text = line
            elif isinstance(line, dict):
                text = line.get("spoken") or line.get("text") or ""
            else:
                text = ""
            text = str(text).strip()
            if text:
                spoken.append(text)
        paragraph = "\n".join(spoken).strip()
        if not paragraph:
            raise ValueError(f"第{index}场没有可朗读文本")
        scene_id = str(scene.get("id") or scene.get("scene_id") or f"scene-{index:02d}")
        safe_id = re.sub(r"[^A-Za-z0-9_-]+", "-", scene_id).strip("-") or f"scene-{index:02d}"
        result.append({"id": safe_id, "title": str(scene.get("title") or scene_id), "text": paragraph})
    return result


def fingerprint(text: str, settings: dict[str, Any]) -> str:
    data = json.dumps({"text": text, "settings": settings}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class CaptureResponse:
    """Transparent response wrapper that captures bytes already consumed by the adapter."""

    def __init__(self, response: Any):
        self._response = response
        self.body = b""

    def __enter__(self):
        self._response.__enter__()
        return self

    def __exit__(self, *args):
        return self._response.__exit__(*args)

    def read(self, *args, **kwargs):
        self.body = self._response.read(*args, **kwargs)
        return self.body

    def __getattr__(self, key):
        return getattr(self._response, key)


class SeedRequester:
    def __init__(self):
        self.response: CaptureResponse | None = None
        self.failure: dict[str, Any] | None = None

    def __call__(self, request, *, timeout):
        payload = json.loads(request.data.decode("utf-8"))
        req = payload["req_params"]
        req["audio_params"]["enable_subtitle"] = True
        additions = json.loads(req["additions"])
        # The provider omits timestamps on cache hits; local fingerprints prevent repeat billing.
        additions["cache_config"] = {"text_type": 1, "use_cache": False}
        additions["context_texts"] = [DIRECTOR]
        req["additions"] = json.dumps(additions, ensure_ascii=False, separators=(",", ":"))
        request.data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        from urllib.request import urlopen

        try:
            self.response = CaptureResponse(urlopen(request, timeout=timeout))
        except HTTPError as error:
            body = error.read()
            self.failure = classify_http_failure(error.code, body)
            error.fp = io.BytesIO(body)
            raise
        return self.response


def extract_timestamps(body: bytes) -> list[dict[str, Any]]:
    try:
        content = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return []
    decoder = json.JSONDecoder()
    offset = 0
    words: list[dict[str, Any]] = []
    while offset < len(content):
        while offset < len(content) and content[offset].isspace():
            offset += 1
        if offset >= len(content):
            break
        try:
            frame, offset = decoder.raw_decode(content, offset)
        except json.JSONDecodeError:
            break
        sentence = frame.get("sentence") if isinstance(frame, dict) else None
        if isinstance(sentence, dict) and isinstance(sentence.get("words"), list):
            words.extend(w for w in sentence["words"] if isinstance(w, dict))
        # Some response variants place subtitle words at the frame top level.
        subtitles = frame.get("subtitles") if isinstance(frame, dict) else None
        if isinstance(subtitles, list):
            words.extend(w for w in subtitles if isinstance(w, dict))
    return words


def media_duration(path: Path) -> float:
    tools = resolve_media_tools(ROOT / "prototypes/daily-brief-video")
    ffprobe = tools.get("ffprobe")
    if not ffprobe:
        raise RuntimeError("本机找不到ffprobe，无法记录音频时长")
    output = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return round(float(output), 3)


def make_wav(mp3_path: Path) -> Path:
    tools = resolve_media_tools(ROOT / "prototypes/daily-brief-video")
    ffmpeg = tools.get("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("本机找不到ffmpeg，无法生成WAV副本")
    wav_path = mp3_path.with_suffix(".wav")
    subprocess.run(
        [ffmpeg, "-v", "error", "-y", "-i", str(mp3_path), "-c:a", "pcm_s16le", str(wav_path)],
        check=True, capture_output=True,
    )
    return wav_path


def synthesize_scene(scene: dict[str, str], audio_dir: Path, manifest_path: Path, refresh_changed: bool = False) -> dict[str, Any]:
    settings = {
        "provider": "volcengine",
        "model": MODEL,
        "resource_id": RESOURCE,
        "speaker": SPEAKER,
        "sample_rate": 24000,
        "format": "mp3",
        "speech_rate": 0,
        "loudness_rate": 0,
        "context_texts": [DIRECTOR],
        "enable_subtitle": True,
    }
    fp = fingerprint(scene["text"], settings)
    audio = audio_dir / f"{scene['id']}.mp3"
    receipt = manifest_path.parent / f"{scene['id']}.json"
    if receipt.exists():
        old = read_json(receipt)
        if old.get("fingerprint") == fp and audio.is_file() and old.get("sha256") == hashlib.sha256(audio.read_bytes()).hexdigest():
            wav = audio.with_suffix(".wav")
            if not wav.is_file():
                wav = make_wav(audio)
                old["wav"] = str(wav.resolve())
                old["wav_sha256"] = hashlib.sha256(wav.read_bytes()).hexdigest()
                old["wav_derivation"] = "PCM 16-bit WAV transcoded locally from the provider MP3"
                write_json(receipt, old)
            return old
        valid_old = audio.is_file() and old.get("sha256") == hashlib.sha256(audio.read_bytes()).hexdigest()
        if not refresh_changed or not valid_old:
            raise RuntimeError(f"{scene['id']}已有不同或不完整的记录；变更文案请显式使用--refresh-changed，不完整记录应先核验")
        archive=manifest_path.parent/'versions'/old['fingerprint'][:16]
        archive.mkdir(parents=True,exist_ok=True)
        for previous in [audio,audio.with_suffix('.wav'),receipt]:
            if previous.exists():shutil.copy2(previous,archive/previous.name)
        audio.unlink();receipt.unlink()
        audio.with_suffix('.wav').unlink(missing_ok=True)
    if audio.exists():
        raise RuntimeError(f"{scene['id']}已有无回执音频；为避免重复计费已停止，请先核验文件")

    requester = SeedRequester()
    config = VolcengineTTSConfig(
        speaker=SPEAKER,
        resource_id=RESOURCE,
        audio_format="mp3",
        sample_rate=24000,
        speech_rate=0,
        loudness_rate=0,
    )
    try:
        provider_result = synthesize_to_file(scene["text"], audio, config=config, opener=requester)
    except Exception as exc:
        # The legacy adapter includes provider response text in exceptions; never persist or print it.
        if requester.failure:
            raise SeedVoiceFailure(requester.failure) from None
        if isinstance(exc, VolcengineTTSError):
            raise SeedVoiceFailure({"reason": "provider_or_transport_error", "retryable": True,
                                    "http_status": None, "provider_code": None}) from None
        raise SeedVoiceFailure({"reason": "adapter_error", "retryable": False,
                                "error_type": type(exc).__name__}) from None

    if not audio.is_file() or requester.response is None:
        raise RuntimeError("服务未返回可用音频")
    sha256 = hashlib.sha256(audio.read_bytes()).hexdigest()
    wav = make_wav(audio)
    timestamps = extract_timestamps(requester.response.body)
    duration = media_duration(audio)
    row = {
        "scene_id": scene["id"],
        "title": scene["title"],
        "text": scene["text"],
        "characters_including_punctuation": len(scene["text"].replace("\n", "")),
        "characters_sent_including_linebreaks": len(scene["text"]),
        "audio": str(audio.resolve()),
        "sha256": sha256,
        "wav": str(wav.resolve()),
        "wav_sha256": hashlib.sha256(wav.read_bytes()).hexdigest(),
        "wav_derivation": "PCM 16-bit WAV transcoded locally from the provider MP3",
        "duration_seconds": duration,
        "fingerprint": fp,
        "provider": provider_result.get("provider", "volcengine"),
        "model": MODEL,
        "resource_id": RESOURCE,
        "speaker": SPEAKER,
        "settings": settings,
        "usage": provider_result.get("usage"),
        "request_id": provider_result.get("request_id"),
        "log_id": provider_result.get("log_id"),
        "timestamps": timestamps,
        "timestamps_status": "service_word_timestamps" if timestamps else "not_returned",
    }
    write_json(receipt, row)
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--narration", type=Path, help="旁白JSON（scenes数组；lines可为字符串或{text,spoken}对象）")
    parser.add_argument("--preflight", action="store_true", help="Live short Seed voice check; save separately from edition narration")
    parser.add_argument("--output", required=True, type=Path, help="音频输出目录")
    parser.add_argument("--manifest", type=Path, help="汇总manifest路径，默认写入音频输出目录/run.json")
    parser.add_argument("--refresh-changed", action="store_true", help="Archive intact old clips and regenerate only scenes whose edited text/settings changed")
    args = parser.parse_args()

    if not args.narration and not args.preflight:
        parser.error("--narration is required unless --preflight is selected")
    narration_path = args.narration.resolve() if args.narration else None
    audio_dir = args.output.resolve()
    manifest_path = (args.manifest or audio_dir / "run.json").resolve()
    load_env_file(default_env_path())
    if not os.environ.get("VOLCENGINE_TTS_API_KEY"):
        print("Seed TTS凭据未配置；未发起网络请求。", file=sys.stderr)
        return 2
    scenes = ([{"id": "preflight-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%f"),
                "title": "Seed voice service preflight", "text": "语音服务检查，本期资讯即将开始。"}]
              if args.preflight else narration_scenes(read_json(narration_path)))
    audio_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for scene in scenes:
        for attempt in range(1, 4):
            try:
                row = synthesize_scene(scene, audio_dir, manifest_path, args.refresh_changed)
                break
            except SeedVoiceFailure as exc:
                failure = {"status": "failed", "scene_id": scene["id"], "attempt": attempt,
                           "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                           "successful_scene_ids": [r["scene_id"] for r in rows], **exc.info}
                write_json(manifest_path.parent / "failure.json", failure)
                print(json.dumps(failure, ensure_ascii=False), flush=True)
                if not exc.info.get("retryable") or attempt == 3:
                    return 2
                time.sleep(2 ** attempt)
        rows.append(row)
        write_json(manifest_path, {
            "schema_version": "seed-voice-v2/1",
            "source_narration": str(narration_path) if narration_path else None,
            "purpose": "service_preflight" if args.preflight else "edition_narration",
            "provider": "volcengine",
            "model": MODEL,
            "resource_id": RESOURCE,
            "speaker": SPEAKER,
            "scenes": rows,
        })
        print(f"{scene['id']}: cached/generated, {row['duration_seconds']:.3f}s")
    failure_path = manifest_path.parent / "failure.json"
    if failure_path.exists():
        previous = read_json(failure_path)
        previous.update(status="recovered", recovered_at=dt.datetime.now(dt.timezone.utc).isoformat())
        write_json(failure_path, previous)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
