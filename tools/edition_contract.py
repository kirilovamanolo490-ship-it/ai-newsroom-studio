"""Shared publication-window and content identity contracts for reports."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import re
from zoneinfo import ZoneInfo

BEIJING = ZoneInfo('Asia/Shanghai')

def report_namespace(report, requested=None):
    """Supplemental videos can use distinct folders without replacing an accepted issue."""
    edition = report.get('edition') or ''
    declared = report.get('output_namespace')
    namespace = requested if requested is not None else declared or edition
    if declared and requested is not None and declared != requested:
        raise ValueError('Requested namespace differs from the reviewed report')
    if namespace != edition:
        if edition != 'briefing' or not re.fullmatch(r'briefing-[a-z0-9]+(?:-[a-z0-9]+)*', namespace):
            raise ValueError('Only briefing reports may use a separate briefing-* namespace')
    return namespace

def edition_window(date: str, edition: str):
    day = dt.date.fromisoformat(date)
    if edition == 'morning':
        end = dt.datetime.combine(day, dt.time(8), BEIJING)
    elif edition == 'evening':
        end = dt.datetime.combine(day, dt.time(20), BEIJING)
    else:
        raise ValueError('edition must be morning or evening')
    return end - dt.timedelta(hours=12), end

def report_fingerprint(report):
    keys = ['date','evidence_cutoff','stories','charts']
    if report.get('report_kind') == 'status_only':
        keys += ['report_kind', 'status_summary']
    edition = report.get('edition')
    if edition:
        keys += ['edition','window_start','window_end']
    payload = {key:report.get(key) for key in keys}
    if edition:
        payload['stories'] = sorted(payload.get('stories') or [], key=lambda s:str(s.get('id','')))
        data = json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    else:
        data = json.dumps(payload,ensure_ascii=False,sort_keys=True)
    return hashlib.sha256(data.encode()).hexdigest()

def navigation_story_order(report):
    """Return story IDs in the reviewed navigation order.

    Grouped reports use group order and each group's story_ids order. Reports
    without groups retain their stories array order for compatibility.
    """
    stories = report.get('stories') or []
    if report.get('report_kind') == 'status_only':
        if stories:
            raise ValueError('status_only report must have no stories')
        return []
    story_ids = [story.get('id') for story in stories]
    if any(not isinstance(story_id, str) or not story_id for story_id in story_ids):
        raise ValueError('Every story must have a non-empty id')
    if len(story_ids) != len(set(story_ids)):
        raise ValueError('Story IDs must be unique')
    presentation = report.get('presentation') or {}
    if 'groups' not in presentation:
        return story_ids
    groups = presentation['groups']
    if not isinstance(groups, list):
        raise ValueError('presentation.groups must be a list')
    ordered = []
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get('story_ids'), list):
            raise ValueError('Every group must have a story_ids list')
        ordered.extend(group['story_ids'])
    if any(not isinstance(story_id, str) or not story_id for story_id in ordered):
        raise ValueError('Group story_ids must contain non-empty IDs')
    if len(ordered) != len(set(ordered)):
        raise ValueError('Grouped story IDs must not repeat')
    unknown = set(ordered) - set(story_ids)
    missing = set(story_ids) - set(ordered)
    if unknown or missing:
        raise ValueError(f'Groups must cover report stories exactly (unknown={sorted(unknown)}, missing={sorted(missing)})')
    return ordered

def validate_narration_order(report, scenes):
    """Require opening, stories in navigation order, then closing."""
    expected = ['opening', *navigation_story_order(report), 'closing']
    actual = [scene.get('id') if isinstance(scene, dict) else None for scene in scenes]
    if actual != expected:
        raise ValueError(f'Narration scene order must be {expected}; got {actual}')
    return expected

def validate_report_window(report):
    report_namespace(report)
    if not report.get('edition'):
        return
    if report['edition'] == 'briefing':
        start_value, end_value = report.get('window_start'), report.get('window_end')
        if not isinstance(start_value, str) or not isinstance(end_value, str):
            raise ValueError('Briefing reports require explicit window_start and window_end timestamps')
        try:
            start = dt.datetime.fromisoformat(start_value.replace('Z', '+00:00'))
            end = dt.datetime.fromisoformat(end_value.replace('Z', '+00:00'))
        except ValueError as exc:
            raise ValueError('Briefing window timestamps must be valid ISO 8601 values') from exc
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError('Briefing window timestamps must include timezones')
        if end <= start:
            raise ValueError('Briefing window_end must be later than window_start')
        for story in report.get('stories', []):
            timestamp = story.get('published_at')
            if not timestamp:
                raise ValueError(f"Missing actual publication time: {story.get('id') or story.get('event_id') or story.get('title', 'unknown story')}")
            try:
                published = dt.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            except (AttributeError, ValueError) as exc:
                raise ValueError(f"Invalid publication time: {story.get('id') or story.get('event_id') or story.get('title', 'unknown story')}") from exc
            if published.tzinfo is None or not start <= published < end:
                raise ValueError(f"Story outside the briefing window: {story.get('id') or story.get('event_id') or story.get('title', 'unknown story')}")
        return
    start,end = edition_window(report['date'],report['edition'])
    if dt.datetime.fromisoformat(report['window_start']) != start or dt.datetime.fromisoformat(report['window_end']) != end:
        raise ValueError('The report must cover exactly its scheduled 12-hour window')
    for story in report.get('stories',[]):
        timestamp = story.get('published_at')
        if not timestamp:
            raise ValueError(f"Missing actual publication time: {story['id']}")
        published = dt.datetime.fromisoformat(timestamp.replace('Z','+00:00'))
        if published.tzinfo is None or not start <= published < end:
            raise ValueError(f"Story outside the scheduled window: {story['id']}")
