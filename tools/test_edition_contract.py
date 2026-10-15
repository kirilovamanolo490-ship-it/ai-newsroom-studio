import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from edition_contract import edition_window, validate_report_window, report_namespace


def briefing_report():
    return {
        'date': '2026-10-13',
        'edition': 'briefing',
        'window_start': '2026-10-13T12:00:00+08:00',
        'window_end': '2026-10-13T14:00:00+08:00',
        'stories': [
            {'id': 'a', 'published_at': '2026-10-13T13:15:00+08:00'},
        ],
    }


class EditionContractTests(unittest.TestCase):
    def test_supplemental_namespace_cannot_replace_digest_or_escape_folder(self):
        report = briefing_report()
        report['output_namespace'] = 'briefing-1600'
        self.assertEqual(report_namespace(report), 'briefing-1600')
        for namespace in ['morning', 'evening', '../briefing', 'briefing/1600']:
            with self.assertRaises(ValueError):
                report_namespace({'edition': 'briefing'}, namespace)
        with self.assertRaises(ValueError):
            report_namespace({'edition': 'morning'}, 'briefing-1600')
        with self.assertRaises(ValueError):
            report_namespace(report, 'briefing')

    def test_second_briefing_web_preserves_accepted_first_briefing(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'research/report-redesign'))
        from build_edition_report import build
        report = briefing_report()
        report.update(output_namespace='briefing-1600', evidence_cutoff=report['window_end'], charts=[])
        report['stories'] = [{'id': 'a', 'title': '新批消息', 'summary': '已核摘要',
                             'published_at': '2026-10-13T13:15:00+08:00', 'primary_url': 'https://example.test/source'}]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = root / report['date'] / 'briefing' / 'index.html'
            first.parent.mkdir(parents=True)
            first.write_text('accepted-first-briefing', encoding='utf-8')
            source = root / 'report.json'
            source.write_text(json.dumps(report), encoding='utf-8')
            with patch('build_edition_report.PUBLIC', root):
                build(source)
            self.assertIn('新批消息', (root / report['date'] / 'briefing-1600/index.html').read_text())
            self.assertEqual(first.read_text(), 'accepted-first-briefing')

    def test_fixed_digest_windows_remain_unchanged(self):
        self.assertEqual(
            edition_window('2026-10-13', 'morning'),
            (dt.datetime.fromisoformat('2026-10-12T20:00:00+08:00'),
             dt.datetime.fromisoformat('2026-10-13T08:00:00+08:00')),
        )
        self.assertEqual(
            edition_window('2026-10-13', 'evening'),
            (dt.datetime.fromisoformat('2026-10-13T08:00:00+08:00'),
             dt.datetime.fromisoformat('2026-10-13T20:00:00+08:00')),
        )

    def test_briefing_accepts_explicit_non_digest_window_and_checks_story_times(self):
        report = briefing_report()
        report['stories'].append({'id': 'b', 'published_at': '2026-10-13T20:59:00Z'})
        with self.assertRaisesRegex(ValueError, 'outside the briefing window'):
            validate_report_window(report)
        report['stories'].pop()
        validate_report_window(report)

    def test_briefing_requires_timezone_and_ordered_window(self):
        report = briefing_report()
        report['window_start'] = '2026-10-13T12:00:00'
        with self.assertRaisesRegex(ValueError, 'include timezones'):
            validate_report_window(report)
        report = briefing_report()
        report['window_end'] = '2026-10-13T11:59:00+08:00'
        with self.assertRaisesRegex(ValueError, 'later than window_start'):
            validate_report_window(report)

    def test_briefing_web_title_hides_schedule_window_but_keeps_source_timestamp(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'research/report-redesign'))
        from build_edition_report import build

        report = briefing_report()
        report['evidence_cutoff'] = '2026-10-13T14:00:00+08:00'
        report['stories'] = [{
            'id': 'a', 'title': '一条消息', 'summary': '摘要',
            'published_at': '2026-10-13T13:15:00+08:00',
            'primary_url': 'https://example.test/source', 'source_name': '示例来源',
            'details': '核验补充', 'qualification': '仍需核对',
        }]
        report['charts'] = []
        report['image_assets'] = []
        report['brand_assets'] = []
        report['presentation'] = {'issue_title': '今日AI资讯', 'show_schedule_time': False}

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'report.json'
            source.write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
            old_date_index = root / '2026-10-13' / 'index.html'
            old_date_index.parent.mkdir(parents=True)
            old_date_index.write_text('preserve-date-root', encoding='utf-8')
            site_index = root / 'index.html'
            site_index.write_text('preserve-site-root', encoding='utf-8')
            with patch('build_edition_report.PUBLIC', root):
                build(source)
            page = (root / '2026-10-13/briefing/index.html').read_text(encoding='utf-8')
            self.assertIn('<h1>10月13日 今日AI资讯</h1>', page)
            self.assertNotIn('本期覆盖', page)
            self.assertNotIn('12:00 — 14:00', page)
            self.assertIn('原文发布时间：', page)
            self.assertIn('2026-10-13T13:15:00+08:00', page)
            self.assertEqual(old_date_index.read_text(encoding='utf-8'), 'preserve-date-root')
            self.assertEqual(site_index.read_text(encoding='utf-8'), 'preserve-site-root')


if __name__ == '__main__':
    unittest.main()
