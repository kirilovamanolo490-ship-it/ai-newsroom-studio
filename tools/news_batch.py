#!/usr/bin/env python3
"""Read-only planning and bundling for fixed two-hour news batches."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

from edition_contract import BEIJING, edition_window


def _aware(value: str) -> dt.datetime:
    if not isinstance(value, str):
        raise ValueError('timestamp must be a string')
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timestamp must include a timezone')
    return parsed.astimezone(BEIJING)


def _batch_ref(root: Path, end: dt.datetime) -> dict:
    batch_id = f"{end:%Y-%m-%d}/{end:%H}00"
    return {'batch_id': batch_id,
            'batch_path': str(root / 'research' / 'news-batches' / batch_id / 'batch.json'),
            'window_start': (end - dt.timedelta(hours=2)).isoformat(),
            'window_end': end.isoformat()}


def plan(scheduled_for: str | None = None, root: Path | str | None = None) -> dict:
    root = Path(root) if root is not None else Path(__file__).resolve().parent.parent
    inferred = scheduled_for is None
    if inferred:
        now = dt.datetime.now(BEIJING)
        end = now.replace(minute=0, second=0, microsecond=0)
        end -= dt.timedelta(hours=end.hour % 2)
        if end > now:
            end -= dt.timedelta(hours=2)
    else:
        end = _aware(scheduled_for)
        if end.minute or end.second or end.microsecond or end.hour % 2:
            raise ValueError('scheduled-for must be an even hour with zero minutes and seconds')
    video_kind = 'digest' if end.hour in (8, 20) else 'briefing'
    if end.hour == 8:
        owner_date, owner_edition = end.date().isoformat(), 'morning'
    elif end.hour == 20:
        owner_date, owner_edition = end.date().isoformat(), 'evening'
    elif 8 < end.hour < 20:
        owner_date, owner_edition = end.date().isoformat(), 'evening'
    elif end.hour < 8:
        owner_date, owner_edition = end.date().isoformat(), 'morning'
    else:  # 22:00 is the first batch of the next morning's edition
        owner_date, owner_edition = (end.date() + dt.timedelta(days=1)).isoformat(), 'morning'
    digest_start, digest_end = edition_window(owner_date, owner_edition)
    digest_refs = [_batch_ref(root, digest_start + dt.timedelta(hours=2*n)) for n in range(1, 7)]
    ed_date = end.date().isoformat()
    edition = owner_edition if video_kind == 'digest' else 'briefing'
    refs = []
    if video_kind == 'briefing':
        refs = [_batch_ref(root, end)]
    else:
        refs = digest_refs
    current = _batch_ref(root, end)
    namespace = ('morning' if end.hour == 8 else 'evening') if video_kind == 'digest' else f'briefing-{end:%H}00'
    issue_title = ('AI早报' if end.hour == 8 else 'AI晚报') if video_kind == 'digest' else 'AI此刻'
    return {**current, 'inferred': inferred, 'edition_date': ed_date, 'edition': edition,
            'is_digest': end.hour in (8, 20), 'edition_batch_ids': [r['batch_id'] for r in refs],
            'edition_batch_paths': [r['batch_path'] for r in refs], 'video_kind': video_kind,
            'output_namespace': namespace, 'issue_title': issue_title,
            'should_make_batch_video': video_kind == 'briefing',
            'owning_digest_date': owner_date, 'owning_digest_edition': owner_edition,
            'digest_batch_ids': [r['batch_id'] for r in digest_refs],
            'digest_batch_paths': [r['batch_path'] for r in digest_refs]}


def bundle(date: str, edition: str, root: Path | str | None = None,
           scheduled_for: str | None = None) -> tuple[dict, bool]:
    root = Path(root) if root is not None else Path(__file__).resolve().parent.parent
    if edition == 'briefing':
        if scheduled_for is None:
            raise ValueError('briefing bundle requires --scheduled-for')
        end = _aware(scheduled_for)
        if end.date().isoformat() != date or end.minute or end.second or end.microsecond or end.hour % 2 or end.hour in (8, 20):
            raise ValueError('briefing scheduled-for must match date and be a non-digest even hour')
        start = end - dt.timedelta(hours=2)
        ends = [end]
    else:
        if scheduled_for is not None:
            raise ValueError('--scheduled-for is only used with briefing bundles')
        start, end = edition_window(date, edition)
        ends = [start + dt.timedelta(hours=2 * n) for n in range(1, 7)]
    refs, gaps, selected, by_key = [], [], [], {}
    incomplete = False
    for batch_end in ends:
        ref = _batch_ref(root, batch_end)
        state = {'batch_id': ref['batch_id'], 'batch_path': ref['batch_path'], 'status': 'missing'}
        refs.append(state)
        path = Path(ref['batch_path'])
        if not path.is_file():
            gaps.append({'batch_id': ref['batch_id'], 'reason': 'missing batch.json'}); incomplete = True
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except Exception as exc:
            state.update(status='invalid', error=f'cannot read JSON: {exc}')
            gaps.append({'batch_id': ref['batch_id'], 'reason': state['error']}); incomplete = True
            continue
        errors = []
        required = {'schema_version': int, 'batch_id': str, 'window_start': str, 'window_end': str,
                    'status': str, 'source_run_ids': list, 'coverage_gaps': list, 'stories': list,
                    'special_reports': list}
        if not isinstance(data, dict):
            errors.append('root must be an object')
        else:
            for field, typ in required.items():
                if field not in data or type(data[field]) is not typ:
                    errors.append(f'{field} missing or wrong type')
            if data.get('schema_version') != 1: errors.append('schema_version must be 1')
            if data.get('batch_id') != ref['batch_id']: errors.append('batch_id mismatch')
            if data.get('status') != 'reviewed': errors.append('status is not reviewed')
            if isinstance(data.get('source_run_ids'), list) and (not data['source_run_ids'] or any(not isinstance(x, str) or not x for x in data['source_run_ids'])):
                errors.append('source_run_ids must contain nonempty strings')
            elif isinstance(data.get('source_run_ids'), list):
                for run_id in data['source_run_ids']:
                    run_path = root / 'research' / 'source-watch' / 'runs' / run_id / 'report.json'
                    if not run_path.is_file():
                        errors.append(f'source run report missing: {run_id}')
                    else:
                        try:
                            report = json.loads(run_path.read_text(encoding='utf-8'))
                            if not isinstance(report, dict) or report.get('run_id') != run_id:
                                errors.append(f'source run report invalid or run_id mismatch: {run_id}')
                        except (OSError, ValueError) as exc:
                            errors.append(f'source run report unreadable: {run_id}: {exc}')
            try:
                if _aware(data['window_start']) != _aware(ref['window_start']) or _aware(data['window_end']) != _aware(ref['window_end']):
                    errors.append('window mismatch')
            except (KeyError, ValueError, TypeError): errors.append('window_start/window_end invalid')
            if isinstance(data.get('coverage_gaps'), list) and data['coverage_gaps']:
                gaps.append({'batch_id': ref['batch_id'], 'reason': 'coverage_gaps reported', 'details': data['coverage_gaps']}); incomplete = True
            batch_stories = []
            if not errors and isinstance(data.get('stories'), list):
                try: bs, be = _aware(ref['window_start']), _aware(ref['window_end'])
                except Exception: bs = be = None
                for i, story in enumerate(data['stories']):
                    if not isinstance(story, dict) or any(not isinstance(story.get(k), str) or not story[k] for k in ('event_id','content_version','title','url','published_at')):
                        errors.append(f'story[{i}] missing required fields'); continue
                    try: published = _aware(story['published_at'])
                    except (ValueError, TypeError):
                        errors.append(f'story[{i}] published_at lacks valid timezone'); continue
                    if bs is None or not bs <= published < be:
                        errors.append(f'story[{i}] published_at outside batch window'); continue
                    key = (story['event_id'], story['content_version'])
                    batch_stories.append((key, story))
            if not errors:
                for key, story in batch_stories:
                    if key not in by_key:
                        item = dict(story); item['batch_refs'] = []
                        by_key[key] = item; selected.append(item)
                    if ref['batch_id'] not in by_key[key]['batch_refs']:
                        by_key[key]['batch_refs'].append(ref['batch_id'])
        if errors:
            state.update(status='invalid', errors=errors)
            gaps.extend({'batch_id': ref['batch_id'], 'reason': err} for err in errors)
            incomplete = True
        else:
            state['status'] = 'reviewed'
        if isinstance(data, dict) and data.get('special_reports'):
            state['special_reports'] = data['special_reports']
        if isinstance(data, dict):
            if isinstance(data.get('source_run_ids'), list):
                state['source_run_ids'] = data['source_run_ids']
            if 'pending_editorial' in data:
                state['pending_editorial'] = data['pending_editorial']
    result = {'schema_version': 1, 'date': date, 'edition': edition,
              'window_start': start.isoformat(), 'window_end': end.isoformat(),
              'batch_refs': refs, 'missing_invalid_coverage_gaps': gaps,
              'pending_editorial': [
                  {'batch_id': ref['batch_id'], 'items': ref['pending_editorial']}
                  for ref in refs if ref.get('pending_editorial')
              ],
              'stories': selected,
              'editorial_note': '需人工编辑合并同事件多个版本；聚合不是成品，且不代表真实内容核验通过。',
              'production_verified': False}
    return result, incomplete


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('plan'); p.add_argument('--scheduled-for');
    b = sub.add_parser('bundle'); b.add_argument('--date', required=True); b.add_argument('--edition', required=True, choices=('morning','evening','briefing')); b.add_argument('--scheduled-for'); b.add_argument('--output')
    args = parser.parse_args(argv)
    try:
        if args.command == 'plan':
            result = plan(args.scheduled_for)
            code = 0
        else:
            result, incomplete = bundle(args.date, args.edition, scheduled_for=args.scheduled_for)
            code = 2 if incomplete else 0
            if args.output: _atomic_write(Path(args.output), result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code
    except (ValueError, OSError) as exc:
        print(f'error: {exc}', file=sys.stderr); return 2


if __name__ == '__main__':
    raise SystemExit(main())
