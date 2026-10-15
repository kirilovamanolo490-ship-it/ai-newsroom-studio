#!/usr/bin/env python3
"""Guarded local publisher for verified morning/evening editions."""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SAU_REPO = ROOT / "GitHub/social-auto-upload"
SAU = SAU_REPO / ".venv/bin/sau"
PRIVATE = ROOT / ".secrets/social-publisher"
EVIDENCE = ROOT / "research/evidence"
TZ = ZoneInfo("Asia/Shanghai")
PLATFORMS = ("bilibili", "douyin", "xiaohongshu", "youtube")


def now_local():
    return dt.datetime.now(TZ)


def atomic_json(path: Path, value: dict, private=False):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700 if private else 0o755)
    if private:
        os.chmod(path.parent, 0o700)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600 if private else 0o644)
    tmp.replace(path)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def config():
    path = PRIVATE / "config.json"
    if not path.is_file():
        raise ValueError("config_missing")
    return read_json(path)


BRIEFING_HOURS = ("00", "02", "04", "06", "10", "12", "14", "16", "18", "22")


def briefing_namespace(namespace):
    if not isinstance(namespace, str) or not re.fullmatch(r"briefing-(?:" + "|".join(BRIEFING_HOURS) + r")00", namespace):
        raise ValueError("invalid_briefing_namespace")
    return namespace


def active_bindings(c):
    configured = c.get("platforms", {}) if isinstance(c, dict) else {}
    return {p: b for p in PLATFORMS
            if isinstance((b := configured.get(p)), dict)
            and b.get("confirmed") is True and b.get("enabled") is not False}


def submission_result(platform, receipt):
    """Keep raw evidence while ending successful upload workflows without UI readback."""
    state = receipt.get("status", "ambiguous")
    submitted = state in ("public", "processing") or (
        state == "submitted_unverified" and receipt.get("exit_code") == 0)
    result = {"platform": platform, "status": state,
              "submission_complete": submitted,
              "publication_workflow_complete": submitted,
              "verification_required": False, "needs_verification": False,
              "needs_attention": not submitted and state != "skipped_unbound"}
    for field in ("exit_code", "reason", "error_type", "link", "evidence"):
        if field in receipt:
            result[field] = receipt[field]
    return result


def publication_summary(targets, results):
    active = [row for row in results if row["platform"] in targets]
    complete = bool(active) and all(row["submission_complete"] for row in active)
    public = bool(active) and all(row["status"] == "public" for row in active)
    state = ("no_bound_accounts" if not active else "failed"
             if any(row["status"] == "rejected" for row in active) else
             "complete" if public else "submitted" if complete else "partial")
    return {"status": state, "target_platforms": list(targets), "results": results,
            "submission_complete": complete, "publication_workflow_complete": complete,
            "verification_required": False, "all_targets_public": public,
            "needs_attention_platforms": [row["platform"] for row in active if row["needs_attention"]]}


def paths(date, edition, namespace=None):
    if dt.date.fromisoformat(date).isoformat() != date:
        raise ValueError("invalid_date")
    if edition in ("morning", "evening"):
        if namespace is not None:
            raise ValueError("namespace_only_valid_for_briefing")
        folder = edition
    elif edition == "briefing":
        folder = briefing_namespace(namespace)
    else:
        raise ValueError("invalid_edition")
    base = EVIDENCE / date / folder
    return base / "report.json", base / "own-video.json", base / "own-video.json"


def verified(report_path, manifest_path, date=None, edition=None, namespace=None):
    from completion_gate import check_video
    from edition_contract import report_fingerprint, validate_report_window
    report = read_json(report_path)
    validate_report_window(report)
    date = date or report_path.parent.parent.name
    edition = edition or report.get("edition")
    if edition == "briefing":
        namespace = briefing_namespace(namespace or report_path.parent.name)
        _validate_briefing_window(report, date, namespace)
    elif namespace is not None:
        raise ValueError("namespace_only_valid_for_briefing")
    if (report.get("date") != date or report.get("edition") != edition or
            report_path.parent.parent.name != date or report_path.parent.name != (namespace or edition)):
        raise ValueError("report_scope_mismatch")
    manifest = read_json(manifest_path)
    if (manifest.get("date") != report["date"] or manifest.get("edition") != report["edition"] or
            manifest.get("window_start") != report.get("window_start") or
            manifest.get("window_end") != report.get("window_end")):
        raise ValueError("manifest_scope_mismatch")
    if manifest.get("output_namespace") is not None and manifest.get("output_namespace") != (namespace or report.get("output_namespace")):
        raise ValueError("manifest_namespace_mismatch")
    from media_runtime import resolve_media_tools
    ffprobe = resolve_media_tools(ROOT / "prototypes/daily-brief-video").get("ffprobe")
    if not ffprobe:
        raise ValueError("ffprobe_missing")
    media = check_video(report, manifest_path, EVIDENCE, ffprobe)
    return report, media, report_fingerprint(report)


def _validate_briefing_window(report, date, namespace):
    namespace = briefing_namespace(namespace)
    if report.get("date") != date or report.get("edition") != "briefing" or report.get("output_namespace") != namespace:
        raise ValueError("report_namespace_mismatch")
    hour = int(namespace[9:11])
    end = dt.datetime.combine(dt.date.fromisoformat(date), dt.time(hour), TZ)
    start = end - dt.timedelta(hours=2)
    expected_start, expected_end = start.isoformat(), end.isoformat()
    if report.get("window_start") != expected_start or report.get("window_end") != expected_end:
        raise ValueError("briefing_window_mismatch")
    return end


def publication_copy(report, date, edition, namespace=None):
    if edition == "morning": suffix = f"AI早报{date[5:7]}.{date[8:10]}"
    elif edition == "evening": suffix = f"AI晚报{date[5:7]}.{date[8:10]}"
    else:
        briefing_namespace(namespace)
        suffix = f"AI此刻{date[5:7]}.{date[8:10]}·{namespace[9:11]}点"
    presentation = report.get("presentation") or {}
    stories = report.get("stories") or []
    lead_id = presentation.get("lead_story_id")
    lead = next((story for story in stories if story.get("id") == lead_id), None)
    lead = lead or (stories[0] if stories else {})
    headline = re.sub(r"\s+", " ", str(presentation.get("cover_headline") or lead.get("title") or "")).strip()
    summary = str(lead.get("summary") or presentation.get("overview") or "").strip()
    copy_path = publishing_copy_path(date, edition, namespace)
    copy_hash = None
    editorial = {}
    if copy_path.is_file():
        copy_hash = hashlib.sha256(copy_path.read_bytes()).hexdigest()
        editorial = read_json(copy_path)
        from edition_contract import report_fingerprint
        if editorial.get("report_fingerprint") != report_fingerprint(report):
            raise ValueError("publishing_copy_fingerprint_conflict")
        if editorial.get("namespace", namespace) != namespace:
            raise ValueError("publishing_copy_namespace_conflict")
        headline, summary = str(editorial.get("headline") or "").strip(), str(editorial.get("summary") or "").strip()
        if not headline or not summary:
            raise ValueError("publishing_copy_headline_and_summary_required")
    if not headline or not summary:
        raise ValueError("lead_story_copy_missing")
    title = f"{headline}｜{suffix}"
    platform_titles = {p: title for p in PLATFORMS}
    explicit = editorial.get("platform_titles", {})
    if not isinstance(explicit, dict) or any(p not in PLATFORMS for p in explicit):
        raise ValueError("publishing_copy_platform_titles_invalid")
    for p, value in explicit.items():
        if not isinstance(value, str) or not value.endswith(f"｜{suffix}"):
            raise ValueError("publishing_copy_title_suffix_required")
        platform_titles[p] = value
    description = summary.strip()
    if len(description) > 900:
        raise ValueError("description_exceeds_limit")
    sources = []
    for story in stories:
        candidates = [story.get("primary_url"), story.get("url"), story.get("source_url")]
        candidates.extend(x.get("url") for x in story.get("related", []) if isinstance(x, dict))
        candidates.extend(x.get("url") for x in story.get("sources", []) if isinstance(x, dict))
        for url in candidates:
            if isinstance(url, str) and url.startswith("https://") and url not in sources:
                sources.append(url)
    return {"title": title, "platform_titles": platform_titles, "description": description,
            "headline": headline, "summary": summary, "lead_story_title": str(lead.get("title") or headline),
            "source_urls": sources, "tags": ["AI资讯", "AI观察", "科技动态"], "copy_sha256": copy_hash}


def make_package(date, edition, namespace=None):
    report_path, manifest_path, _ = paths(date, edition, namespace)
    report, media, fingerprint = verified(report_path, manifest_path, date, edition, namespace)
    manifest = read_json(manifest_path)
    video = Path(media["path"])
    poster = (EVIDENCE / str(manifest.get("poster", "")).lstrip("/")).resolve()
    if not poster.is_relative_to(EVIDENCE.resolve()) or not poster.is_file():
        raise ValueError("poster_missing")
    copy = publication_copy(report, date, edition, namespace)
    return {"schema_version": 1, "date": date, "edition": edition, "namespace": namespace, **copy,
            "video_path": str(video.resolve()), "poster_path": str(poster),
            "video_sha256": media["sha256"], "report_fingerprint": fingerprint,
            "poster_sha256": hashlib.sha256(poster.read_bytes()).hexdigest(),
            "prepared_at": now_local().isoformat()}


def package_path(date, edition, namespace=None):
    _, _, _ = paths(date, edition, namespace)
    return ROOT / "research/publishing" / date / (namespace or edition) / "publication-package.json"


def publishing_copy_path(date, edition, namespace=None):
    return package_path(date, edition, namespace).with_name("publishing-copy.json")


def state_dir(date, edition, namespace=None):
    paths(date, edition, namespace)
    p = PRIVATE / "state" / date / (namespace or edition)
    p.mkdir(parents=True, exist_ok=True, mode=0o700)
    for folder in (PRIVATE, PRIVATE / "state", PRIVATE / "state" / date, p):
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(folder, 0o700)
    return p


def key(date, edition, platform, account, namespace=None):
    if edition == "briefing":
        briefing_namespace(namespace)
        identity = f"{date}|{edition}|{namespace}|{platform}|{account}"
    else:
        if namespace is not None:
            raise ValueError("namespace_only_valid_for_briefing")
        identity = f"{date}|{edition}|{platform}|{account}"
    return hashlib.sha256(identity.encode()).hexdigest()


def cookie_exists(platform, account):
    if not isinstance(account, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", account):
        return False
    return (SAU_REPO / "cookies" / f"{platform}_{account}.json").is_file()


def run(args, timeout=1800):
    env = os.environ.copy()
    env["TZ"] = "Asia/Shanghai"
    with subprocess.Popen(args, cwd=SAU_REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, env=env, start_new_session=True) as proc:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Stop the browser/driver children too; an unresolved upload is never retried.
            try: os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError: pass
            try: stdout, stderr = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                try: os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                stdout, stderr = proc.communicate()
            raise subprocess.TimeoutExpired(args, timeout, output=stdout, stderr=stderr)
        return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)


def account_check(platform, account):
    if not cookie_exists(platform, account):
        return False, "cookie_missing"
    # These calls only inspect authentication; retry once for transport failures.
    # Upload attempts remain protected by their durable receipts and are never retried here.
    for attempt in range(2):
        try:
            r = run([str(SAU), platform, "check", "--account", account], 90)
        except subprocess.TimeoutExpired:
            transient = True
        except Exception:
            return False, "account_check_failed"
        else:
            out = ((r.stdout or "") + "\n" + (r.stderr or "")).lower()
            if r.returncode == 0 and "valid" in out and "invalid" not in out:
                return True, "valid"
            transient = any(marker in out for marker in (
                "timeout", "timed out", "net::err_", "econnreset", "connection reset",
                "connection refused", "connection closed", "network error"))
            if not transient:
                return False, "account_invalid"
        if attempt == 0:
            time.sleep(2)
    return False, "account_check_transient"


def safe_links(text, platform):
    found = []
    for raw in re.findall(r"https?://[^\s\]\[<>\"']+", text):
        raw = raw.rstrip(".,);，。")
        u = urlparse(raw)
        host = (u.hostname or "").lower()
        if u.scheme != "https" or u.username or u.password:
            continue
        if platform == "bilibili" and host in ("bilibili.com", "www.bilibili.com"):
            m = re.fullmatch(r"/video/(BV[0-9A-Za-z]{10})/?", u.path)
            if m: found.append(f"https://www.bilibili.com/video/{m.group(1)}")
        elif platform == "douyin" and (host == "douyin.com" or host.endswith(".douyin.com")):
            m = re.fullmatch(r"/video/(\d{10,24})/?", u.path)
            if m: found.append(f"https://www.douyin.com/video/{m.group(1)}")
        elif platform == "xiaohongshu" and (host == "xiaohongshu.com" or host.endswith(".xiaohongshu.com")):
            m = re.fullmatch(r"/(?:explore/([0-9a-fA-F]{24})|discovery/item/([0-9a-fA-F]{24}))/?", u.path)
            if m: found.append(f"https://www.xiaohongshu.com/{u.path.strip('/')}")
        elif platform == "youtube":
            if host == "youtu.be":
                m = re.fullmatch(r"/([A-Za-z0-9_-]{11})/?", u.path)
                if m: found.append(f"https://www.youtube.com/watch?v={m.group(1)}")
            elif host in ("youtube.com", "www.youtube.com", "m.youtube.com") and u.path == "/watch":
                video_id = parse_qs(u.query).get("v", [""])[0]
                if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                    found.append("https://www.youtube.com/watch?" + urlencode({"v": video_id}))
    return list(dict.fromkeys(found))


def upload_args(platform, binding, package):
    account = binding.get("account")
    if not isinstance(account, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", account):
        raise ValueError("invalid_account_name")
    title = package.get("platform_titles", {}).get(platform, package.get("title"))
    max_title = {"douyin": 30, "xiaohongshu": 20, "bilibili": 80, "youtube": 100}[platform]
    if not isinstance(title, str) or not title.strip() or len(title) > max_title:
        raise ValueError("invalid_publication_title")
    if not isinstance(package.get("description"), str) or len(package["description"]) > 900:
        raise ValueError("invalid_publication_description")
    if not isinstance(package.get("tags"), list) or any(not isinstance(t, str) for t in package["tags"]):
        raise ValueError("invalid_publication_tags")
    args = [str(SAU), platform, "upload-video", "--account", binding["account"],
            "--file", package["video_path"], "--title", title,
            "--desc", package["description"], "--tags", ",".join(package["tags"]),
            "--thumbnail", package["poster_path"]]
    if platform == "bilibili":
        if not isinstance(binding.get("tid"), int) or binding["tid"] <= 0:
            raise ValueError("bilibili_tid_required")
        args += ["--tid", str(binding["tid"])]
    if platform == "youtube":
        visibility = binding.get("visibility", "public")
        if visibility not in ("public", "unlisted", "private"):
            raise ValueError("invalid_youtube_visibility")
        args += ["--visibility", visibility]
    if binding.get('headless') is False:
        args += ['--headed']
    return args


def cutoff(date, edition, report=None, namespace=None):
    if edition == "morning":
        hour = 8
    elif edition == "evening":
        hour = 20
    elif edition == "briefing" and report is not None:
        return _validate_briefing_window(report, date, namespace)
    else:
        raise ValueError("invalid_edition")
    return dt.datetime.combine(dt.date.fromisoformat(date), dt.time(hour), TZ)


def xhs_trace_proves_pre_submission_failure(receipt, trace):
    if receipt.get("status") != "ambiguous":
        return False
    stopped_wait = receipt.get("exit_code") == -15 and trace.count("还没看到上传成功标识") >= 2
    input_timeout = receipt.get("exit_code") == 1 and "Locator.set_input_files: Timeout" in trace
    readiness_timeout = receipt.get("exit_code") == 1 and "xhs_upload_readiness_timeout_before_metadata" in trace
    return ((stopped_wait or input_timeout or readiness_timeout) and
            not any(marker in trace for marker in ("小人开始填标题", "小人正在冲刺发布", "视频发布成功", "xhs_publish_click")))


def prepare_xhs_pre_submission_retry(date, edition, namespace=None):
    """Recover only a stopped XHS readiness loop proven not to have reached metadata/publish.

    This explicit recovery preserves the original receipt and trace. It is not
    automatic retry permission for ambiguous uploads or submission failures.
    """
    directory = state_dir(date, edition, namespace)
    receipt_path = directory / "xiaohongshu.json"
    log_path = directory / "xiaohongshu.log"
    with (PRIVATE / "publisher.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipt = read_json(receipt_path)
        trace = log_path.read_text(encoding="utf-8")
        if not xhs_trace_proves_pre_submission_failure(receipt, trace):
            raise ValueError("trace_does_not_prove_pre_submission_stop")
        evidence_dir = directory / "attempts" / now_local().strftime("%Y%m%dT%H%M%S%f")
        evidence_dir.mkdir(parents=True, mode=0o700)
        atomic_json(evidence_dir / "receipt.json", receipt, True)
        archived_log = evidence_dir / "uploader.log"
        archived_log.write_text(trace, encoding="utf-8")
        archived_log.chmod(0o600)
        receipt.update(status="failed_before_submission", retry_evidence={
            "method": "stopped_uploader_stage_trace", "stage": "waiting_for_upload_readiness",
            "publish_attempted": False, "archive": str(evidence_dir),
            "log_sha256": hashlib.sha256(archived_log.read_bytes()).hexdigest(),
            "confirmed_at": now_local().isoformat()})
        atomic_json(receipt_path, receipt, True)
        return {"status": "retry_prepared", "platform": "xiaohongshu", "original_attempt_preserved": True}


def verified_pre_submission_retry(receipt, directory):
    evidence = receipt.get("retry_evidence", {})
    archive = Path(evidence.get("archive", "")).resolve()
    if not archive.is_relative_to((directory / "attempts").resolve()):
        return False
    prior_path, log_path = archive / "receipt.json", archive / "uploader.log"
    if not prior_path.is_file() or not log_path.is_file():
        return False
    prior = read_json(prior_path)
    trace = log_path.read_text(encoding="utf-8")
    return (evidence.get("publish_attempted") is False and
            xhs_trace_proves_pre_submission_failure(prior, trace) and
            prior.get("key") == receipt.get("key") and prior.get("fingerprint") == receipt.get("fingerprint") and
            hashlib.sha256(log_path.read_bytes()).hexdigest() == evidence.get("log_sha256"))


def publish(date, edition, namespace=None):
    c = config()
    if c.get("enabled") is not True:
        raise ValueError("publishing_disabled")
    targets = active_bindings(c)
    if not targets:
        raise ValueError("no_bound_accounts")
    current = now_local()
    pkg_path = package_path(date, edition, namespace)
    package = read_json(pkg_path)
    report_path, manifest_path, _ = paths(date, edition, namespace)
    report, media, fp = verified(report_path, manifest_path, date, edition, namespace)
    due = cutoff(date, edition, report, namespace)
    if due > current:
        raise ValueError("before_edition_cutoff")
    if current - due > dt.timedelta(hours=8):
        raise ValueError("edition_window_expired_no_backlog_publish")
    not_before = c.get("not_before")
    configured_start = dt.datetime.fromisoformat(not_before) if not_before else due
    if configured_start.tzinfo is None:
        raise ValueError("not_before_timezone_required")
    if due < configured_start.astimezone(TZ):
        raise ValueError("edition_predates_publishing_activation")
    if current < max(due, configured_start.astimezone(TZ)):
        raise ValueError("before_configured_not_before")
    if package.get("date") != date or package.get("edition") != edition or package.get("namespace") != namespace:
        raise ValueError("prepared_package_scope_mismatch")
    expected_copy = publication_copy(report, date, edition, namespace)
    if any(package.get(field) != value for field, value in expected_copy.items()):
        raise ValueError("prepared_package_metadata_conflict")
    if package.get("report_fingerprint") != fp or package.get("video_sha256") != media["sha256"]:
        raise ValueError("prepared_package_fingerprint_conflict")
    actual_video = Path(media["path"]).resolve()
    if Path(package.get("video_path", "")).resolve() != actual_video:
        raise ValueError("prepared_package_video_path_conflict")
    manifest = read_json(manifest_path)
    actual_poster = (EVIDENCE / str(manifest.get("poster", "")).lstrip("/")).resolve()
    if (not actual_poster.is_relative_to(EVIDENCE.resolve()) or not actual_poster.is_file() or
            Path(package.get("poster_path", "")).resolve() != actual_poster or
            package.get("poster_sha256") != hashlib.sha256(actual_poster.read_bytes()).hexdigest()):
        raise ValueError("prepared_package_poster_conflict")
    # Validate every active target independently before writing any submission receipt.
    commands, command_errors = {}, {}
    for p, binding in targets.items():
        try:
            commands[p] = upload_args(p, binding, package)
        except (ValueError, KeyError, TypeError) as exc:
            command_errors[p] = str(exc)
    d = state_dir(date, edition, namespace)
    lockpath = PRIVATE / "publisher.lock"
    lockpath.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with lockpath.open("a") as lock:
        os.chmod(lockpath, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("publisher_already_running") from exc
        results = []
        for platform, b in targets.items():
            if now_local() - due > dt.timedelta(hours=8):
                results.append({"platform": platform, "status": "edition_window_expired"})
                continue
            receipt_path = d / f"{platform}.json"
            receipt = read_json(receipt_path) if receipt_path.exists() else None
            account = b.get("account")
            ident = key(date, edition, platform, account or "", namespace)
            if receipt and receipt.get("key") != ident:
                results.append({"platform": platform, "status": "blocked_key_conflict"}); continue
            if receipt and receipt.get("fingerprint") != fp:
                results.append({"platform": platform, "status": "blocked_fingerprint_conflict"}); continue
            previous_attempts = []
            if (platform == "xiaohongshu" and receipt and receipt.get("status") == "failed_before_submission"
                    and verified_pre_submission_retry(receipt, d)):
                previous_attempts = [*receipt.get("previous_attempts", []), receipt["retry_evidence"]["archive"]]
                receipt = None
            if receipt:
                # Any durable receipt means an upload attempt may have reached the platform.
                # Resolve it with status/reconciliation; never upload that key twice.
                results.append(submission_result(platform, receipt)); continue
            if platform in command_errors:
                failure = {"key": ident, "fingerprint": fp, "status": "preflight_failed",
                           "reason": command_errors[platform], "checked_at": now_local().isoformat()}
                atomic_json(d / f"{platform}-preflight.json", failure, True)
                results.append({"platform": platform, **failure}); continue
            ok, why = account_check(platform, account)
            if not ok:
                failure = {"key": ident, "fingerprint": fp, "status": "preflight_failed",
                           "reason": why, "checked_at": now_local().isoformat()}
                atomic_json(d / f"{platform}-preflight.json", failure, True)
                results.append({"platform": platform, **failure}); continue
            if now_local() - due > dt.timedelta(hours=8):
                results.append({"platform": platform, "status": "edition_window_expired"})
                continue
            # Persist before external side effect. An interrupted call stays ambiguous and is never retried.
            receipt = {"key": ident, "fingerprint": fp, "namespace": namespace,
                       "status": "submitting", "started_at": now_local().isoformat(), "link": None}
            if previous_attempts:
                receipt["previous_attempts"] = previous_attempts
            atomic_json(receipt_path, receipt, True)
            logpath = d / f"{platform}.log"
            try:
                proc = run(commands[platform])
                raw = (proc.stdout or "") + "\n" + (proc.stderr or "")
                logpath.write_text(raw, encoding="utf-8")
                os.chmod(logpath, 0o600)
                links = safe_links(raw, platform)
                receipt.update(status="submitted_unverified" if proc.returncode == 0 else "ambiguous",
                               exit_code=proc.returncode, submitted_at=now_local().isoformat(), evidence=links)
            except Exception as exc:
                if isinstance(exc, subprocess.TimeoutExpired):
                    raw = str(exc.output or '') + '\n' + str(exc.stderr or '')
                    logpath.write_text(raw, encoding='utf-8'); os.chmod(logpath, 0o600)
                receipt.update(status="ambiguous", error_type=type(exc).__name__)
            atomic_json(receipt_path, receipt, True)
            results.append(submission_result(platform, receipt))
    return publication_summary(targets, [submission_result(row["platform"], row) for row in results])


def record_publication_result(date, edition, namespace, result):
    """Persist upload completion and queue only actionable failures, never optional UI checks."""
    folder = namespace or edition
    package = read_json(package_path(date, edition, namespace))
    if (package.get("date"), package.get("edition"), package.get("namespace")) != (date, edition, namespace):
        raise ValueError("publication_summary_scope_mismatch")
    summary = {**result, "date": date, "edition": edition, "namespace": namespace,
               "checked_at": now_local().isoformat(),
               "package": str(package_path(date, edition, namespace).relative_to(ROOT)),
               "video_sha256": package["video_sha256"],
               "report_fingerprint": package["report_fingerprint"],
               "completion_basis": "successful_upload_submission",
               "external_publication_complete": result["all_targets_public"],
               "public_urls": [row["link"] for row in result["results"]
                               if row.get("status") == "public" and row.get("link")]}
    atomic_json(package_path(date, edition, namespace).parent / "submission-summary.json", summary)
    atomic_json(EVIDENCE / date / folder / "publication.json", summary)
    issue_key = f"{date}/{folder}"
    pending = result["needs_attention_platforms"]
    for path, records in (
        (ROOT / "research/editions/production-state.json", "supplemental_completed" if namespace else "completed"),
        (ROOT / "research/source-watch/review-state.json", "reported_supplements" if namespace else "reported_editions"),
    ):
        if not path.exists():
            continue
        state = read_json(path)
        if issue_key in state.get(records, {}):
            state[records][issue_key].update(publication=summary, publication_status=result["status"],
                                             submission_complete=result["submission_complete"],
                                             publication_workflow_complete=result["publication_workflow_complete"],
                                             verification_required=False)
        queue = state.setdefault("pending_publications", {})
        if pending:
            queue[issue_key] = {"status": "needs_publication_action", "platforms": pending,
                                "platform_statuses": {row["platform"]: row["status"] for row in result["results"]
                                                      if row["platform"] in pending},
                                "verification_required": False, "updated_at": summary["checked_at"],
                                "receipt": str((package_path(date, edition, namespace).parent / "submission-summary.json").relative_to(ROOT)),
                                "no_resubmit_platforms": [row["platform"] for row in result["results"]
                                                         if row["status"] in ("public", "processing", "submitted_unverified", "submitting", "ambiguous")]}
        else:
            queue.pop(issue_key, None)
        atomic_json(path, state)
    batch_hour = namespace[-4:] if namespace else "0800" if edition == "morning" else "2000"
    batch_dir = ROOT / "research/news-batches" / date / batch_hour
    if batch_dir.exists():
        atomic_json(batch_dir / "publication-receipt.json", summary)
        for name in ("batch.json", "work-receipt.json"):
            path = batch_dir / name
            if path.exists():
                record = read_json(path)
                record.update(publication=summary, submission_complete=result["submission_complete"],
                              publication_workflow_complete=result["publication_workflow_complete"], verification_required=False)
                atomic_json(path, record)
    return summary


def dispatch(date, edition, namespace=None):
    package = make_package(date, edition, namespace)
    target = package_path(date, edition, namespace)
    atomic_json(target, package)
    result = publish(date, edition, namespace)
    result.update({"dispatch": "prepared_and_submitted", "date": date, "edition": edition,
                   "namespace": namespace, "package": str(target)})
    record_publication_result(date, edition, namespace, result)
    return result


def doctor(check_accounts=False):
    try:
        c = config(); configured = True
    except Exception:
        c = {}; configured = False
    targets = active_bindings(c)
    report = {"sau_present": SAU.is_file(), "config_present": configured,
              "enabled": c.get("enabled") is True, "target_platforms": list(targets), "platforms": {}}
    for p in PLATFORMS:
        b = c.get("platforms", {}).get(p, {}) if isinstance(c.get("platforms"), dict) else {}
        active = p in targets
        account = b.get("account") if isinstance(b, dict) else None
        row = {"active": active, "account": account or None,
               "confirmed": isinstance(b, dict) and b.get("confirmed") is True,
               "cookie_present": cookie_exists(p, account or "") if active else False,
               "status": "pending_preflight" if active else "skipped_unbound"}
        if p == "bilibili":
            row["category_configured"] = isinstance(b, dict) and isinstance(b.get("tid"), int) and b["tid"] > 0
        report["platforms"][p] = row
    if check_accounts:
        for p in targets:
            row = report["platforms"][p]
            ok, status = account_check(p, row["account"] or "")
            row["account_check"] = "valid" if ok else status
    valid_targets = []
    for p in targets:
        row = report["platforms"][p]
        valid = row["cookie_present"] and (p != "bilibili" or row["category_configured"])
        if check_accounts:
            valid = valid and row.get("account_check") == "valid"
        row["status"] = "ready" if valid else "preflight_failed"
        if valid: valid_targets.append(p)
    report["all_targets_ready"] = bool(targets) and len(valid_targets) == len(targets)
    report["ready_for_publication"] = report["enabled"] and report["sau_present"] and bool(valid_targets)
    return report


def reconcile(date, edition, platform, evidence_path, namespace=None):
    """Record a separately observed platform state; upload logs are not verification."""
    evidence_path = Path(evidence_path).resolve()
    if not evidence_path.is_relative_to((PRIVATE/'verification').resolve()) or not evidence_path.is_file():
        raise ValueError('verification_evidence_must_be_private_file')
    observation = read_json(evidence_path)
    if (observation.get('platform'), observation.get('date'), observation.get('edition'), observation.get('namespace')) != (platform, date, edition, namespace):
        raise ValueError('verification_scope_mismatch')
    observed_status = observation.get('observed_status')
    if observed_status not in ('public', 'processing', 'rejected'):
        raise ValueError('verification_status_invalid')
    if observation.get('method') not in ('creator_backend', 'official_api'):
        raise ValueError('platform_state_observation_required')
    observed_at = dt.datetime.fromisoformat(observation.get('observed_at', ''))
    if observed_at.tzinfo is None or observed_at > now_local()+dt.timedelta(minutes=5):
        raise ValueError('verification_time_invalid')
    link = observation.get('url') or ''
    canonical = safe_links(link, platform)
    if observed_status == 'public' and len(canonical) != 1:
        raise ValueError('public_work_url_required')
    c = config()
    targets = active_bindings(c)
    if platform not in targets:
        raise ValueError('platform_not_active')
    package = read_json(package_path(date, edition, namespace))
    account = targets[platform].get('account')
    if (observation.get('account') != account or observation.get('video_sha256') != package['video_sha256'] or
            package.get('namespace') != namespace):
        raise ValueError('verification_content_or_account_mismatch')
    receipt_path = state_dir(date, edition, namespace)/f'{platform}.json'
    with (PRIVATE/'publisher.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not receipt_path.is_file():
            raise ValueError('no_submission_to_verify')
        receipt = read_json(receipt_path)
        if (receipt.get('key') != key(date, edition, platform, account, namespace) or
                receipt.get('fingerprint') != package['report_fingerprint'] or receipt.get('namespace') != namespace):
            raise ValueError('verification_receipt_conflict')
        if observed_at < dt.datetime.fromisoformat(receipt['started_at']):
            raise ValueError('verification_predates_submission')
        receipt.update(status=observed_status, link=canonical[0] if canonical else None,
                       verified_at=observed_at.isoformat(), verification_evidence=str(evidence_path),
                       verification_sha256=hashlib.sha256(evidence_path.read_bytes()).hexdigest())
        atomic_json(receipt_path, receipt, True)
    return {'status':'recorded', 'platform':platform, 'observed_status':observed_status, 'link':receipt['link']}


def status(date, edition, namespace=None):
    p = state_dir(date, edition, namespace)
    targets = active_bindings(config())
    rows = []
    for platform in PLATFORMS:
        if platform not in targets:
            rows.append({"platform": platform, "status": "skipped_unbound"})
            continue
        f = p / f"{platform}.json"
        if f.exists():
            r = read_json(f)
            if r.get("key") != key(date, edition, platform, targets[platform].get("account", ""), namespace):
                r = {"status": "blocked_key_conflict"}
            rows.append(submission_result(platform, r))
        else:
            preflight = p / f"{platform}-preflight.json"
            r = read_json(preflight) if preflight.exists() else {"status": "not_submitted"}
            if preflight.exists() and r.get("key") != key(date, edition, platform, targets[platform].get("account", ""), namespace):
                r = {"status": "not_submitted"}
            rows.append(submission_result(platform, r))
    return {"date": date, "edition": edition, "namespace": namespace,
            **publication_summary(targets, rows)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    d = sub.add_parser("doctor"); d.add_argument("--check-accounts", action="store_true")
    for name in ("prepare", "publish", "status", "reconcile", "dispatch"):
        p = sub.add_parser(name); p.add_argument("--date", required=True); p.add_argument("--edition", choices=("morning", "evening", "briefing"), required=True)
        p.add_argument("--namespace")
        if name == 'reconcile':
            p.add_argument('--platform', choices=PLATFORMS, required=True)
            p.add_argument('--evidence', type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        if args.command == "doctor": result = doctor(args.check_accounts)
        elif args.command == "prepare":
            package = make_package(args.date, args.edition, args.namespace)
            atomic_json(package_path(args.date, args.edition, args.namespace), package)
            result = {"status": "prepared", "package": str(package_path(args.date, args.edition, args.namespace)), "fingerprint": package["report_fingerprint"], "video_sha256": package["video_sha256"], "namespace": args.namespace}
        elif args.command == "publish": result = publish(args.date, args.edition, args.namespace)
        elif args.command == 'dispatch': result = dispatch(args.date, args.edition, args.namespace)
        elif args.command == 'reconcile': result = reconcile(args.date,args.edition,args.platform,args.evidence,args.namespace)
        else: result = status(args.date, args.edition, args.namespace)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("status") in (None, "prepared", "submitted", "complete", "recorded") else 2
    except Exception as exc:
        print(json.dumps({"status": "error", "reason": str(exc) if isinstance(exc, ValueError) else type(exc).__name__}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
