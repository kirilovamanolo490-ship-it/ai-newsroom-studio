from __future__ import annotations

import base64
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


VOLCENGINE_TTS_ENDPOINT = (
    "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
)
VOLCENGINE_API_KEY_ENV = "VOLCENGINE_TTS_API_KEY"
VOLCENGINE_RESOURCE_ID_ENV = "VOLCENGINE_TTS_RESOURCE_ID"
VOLCENGINE_SPEAKER_ENV = "VOLCENGINE_TTS_SPEAKER"
DEFAULT_RESOURCE_ID = "volc.service_type.10029"
DEFAULT_SPEAKER = "zh_male_beijingxiaoye_emo_v2_mars_bigtts"
SUPPORTED_SAMPLE_RATES = frozenset({8000, 16000, 22050, 24000, 32000, 44100, 48000})


class VolcengineTTSError(RuntimeError):
    """Raised when Volcengine cannot produce a complete audio response."""


@dataclass(frozen=True)
class VolcengineTTSConfig:
    speaker: str = DEFAULT_SPEAKER
    resource_id: str = DEFAULT_RESOURCE_ID
    audio_format: str = "mp3"
    sample_rate: int = 24000
    speech_rate: int = 0
    loudness_rate: int = 0
    timeout_seconds: float = 120.0
    mix_speakers: tuple[tuple[str, float], ...] = ()

    def validate(self) -> None:
        if not self.speaker.strip():
            raise ValueError("speaker cannot be blank")
        if not self.resource_id.strip():
            raise ValueError("resource_id cannot be blank")
        if self.audio_format != "mp3":
            raise ValueError("the workbench currently supports mp3 output only")
        if self.sample_rate not in SUPPORTED_SAMPLE_RATES:
            raise ValueError(f"unsupported sample rate: {self.sample_rate}")
        if not -50 <= self.speech_rate <= 100:
            raise ValueError("speech_rate must be between -50 and 100")
        if not -50 <= self.loudness_rate <= 100:
            raise ValueError("loudness_rate must be between -50 and 100")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.mix_speakers:
            if not 2 <= len(self.mix_speakers) <= 3:
                raise ValueError("mix_speakers must contain two or three voices")
            if any(not speaker.strip() for speaker, _ in self.mix_speakers):
                raise ValueError("mixed speaker ids cannot be blank")
            if any(weight <= 0 for _, weight in self.mix_speakers):
                raise ValueError("mixed speaker weights must be positive")
            total = sum(weight for _, weight in self.mix_speakers)
            if abs(total - 1.0) > 0.000001:
                raise ValueError("mixed speaker weights must add up to 1.0")

    @property
    def effective_speaker(self) -> str:
        return "custom_mix_bigtts" if self.mix_speakers else self.speaker


def default_env_path() -> Path:
    configured = os.environ.get("AI_NEWS_ENV_FILE")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[1] / ".env"


def load_env_file(path: Path | str) -> None:
    """Load simple KEY=VALUE settings without overriding process environment values."""
    env_path = Path(path)
    if not env_path.is_file():
        return
    for line_number, raw_line in enumerate(
        env_path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, raw_value = line.partition("=")
        if not separator or not key.strip():
            raise ValueError(f"invalid .env entry at line {line_number}")
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def synthesize_to_file(
    text: str,
    output_path: Path | str,
    *,
    config: VolcengineTTSConfig | None = None,
    api_key: str | None = None,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    """Synthesize text with Volcengine V3 HTTP Chunked and save an MP3 file."""
    selected = config or VolcengineTTSConfig()
    selected.validate()
    if not text.strip():
        raise ValueError("text cannot be blank")

    credential = api_key or os.environ.get(VOLCENGINE_API_KEY_ENV)
    if not credential:
        raise VolcengineTTSError(
            f"未配置火山引擎凭据，请设置环境变量 {VOLCENGINE_API_KEY_ENV}"
        )

    request_id = str(uuid.uuid4())
    request = Request(
        VOLCENGINE_TTS_ENDPOINT,
        data=json.dumps(
            _request_payload(text, selected), ensure_ascii=False
        ).encode("utf-8"),
        headers={
            "X-Api-Key": credential,
            "X-Api-Resource-Id": selected.resource_id,
            "X-Api-Request-Id": request_id,
            "Content-Type": "application/json",
            "Connection": "keep-alive",
            "X-Control-Require-Usage-Tokens-Return": "text_words",
        },
        method="POST",
    )

    try:
        with opener(request, timeout=selected.timeout_seconds) as response:
            status = getattr(response, "status", 200)
            log_id = response.headers.get("X-Tt-Logid")
            response_body = response.read()
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace").strip()
        raise VolcengineTTSError(
            f"火山引擎HTTP请求失败（{error.code}）：{detail or error.reason}"
        ) from error
    except URLError as error:
        raise VolcengineTTSError(f"无法连接火山引擎：{error.reason}") from error

    if status < 200 or status >= 300:
        raise VolcengineTTSError(f"火山引擎HTTP请求失败（{status}）")

    audio, chunk_count, usage = _decode_chunked_response(response_body)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(audio)
    return {
        "provider": "volcengine",
        "output": str(destination.resolve()),
        "bytes": len(audio),
        "audio_chunks": chunk_count,
        "request_id": request_id,
        "log_id": log_id,
        "usage": usage,
    }


def _request_payload(text: str, config: VolcengineTTSConfig) -> dict[str, Any]:
    additions = {
        "disable_markdown_filter": True,
        "enable_language_detector": True,
        "enable_latex_tn": True,
        "disable_default_bit_rate": True,
        "max_length_to_filter_parenthesis": 0,
        "cache_config": {"text_type": 1, "use_cache": True},
    }
    payload = {
        "user": {"uid": "video-production-workbench"},
        "req_params": {
            "text": text,
            "speaker": config.effective_speaker,
            "additions": json.dumps(additions, ensure_ascii=False, separators=(",", ":")),
            "audio_params": {
                "format": config.audio_format,
                "sample_rate": config.sample_rate,
                "speech_rate": config.speech_rate,
                "loudness_rate": config.loudness_rate,
            },
        },
    }
    if config.mix_speakers:
        payload["req_params"]["mix_speaker"] = {
            "speakers": [
                {"source_speaker": speaker, "mix_factor": weight}
                for speaker, weight in config.mix_speakers
            ]
        }
    return payload


def _decode_chunked_response(body: bytes) -> tuple[bytes, int, dict[str, Any] | None]:
    try:
        content = body.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise VolcengineTTSError("火山引擎返回了无法解析的响应") from error

    decoder = json.JSONDecoder()
    offset = 0
    frames: list[dict[str, Any]] = []
    while offset < len(content):
        while offset < len(content) and content[offset].isspace():
            offset += 1
        if offset >= len(content):
            break
        try:
            frame, offset = decoder.raw_decode(content, offset)
        except json.JSONDecodeError as error:
            raise VolcengineTTSError("火山引擎返回了无效的分块JSON") from error
        if not isinstance(frame, dict):
            raise VolcengineTTSError("火山引擎返回了未知的响应结构")
        frames.append(frame)

    audio_parts: list[bytes] = []
    finished = False
    usage: dict[str, Any] | None = None
    for frame in frames:
        code = frame.get("code")
        if code == 20000000:
            finished = True
            raw_usage = frame.get("usage")
            if isinstance(raw_usage, dict):
                usage = raw_usage
            continue
        if code != 0:
            message = frame.get("message") or "未知错误"
            raise VolcengineTTSError(f"火山引擎合成失败（{code}）：{message}")
        encoded = frame.get("data")
        if encoded:
            try:
                audio_parts.append(base64.b64decode(encoded, validate=True))
            except (ValueError, TypeError) as error:
                raise VolcengineTTSError("火山引擎返回了无效的Base64音频") from error

    if not finished:
        raise VolcengineTTSError("火山引擎响应未包含合成完成标记")
    if not audio_parts:
        raise VolcengineTTSError("火山引擎响应未包含音频数据")
    return b"".join(audio_parts), len(audio_parts), usage
