import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from completion_gate import check_video, should_render
from edition_contract import report_fingerprint


class CompletionGateTests(unittest.TestCase):
    def test_render_defaults_are_edition_specific_and_maintenance_never_renders(self):
        self.assertTrue(should_render('morning', None))
        self.assertTrue(should_render('evening', None))
        self.assertTrue(should_render('briefing', None))
        self.assertFalse(should_render('briefing', True, web_only_maintenance=True))
        self.assertFalse(should_render('morning', None, verify_only=True))
        self.assertFalse(should_render('briefing', None, verify_only=True))
        self.assertTrue(should_render('briefing', True))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.report = {'date': '2026-10-13', 'edition': 'morning', 'stories': [], 'charts': []}
        self.media = self.root / '2026-10-13/morning/test.mp4'
        self.media.parent.mkdir(parents=True)
        self.media.write_bytes(b'mp4')
        self.manifest = self.media.parent / 'own-video.json'
        self.verification = self.media.parent / 'verification.json'
        digest = hashlib.sha256(self.media.read_bytes()).hexdigest()
        self.value = {'kind': 'own_video', 'status': 'verified', 'path': '/2026-10-13/morning/test.mp4',
                      'source_report_fingerprint': report_fingerprint(self.report), 'video_sha256': digest}
        self.manifest.write_text(json.dumps(self.value))
        episode = {'fps': 30, 'durationInFrames': 375,
                   'source_report_fingerprint': report_fingerprint(self.report),
                   'scenes': [{'id': 'opening', 'startFrame': 0, 'durationInFrames': 30},
                              {'id': 'closing', 'startFrame': 30, 'durationInFrames': 345}]}
        (self.media.parent / 'video-props.json').write_text(json.dumps({'episode': episode}))
        (self.media.parent / 'video-chapters.json').write_text(json.dumps([
            {'id': 'opening', 'start_seconds': 0, 'duration_seconds': 1},
            {'id': 'closing', 'start_seconds': 1, 'duration_seconds': 11.5},
        ]))
        self.verification.write_text(json.dumps({'status': 'passed', 'video_sha256': digest,
                                                  'source_report_fingerprint': report_fingerprint(self.report),
                                                  'played_from_start_to_end': True}))

    def tearDown(self):
        self.temp.cleanup()

    def probe(self, *args, **kwargs):
        class Result:
            stdout = json.dumps({'streams': [{'codec_type': 'video', 'codec_name': 'h264', 'width': 1920, 'height': 1080, 'avg_frame_rate': '30/1'},
                                             {'codec_type': 'audio', 'codec_name': 'aac'}],
                                 'format': {'duration': '12.5'}})
        return Result()

    def test_requires_verified_fingerprint_matched_media_with_audio(self):
        with patch('completion_gate.subprocess.run', side_effect=self.probe):
            result = check_video(self.report, self.manifest, self.root, 'ffprobe')
        self.assertEqual(result['status'], 'verified')
        self.assertTrue(result['audio_present'])

    def test_rendered_manifest_is_not_verified_completion(self):
        self.value['status'] = 'rendered'
        self.manifest.write_text(json.dumps(self.value))
        with self.assertRaisesRegex(ValueError, 'video_not_verified'):
            check_video(self.report, self.manifest, self.root, 'ffprobe')

    def test_rejects_stale_report_and_invalid_media_streams(self):
        self.value['source_report_fingerprint'] = 'old'
        self.manifest.write_text(json.dumps(self.value))
        with self.assertRaisesRegex(ValueError, 'fingerprint_mismatch'):
            check_video(self.report, self.manifest, self.root, 'ffprobe')
        self.value['source_report_fingerprint'] = report_fingerprint(self.report)
        self.manifest.write_text(json.dumps(self.value))
        with patch('completion_gate.subprocess.run', return_value=type('Result', (), {'stdout': json.dumps({'streams': [{'codec_type': 'video', 'codec_name': 'h264', 'width': 1920, 'height': 1080, 'avg_frame_rate': '30/1'}], 'format': {'duration': '1'}})})()):
            with self.assertRaisesRegex(ValueError, 'audio_stream_missing'):
                check_video(self.report, self.manifest, self.root, 'ffprobe')

    def test_requires_matching_video_hash_and_full_playback(self):
        self.verification.write_text(json.dumps({'status': 'passed', 'video_sha256': 'wrong',
                                                  'source_report_fingerprint': report_fingerprint(self.report),
                                                  'played_from_start_to_end': True}))
        with self.assertRaisesRegex(ValueError, 'video_verification_hash_mismatch'):
            check_video(self.report, self.manifest, self.root, 'ffprobe')
        digest = hashlib.sha256(self.media.read_bytes()).hexdigest()
        self.verification.write_text(json.dumps({'status': 'passed', 'video_sha256': digest,
                                                  'source_report_fingerprint': report_fingerprint(self.report),
                                                  'played_from_start_to_end': False}))
        with self.assertRaisesRegex(ValueError, 'video_full_playback_not_verified'):
            check_video(self.report, self.manifest, self.root, 'ffprobe')
        digest = hashlib.sha256(self.media.read_bytes()).hexdigest()
        self.verification.write_text(json.dumps({'status': 'passed', 'video_sha256': digest,
                                                  'source_report_fingerprint': 'stale',
                                                  'played_from_start_to_end': True}))
        with self.assertRaisesRegex(ValueError, 'video_verification_report_fingerprint_mismatch'):
            check_video(self.report, self.manifest, self.root, 'ffprobe')

    def test_accepts_existing_morning_and_briefing_playback_receipt_shapes(self):
        digest = hashlib.sha256(self.media.read_bytes()).hexdigest()
        self.verification.write_text(json.dumps({'status': 'passed', 'video_sha256': digest,
                                                  'source_report_fingerprint': report_fingerprint(self.report),
                                                  'checks': {'browser_actual_mp4_playback': 'passed'}}))
        with patch('completion_gate.subprocess.run', side_effect=self.probe):
            self.assertEqual(check_video(self.report, self.manifest, self.root, 'ffprobe')['status'], 'verified')
        browser = self.media.parent / 'qa/browser-verification.json'
        browser.parent.mkdir()
        browser.write_text(json.dumps({'played_from_start_to_end': True}))
        self.verification.write_text(json.dumps({'status': 'verified', 'source_report_fingerprint': report_fingerprint(self.report), 'video': {'sha256': digest},
                                                  'web': {'browser_receipt': 'qa/browser-verification.json'}}))
        with patch('completion_gate.subprocess.run', side_effect=self.probe):
            self.assertEqual(check_video(self.report, self.manifest, self.root, 'ffprobe')['status'], 'verified')

    def test_rejects_partial_opening_render_despite_verified_receipts(self):
        with patch('completion_gate.subprocess.run', side_effect=lambda *a, **k: type('Result', (), {'stdout': json.dumps({
                'streams': [{'codec_type': 'video', 'codec_name': 'h264', 'width': 1920, 'height': 1080, 'avg_frame_rate': '30/1'},
                            {'codec_type': 'audio', 'codec_name': 'aac'}],
                'format': {'duration': '7.1'}})})()):
            with self.assertRaisesRegex(ValueError, 'video_timeline_duration_mismatch'):
                check_video(self.report, self.manifest, self.root, 'ffprobe')

    def test_requires_story_scene_and_chapter_coverage(self):
        self.report['stories'] = [{'id': 'story-a'}]
        fingerprint = report_fingerprint(self.report)
        self.value['source_report_fingerprint'] = fingerprint
        self.manifest.write_text(json.dumps(self.value))
        props_path = self.media.parent / 'video-props.json'
        props = json.loads(props_path.read_text())
        props['episode']['source_report_fingerprint'] = fingerprint
        props_path.write_text(json.dumps(props))
        digest = hashlib.sha256(self.media.read_bytes()).hexdigest()
        self.verification.write_text(json.dumps({'status': 'passed', 'video_sha256': digest,
                                                  'source_report_fingerprint': fingerprint,
                                                  'played_from_start_to_end': True}))
        with self.assertRaisesRegex(ValueError, 'video_timeline_story_coverage_mismatch'):
            with patch('completion_gate.subprocess.run', side_effect=self.probe):
                check_video(self.report, self.manifest, self.root, 'ffprobe')


if __name__ == '__main__':
    unittest.main()
