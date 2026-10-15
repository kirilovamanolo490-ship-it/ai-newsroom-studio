import datetime as dt
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import social_publisher as sp


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base
        self.private = self.base / ".secrets/social-publisher"
        self.evidence = self.base / "research/evidence"
        self.private.mkdir(parents=True)
        self.date, self.edition, self.namespace = "2026-10-14", "morning", None
        self.clock_value = dt.datetime(2026, 10, 14, 9, tzinfo=sp.TZ)
        self.patch_constants = patch.multiple(sp, ROOT=self.root, PRIVATE=self.private, EVIDENCE=self.evidence)
        self.patch_constants.start()
        self.report, self.video, self.poster = self.make_edition(self.date, self.edition)
        self.config_value = {"enabled": True, "not_before": "2026-10-14T08:00:00+08:00", "platforms": {
            "bilibili": {"account": "bili", "confirmed": False, "tid": None},
            "douyin": {"account": "douyin", "confirmed": True},
            "xiaohongshu": {"account": "xhs", "confirmed": False},
            "youtube": {"account": "yt", "confirmed": False, "visibility": "public"}}}
        (self.private / "config.json").write_text(json.dumps(self.config_value), encoding="utf-8")
        self.clock = patch.object(sp, "now_local", side_effect=lambda: self.clock_value)
        self.clock.start()
        def verified(report_path, manifest_path, date=None, edition=None, namespace=None):
            report = sp.read_json(report_path)
            video_path = self.evidence / date / (namespace or edition) / "video.mp4"
            return report, {"status": "verified", "path": str(video_path), "sha256": hashlib.sha256(video_path.read_bytes()).hexdigest()}, "fp-" + (namespace or edition)
        self.verified = patch.object(sp, "verified", side_effect=verified)
        self.verified.start()
        self.preflight = patch.object(sp, "account_check", side_effect=lambda platform, account: (True, ""))
        self.preflight.start()
        self.write_package()

    def tearDown(self):
        patch.stopall()
        self.tmp.cleanup()

    def make_edition(self, date, edition, namespace=None):
        folder = namespace or edition
        out = self.evidence / date / folder
        out.mkdir(parents=True, exist_ok=True)
        video, poster = out / "video.mp4", out / "poster.png"
        video.write_bytes(("video-" + folder).encode())
        poster.write_bytes(("poster-" + folder).encode())
        if edition == "briefing":
            hour = int(namespace[9:11])
            end = dt.datetime.combine(dt.date.fromisoformat(date), dt.time(hour), sp.TZ)
            start = end - dt.timedelta(hours=2)
            story = {"id": "lead", "title": "Lead story title", "summary": "Lead summary with the material fact.",
                     "published_at": (start + dt.timedelta(minutes=15)).isoformat(), "related": [{"url": "https://example.com/source"}]}
            report = {"date": date, "edition": "briefing", "output_namespace": namespace,
                      "report_kind": "scheduled_digest", "timezone": "Asia/Shanghai",
                      "window_start": start.isoformat(), "window_end": end.isoformat(), "evidence_cutoff": end.isoformat(),
                      "stories": [story], "charts": [], "presentation": {"lead_story_id": "lead", "cover_headline": "Cover lead\nMain fact"}}
        else:
            report = {"date": date, "edition": edition, "report_kind": "scheduled_digest", "timezone": "Asia/Shanghai",
                      "window_start": date + "T08:00:00+08:00", "window_end": date + "T20:00:00+08:00",
                      "evidence_cutoff": date + "T20:00:00+08:00", "stories": [
                          {"id": "lead", "title": "Lead story title", "summary": "Lead summary with the material fact.", "related": [{"url": "https://example.com/source"}]},
                          {"id": "other", "title": "Other story", "summary": "This must not enter the caption."}],
                      "charts": [], "presentation": {"lead_story_id": "lead", "cover_headline": "Cover lead\nMain fact"}}
        (out / "report.json").write_text(json.dumps(report), encoding="utf-8")
        manifest = {"date": date, "edition": edition, "window_start": report["window_start"],
                    "window_end": report["window_end"], "poster": f"/{date}/{folder}/poster.png"}
        (out / "own-video.json").write_text(json.dumps(manifest), encoding="utf-8")
        return report, video, poster

    def write_package(self):
        package = sp.make_package(self.date, self.edition, self.namespace)
        sp.atomic_json(sp.package_path(self.date, self.edition, self.namespace), package)
        return package

    def set_bindings(self, *names):
        for platform, binding in self.config_value["platforms"].items():
            binding["confirmed"] = platform in names
        (self.private / "config.json").write_text(json.dumps(self.config_value), encoding="utf-8")

    def successful_run(self, stdout="submitted"):
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    def test_only_confirmed_platforms_are_targeted_and_unbound_are_skipped(self):
        with patch.object(sp, "run", return_value=self.successful_run()) as uploader:
            result = sp.publish(self.date, self.edition)
        self.assertEqual(result["target_platforms"], ["douyin"])
        self.assertEqual(result["results"][0]["status"], "submitted_unverified")
        self.assertTrue(result["results"][0]["submission_complete"])
        self.assertFalse(result["results"][0]["needs_verification"])
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(len(uploader.call_args_list), 1)
        doctor = sp.doctor()
        self.assertEqual(doctor["target_platforms"], ["douyin"])
        self.assertEqual(doctor["platforms"]["youtube"]["status"], "skipped_unbound")
        state = sp.status(self.date, self.edition)
        self.assertEqual(state["target_platforms"], ["douyin"])
        self.assertEqual(next(x for x in state["results"] if x["platform"] == "youtube")["status"], "skipped_unbound")

    def test_later_confirmed_bilibili_joins_without_repeating_douyin(self):
        with patch.object(sp, "run", return_value=self.successful_run()) as first:
            sp.publish(self.date, self.edition)
        self.assertEqual(len(first.call_args_list), 1)
        self.config_value["platforms"]["bilibili"].update(confirmed=True, tid=201)
        (self.private / "config.json").write_text(json.dumps(self.config_value), encoding="utf-8")
        with patch.object(sp, "run", return_value=self.successful_run()) as second:
            result = sp.publish(self.date, self.edition)
        self.assertEqual([c.args[0][1] for c in second.call_args_list], ["bilibili"])
        self.assertEqual(result["target_platforms"], ["bilibili", "douyin"])

    def test_bad_bilibili_tid_is_platform_failure_and_douyin_still_submits(self):
        self.config_value["platforms"]["bilibili"]["confirmed"] = True
        (self.private / "config.json").write_text(json.dumps(self.config_value), encoding="utf-8")
        with patch.object(sp, "run", return_value=self.successful_run()) as uploader:
            result = sp.publish(self.date, self.edition)
        self.assertEqual(result["results"][0]["status"], "preflight_failed")
        self.assertEqual(result["results"][0]["reason"], "bilibili_tid_required")
        self.assertEqual([c.args[0][1] for c in uploader.call_args_list], ["douyin"])
        self.assertFalse((sp.state_dir(self.date, self.edition) / "bilibili.json").exists())

    def test_no_active_binding_fails_cleanly(self):
        self.set_bindings()
        with self.assertRaisesRegex(ValueError, "no_bound_accounts"):
            sp.publish(self.date, self.edition)
        self.assertEqual(sp.doctor()["target_platforms"], [])
        self.assertEqual(sp.status(self.date, self.edition)["status"], "no_bound_accounts")

    def test_missing_cookie_is_per_platform_preflight_failure(self):
        with patch.object(sp, "account_check", return_value=(False, "cookie_missing")), patch.object(sp, "run") as uploader:
            result = sp.publish(self.date, self.edition)
        uploader.assert_not_called()
        self.assertEqual(result["results"][0]["status"], "preflight_failed")
        self.assertFalse((sp.state_dir(self.date, self.edition) / "douyin.json").exists())

    def test_briefing_0000_and_0200_have_distinct_package_state_and_keys(self):
        d0, d2 = "2026-10-15", "2026-10-15"
        for ns in ("briefing-0000", "briefing-0200"):
            self.make_edition(d0, "briefing", ns)
            pkg = sp.make_package(d0, "briefing", ns)
            sp.atomic_json(sp.package_path(d0, "briefing", ns), pkg)
        self.assertNotEqual(sp.package_path(d0, "briefing", "briefing-0000"), sp.package_path(d2, "briefing", "briefing-0200"))
        self.assertNotEqual(sp.state_dir(d0, "briefing", "briefing-0000"), sp.state_dir(d2, "briefing", "briefing-0200"))
        self.assertNotEqual(sp.key(d0, "briefing", "douyin", "acct", "briefing-0000"),
                            sp.key(d2, "briefing", "douyin", "acct", "briefing-0200"))

    def test_wrong_briefing_namespace_and_window_are_rejected(self):
        report = self.make_edition("2026-10-15", "briefing", "briefing-0000")[0]
        with self.assertRaisesRegex(ValueError, "report_namespace_mismatch"):
            sp._validate_briefing_window(report, "2026-10-15", "briefing-0200")
        report["window_end"] = "2026-10-15T02:00:00+08:00"
        with self.assertRaisesRegex(ValueError, "briefing_window_mismatch"):
            sp._validate_briefing_window(report, "2026-10-15", "briefing-0000")
        with self.assertRaisesRegex(ValueError, "invalid_briefing_namespace"):
            sp.paths("2026-10-15", "briefing", "briefing-0800")

    def test_briefing_copy_uses_cover_lead_slot_and_only_lead_description(self):
        report, _, _ = self.make_edition("2026-10-15", "briefing", "briefing-0000")
        copy = sp.publication_copy(report, "2026-10-15", "briefing", "briefing-0000")
        self.assertEqual(copy["title"], "Cover lead Main fact｜AI此刻10.15·00点")
        self.assertIn("Lead summary", copy["description"])
        self.assertNotIn("Other story", copy["description"])
        self.assertTrue(copy["platform_titles"]["douyin"].endswith("｜AI此刻10.15·00点"))

    def test_optional_editorial_copy_is_fingerprint_bound_and_platform_title_keeps_suffix(self):
        report, _, _ = self.make_edition("2026-10-15", "briefing", "briefing-0000")
        from edition_contract import report_fingerprint
        copy_path = sp.publishing_copy_path("2026-10-15", "briefing", "briefing-0000")
        copy_path.parent.mkdir(parents=True, exist_ok=True)
        editorial = {"report_fingerprint": report_fingerprint(report), "namespace": "briefing-0000",
                     "headline": "GLM限时100美元额度", "summary": "额度来自服务商公告，不是现金到账。",
                     "platform_titles": {"douyin": "GLM限时100美元额度｜AI此刻10.15·00点"}}
        copy_path.write_text(json.dumps(editorial), encoding="utf-8")
        generated = sp.publication_copy(report, "2026-10-15", "briefing", "briefing-0000")
        self.assertEqual(generated["platform_titles"]["douyin"], editorial["platform_titles"]["douyin"])
        editorial["platform_titles"]["douyin"] = "truncated or missing suffix"
        copy_path.write_text(json.dumps(editorial), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "title_suffix_required"):
            sp.publication_copy(report, "2026-10-15", "briefing", "briefing-0000")

    def test_dispatch_prepares_and_publishes_exact_briefing_namespace(self):
        date, ns = "2026-10-15", "briefing-0000"
        report, _, _ = self.make_edition(date, "briefing", ns)
        from edition_contract import report_fingerprint
        copy_path = sp.publishing_copy_path(date, "briefing", ns)
        copy_path.parent.mkdir(parents=True, exist_ok=True)
        copy_path.write_text(json.dumps({"report_fingerprint": report_fingerprint(report), "namespace": ns,
                                         "headline": "Short GLM headline", "summary": "Service credits are not cash.",
                                         "platform_titles": {"douyin": "GLM100｜AI此刻10.15·00点"}}), encoding="utf-8")
        self.clock_value = dt.datetime(2026, 10, 15, 1, 40, tzinfo=sp.TZ)
        self.config_value["not_before"] = "2026-10-14T20:00:00+08:00"
        (self.private / "config.json").write_text(json.dumps(self.config_value), encoding="utf-8")
        with patch.object(sp, "run", return_value=self.successful_run()) as uploader:
            result = sp.dispatch(date, "briefing", ns)
        saved = sp.read_json(sp.package_path(date, "briefing", ns))
        self.assertEqual(result["namespace"], ns)
        self.assertEqual(saved["namespace"], ns)
        self.assertEqual(saved["edition"], "briefing")
        self.assertEqual(result["target_platforms"], ["douyin"])
        self.assertEqual(len(uploader.call_args_list), 1)

    def test_long_douyin_title_is_only_a_douyin_preflight_failure(self):
        report, _, _ = self.make_edition("2026-10-15", "briefing", "briefing-0000")
        report["presentation"]["cover_headline"] = "这是一个没有编辑缩短的超长封面标题必须等待编辑者确认之后才能发布"
        (self.evidence / "2026-10-15" / "briefing-0000" / "report.json").write_text(json.dumps(report))
        self.clock_value = dt.datetime(2026, 10, 15, 1, 40, tzinfo=sp.TZ)
        self.write_package_for("2026-10-15", "briefing", "briefing-0000")
        with patch.object(sp, "run", return_value=self.successful_run()) as uploader:
            result = sp.publish("2026-10-15", "briefing", "briefing-0000")
        self.assertEqual(result["results"][0]["reason"], "invalid_publication_title")
        uploader.assert_not_called()

    def write_package_for(self, date, edition, namespace):
        package = sp.make_package(date, edition, namespace)
        sp.atomic_json(sp.package_path(date, edition, namespace), package)

    def test_zero_exit_remains_submitted_unverified_and_is_not_retried(self):
        with patch.object(sp, "run", return_value=self.successful_run()) as uploader:
            first = sp.publish(self.date, self.edition)
        self.assertEqual(first["results"][0]["status"], "submitted_unverified")
        uploader.reset_mock()
        second = sp.publish(self.date, self.edition)
        uploader.assert_not_called()
        self.assertEqual(second["results"][0]["status"], "submitted_unverified")

    def test_ambiguous_receipt_never_retries(self):
        directory = sp.state_dir(self.date, self.edition)
        sp.atomic_json(directory / "douyin.json", {"key": sp.key(self.date, self.edition, "douyin", "douyin"),
                                                    "fingerprint": "fp-morning", "status": "ambiguous"}, True)
        with patch.object(sp, "run") as uploader:
            result = sp.publish(self.date, self.edition)
        uploader.assert_not_called()
        self.assertEqual(result["results"][0]["status"], "ambiguous")
        self.assertFalse(result["submission_complete"])
        self.assertEqual(result["needs_attention_platforms"], ["douyin"])

    def test_successful_submissions_exit_zero_without_public_claim_or_second_upload(self):
        import contextlib
        import io
        with patch.object(sp, "run", return_value=self.successful_run()) as uploader:
            sp.publish(self.date, self.edition)
        receipt = sp.state_dir(self.date, self.edition) / "douyin.json"
        original = receipt.read_bytes()
        with patch.object(sp, "run") as uploader, patch.object(sp, "account_check") as check, contextlib.redirect_stdout(io.StringIO()) as output:
            code = sp.main(["dispatch", "--date", self.date, "--edition", self.edition])
        uploader.assert_not_called()
        check.assert_not_called()
        result = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "submitted")
        self.assertTrue(result["publication_workflow_complete"])
        self.assertFalse(result["verification_required"])
        self.assertFalse(result["all_targets_public"])
        self.assertEqual(receipt.read_bytes(), original)

    def test_preflight_failure_is_durable_status_but_not_a_submission_and_can_resume(self):
        self.set_bindings("douyin", "youtube")
        with patch.object(sp, "account_check", side_effect=lambda p, a: (p == "youtube", "account_invalid")), patch.object(sp, "run", return_value=self.successful_run()) as uploader:
            first = sp.dispatch(self.date, self.edition)
        self.assertEqual(first["needs_attention_platforms"], ["douyin"])
        state = sp.status(self.date, self.edition)
        row = next(x for x in state["results"] if x["platform"] == "douyin")
        self.assertEqual((row["status"], row["reason"]), ("preflight_failed", "account_invalid"))
        self.assertFalse((sp.state_dir(self.date, self.edition) / "douyin.json").exists())
        with patch.object(sp, "run", return_value=self.successful_run()) as uploader:
            resumed = sp.dispatch(self.date, self.edition)
        self.assertEqual([x.args[0][1] for x in uploader.call_args_list], ["douyin"])
        self.assertTrue(resumed["submission_complete"])

    def test_submission_summary_removes_optional_verification_from_pending_queue(self):
        issue = self.date + "/" + self.edition
        state_path = self.root / "research/editions/production-state.json"
        sp.atomic_json(state_path, {"completed": {issue: {"status": "verified"}},
                                    "pending_publications": {issue: {"platforms": ["douyin"]}}})
        with patch.object(sp, "run", return_value=self.successful_run()):
            sp.dispatch(self.date, self.edition)
        state = sp.read_json(state_path)
        self.assertNotIn(issue, state["pending_publications"])
        self.assertTrue(state["completed"][issue]["publication_workflow_complete"])
        self.assertFalse(state["completed"][issue]["verification_required"])
        self.assertEqual(state["completed"][issue]["status"], "verified")

    def test_status_does_not_treat_receipt_without_success_as_completed(self):
        for state in ("submitted_unverified", "submitting", "ambiguous"):
            with self.subTest(state=state):
                row = sp.submission_result("douyin", {"status": state})
                self.assertFalse(row["submission_complete"])
                self.assertTrue(row["needs_attention"])
        for state in ("processing", "public"):
            self.assertTrue(sp.submission_result("douyin", {"status": state})["submission_complete"])

    def test_account_page_timeout_retries_once_without_claiming_expired_login(self):
        self.preflight.stop()
        failure = SimpleNamespace(returncode=1, stdout="invalid", stderr="Page.goto: Timeout 30000ms exceeded")
        with patch.object(sp, "cookie_exists", return_value=True), patch.object(sp, "time") as clock, patch.object(sp, "run", side_effect=[failure, self.successful_run("valid")]) as checker:
            self.assertEqual(sp.account_check("xiaohongshu", "xhs"), (True, "valid"))
        self.assertEqual(checker.call_count, 2)
        clock.sleep.assert_called_once_with(2)

    def test_repeated_account_timeout_remains_transient_and_real_invalid_is_not_retried(self):
        self.preflight.stop()
        with patch.object(sp, "cookie_exists", return_value=True), patch.object(sp, "time"), patch.object(sp, "run", return_value=SimpleNamespace(returncode=1, stdout="invalid", stderr="Page.goto: Timeout 30000ms exceeded")) as checker:
            self.assertEqual(sp.account_check("xiaohongshu", "xhs"), (False, "account_check_transient"))
            self.assertEqual(checker.call_count, 2)
        with patch.object(sp, "cookie_exists", return_value=True), patch.object(sp, "run", return_value=SimpleNamespace(returncode=1, stdout="invalid", stderr="redirected to login page")) as checker:
            self.assertEqual(sp.account_check("xiaohongshu", "xhs"), (False, "account_invalid"))
            self.assertEqual(checker.call_count, 1)

    def test_xhs_stopped_readiness_recovery_preserves_attempt_and_can_submit_once(self):
        self.set_bindings("xiaohongshu")
        directory = sp.state_dir(self.date, self.edition)
        receipt = {"key": sp.key(self.date, self.edition, "xiaohongshu", "xhs"),
                   "fingerprint": "fp-morning", "namespace": None, "status": "ambiguous", "exit_code": -15}
        sp.atomic_json(directory / "xiaohongshu.json", receipt, True)
        (directory / "xiaohongshu.log").write_text("还没看到上传成功标识\n还没看到上传成功标识\n")
        sp.prepare_xhs_pre_submission_retry(self.date, self.edition)
        approved = sp.read_json(directory / "xiaohongshu.json")
        archive = Path(approved["retry_evidence"]["archive"])
        self.assertEqual(sp.read_json(archive / "receipt.json"), receipt)
        with patch.object(sp, "upload_args", return_value=["sau", "xiaohongshu"]), patch.object(sp, "run", return_value=self.successful_run()) as uploader:
            first = sp.publish(self.date, self.edition)
            second = sp.publish(self.date, self.edition)
        self.assertEqual(uploader.call_count, 1)
        self.assertTrue(first["submission_complete"])
        self.assertTrue(second["submission_complete"])
        self.assertEqual(sp.read_json(archive / "receipt.json"), receipt)

    def test_xhs_recovery_refuses_any_metadata_or_publish_stage(self):
        directory = sp.state_dir(self.date, self.edition)
        sp.atomic_json(directory / "xiaohongshu.json", {"status": "ambiguous", "exit_code": -15}, True)
        for marker in ("小人开始填标题", "小人正在冲刺发布", "视频发布成功"):
            (directory / "xiaohongshu.log").write_text("还没看到上传成功标识\n还没看到上传成功标识\n" + marker)
            with self.assertRaisesRegex(ValueError, "does_not_prove"):
                sp.prepare_xhs_pre_submission_retry(self.date, self.edition)

    def test_not_before_applies_without_discarding_still_fresh_edition(self):
        self.config_value["not_before"] = "2026-10-14T08:30:00+08:00"
        (self.private / "config.json").write_text(json.dumps(self.config_value), encoding="utf-8")
        with patch.object(sp, "run") as uploader:
            with self.assertRaisesRegex(ValueError, "edition_predates_publishing_activation"):
                sp.publish(self.date, self.edition)
        uploader.assert_not_called()

    def test_publication_window_rejects_future_and_old_edition(self):
        with patch.object(sp, "now_local", return_value=dt.datetime(2026, 10, 14, 7, tzinfo=sp.TZ)):
            with self.assertRaisesRegex(ValueError, "before_edition_cutoff"):
                sp.publish(self.date, self.edition)
        with patch.object(sp, "now_local", return_value=dt.datetime(2026, 10, 14, 17, tzinfo=sp.TZ)):
            with self.assertRaisesRegex(ValueError, "edition_window_expired"):
                sp.publish(self.date, self.edition)

    def test_midnight_previous_day_evening_remains_fresh(self):
        date = "2026-10-14"
        self.make_edition(date, "evening")
        # Evenings close at 20:00 and remain publishable through 04:00 next day.
        self.clock_value = dt.datetime(2026, 10, 15, 1, 0, tzinfo=sp.TZ)
        self.config_value["not_before"] = "2026-10-14T20:00:00+08:00"
        (self.private / "config.json").write_text(json.dumps(self.config_value), encoding="utf-8")
        package = sp.make_package(date, "evening")
        sp.atomic_json(sp.package_path(date, "evening"), package)
        with patch.object(sp, "run", return_value=self.successful_run()):
            self.assertEqual(sp.publish(date, "evening")["results"][0]["status"], "submitted_unverified")

    def test_substituted_media_or_metadata_never_reaches_upload(self):
        path=sp.package_path(self.date,self.edition)
        original=sp.read_json(path)
        substitutions={'video_path':str(self.base/'another.mp4'),
                       'poster_path':str(self.base/'another.png'),
                       'report_fingerprint':'another-report','video_sha256':'wrong-video',
                       'title':'An unrelated post'}
        for field,value in substitutions.items():
            with self.subTest(field=field):
                sp.atomic_json(path,{**original,field:value})
                with patch.object(sp,'run') as uploader:
                    with self.assertRaises(ValueError):sp.publish(self.date,self.edition)
                uploader.assert_not_called()
        sp.atomic_json(path,original)

    def test_disabled_switch_does_not_submit(self):
        self.config_value['enabled']=False
        (self.private/'config.json').write_text(json.dumps(self.config_value))
        with patch.object(sp,'account_check') as check,patch.object(sp,'run') as uploader:
            with self.assertRaisesRegex(ValueError,'publishing_disabled'):
                sp.publish(self.date,self.edition)
        check.assert_not_called();uploader.assert_not_called()

    def test_youtube_can_use_visible_chrome_without_changing_other_platforms(self):
        package=self.write_package()
        youtube=sp.upload_args('youtube',{'account':'yt','visibility':'public','headless':False},package)
        douyin=sp.upload_args('douyin',{'account':'dy'},package)
        self.assertIn('--headed',youtube)
        self.assertNotIn('--headed',douyin)


if __name__ == "__main__":
    unittest.main()
