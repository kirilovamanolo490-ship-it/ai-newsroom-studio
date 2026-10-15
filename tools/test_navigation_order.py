import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from edition_contract import navigation_story_order, validate_narration_order


def report():
    return {
        'stories': [{'id': 'model'}, {'id': 'tool'}, {'id': 'company'}],
        'presentation': {'groups': [
            {'id': 'models', 'story_ids': ['model']},
            {'id': 'tools', 'story_ids': ['tool']},
            {'id': 'companies', 'story_ids': ['company']},
        ]},
    }


class NavigationOrderTests(unittest.TestCase):
    def test_rejects_scene_order_that_disagrees_with_groups(self):
        with self.assertRaisesRegex(ValueError, 'Narration scene order'):
            validate_narration_order(report(), [
                {'id': 'opening'}, {'id': 'tool'}, {'id': 'model'},
                {'id': 'company'}, {'id': 'closing'},
            ])

    def test_groups_must_cover_each_story_once(self):
        invalid_groups = [
            [{'story_ids': ['model', 'tool']}],  # missing
            [{'story_ids': ['model', 'tool', 'tool', 'company']}],  # duplicate
            [{'story_ids': ['model', 'tool', 'company', 'unknown']}],  # unknown
        ]
        for groups in invalid_groups:
            candidate = report()
            candidate['presentation']['groups'] = groups
            with self.subTest(groups=groups), self.assertRaises(ValueError):
                navigation_story_order(candidate)

    def test_valid_group_order_and_scene_order(self):
        candidate = report()
        self.assertEqual(navigation_story_order(candidate), ['model', 'tool', 'company'])
        expected_scenes = [{'id': sid} for sid in ['opening', 'model', 'tool', 'company', 'closing']]
        self.assertEqual(validate_narration_order(candidate, expected_scenes),
                         ['opening', 'model', 'tool', 'company', 'closing'])

    def test_reports_without_groups_keep_stories_order(self):
        candidate = {'stories': [{'id': 'second'}, {'id': 'first'}]}
        self.assertEqual(navigation_story_order(candidate), ['second', 'first'])
        scenes = [{'id': sid} for sid in ['opening', 'second', 'first', 'closing']]
        validate_narration_order(candidate, scenes)

    def test_status_only_has_no_story_ids_but_keeps_bookends(self):
        candidate = {'report_kind': 'status_only', 'stories': []}
        self.assertEqual(navigation_story_order(candidate), [])
        self.assertEqual(validate_narration_order(candidate, [{'id': 'opening'}, {'id': 'closing'}]),
                         ['opening', 'closing'])


if __name__ == '__main__':
    unittest.main()
