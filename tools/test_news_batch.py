import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from news_batch import bundle, plan


class NewsBatchTests(unittest.TestCase):
    def test_cross_midnight_batch_ids_and_paths(self):
        p = plan('2026-10-14T00:00:00+08:00', '/tmp/root')
        self.assertEqual(p['batch_id'], '2026-10-14/0000')
        self.assertTrue(p['batch_path'].endswith('research/news-batches/2026-10-14/0000/batch.json'))
        self.assertEqual(p['window_start'], '2026-10-13T22:00:00+08:00')
        p22 = plan('2026-10-13T22:00:00+08:00', '/tmp/root')
        self.assertEqual(p22['batch_id'], '2026-10-13/2200')
        self.assertEqual(p22['edition'], 'briefing')
        self.assertEqual(p22['edition_date'], '2026-10-13')
        self.assertEqual(p22['output_namespace'], 'briefing-2200')
        self.assertEqual((p22['owning_digest_date'], p22['owning_digest_edition']), ('2026-10-14', 'morning'))
        self.assertEqual(p22['digest_batch_ids'], ['2026-10-13/2200', '2026-10-14/0000', '2026-10-14/0200', '2026-10-14/0400', '2026-10-14/0600', '2026-10-14/0800'])
        self.assertEqual(len(p22['digest_batch_paths']), 6)

    def test_digest_contains_exact_six_nonoverlapping_windows(self):
        for date, edition, end_hour in [('2026-10-13', 'morning', 8), ('2026-10-13', 'evening', 20)]:
            p = plan(f'{date}T{end_hour:02d}:00:00+08:00', '/tmp/root')
            self.assertTrue(p['is_digest'])
            self.assertEqual(len(p['edition_batch_ids']), 6)
            self.assertEqual(p['edition_batch_ids'][-1], p['batch_id'])
            times = []
            for batch_id in p['edition_batch_ids']:
                day, hh = batch_id.split('/')
                times.append(dt.datetime.fromisoformat(f'{day}T{hh[:2]}:00:00+08:00'))
            for left, right in zip(times, times[1:]):
                self.assertEqual(right - left, dt.timedelta(hours=2))
            self.assertEqual(times[-1].hour, end_hour)

    def test_evening_batch_starting_at_eight_is_not_digest(self):
        p = plan('2026-10-13T10:00:00+08:00', '/tmp/root')
        self.assertEqual(p['edition'], 'briefing')
        self.assertFalse(p['is_digest'])
        self.assertEqual(p['window_start'], '2026-10-13T08:00:00+08:00')

    def test_daily_schedule_has_twelve_unique_video_outputs_and_no_double_production(self):
        video_slots = []
        for hour in range(24):
            if hour % 2:
                continue
            p = plan(f'2026-10-13T{hour:02d}:00:00+08:00', '/tmp/root')
            if p['output_namespace']:
                video_slots.append((hour, p['video_kind'], p['output_namespace']))
            self.assertFalse(p['should_make_batch_video'] and p['video_kind'] == 'digest')
            self.assertEqual(p['should_make_batch_video'], p['video_kind'] == 'briefing')
        self.assertEqual(len(video_slots), 12)
        self.assertEqual(len({namespace for _, _, namespace in video_slots}), 12)
        for hour in (8, 20):
            p = plan(f'2026-10-13T{hour:02d}:00:00+08:00', '/tmp/root')
            self.assertEqual(p['video_kind'], 'digest')
            self.assertFalse(p['should_make_batch_video'])
        p = plan('2026-10-13T14:00:00+08:00', '/tmp/root')
        self.assertEqual((p['edition'], p['output_namespace'], p['issue_title']), ('briefing', 'briefing-1400', 'AI此刻'))
        self.assertEqual(len(p['edition_batch_ids']), 1)
        self.assertEqual(p['edition_batch_ids'], ['2026-10-13/1400'])
        self.assertEqual((p['owning_digest_date'], p['owning_digest_edition']), ('2026-10-13', 'evening'))
        self.assertEqual(p['digest_batch_ids'], ['2026-10-13/1000', '2026-10-13/1200', '2026-10-13/1400', '2026-10-13/1600', '2026-10-13/1800', '2026-10-13/2000'])
        self.assertEqual(len(p['digest_batch_paths']), 6)

    def test_midnight_briefing_uses_new_date_namespace_and_two_hour_window(self):
        p = plan('2026-10-14T00:00:00+08:00', '/tmp/root')
        self.assertEqual((p['edition_date'], p['edition'], p['output_namespace']), ('2026-10-14', 'briefing', 'briefing-0000'))
        self.assertEqual((p['window_start'], p['window_end']), ('2026-10-13T22:00:00+08:00', '2026-10-14T00:00:00+08:00'))

    def test_rejects_missing_timezone_and_non_even_hour(self):
        for value in ('2026-10-13T14:00:00', '2026-10-13T15:00:00+08:00', '2026-10-13T14:01:00+08:00'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                plan(value, '/tmp/root')

    def test_explicit_late_invocation_keeps_requested_window(self):
        p = plan('2026-10-13T14:00:00+08:00', '/tmp/root')
        self.assertEqual(p['window_start'], '2026-10-13T12:00:00+08:00')
        self.assertEqual(p['window_end'], '2026-10-13T14:00:00+08:00')
        self.assertFalse(p['inferred'])

    def _write_reviewed(self, root, ref, stories=None, coverage_gaps=None):
        path = Path(ref['batch_path']); path.parent.mkdir(parents=True, exist_ok=True)
        run_path = Path(root) / 'research/source-watch/runs/run-real-1/report.json'
        run_path.parent.mkdir(parents=True, exist_ok=True); run_path.write_text('{"run_id":"run-real-1"}', encoding='utf-8')
        payload = {'schema_version': 1, 'batch_id': ref['batch_id'],
                   'window_start': ref['window_start'], 'window_end': ref['window_end'],
                   'status': 'reviewed', 'source_run_ids': ['run-real-1'],
                   'coverage_gaps': coverage_gaps or [], 'stories': stories or [], 'special_reports': []}
        path.write_text(json.dumps(payload), encoding='utf-8')
        return path

    def test_missing_corrupt_and_partial_batches_return_gaps_and_keep_valid_story(self):
        with tempfile.TemporaryDirectory() as temp:
            p = plan('2026-10-13T08:00:00+08:00', temp)
            refs = []
            for batch_id in p['edition_batch_ids']:
                day, hour = batch_id.split('/')
                end = f'{day}T{hour[:2]}:00:00+08:00'
                # Plan path metadata for each fixed interval.
                refs.append(plan(end, temp))
            refs[0]['batch_path'] = str(Path(temp) / 'research/news-batches' / p['edition_batch_ids'][0] / 'batch.json')
            first = refs[0]
            story = {'event_id': 'e1', 'content_version': 'v1', 'title': 'one', 'url': 'https://example.test/1',
                     'published_at': '2026-10-12T21:00:00+08:00'}
            self._write_reviewed(temp, first, [story], ['one source incomplete'])
            second_path = Path(temp) / 'research/news-batches' / p['edition_batch_ids'][1] / 'batch.json'
            second_path.parent.mkdir(parents=True, exist_ok=True); second_path.write_text('{broken', encoding='utf-8')
            result, incomplete = bundle('2026-10-13', 'morning', temp)
            self.assertTrue(incomplete)
            self.assertEqual(len(result['batch_refs']), 6)
            self.assertEqual(len(result['stories']), 1)
            self.assertTrue(result['missing_invalid_coverage_gaps'])
            self.assertFalse(result['production_verified'])

    def test_unreviewed_batch_and_mismatched_source_report_do_not_contribute_stories(self):
        with tempfile.TemporaryDirectory() as temp:
            p = plan('2026-10-13T08:00:00+08:00', temp)
            bid = p['edition_batch_ids'][0]
            day, hour = bid.split('/')
            ref = {'batch_id': bid, 'batch_path': str(Path(temp) / 'research/news-batches' / bid / 'batch.json'),
                   'window_start': (dt.datetime.fromisoformat(f'{day}T{hour[:2]}:00:00+08:00') - dt.timedelta(hours=2)).isoformat(),
                   'window_end': f'{day}T{hour[:2]}:00:00+08:00'}
            story = {'event_id': 'e1', 'content_version': 'v1', 'title': 'one', 'url': 'https://example.test/1',
                     'published_at': '2026-10-12T21:00:00+08:00'}
            self._write_reviewed(temp, ref, [story])
            batch_path = Path(ref['batch_path'])
            payload = json.loads(batch_path.read_text(encoding='utf-8'))
            payload['status'] = 'planned'
            batch_path.write_text(json.dumps(payload), encoding='utf-8')
            report_path = Path(temp) / 'research/source-watch/runs/run-real-1/report.json'
            report_path.write_text('{"run_id":"different"}', encoding='utf-8')
            result, incomplete = bundle('2026-10-13', 'morning', temp)
            self.assertTrue(incomplete)
            self.assertEqual(result['stories'], [])
            first = result['batch_refs'][0]
            self.assertEqual(first['source_run_ids'], ['run-real-1'])
            self.assertEqual(first['status'], 'invalid')
            self.assertTrue(any('status is not reviewed' in x['reason'] for x in result['missing_invalid_coverage_gaps']))
            self.assertTrue(any('run_id mismatch' in x['reason'] for x in result['missing_invalid_coverage_gaps']))

    def test_deduplicates_same_version_but_keeps_versions_and_batch_refs(self):
        with tempfile.TemporaryDirectory() as temp:
            p = plan('2026-10-13T08:00:00+08:00', temp)
            batch_ids = p['edition_batch_ids']
            timestamps = ['2026-10-12T21:00:00+08:00', '2026-10-12T23:00:00+08:00']
            for idx in (0, 1):
                day, hour = batch_ids[idx].split('/')
                ref = {'batch_id': batch_ids[idx], 'batch_path': str(Path(temp) / 'research/news-batches' / batch_ids[idx] / 'batch.json'),
                       'window_start': (dt.datetime.fromisoformat(f'{day}T{hour[:2]}:00:00+08:00') - dt.timedelta(hours=2)).isoformat(),
                       'window_end': f'{day}T{hour[:2]}:00:00+08:00'}
                base = {'event_id': 'same', 'title': 'same', 'url': 'https://example.test/same'}
                s1 = {**base, 'content_version': 'v1', 'published_at': timestamps[idx]}
                stories = [s1, {**base, 'content_version': 'v2', 'published_at': timestamps[idx]}]
                self._write_reviewed(temp, ref, stories)
            result, incomplete = bundle('2026-10-13', 'morning', temp)
            self.assertTrue(incomplete)  # four other batches are absent
            self.assertEqual(len(result['stories']), 2)
            same = [s for s in result['stories'] if s['event_id'] == 'same']
            self.assertEqual({s['content_version'] for s in same}, {'v1', 'v2'})
            v1 = next(s for s in same if s['content_version'] == 'v1')
            self.assertEqual(v1['batch_refs'], batch_ids[:2])

    def test_six_empty_reviewed_batches_are_valid_but_missing_run_is_not(self):
        with tempfile.TemporaryDirectory() as temp:
            schedule = plan('2026-10-13T20:00:00+08:00', temp)
            for bid in schedule['edition_batch_ids']:
                day, hour = bid.split('/')
                self._write_reviewed(temp, plan(f'{day}T{hour[:2]}:00:00+08:00', temp))
            result, incomplete = bundle('2026-10-13', 'evening', temp)
            self.assertFalse(incomplete)
            self.assertEqual(result['stories'], [])
            self.assertFalse(result['production_verified'])
            (Path(temp) / 'research/source-watch/runs/run-real-1/report.json').unlink()
            result, incomplete = bundle('2026-10-13', 'evening', temp)
            self.assertTrue(incomplete)
            self.assertTrue(all(ref['status'] == 'invalid' for ref in result['batch_refs']))

    def test_story_at_eight_is_excluded_from_morning_and_allowed_in_evening(self):
        with tempfile.TemporaryDirectory() as temp:
            story = {'event_id': 'boundary', 'content_version': 'v1', 'title': 'boundary',
                     'url': 'https://example.test/boundary', 'published_at': '2026-10-13T08:00:00+08:00'}
            self._write_reviewed(temp, plan('2026-10-13T08:00:00+08:00', temp), [story])
            morning, _ = bundle('2026-10-13', 'morning', temp)
            self.assertEqual(morning['stories'], [])
            self._write_reviewed(temp, plan('2026-10-13T10:00:00+08:00', temp), [story])
            evening, _ = bundle('2026-10-13', 'evening', temp)
            self.assertEqual(len(evening['stories']), 1)

    def test_invalid_window_type_is_reported_as_a_gap(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self._write_reviewed(temp, plan('2026-10-13T08:00:00+08:00', temp))
            data = json.loads(path.read_text())
            data['window_start'] = None
            path.write_text(json.dumps(data))
            result, incomplete = bundle('2026-10-13', 'morning', temp)
            self.assertTrue(incomplete)
            self.assertEqual(result['batch_refs'][-1]['status'], 'invalid')


if __name__ == '__main__':
    unittest.main()
