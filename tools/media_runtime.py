"""Resolve Node and FFmpeg tools from the active environment or Remotion install."""
from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path


def resolve_node() -> str | None:
    return shutil.which("node")


def _compositor_names() -> tuple[str, ...]:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin":
        arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
        return (f"@remotion/compositor-darwin-{arch}",)
    if system == "linux":
        arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
        return (f"@remotion/compositor-linux-{arch}-gnu", f"@remotion/compositor-linux-{arch}-musl")
    if system == "windows":
        arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
        return (f"@remotion/compositor-win32-{arch}-msvc",)
    return ()


def resolve_media_tools(project: Path | str) -> dict[str, str | None]:
    """Resolve ffmpeg/ffprobe through PATH, then the platform Remotion package."""
    project = Path(project)
    result: dict[str, str | None] = {}
    local_dirs: list[str] = []
    package_root = project / "node_modules"
    for name in ("ffmpeg", "ffprobe"):
        override = os.environ.get(name.upper() + "_PATH")
        executable = shutil.which(override) if override else shutil.which(name)
        if override and not executable:
            raise RuntimeError(f"{name.upper()}_PATH does not point to an executable")
        if executable is None:
            suffix = ".exe" if platform.system() == "Windows" else ""
            for package in _compositor_names():
                candidate = package_root / package / f"{name}{suffix}"
                if candidate.is_file():
                    executable = str(candidate)
                    local_dirs.append(str(candidate.parent))
                    break
        result[name] = executable
        if executable and platform.system() == "Darwin" and "@remotion" in executable:
            library_dir = str(Path(executable).parent)
            existing = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
            parts = list(dict.fromkeys([library_dir, *filter(None, existing.split(os.pathsep))]))
            os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = os.pathsep.join(parts)
    if local_dirs:
        prefix = list(dict.fromkeys(local_dirs))
        os.environ["PATH"] = os.pathsep.join([*prefix, os.environ.get("PATH", "")])
    return result
