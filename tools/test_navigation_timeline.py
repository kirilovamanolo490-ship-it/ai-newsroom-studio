import json
import tempfile
import unittest
from pathlib import Path
from completion_gate import _validate_timeline
from edition_contract import report_fingerprint

class NavigationTimelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.manifest=self.root/'own-video.json'
        self.report={'date':'2026-10-14','edition':'morning','stories':[{'id':'industry'},{'id':'models'},{'id':'tools'}],'charts':{},'presentation':{'groups':[{'id':'m','story_ids':['models']},{'id':'t','story_ids':['tools']},{'id':'i','story_ids':['industry']}]}}
    def tearDown(self):self.temp.cleanup()
    def write_timeline(self, order, modern=True, covers=None):
        scenes=[{'id':sid,'startFrame':i*30,'durationInFrames':30} for i,sid in enumerate(['opening',*order,'closing'])]
        ep={'fps':30,'durationInFrames':len(scenes)*30,'source_report_fingerprint':report_fingerprint(self.report),'scenes':scenes}
        if modern:ep.update(sequence_contract='navigation-groups-v1',navigation_story_order=['models','tools','industry'],presentation={**self.report['presentation'],'cover_story_ids':covers or ['models','industry']})
        (self.root/'video-props.json').write_text(json.dumps({'episode':ep}))
        (self.root/'video-chapters.json').write_text(json.dumps([{'id':s['id'],'start_seconds':s['startFrame']/30,'duration_seconds':1} for s in scenes]))
    def test_modern_timeline_follows_navigation_not_story_storage_order(self):
        self.write_timeline(['models','tools','industry'])
        self.assertEqual(_validate_timeline(self.report,self.root,self.manifest)[1],5)
    def test_same_story_set_in_wrong_order_is_rejected(self):
        self.write_timeline(['industry','models','tools'])
        with self.assertRaisesRegex(ValueError,'story_coverage_mismatch'):_validate_timeline(self.report,self.root,self.manifest)
    def test_selected_cover_items_preserve_their_relative_order(self):
        self.write_timeline(['models','tools','industry'],covers=['industry','models'])
        with self.assertRaisesRegex(ValueError,'cover_order_mismatch'):_validate_timeline(self.report,self.root,self.manifest)
    def test_accepted_legacy_timeline_not_retroactively_reordered(self):
        self.write_timeline(['industry','models','tools'],modern=False)
        self.assertEqual(_validate_timeline(self.report,self.root,self.manifest)[1],5)

if __name__=='__main__':unittest.main()
