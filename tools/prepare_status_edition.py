#!/usr/bin/env python3
"""Create an auditable no-story edition from six reviewed two-hour batches."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from edition_contract import BEIJING, edition_window
from news_batch import bundle


def prepare(date: str, edition: str, root: Path | str | None = None,
            scheduled_for: str | None = None) -> tuple[dict, dict]:
    root = Path(root) if root else Path(__file__).resolve().parent.parent
    if edition == 'briefing':
        if scheduled_for is None:
            raise ValueError('briefing status-only reports require --scheduled-for')
        return _prepare_briefing(date, scheduled_for, root)
    bundled, _ = bundle(date, edition, root)
    refs = bundled.get('batch_refs', [])
    expected = [f"{(edition_window(date, edition)[0] + dt.timedelta(hours=2*n)):%Y-%m-%d/%H}00" for n in range(1, 7)]
    if [r.get('batch_id') for r in refs] != expected or any(r.get('status') != 'reviewed' for r in refs):
        raise ValueError('status-only editions require all six scheduled batch.json files to be reviewed and valid')
    if bundled.get('stories'):
        raise ValueError('status-only edition is allowed only when the six-batch bundle contains zero stories')

    batch_data = [json.loads(Path(r['batch_path']).read_text(encoding='utf-8')) for r in refs]
    gaps = bundled.get('missing_invalid_coverage_gaps', [])
    statuses = [b.get('coverage_status', 'unknown') for b in batch_data]
    source_states: dict[str, str] = {}
    source_names: dict[str, str] = {}
    for batch in batch_data:
        for gap in batch.get('coverage_gaps', []):
            source_id = str(gap.get('source_id') or gap.get('id') or gap.get('name') or 'unknown')
            state = gap.get('status', 'unknown')
            rank = {'failed': 3, 'partial': 2, 'unknown': 1, 'complete': 0}
            if source_id not in source_states or rank.get(state, 1) > rank.get(source_states.get(source_id, 'complete'), 0):
                source_states[source_id] = state
            source_names[source_id] = str(gap.get('name') or source_names.get(source_id) or source_id)
    partial = bool(gaps) or any(status != 'complete' for status in statuses)
    failed = sum(state == 'failed' for state in source_states.values())
    partial_sources = sum(state == 'partial' for state in source_states.values())
    start, end = edition_window(date, edition)
    coverage_text = (
        f"已核查本期6个两小时批次，确认新增可发布消息0条；采集覆盖不完整，"
        f"跨六批去重后记录到{failed}个失败入口、{partial_sources}个不完整入口及{len(gaps)}项批次覆盖缺口。"
        if partial else '已核查本期6个两小时批次，确认新增可发布消息0条；本期采集覆盖完整。'
    )
    run_ids = list(dict.fromkeys(run_id for batch in batch_data for run_id in batch.get('source_run_ids', [])))
    coverage = {
        'status': 'partial' if partial else 'complete',
        'batch_statuses': statuses,
        'source_status_counts': {'failed': failed, 'partial': partial_sources,
                                 'complete': sum(state == 'complete' for state in source_states.values()),
                                 'unknown': sum(state == 'unknown' for state in source_states.values())},
        'source_status_by_id': source_states,
        'source_names_by_id': source_names,
        'missing_invalid_coverage_gaps': gaps,
    }
    summary = {
        'batch_count': 6, 'batch_ids': expected, 'story_count': 0,
        'coverage_status': 'partial' if partial else 'complete',
        'coverage_status_by_batch': statuses,
        'failed_source_count': failed, 'partial_source_count': partial_sources,
        'coverage_gap_count': len(gaps), 'coverage_gaps': gaps,
        'narration': coverage_text, 'coverage_text': coverage_text,
    }
    report = {
        'schema_version': 1, 'report_kind': 'status_only', 'date': date, 'edition': edition,
        'window_start': start.isoformat(), 'window_end': end.isoformat(),
        'timezone': 'Asia/Shanghai', 'evidence_cutoff': end.isoformat(),
        'output_namespace': edition, 'issue_time': end.isoformat(),
        'source_run_ids': run_ids, 'source_batch_ids': expected, 'coverage': coverage,
        'stories': [],
        'charts': {'prices': {'rows': []}, 'fast': {'rows': []}, 'benchmarks': {}},
        'image_assets': [], 'video_assets': [], 'videos': [], 'brand_assets': [],
        'supplementary_entries': [], 'status_summary': summary,
        'batch_refs': refs,
        'presentation': {'version': 8, 'issue_title': 'AI早报' if edition == 'morning' else 'AI晚报',
                         'issue_time': end.isoformat(), 'show_schedule_time': True},
        'production_verified': False,
    }
    if partial:
        opening = '部分采集入口没有完整读取，所以不能据此判断全网没有相关新闻。后续批次会继续补充核查。'
    else:
        opening = '本期采集覆盖完整，目前没有新增到可发布的AI消息。'
    narration = {
        'revision': 1,
        'voice': {'provider': 'seed', 'name': 'zh_female_vv_uranus_bigtts'},
        'editorial_note': '状态期旁白只报告本期六批采集覆盖和筛选结果，不推断全网新闻情况。',
        'scenes': [
            {'id': 'opening', 'title': f'{date} {"AI早报" if edition == "morning" else "AI晚报"}',
             'short_label': '导读', 'category': '导读', 'keypoints': [],
             'lines': [f'这里是{date}AI{("早报" if edition == "morning" else "晚报")}。',
                       '已经核查这一期的六个两小时采集批次，确认新增可发布消息零条。', opening],
             'source_label': '六批采集覆盖记录', 'source_url': None, 'caveat': coverage_text},
            {'id': 'closing', 'title': '本期采集状态', 'short_label': '结语',
             'category': '结语', 'keypoints': [],
             'lines': ['以上是本期采集状态。我们会在下一期继续核查新消息。'],
             'source_label': '六批采集覆盖记录', 'source_url': None, 'caveat': ''},
        ],
    }
    return report, narration


def _prepare_briefing(date: str, scheduled_for: str, root: Path) -> tuple[dict, dict]:
    bundled, _ = bundle(date, 'briefing', root, scheduled_for)
    refs = bundled.get('batch_refs', [])
    if len(refs) != 1 or refs[0].get('status') != 'reviewed':
        raise ValueError('briefing status-only requires one reviewed valid batch')
    if bundled.get('stories'):
        raise ValueError('briefing status-only is allowed only when the batch contains zero stories')
    batch = json.loads(Path(refs[0]['batch_path']).read_text(encoding='utf-8'))
    batch_id = refs[0]['batch_id']
    gaps = bundled.get('missing_invalid_coverage_gaps', [])
    coverage_status = batch.get('coverage_status', 'unknown')
    partial = bool(gaps) or coverage_status != 'complete'
    source_gaps = [g for g in batch.get('coverage_gaps', []) if isinstance(g, dict)]
    failed = sum(g.get('status') == 'failed' for g in source_gaps)
    partial_sources = sum(g.get('status') == 'partial' for g in source_gaps)
    start = dt.datetime.fromisoformat(bundled['window_start'])
    end = dt.datetime.fromisoformat(bundled['window_end'])
    namespace = f'briefing-{end:%H}00'
    coverage_text = (f'已核查一个两小时批次，确认新增可发布消息0条；采集覆盖不完整，记录到{failed}个失败入口、{partial_sources}个不完整入口及{len(gaps)}项覆盖缺口。'
                     if partial else '已核查一个两小时批次，确认新增可发布消息0条；本时段采集覆盖完整。')
    opening = ('部分采集入口没有完整读取，因此不能据此判断全网没有相关新闻。'
               if partial else '本时段采集覆盖完整，目前没有新增到可发布的AI消息。')
    report = {
        'schema_version': 1, 'report_kind': 'status_only', 'date': date, 'edition': 'briefing',
        'output_namespace': namespace, 'window_start': start.isoformat(), 'window_end': end.isoformat(),
        'timezone': 'Asia/Shanghai', 'evidence_cutoff': end.isoformat(), 'issue_time': end.isoformat(),
        'source_run_ids': list(batch.get('source_run_ids', [])), 'source_batch_ids': [batch_id],
        'coverage': {'status': 'partial' if partial else 'complete', 'batch_statuses': [coverage_status],
                     'source_status_counts': {'failed': failed, 'partial': partial_sources},
                     'missing_invalid_coverage_gaps': gaps},
        'stories': [], 'charts': {'prices': {'rows': []}, 'fast': {'rows': []}, 'benchmarks': {}},
        'image_assets': [], 'video_assets': [], 'videos': [], 'brand_assets': [], 'supplementary_entries': [],
        'status_summary': {'batch_count': 1, 'batch_ids': [batch_id], 'story_count': 0,
                           'coverage_status': 'partial' if partial else 'complete',
                           'coverage_status_by_batch': [coverage_status], 'failed_source_count': failed,
                           'partial_source_count': partial_sources, 'coverage_gap_count': len(gaps),
                           'coverage_gaps': gaps, 'narration': coverage_text, 'coverage_text': coverage_text},
        'batch_refs': refs, 'pending_editorial': bundled.get('pending_editorial', []),
        'presentation': {'version': 8, 'issue_title': 'AI此刻', 'issue_time': end.isoformat(), 'show_schedule_time': True},
        'production_verified': False,
    }
    narration = {
        'revision': 1, 'voice': {'provider': 'seed', 'name': 'zh_female_vv_uranus_bigtts'},
        'editorial_note': '短版状态旁白只报告本两小时批次结果；不能据此推断未覆盖来源。',
        'scenes': [
            {'id': 'opening', 'title': f'{date} AI此刻', 'short_label': '导读', 'category': '导读',
             'keypoints': [], 'lines': ['这里是AI此刻。', '已经核查本时段的一个两小时采集批次，确认新增可发布消息零条。', opening],
             'source_label': '两小时采集覆盖记录', 'source_url': None, 'caveat': coverage_text},
            {'id': 'closing', 'title': '本时段采集状态', 'short_label': '结语', 'category': '结语',
             'keypoints': [], 'lines': ['以上是本时段采集状态，我们会在下一时段继续核查新消息。'],
             'source_label': '两小时采集覆盖记录', 'source_url': None, 'caveat': ''},
        ],
    }
    return report, narration


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', required=True)
    parser.add_argument('--edition', choices=['morning', 'evening', 'briefing'], required=True)
    parser.add_argument('--scheduled-for', help='Required for one-batch briefing status-only reports')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--overwrite', action='store_true', help='Replace unaccepted report and narration outputs')
    args = parser.parse_args(argv)
    report, narration = prepare(args.date, args.edition, scheduled_for=args.scheduled_for)
    report_path = args.output_dir / 'report.json'
    narration_path = args.output_dir / 'narration-draft.json'
    existing = [path for path in (report_path, narration_path) if path.exists()]
    if existing and not args.overwrite:
        raise FileExistsError('Refusing to overwrite existing output; pass --overwrite only for an unaccepted issue')
    state_path = Path(__file__).resolve().parents[1] / 'research/editions/production-state.json'
    if args.overwrite and state_path.is_file():
        state = json.loads(state_path.read_text(encoding='utf-8'))
        issue_key = f"{args.date}/{args.edition}"
        accepted = state.get('completed', {}).get(issue_key, {}).get('status') == 'verified'
        accepted = accepted or state.get('supplemental_completed', {}).get(issue_key, {}).get('status') == 'verified'
        if accepted:
            raise ValueError(f'Refusing to overwrite verified issue {issue_key}')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    narration_path.write_text(json.dumps(narration, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'report': str(report_path), 'narration': str(narration_path), 'coverage_status': report['status_summary']['coverage_status']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
