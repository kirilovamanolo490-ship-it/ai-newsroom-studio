import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / 'research/report-redesign'))
from edition_contract import report_fingerprint, validate_report_window
from prepare_status_edition import prepare
from build_edition_report import build
from synthesize_seed_voice import narration_scenes


class StatusEditionTests(unittest.TestCase):
    def _fixture(self, root, with_story=False):
        date = '2026-10-13'
        end = dt.datetime.fromisoformat(date + 'T08:00:00+08:00')
        for n in range(1, 7):
            batch_end = end - dt.timedelta(hours=12 - 2*n)
            batch_id = f'{batch_end:%Y-%m-%d/%H}00'
            run_id = f'run-{n}'
            run = root / 'research/source-watch/runs' / run_id / 'report.json'
            run.parent.mkdir(parents=True, exist_ok=True)
            run.write_text(json.dumps({'run_id': run_id}), encoding='utf-8')
            story_list = []
            if with_story and n == 1:
                story_list = [{'event_id': 'e', 'content_version': 'v1', 'title': '真实消息', 'url': 'https://example.test', 'published_at': (batch_end-dt.timedelta(minutes=10)).isoformat()}]
            batch = {'schema_version': 1, 'batch_id': batch_id,
                     'window_start': (batch_end-dt.timedelta(hours=2)).isoformat(), 'window_end': batch_end.isoformat(),
                     'status': 'reviewed', 'source_run_ids': [run_id], 'coverage_gaps': [], 'stories': story_list,
                     'special_reports': [], 'coverage_status': 'complete'}
            path = root / 'research/news-batches' / batch_id / 'batch.json'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(batch), encoding='utf-8')
        return date

    def test_requires_six_valid_reviewed_batches_and_zero_bundled_stories(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); date = self._fixture(root)
            report, draft = prepare(date, 'morning', root)
            self.assertEqual(report['report_kind'], 'status_only')
            self.assertEqual(report['stories'], [])
            self.assertEqual(report['status_summary']['batch_count'], 6)
            self.assertEqual(report['status_summary']['coverage_status'], 'complete')
            self.assertEqual(report['charts'], {'prices': {'rows': []}, 'fast': {'rows': []}, 'benchmarks': {}})
            self.assertEqual(len(report['source_batch_ids']), 6)
            self.assertEqual(len(report['source_run_ids']), 6)
            self.assertIn('完整', report['status_summary']['narration'])
            self.assertEqual(report['presentation']['version'], 8)
            self.assertEqual(report['presentation']['issue_title'], 'AI早报')
            self.assertEqual(report['presentation']['issue_time'], '2026-10-13T08:00:00+08:00')
            self.assertEqual(draft['voice']['provider'], 'seed')
            self.assertEqual([scene['id'] for scene in draft['scenes']], ['opening', 'closing'])
            self.assertEqual(len(narration_scenes(draft)), 2)
            validate_report_window(report)
            self.assertNotEqual(report_fingerprint(report), report_fingerprint({**report, 'status_summary': {**report['status_summary'], 'coverage_status': 'partial'}}))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); date = self._fixture(root, with_story=True)
            with self.assertRaisesRegex(ValueError, 'zero stories'):
                prepare(date, 'morning', root)

    def test_partial_coverage_wording_does_not_claim_no_news_exists(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); date = self._fixture(root)
            path = root / 'research/news-batches/2026-10-13/0600/batch.json'
            batch = json.loads(path.read_text())
            batch['coverage_status'] = 'partial'
            batch['coverage_gaps'] = [{'id': 'feed', 'status': 'failed'}]
            path.write_text(json.dumps(batch), encoding='utf-8')
            report, draft = prepare(date, 'morning', root)
            self.assertEqual(report['status_summary']['coverage_status'], 'partial')
            self.assertEqual(report['presentation']['version'], 8)
            self.assertEqual(report['presentation']['issue_title'], 'AI早报')
            self.assertEqual(report['presentation']['issue_time'], '2026-10-13T08:00:00+08:00')
            self.assertIn('覆盖不完整', report['status_summary']['narration'])
            joined = ' '.join(line for scene in draft['scenes'] for line in scene['lines'])
            self.assertIn('全网没有相关新闻', joined)
            self.assertIn('确认新增可发布消息零条', joined)
            self.assertEqual(report['coverage']['source_status_counts']['failed'], 1)
            with tempfile.TemporaryDirectory() as out:
                source = Path(out) / 'report.json'
                source.write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
                with patch('build_edition_report.PUBLIC', Path(out) / 'public'):
                    build(source)
                page = (Path(out) / 'public/2026-10-13/morning/index.html').read_text(encoding='utf-8')
                self.assertIn('本期采集状态', page)
                self.assertIn('新增可发布消息0条', page)
                self.assertNotIn('本期消息</h2>', page)

    def test_briefing_status_only_uses_one_reviewed_two_hour_batch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scheduled = '2026-10-13T14:00:00+08:00'
            from news_batch import plan as make_plan
            plan = make_plan(scheduled, root)
            run_id = 'run-briefing'
            run_path = root / 'research/source-watch/runs' / run_id / 'report.json'
            run_path.parent.mkdir(parents=True)
            run_path.write_text(json.dumps({'run_id': run_id}), encoding='utf-8')
            batch = {'schema_version': 1, 'batch_id': plan['batch_id'],
                     'window_start': plan['window_start'], 'window_end': plan['window_end'],
                     'status': 'reviewed', 'source_run_ids': [run_id], 'coverage_gaps': [],
                     'coverage_status': 'partial', 'stories': [], 'special_reports': []}
            path = Path(plan['batch_path']); path.parent.mkdir(parents=True)
            path.write_text(json.dumps(batch), encoding='utf-8')
            report, draft = prepare('2026-10-13', 'briefing', root, scheduled)
            self.assertEqual(report['edition'], 'briefing')
            self.assertEqual(report['output_namespace'], 'briefing-1400')
            self.assertEqual(report['status_summary']['batch_count'], 1)
            self.assertEqual(report['status_summary']['coverage_status'], 'partial')
            self.assertEqual(report['presentation']['version'], 8)
            self.assertEqual(report['presentation']['issue_title'], 'AI此刻')
            self.assertEqual(report['presentation']['issue_time'], scheduled)
            self.assertEqual(report['window_start'], '2026-10-13T12:00:00+08:00')
            self.assertEqual(report['window_end'], '2026-10-13T14:00:00+08:00')
            self.assertEqual([scene['id'] for scene in draft['scenes']], ['opening', 'closing'])
            validate_report_window(report)


if __name__ == '__main__':
    unittest.main()
