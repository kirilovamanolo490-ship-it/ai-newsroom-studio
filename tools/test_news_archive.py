import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import news_archive


class NewsArchiveTests(unittest.TestCase):
    def fixture(self, root: Path):
        evidence = root / "research/evidence/2026-10-13/briefing"
        evidence.mkdir(parents=True)
        report = {
            "date": "2026-10-13", "edition": "briefing", "report_kind": "user_requested_news_video",
            "window_start": "2026-10-13T12:00:00+08:00", "window_end": "2026-10-13T14:00:00+08:00",
            "source_batch_ids": ["2026-10-13/1400"],
            "presentation": {"issue_title": "今日AI资讯", "cover_headline": " 事件 A\n重点", "cover_story_ids": ["story-a"]},
            "stories": [{"id": "story-a", "event_id": "event-a", "content_version": "v1",
                         "title": "事件 A", "summary": "摘要", "primary_url": "https://example.test/a",
                         "published_at": "2026-10-13T13:00:00+08:00"}],
            "image_assets": [{"path": "/2026-10-13/briefing/media/a.png", "sha256": "abc"}],
        }
        (evidence / "report.json").write_text(json.dumps(report), encoding="utf-8")
        batch = root / "research/news-batches/2026-10-13/1400"
        batch.mkdir(parents=True)
        (batch / "batch.json").write_text(json.dumps({
            "batch_id": "2026-10-13/1400", "window_start": report["window_start"],
            "window_end": report["window_end"], "status": "reviewed", "coverage_status": "partial",
            "source_run_ids": ["run-real"], "bulletin": "research/evidence/bulletins/2026-10-13/1400/index.html",
            "stories": [{"id": "story-a", "event_id": "event-a", "content_version": "v1",
                         "title": "事件 A", "summary": "摘要", "url": "https://example.test/a",
                         "published_at": "2026-10-13T13:00:00+08:00"}], "special_reports": []
        }), encoding="utf-8")
        state_dir = root / "research/editions"
        state_dir.mkdir(parents=True)
        state = {
            "completed": {},
            "supplemental_completed": {"2026-10-13/briefing": {
                "status": "verified", "title": "当日AI资讯", "report": "research/evidence/2026-10-13/briefing/report.json",
                "web_url": "/2026-10-13/briefing/",
                "video": "/2026-10-13/briefing/missing.mp4", "poster": "/2026-10-13/briefing/missing.png",
                "source_batch_ids": ["2026-10-13/1400"], "coverage_status": "partial",
            }},
            "in_progress": {"2026-10-13/evening": {"status": "failed", "title": "晚报处理中"}},
            "batches": {},
        }
        (state_dir / "production-state.json").write_text(json.dumps(state), encoding="utf-8")

    def test_merge_story_and_same_batch_briefing_without_fake_video(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.fixture(root)
            result = news_archive.rebuild(root)
            data = json.loads((root / "research/evidence/archive/data.json").read_text())
            bulletin = [x for x in data["editions"] if x["kind"] == "bulletin"]
            self.assertEqual(len(bulletin), 1)
            self.assertEqual(bulletin[0]["story_count"], 1)
            self.assertEqual(bulletin[0]["video_status"], "missing")
            self.assertIsNone(bulletin[0]["video_url"])
            self.assertEqual(bulletin[0]["url"], "/2026-10-13/briefing/")
            self.assertEqual(bulletin[0]["bulletin_url"], "/bulletins/2026-10-13/1400/index.html")
            self.assertEqual(bulletin[0]["video_story_count"], 1)
            self.assertNotIn("briefing", [x["kind"] for x in data["editions"]])
            self.assertEqual(len(data["stories"]), 1)
            self.assertEqual(bulletin[0]["title"], "2026年10月13日 今日AI资讯")
            self.assertEqual(bulletin[0]["headline"], "事件 A 重点")
            self.assertEqual(bulletin[0]["summary"], "摘要")
            self.assertEqual(bulletin[0]["headline_source_story_id"], data["stories"][0]["id"])
            self.assertEqual(data["stories"][0]["edition_ids"], [bulletin[0]["id"]])
            self.assertTrue(any(x["status"] == "failed" for x in data["editions"]))
            self.assertEqual(result["counts"]["editions"], len(data["editions"]))
            with sqlite3.connect(root / "research/newsroom/newsroom.sqlite") as con:
                self.assertEqual(con.execute("PRAGMA foreign_key_check").fetchall(), [])
                self.assertEqual(con.execute("SELECT COUNT(*) FROM edition_stories").fetchone()[0], 1)
                self.assertEqual(con.execute("SELECT kind,status FROM editions WHERE kind='evening'").fetchone(), ("evening", "failed"))

    def test_in_progress_single_batch_briefing_merges_and_digest_stays_separate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.fixture(root)

            # Reproduce a batch whose bulletin reference is the object form
            # written by the current collector, while retaining the briefing
            # as in progress and without any completed video.
            bulletin_page = root / "research/evidence/2026-10-13/briefing/index.html"
            bulletin_page.parent.mkdir(parents=True, exist_ok=True)
            bulletin_page.write_text("<main>briefing page</main>", encoding="utf-8")
            batch_path = root / "research/news-batches/2026-10-13/1400/batch.json"
            batch = json.loads(batch_path.read_text(encoding="utf-8"))
            batch["bulletin"] = {
                "path": "research/evidence/2026-10-13/briefing/index.html",
                "status": "in_production",
            }
            batch_path.write_text(json.dumps(batch), encoding="utf-8")

            evening_report_path = root / "research/evidence/2026-10-13/evening/report.json"
            evening_report_path.parent.mkdir(parents=True, exist_ok=True)
            evening_report_path.write_text(json.dumps({
                "date": "2026-10-13", "edition": "evening", "report_kind": "scheduled_digest",
                "window_start": "2026-10-13T08:00:00+08:00", "window_end": "2026-10-13T20:00:00+08:00",
                "source_batch_ids": ["2026-10-13/2000"],
                "stories": [{"id": "story-evening", "event_id": "event-evening", "content_version": "v1",
                             "title": "晚报故事", "url": "https://example.test/evening"}],
            }), encoding="utf-8")
            evening_batch_path = root / "research/news-batches/2026-10-13/2000/batch.json"
            evening_batch_path.parent.mkdir(parents=True)
            evening_batch_path.write_text(json.dumps({
                "batch_id": "2026-10-13/2000", "window_start": "2026-10-13T18:00:00+08:00",
                "window_end": "2026-10-13T20:00:00+08:00", "status": "reviewed",
                "bulletin": {"path": "research/evidence/2026-10-13/evening/index.html", "status": "in_production"},
                "stories": [{"id": "story-evening", "event_id": "event-evening", "content_version": "v1",
                             "title": "晚报故事", "url": "https://example.test/evening"}],
            }), encoding="utf-8")

            state_path = root / "research/editions/production-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["supplemental_completed"] = {}
            state["in_progress"] = {
                "2026-10-13/briefing-1400": {
                    "status": "producing", "title": "今日AI资讯",
                    "report": "research/evidence/2026-10-13/briefing/report.json",
                    "web_url": "/2026-10-13/briefing/",
                },
                "2026-10-13/evening": {
                    "status": "producing", "title": "晚报处理中",
                    "report": "research/evidence/2026-10-13/evening/report.json",
                    "web_url": "/2026-10-13/evening/",
                },
            }
            state_path.write_text(json.dumps(state), encoding="utf-8")

            result = news_archive.rebuild(root)
            data = json.loads((root / "research/evidence/archive/data.json").read_text())
            same_window = [x for x in data["editions"]
                           if x["date"] == "2026-10-13" and x["window_end"] == "2026-10-13T14:00:00+08:00"]
            self.assertEqual(len(same_window), 1)
            briefing = same_window[0]
            self.assertEqual(briefing["kind"], "bulletin")
            self.assertEqual(briefing["url"], "/2026-10-13/briefing/")
            self.assertEqual(briefing["bulletin_url"], "/2026-10-13/briefing/index.html")
            self.assertEqual(briefing["video_status"], "missing")
            self.assertIsNone(briefing["video_url"])
            self.assertEqual(briefing["story_count"], 1)
            briefing_story = next(x for x in data["stories"] if x["event_id"] == "event-a")
            self.assertEqual(briefing_story["edition_ids"], [briefing["id"]])
            batch_row = next(x for x in data["batches"] if x["id"] == "2026-10-13/1400")
            self.assertEqual(batch_row["url"], "/2026-10-13/briefing/index.html")

            evening = [x for x in data["editions"] if x["kind"] == "evening"]
            self.assertEqual(len(evening), 1)
            self.assertEqual(evening[0]["status"], "producing")
            self.assertEqual(evening[0]["batch_ids"], ["2026-10-13/2000"])
            self.assertFalse(any(x["kind"] == "bulletin" and x["window_end"] == "2026-10-13T20:00:00+08:00"
                                 for x in data["editions"]))
            self.assertEqual(result["counts"]["editions"], len(data["editions"]))

    def test_rebuild_is_stable_and_invalid_json_is_warning(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.fixture(root)
            first = news_archive.rebuild(root)
            data_path = root / "research/evidence/archive/data.json"
            one = json.loads(data_path.read_text())
            (root / "research/news-batches/2026-10-13/1600").mkdir(parents=True)
            (root / "research/news-batches/2026-10-13/1600/batch.json").write_text("{bad", encoding="utf-8")
            second = news_archive.rebuild(root)
            two = json.loads(data_path.read_text())
            self.assertEqual([x["id"] for x in one["editions"]], [x["id"] for x in two["editions"]])
            self.assertEqual([x["id"] for x in one["stories"]], [x["id"] for x in two["stories"]])
            self.assertTrue(any(x.startswith("invalid_json:") for x in second["warnings"]))
            self.assertEqual(first["counts"], second["counts"])
            self.assertNotIn(str(root), data_path.read_text())

    def test_public_url_rejects_local_paths_and_traversal(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            evidence_file = root / "research/evidence/2026-10-13/a.png"
            evidence_file.parent.mkdir(parents=True)
            evidence_file.write_bytes(b"x")
            self.assertEqual(news_archive.clean_public_url(str(evidence_file), root), "/2026-10-13/a.png")
            self.assertIsNone(news_archive.clean_public_url("/Users/mac/private/token.txt", root))
            self.assertIsNone(news_archive.clean_public_url("research/evidence/../../.secrets/token", root))
            self.assertIsNone(news_archive.clean_public_url("/bulletins/../private/file", root))
            self.assertIsNone(news_archive.clean_public_url("https://example.test/page?api_key=private", root))
            self.assertEqual(news_archive.truthy_status({"status": "verified"}, "/../../private.mp4", root), ("missing", None))
            self.assertEqual(news_archive.canonical_source_url("https://EXAMPLE.test/a?utm_source=x&lang=zh#section"),
                             "https://example.test/a?lang=zh")

    def test_url_alias_merges_no_version_report_and_versioned_batch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.fixture(root)
            report_path = root / "research/evidence/2026-10-13/briefing/report.json"
            report = json.loads(report_path.read_text())
            report["stories"] = [{"id": "report-local-id", "title": "事件 A 精编标题",
                                  "primary_url": "https://example.test/a?utm_campaign=x#top",
                                  "summary": "report summary", "published_at": "2026-10-13T13:00:00+08:00"}]
            report_path.write_text(json.dumps(report), encoding="utf-8")
            news_archive.rebuild(root)
            data = json.loads((root / "research/evidence/archive/data.json").read_text())
            self.assertEqual(len(data["stories"]), 1)
            self.assertEqual(data["stories"][0]["event_id"], "event-a")
            self.assertEqual(data["stories"][0]["content_version"], "v1")
            self.assertEqual(data["stories"][0]["edition_ids"], [next(e["id"] for e in data["editions"] if e["kind"] == "bulletin")])

    def test_story_batches_use_membership_not_digest_batch_list(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.fixture(root)
            # A scheduled digest cites two batches, but each item belongs only
            # to the batch manifest that actually contains it.
            batch2 = root / "research/news-batches/2026-10-13/1600"
            batch2.mkdir(parents=True)
            (batch2 / "batch.json").write_text(json.dumps({
                "batch_id": "2026-10-13/1600", "window_start": "2026-10-13T14:00:00+08:00",
                "window_end": "2026-10-13T16:00:00+08:00", "status": "reviewed", "coverage_status": "unknown",
                "stories": [{"id": "story-b", "event_id": "event-b", "content_version": "v1",
                             "title": "事件 B", "url": "https://example.test/b"}]
            }), encoding="utf-8")
            morning = root / "research/evidence/2026-10-13/morning"
            morning.mkdir(parents=True)
            (morning / "report.json").write_text(json.dumps({
                "date": "2026-10-13", "edition": "morning", "source_batch_ids": ["2026-10-13/1400", "2026-10-13/1600"],
                "stories": [{"id": "story-a", "event_id": "event-a", "content_version": "v1", "title": "事件 A", "url": "https://example.test/a"},
                            {"id": "story-b", "event_id": "event-b", "content_version": "v1", "title": "事件 B", "url": "https://example.test/b"}]
            }), encoding="utf-8")
            state_path = root / "research/editions/production-state.json"
            state = json.loads(state_path.read_text())
            state["completed"] = {"2026-10-13/morning": {"status": "verified", "report": "research/evidence/2026-10-13/morning/report.json"}}
            state_path.write_text(json.dumps(state), encoding="utf-8")
            news_archive.rebuild(root)
            data = json.loads((root / "research/evidence/archive/data.json").read_text())
            by_event = {story["event_id"]: story for story in data["stories"]}
            self.assertEqual(by_event["event-a"]["batch_ids"], ["2026-10-13/1400"])
            self.assertEqual(by_event["event-b"]["batch_ids"], ["2026-10-13/1600"])
            with sqlite3.connect(root / "research/newsroom/newsroom.sqlite") as con:
                self.assertEqual(con.execute("PRAGMA foreign_key_check").fetchall(), [])
                self.assertEqual(con.execute("SELECT COUNT(*) FROM story_batches").fetchone()[0], 2)

    def test_source_event_versions_anchor_editorial_summary_to_real_source_version(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.fixture(root)
            report_path = root / "research/evidence/2026-10-13/briefing/report.json"
            report = json.loads(report_path.read_text())
            report["stories"] = [{
                "id": "story-a", "event_id": "event-a", "content_version": "editorial-summary-digest",
                "title": "事件 A 精编标题", "summary": "完整编辑摘要", "primary_url": "https://example.test/a",
                "url": "https://example.test/a", "published_at": "2026-10-13T13:00:00+08:00",
                "source_event_versions": [{"batch_id": "2026-10-13/1400", "event_id": "event-a",
                    "content_version": "v1", "url": "https://example.test/a"}],
            }]
            report_path.write_text(json.dumps(report), encoding="utf-8")

            news_archive.rebuild(root)
            data = json.loads((root / "research/evidence/archive/data.json").read_text())
            edition = next(x for x in data["editions"] if x["kind"] == "bulletin")
            self.assertEqual(len(data["stories"]), 1)
            self.assertEqual(data["stories"][0]["event_id"], "event-a")
            self.assertEqual(data["stories"][0]["content_version"], "v1")
            self.assertEqual(data["stories"][0]["title"], "事件 A 精编标题")
            self.assertEqual(data["stories"][0]["summary"], "完整编辑摘要")
            self.assertEqual(edition["video_story_count"], 1)

    def test_briefing_lead_story_controls_headline_summary_and_source_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.fixture(root)
            batch_path = root / "research/news-batches/2026-10-13/1400/batch.json"
            batch = json.loads(batch_path.read_text())
            batch["stories"].append({
                "id": "source-claudia", "event_id": "event-claudia", "content_version": "v1",
                "title": "Claudia 公布新音乐模型", "summary": "来源核验后的 Claudia 摘要",
                "url": "https://example.test/claudia", "published_at": "2026-10-13T13:30:00+08:00",
            })
            batch_path.write_text(json.dumps(batch), encoding="utf-8")

            report_path = root / "research/evidence/2026-10-13/briefing/report.json"
            report = json.loads(report_path.read_text())
            report["presentation"]["lead_story_id"] = "claudia-music"
            report["presentation"]["cover_headline"] = "Claudia 发布音乐模型"
            report["stories"] = [
                {"id": "local-workers", "event_id": "event-a", "content_version": "digest-a",
                 "title": "本地工作者进展", "summary": "local-workers 摘要", "primary_url": "https://example.test/a",
                 "source_event_versions": [{"batch_id": "2026-10-13/1400", "event_id": "event-a",
                     "content_version": "v1", "url": "https://example.test/a"}]},
                {"id": "claudia-music", "event_id": "event-claudia", "content_version": "digest-claudia",
                 "title": "Claudia 发布音乐模型", "summary": "Claudia 编辑摘要", "primary_url": "https://example.test/claudia",
                 "source_event_versions": [{"batch_id": "2026-10-13/1400", "event_id": "event-claudia",
                     "content_version": "v1", "url": "https://example.test/claudia"}]},
            ]
            report_path.write_text(json.dumps(report), encoding="utf-8")

            news_archive.rebuild(root)
            data = json.loads((root / "research/evidence/archive/data.json").read_text())
            edition = next(x for x in data["editions"] if x["kind"] == "bulletin")
            by_event = {story["event_id"]: story for story in data["stories"]}
            self.assertEqual(edition["headline"], "Claudia 发布音乐模型")
            self.assertEqual(edition["summary"], "来源核验后的 Claudia 摘要")
            self.assertEqual(edition["headline_source_story_id"], by_event["event-claudia"]["id"])
            self.assertEqual(edition["story_ids"], [by_event["event-a"]["id"], by_event["event-claudia"]["id"]])
            self.assertEqual(by_event["event-claudia"]["content_version"], "v1")

    def test_two_events_merged_in_one_scene_keep_real_source_versions_and_batches(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.fixture(root)
            batch2 = root / "research/news-batches/2026-10-13/1600"
            batch2.mkdir(parents=True)
            (batch2 / "batch.json").write_text(json.dumps({
                "batch_id": "2026-10-13/1600", "window_start": "2026-10-13T14:00:00+08:00",
                "window_end": "2026-10-13T16:00:00+08:00", "status": "reviewed",
                "stories": [{"id": "story-b", "event_id": "event-b", "content_version": "v2",
                    "title": "事件 B 原文", "url": "https://example.test/b", "published_at": "2026-10-13T15:00:00+08:00"}],
            }), encoding="utf-8")
            report_path = root / "research/evidence/2026-10-13/briefing/report.json"
            report = json.loads(report_path.read_text())
            report["source_batch_ids"] = ["2026-10-13/1400", "2026-10-13/1600"]
            report["stories"] = [{
                "id": "scene-ab", "event_id": "event-a", "content_version": "merged-editorial-digest",
                "title": "A与B合并稿", "summary": "一个章节包含两个独立来源事件",
                "primary_url": "https://example.test/a", "url": "https://example.test/a",
                "source_event_versions": [
                    {"batch_id": "2026-10-13/1400", "event_id": "event-a", "content_version": "v1", "url": "https://example.test/a"},
                    {"batch_id": "2026-10-13/1600", "event_id": "event-b", "content_version": "v2", "url": "https://example.test/b"},
                ],
            }]
            report_path.write_text(json.dumps(report), encoding="utf-8")
            state_path = root / "research/editions/production-state.json"
            state = json.loads(state_path.read_text())
            state["completed"] = {"2026-10-13/morning": {"status": "verified", "report": "research/evidence/2026-10-13/briefing/report.json",
                "video": "/2026-10-13/briefing/morning.mp4"}}
            state["supplemental_completed"] = {}
            state_path.write_text(json.dumps(state), encoding="utf-8")

            news_archive.rebuild(root)
            data = json.loads((root / "research/evidence/archive/data.json").read_text())
            edition = next(x for x in data["editions"] if x["kind"] == "morning")
            by_event = {story["event_id"]: story for story in data["stories"]}
            self.assertEqual(set(by_event), {"event-a", "event-b"})
            self.assertEqual(by_event["event-a"]["content_version"], "v1")
            self.assertEqual(by_event["event-b"]["content_version"], "v2")
            self.assertEqual(by_event["event-a"]["batch_ids"], ["2026-10-13/1400"])
            self.assertEqual(by_event["event-b"]["batch_ids"], ["2026-10-13/1600"])
            self.assertEqual(edition["story_ids"], [by_event["event-a"]["id"]])
            self.assertEqual(edition["story_count"], 1)
            self.assertEqual(edition["video_story_count"], 1)
            self.assertIn(edition["id"], by_event["event-b"]["edition_ids"])
            with sqlite3.connect(root / "research/newsroom/newsroom.sqlite") as con:
                self.assertEqual(con.execute("SELECT relation FROM edition_stories WHERE story_id=?", (by_event["event-b"]["id"],)).fetchone(), ("merged_progress",))

    def test_invalid_source_event_version_refs_do_not_create_story_or_relation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.fixture(root)
            report_path = root / "research/evidence/2026-10-13/briefing/report.json"
            report = json.loads(report_path.read_text())
            report["stories"] = [{
                "id": "fake-scene", "event_id": "fake-event", "content_version": "fake-summary-version",
                "title": "伪造来源摘要", "summary": "不能成为读者消息", "primary_url": "https://example.test/fake",
                "source_event_versions": [{"batch_id": "2026-10-13/1400", "event_id": "fake-event",
                    "content_version": "fake-source-version", "url": "https://example.test/fake"}],
            }]
            report_path.write_text(json.dumps(report), encoding="utf-8")

            result = news_archive.rebuild(root)
            data = json.loads((root / "research/evidence/archive/data.json").read_text())
            self.assertNotIn("fake-event", [story["event_id"] for story in data["stories"]])
            self.assertEqual([(story["event_id"], story["content_version"]) for story in data["stories"]], [("event-a", "v1")])
            self.assertTrue(any("invalid_source_event_version_ref" in warning or "primary_source_ref_missing" in warning for warning in result["warnings"]))
            with sqlite3.connect(root / "research/newsroom/newsroom.sqlite") as con:
                self.assertEqual(con.execute("SELECT COUNT(*) FROM edition_stories WHERE relation='merged_progress'").fetchone()[0], 0)

    def test_unreviewed_batch_source_ref_does_not_link_to_edition(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.fixture(root)
            batch_path = root / "research/news-batches/2026-10-13/1400/batch.json"
            batch = json.loads(batch_path.read_text())
            batch["status"] = "in_progress"
            batch_path.write_text(json.dumps(batch), encoding="utf-8")

            report_path = root / "research/evidence/2026-10-13/briefing/report.json"
            report = json.loads(report_path.read_text())
            report["stories"] = [{
                "id": "story-a", "event_id": "event-a", "content_version": "editorial-digest",
                "title": "编辑稿标题", "summary": "编辑稿摘要", "primary_url": "https://example.test/a",
                "source_event_versions": [{"batch_id": "2026-10-13/1400", "event_id": "event-a",
                    "content_version": "v1", "url": "https://example.test/a"}],
            }]
            report_path.write_text(json.dumps(report), encoding="utf-8")
            state_path = root / "research/editions/production-state.json"
            state = json.loads(state_path.read_text())
            state["completed"] = {"2026-10-13/morning": {"status": "verified", "report": "research/evidence/2026-10-13/briefing/report.json",
                "video": "/2026-10-13/briefing/morning.mp4"}}
            state["supplemental_completed"] = {}
            state_path.write_text(json.dumps(state), encoding="utf-8")

            result = news_archive.rebuild(root)
            data = json.loads((root / "research/evidence/archive/data.json").read_text())
            story = next(story for story in data["stories"] if story["event_id"] == "event-a")
            morning = next(edition for edition in data["editions"] if edition["kind"] == "morning")
            self.assertEqual(story["content_version"], "v1")
            self.assertNotIn(morning["id"], story["edition_ids"])
            self.assertEqual(morning["story_ids"], [])
            self.assertTrue(any("unreviewed_batch" in warning for warning in result["warnings"]))
            with sqlite3.connect(root / "research/newsroom/newsroom.sqlite") as con:
                self.assertEqual(con.execute("SELECT COUNT(*) FROM edition_stories WHERE relation='merged_progress'").fetchone()[0], 0)

    def test_pending_and_unmatched_specials_remain_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.fixture(root)
            batch_path = root / "research/news-batches/2026-10-13/1400/batch.json"
            batch = json.loads(batch_path.read_text())
            batch["pending_editorial"] = [{"event_id": "pending-event", "url": "https://example.test/pending",
                                           "reason": "发布时间待核"}]
            batch["special_reports"] = [{"event_id": "unmatched-event", "title": "待补原始故事的专题",
                                         "path": "research/evidence/bulletins/2026-10-13/1400/special/index.html",
                                         "status": "verified"}]
            batch_path.write_text(json.dumps(batch), encoding="utf-8")
            news_archive.rebuild(root)
            data = json.loads((root / "research/evidence/archive/data.json").read_text())
            self.assertNotIn("pending-event", [story["event_id"] for story in data["stories"]])
            special = next(edition for edition in data["editions"] if edition["kind"] == "special")
            self.assertIsNone(special["story_count"])
            bulletin = next(edition for edition in data["editions"] if edition["kind"] == "bulletin")
            self.assertEqual(bulletin["coverage_status"], "partial")
            with sqlite3.connect(root / "research/newsroom/newsroom.sqlite") as con:
                self.assertEqual(con.execute("SELECT status FROM stories WHERE event_id='pending-event'").fetchone(), ("pending",))

    def test_special_reports_deduplicate_across_batches_and_skip_video_companions(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.fixture(root)
            batch_path = root / "research/news-batches/2026-10-13/1400/batch.json"
            batch = json.loads(batch_path.read_text())
            batch["special_reports"] = [
                {"event_id": "event-a", "type": "major_company_change_backfill", "path": "research/evidence/bulletins/2026-10-13/1400/special-a/index.html", "status": "verified"},
                {"type": "user_requested_news_video", "path": "/2026-10-13/briefing/index.html", "status": "verified"},
            ]
            batch_path.write_text(json.dumps(batch), encoding="utf-8")
            batch2 = root / "research/news-batches/2026-10-13/1600"
            batch2.mkdir(parents=True)
            (batch2 / "batch.json").write_text(json.dumps({
                "batch_id": "2026-10-13/1600", "status": "reviewed", "coverage_status": "unknown",
                "stories": [], "special_reports": [{"event_id": "event-a", "type": "major_company_change_backfill",
                    "path": "research/evidence/bulletins/2026-10-13/1400/special-a/index.html", "status": "verified"}]
            }), encoding="utf-8")
            news_archive.rebuild(root)
            data = json.loads((root / "research/evidence/archive/data.json").read_text())
            specials = [edition for edition in data["editions"] if edition["kind"] == "special"]
            self.assertEqual(len(specials), 1)
            self.assertEqual(specials[0]["title"], "事件 A")
            self.assertEqual(specials[0]["story_count"], 1)
            with sqlite3.connect(root / "research/newsroom/newsroom.sqlite") as con:
                eid = specials[0]["id"]
                self.assertEqual(con.execute("SELECT COUNT(*) FROM edition_batches WHERE edition_id=?", (eid,)).fetchone()[0], 2)

    def test_eight_and_twenty_batches_are_digest_inputs_not_short_editions(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.fixture(root)
            for slot, hour in (("0800", "06"), ("2000", "18")):
                folder = root / f"research/news-batches/2026-10-13/{slot}"
                folder.mkdir(parents=True)
                story = {"id": f"story-{slot}", "event_id": f"event-{slot}", "content_version": "v1",
                         "title": f"事件 {slot}", "url": f"https://example.test/{slot}"}
                (folder / "batch.json").write_text(json.dumps({
                    "batch_id": f"2026-10-13/{slot}", "window_start": f"2026-10-13T{hour}:00:00+08:00",
                    "window_end": f"2026-10-13T{slot[:2]}:00:00+08:00", "status": "reviewed",
                    "bulletin": f"research/evidence/bulletins/2026-10-13/{slot}/index.html", "stories": [story]
                }), encoding="utf-8")
            news_archive.rebuild(root)
            data = json.loads((root / "research/evidence/archive/data.json").read_text())
            self.assertFalse(any(e["kind"] == "bulletin" and e["date"] == "2026-10-13" and e["scheduled_at"] in ("2026-10-13T08:00:00+08:00", "2026-10-13T20:00:00+08:00") for e in data["editions"]))
            for slot in ("0800", "2000"):
                batch = next(row for row in data["batches"] if row["slot"] == slot)
                self.assertEqual(batch["edition_ids"], [])
                self.assertIsNotNone(batch["url"])
                story = next(s for s in data["stories"] if s["event_id"] == f"event-{slot}")
                self.assertEqual(story["batch_ids"], [f"2026-10-13/{slot}"])


if __name__ == "__main__":
    unittest.main()
