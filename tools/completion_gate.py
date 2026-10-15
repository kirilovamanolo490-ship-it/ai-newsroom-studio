"""Strict completion checks for a daily edition's original video."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


def should_render(edition: str | None, render_requested: bool | None,
                  web_only_maintenance: bool = False, verify_only: bool = False) -> bool:
    if web_only_maintenance or verify_only:
        return False
    return render_requested if render_requested is not None else edition in ('morning', 'evening', 'briefing')


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError('verification_receipt_invalid') from exc


def _played_to_end(receipt: dict, receipt_path: Path) -> bool:
    if receipt.get('played_from_start_to_end') is True:
        return True
    if receipt.get('video', {}).get('played_from_start_to_end') is True:
        return True
    # The morning receipt predates the explicit boolean and records the complete
    # MP4 playback assertion in its structured checks.
    if receipt.get('checks', {}).get('browser_actual_mp4_playback') == 'passed':
        return True
    # Briefing stores the playback detail in verification.json and the explicit
    # boolean in its referenced browser receipt.
    refs = [receipt.get('browser_receipt'), receipt.get('web', {}).get('browser_receipt')]
    for ref in refs:
        if not isinstance(ref, str):
            continue
        candidate = (receipt_path.parent / ref).resolve()
        if candidate.is_file() and _read_json(candidate).get('played_from_start_to_end') is True:
            return True
    return False


def _validate_timeline(report: dict, evidence_root: Path, manifest_path: Path) -> tuple[dict, float]:
    props_path = manifest_path.parent / 'video-props.json'
    chapters_path = manifest_path.parent / 'video-chapters.json'
    if not props_path.is_file() or not chapters_path.is_file():
        raise ValueError('video_timeline_files_missing')
    props = _read_json(props_path).get('episode')
    chapters = _read_json(chapters_path)
    if not isinstance(props, dict) or not isinstance(chapters, list):
        raise ValueError('video_timeline_invalid')
    from edition_contract import report_fingerprint
    fps = props.get('fps')
    total = props.get('durationInFrames')
    if fps != 30 or not isinstance(total, int) or total <= 0:
        raise ValueError('video_timeline_rate_invalid')
    if props.get('source_report_fingerprint') != report_fingerprint(report):
        raise ValueError('video_timeline_report_fingerprint_mismatch')
    scenes = props.get('scenes')
    if not isinstance(scenes, list) or not scenes:
        raise ValueError('video_timeline_scenes_invalid')
    sequence_contract = props.get('sequence_contract')
    if sequence_contract not in (None, 'navigation-groups-v1'):
        raise ValueError('video_sequence_contract_invalid')
    if sequence_contract == 'navigation-groups-v1':
        from edition_contract import navigation_story_order
        ordered = navigation_story_order(report)
        if props.get('navigation_story_order') != ordered:
            raise ValueError('video_navigation_order_mismatch')
        if props.get('presentation', {}).get('groups') != report.get('presentation', {}).get('groups'):
            raise ValueError('video_navigation_groups_mismatch')
        selected = props.get('presentation', {}).get('cover_story_ids', [])
        if selected != [sid for sid in ordered if sid in set(selected)]:
            raise ValueError('video_cover_order_mismatch')
        expected_ids = ['opening'] + ordered + ['closing']
    else:
        # Keep already accepted editions valid. New production always writes v1.
        expected_ids = ['opening'] + ([] if report.get('report_kind') == 'status_only' else [s.get('id') for s in report.get('stories', [])]) + ['closing']
    scene_ids = [scene.get('id') for scene in scenes]
    chapter_ids = [chapter.get('id') for chapter in chapters]
    if scene_ids != expected_ids or chapter_ids != expected_ids:
        raise ValueError('video_timeline_story_coverage_mismatch')
    if len(set(scene_ids)) != len(scene_ids):
        raise ValueError('video_timeline_duplicate_scene')
    scene_by_id = {scene['id']: scene for scene in scenes}
    timeline_end = 0
    for scene in scenes:
        start, length = scene.get('startFrame'), scene.get('durationInFrames')
        if not isinstance(start, int) or not isinstance(length, int) or start < 0 or length <= 0:
            raise ValueError('video_timeline_scene_frames_invalid')
        timeline_end = max(timeline_end, start + length)
    if timeline_end != total:
        raise ValueError('video_timeline_total_frames_mismatch')
    for chapter in chapters:
        scene = scene_by_id[chapter['id']]
        try:
            chapter_start = float(chapter['start_seconds'])
            chapter_duration = float(chapter['duration_seconds'])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError('video_chapter_timing_invalid') from exc
        if (abs(chapter_start - scene['startFrame'] / fps) > 1 / fps or
                abs(chapter_duration - scene['durationInFrames'] / fps) > 1 / fps):
            raise ValueError('video_chapter_timing_mismatch')
    return props, total / fps


def check_video(report: dict, manifest_path: Path, evidence_root: Path, ffprobe: str) -> dict:
    """Require verified, fingerprint-matched media and matching full-playback QA."""
    from edition_contract import report_fingerprint

    if not manifest_path.is_file():
        raise ValueError('video_manifest_missing')
    manifest = _read_json(manifest_path)
    if manifest.get('status') != 'verified':
        raise ValueError('video_not_verified')
    if manifest.get('kind') != 'own_video':
        raise ValueError('video_manifest_kind_invalid')
    if manifest.get('source_report_fingerprint') != report_fingerprint(report):
        raise ValueError('video_report_fingerprint_mismatch')
    rel = str(manifest.get('path') or '').lstrip('/')
    path = (evidence_root / rel).resolve()
    if not path.is_relative_to(evidence_root.resolve()) or not path.is_file() or path.stat().st_size == 0:
        raise ValueError('video_file_missing')
    actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    verification_path = manifest_path.parent / 'verification.json'
    if not verification_path.is_file():
        raise ValueError('video_verification_missing')
    verification = _read_json(verification_path)
    if verification.get('status') not in ('passed', 'verified'):
        raise ValueError('video_verification_not_passed')
    if verification.get('source_report_fingerprint') != report_fingerprint(report):
        raise ValueError('video_verification_report_fingerprint_mismatch')
    verified_hash = verification.get('video_sha256') or verification.get('video', {}).get('sha256')
    if verified_hash != actual_hash or manifest.get('video_sha256') not in (None, actual_hash):
        raise ValueError('video_verification_hash_mismatch')
    if not _played_to_end(verification, verification_path):
        raise ValueError('video_full_playback_not_verified')
    episode, expected_duration = _validate_timeline(report, evidence_root, manifest_path)
    try:
        result = subprocess.run(
            [ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
            capture_output=True, text=True, check=True, cwd=str(Path(ffprobe).resolve().parent),
        )
        media = json.loads(result.stdout)
    except Exception as exc:
        raise ValueError('video_probe_failed') from exc
    streams = media.get('streams', [])
    video = next((s for s in streams if s.get('codec_type') == 'video'), None)
    audio = next((s for s in streams if s.get('codec_type') == 'audio'), None)
    if not video or not audio:
        raise ValueError('video_audio_stream_missing')
    if video.get('codec_name') != 'h264' or audio.get('codec_name') != 'aac':
        raise ValueError('video_codec_invalid')
    if video.get('width') != 1920 or video.get('height') != 1080:
        raise ValueError('video_resolution_invalid')
    try:
        rate = str(video.get('avg_frame_rate') or video.get('r_frame_rate') or '0')
        numerator, denominator = rate.split('/', 1)
        actual_fps = float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError):
        actual_fps = 0
    if abs(actual_fps - 30) > 0.01:
        raise ValueError('video_frame_rate_invalid')
    duration = float(media.get('format', {}).get('duration') or 0)
    if duration <= 0:
        raise ValueError('video_duration_invalid')
    if abs(duration - expected_duration) > 0.5:
        raise ValueError('video_timeline_duration_mismatch')
    return {'status': 'verified', 'path': str(path), 'sha256': actual_hash,
            'width': 1920, 'height': 1080, 'duration_seconds': duration,
            'fps': 30, 'audio_present': True, 'played_from_start_to_end': True,
            'scene_ids': [s['id'] for s in episode['scenes']]}
