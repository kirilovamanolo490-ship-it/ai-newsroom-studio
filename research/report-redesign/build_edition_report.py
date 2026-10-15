"""Build one reader-facing issue from verified evidence; no legacy demo content."""
from pathlib import Path
import argparse,datetime as dt,html,json,shutil,sys
ROOT=Path(__file__).resolve().parents[2]
PUBLIC=ROOT/'research/evidence'
BASE=Path(__file__).parent
sys.path.insert(0,str(ROOT/'tools'))
from edition_contract import report_fingerprint,validate_report_window,report_namespace,navigation_story_order
ESC=lambda value:html.escape(str(value or ''),quote=True)

def build(input_path):
    source=Path(input_path).resolve()
    report=json.loads(source.read_text())
    validate_report_window(report)
    status_only = report.get('report_kind') == 'status_only'
    assert report.get('edition') in {'morning','evening','briefing'} and (status_only or report.get('stories'))
    if status_only:
        assert report.get('stories') == [] and isinstance(report.get('status_summary'), dict)
    date=report['date'];edition=report['edition']
    presentation=report.get('presentation',{})
    label={'morning':'早报','evening':'晚报','briefing':'此刻'}[edition]
    namespace=report_namespace(report)
    day=dt.date.fromisoformat(date);out=PUBLIC/date/namespace;out.mkdir(parents=True,exist_ok=True)
    fingerprint=report_fingerprint(report)
    editorial_path=out/'web-editorial.json'
    editorial=json.loads(editorial_path.read_text()) if editorial_path.exists() else {}
    assert not editorial or (editorial['date']==date and editorial['edition']==edition)
    copy_by_id=editorial.get('stories',{})
    stories=report['stories'];by_id={s['id']:s for s in stories}
    groups=[g for g in presentation.get('groups',[]) if any(sid in by_id for sid in g.get('story_ids',[]))]
    if not groups:
        groups=[{'id':'news','label':'今日消息','story_ids':[s['id'] for s in stories]}]
    brand_by_id={a['id']:a for a in report.get('brand_assets',[]) if a.get('id')}
    def headline(s):return copy_by_id.get(s['id'],{}).get('headline') or s['title']
    def brief(s):return copy_by_id.get(s['id'],{}).get('brief') or s['summary']
    def image_url(s):
        image=s.get('image')
        return (image.get('path') if isinstance(image,dict) else image) or (s.get('source_captures') or [{}])[0].get('path')
    def image_button(path,title,caption,source_url,cls='story-thumbnail'):
        if not path:return ''
        return f'<button class="image-open {cls}" type="button" data-image="{ESC(path)}" data-title="{ESC(title)}" data-caption="{ESC(caption)}" data-source="{ESC(source_url)}" aria-label="放大查看：{ESC(title)}"><img src="{ESC(path)}" alt="{ESC(title)}" loading="lazy"><span>放大查看 ↗</span></button>'
    def story_card(s,number):
        bid=s.get('video_brand_id');brand=brand_by_id.get(bid,{})
        logo=f'<img class="source-logo" src="{ESC(brand.get("path"))}" alt="" loading="lazy">' if brand.get('path') else ''
        source_name=s.get('author') or s.get('source_name') or '消息来源'
        primary=s.get('primary_url','')
        published=dt.datetime.fromisoformat(s['published_at'])
        stamp=published.strftime('%m.%d %H:%M')
        web_copy=copy_by_id.get(s['id'],{})
        figure=image_button(image_url(s),headline(s),s.get('image_caption') or '原发布页面截图；可打开原文核对全文',web_copy.get('image_article_url') or s.get('image_source_url') or primary)
        captures=''.join('<figure>'+image_button(c.get('path'),c.get('label') or '原帖截图',c.get('capture_integrity') or c.get('capture_note'),c.get('source_url') or primary,'source-capture')+'</figure>' for c in s.get('source_captures',[]))
        captures+=''.join('<figure>'+image_button(a['path'],a.get('caption') or '高清原图 / 图表','发布者原始素材，按原比例显示；数据与测试条件详见原图。',primary,'source-capture')+'</figure>'
                          for a in report.get('image_assets',[]) if a.get('source_url')==primary and a.get('path') and a['path']!=image_url(s))
        related=''.join(f'<a href="{ESC(x["url"])}" target="_blank" rel="noopener">{ESC(x.get("label") or "补充来源")} ↗</a>' for x in s.get('related',[]) if isinstance(x,dict) and x.get('url'))
        original=s.get('source_video',{})
        original_video=f'<div class="original-video"><video controls playsinline preload="none" poster="{ESC(s.get("image"))}" src="{ESC(original.get("path"))}"></video><p>原发布演示 · {ESC(original.get("creator") or source_name)} · <a href="{ESC(original.get("source_url") or primary)}" target="_blank" rel="noopener">查看来源 ↗</a></p></div>' if original.get('path') else ''
        exact_publication=(f'<p class="source-published-at">原文发布时间：<time datetime="{ESC(published.isoformat())}">{ESC(published.isoformat())}</time></p>' if presentation.get('show_schedule_time') is False else '')
        detail=f'<details class="story-detail"><summary>来源与补充</summary><div class="detail-body">{exact_publication}<p>{ESC(s.get("details"))}</p><p class="qualification">{ESC(web_copy.get("qualification") or s.get("qualification"))}</p>{f"<div class=related-links>{related}</div>" if related else ""}<div class="source-previews">{captures}</div>{original_video}</div></details>'
        return f'<article class="news-row" id="{ESC(s["id"])}"><span class="story-number">{number:02}</span><div class="story-copy"><div class="story-meta">{logo}<span>{ESC(source_name)}</span><time datetime="{ESC(s["published_at"])}">{stamp}</time></div><h3>{ESC(headline(s))}</h3><p class="summary">{ESC(brief(s))}</p><div class="story-actions"><a href="{ESC(primary)}" target="_blank" rel="noopener">阅读原文 ↗</a>{detail}</div></div>{figure}</article>'
    nav=''.join(f'<a href="#{ESC(g["id"])}">{ESC(g["label"])}</a>' for g in groups)
    sections=[];number=0
    for group in groups:
        cards=[]
        for sid in group['story_ids']:
            if sid in by_id:
                number+=1;cards.append(story_card(by_id[sid],number))
        sections.append(f'<section class="story-section" id="{ESC(group["id"])}"><h2>{ESC(group["label"])}</h2>{"".join(cards)}</section>')
    own_path=out/'own-video.json';own=json.loads(own_path.read_text()) if own_path.exists() else None
    if own:assert own.get('source_report_fingerprint')==fingerprint and (PUBLIC/own['path'].lstrip('/')).is_file()
    duration=int(round(own.get('duration_seconds',0))) if own else 0
    duration_label=f'{duration//60}分{duration%60:02}秒' if duration else ''
    title=(f'{day.month}月{day.day}日 {presentation["issue_title"]}' if presentation.get('issue_title') else f'{day.month}月{day.day}日 AI{label}')
    issue_title=(f'{date} {presentation["issue_title"]}' if presentation.get('issue_title') else f'{date} AI{label}')
    ordered_focus=navigation_story_order(report)
    selected_focus=set(report.get('presentation',{}).get('cover_story_ids') or ordered_focus[:6])
    focus_ids=[sid for sid in ordered_focus if sid in selected_focus][:6]
    focus=[]
    for i,sid in enumerate(focus_ids,1):
        focus_headline=copy_by_id.get(sid,{}).get('focus_headline') or headline(by_id[sid])
        focus.append(f'<li><a href="#{ESC(sid)}"><span>{i:02}</span><strong>{ESC(focus_headline)}</strong><span aria-hidden="true">↗</span></a></li>')
    focus=''.join(focus)
    chapters=''
    if own:
        for c in own.get('chapters',[]):
            name=by_id.get(c['id'],{}).get('short_label') or ('导读' if c['id']=='opening' else '回顾' if c['id']=='closing' else c['title'])
            seconds=float(c['start_seconds']);stamp=f'{int(seconds)//60:02}:{int(seconds)%60:02}'
            chapters+=f'<button type="button" data-seek="{seconds}" aria-label="播放{name}，{stamp}"><span>{ESC(name)}</span><time>{stamp}</time></button>'
    film=f'<div class="film"><button class="film-start" type="button" aria-label="播放{ESC(title)}视频"><img src="{ESC(own["poster"])}" alt="{ESC(title)}封面" fetchpriority="high"><span class="play-icon" aria-hidden="true">▶</span></button><video id="own-video" controls playsinline preload="none" poster="{ESC(own["poster"])}" src="{ESC(own["path"])}" hidden></video><div class="film-toolbar"><details class="chapter-picker"><summary>章节导航</summary><nav class="chapters" aria-label="视频章节">{chapters}</nav></details><div class="downloads"><a href="{ESC(own["path"])}" download>下载视频</a><a href="{ESC(own["poster"])}" download>下载封面</a><a href="{ESC(own["subtitles"])}" download>字幕</a></div></div></div>' if own else ''
    start=dt.datetime.fromisoformat(report['window_start']);end=dt.datetime.fromisoformat(report['window_end'])
    window=f'{start.month}月{start.day}日 {start:%H:%M} — {end.month}月{end.day}日 {end:%H:%M}'
    show_schedule_time=presentation.get('show_schedule_time',True)
    meta=f'{end:%H:%M} · {len(stories)}条消息' if show_schedule_time else f'{len(stories)}条消息'
    if duration_label:meta+=f' · 视频{duration_label}'
    window_line=f'<p class="window">本期覆盖 {ESC(window)}（北京时间）</p>' if show_schedule_time else ''
    status_summary=report.get('status_summary') or {}
    overview=editorial.get('overview') or (status_summary.get('narration') if status_only else None) or '关注模型、产品和开发工具的新动态。'
    gaps=''
    if (out/'source-coverage.json').exists():
        coverage=json.loads((out/'source-coverage.json').read_text());counts=coverage.get('source_watch',{}).get('source_status_counts',{})
        if counts.get('failed') or counts.get('partial'):
            gaps=f'<p>本期有{int(counts.get("failed",0))}个采集入口读取失败，{int(counts.get("partial",0))}个入口覆盖不完整。受限来源与待核条目已单独记录。</p>'
    content=f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#f4f2ee"><title>{ESC(issue_title)} · AI每日观察</title><meta name="description" content="{ESC(overview)}"><link rel="stylesheet" href="/assets/edition-report.css"></head>
<body><a class="skip" href="#news">跳到消息正文</a><header class="masthead"><div class="masthead-inner"><a class="brand" href="/" aria-label="AI每日观察资讯库"><i aria-hidden="true"></i>AI每日观察</a><nav class="mobile-nav" aria-label="页面导航"><a href="/">资讯库</a><a href="#videos">看视频</a><a href="#news">阅读消息</a><a href="#sources">来源说明</a></nav></div></header>
<main class="issue" id="top"><header class="issue-heading"><h1>{ESC(title)}</h1><p class="issue-meta">{ESC(meta)}</p><p class="overview">{ESC(overview)}</p>{window_line}</header>
<section class="edition-hero" id="videos" aria-label="本期{ESC(label)}视频"><div>{film}</div><aside class="focus">{f'<h2>采集结论</h2><p>{ESC(status_summary.get("coverage_text") or overview)}</p>' if status_only else f'<h2>本期重点</h2><ol>{focus}</ol>'}</aside></section>
<section class="news" id="news"><div class="news-heading"><h2>{'本期采集状态' if status_only else '本期消息'}</h2><nav class="section-nav" aria-label="消息栏目">{nav}</nav></div>{f'<p class="status-only">{ESC(status_summary.get("coverage_text") or overview)}</p>' if status_only else ''.join(sections)}</section>
<section class="source-notes" id="sources"><h2>来源说明</h2><p>消息时间按原发布时点记录。性能数据、评测结果和部署计划按发布方口径注明，原帖与补充材料可在各条消息中展开。</p><details><summary>查看采集覆盖与本期数据</summary><div>{gaps}<p><a href="source-coverage.json">来源覆盖记录</a> · <a href="candidate-audit.json">候选审阅记录</a> · <a href="report.json">本期原始数据</a></p></div></details></section>
</main><footer class="site-footer"><span>AI每日观察</span><span>{date} · AI{label}</span><a href="#top">回到顶部 ↑</a></footer>
<dialog id="image-viewer" class="viewer"><div class="viewer-top"><strong id="viewer-title"></strong><button id="viewer-close" type="button" aria-label="关闭图片">×</button></div><img id="viewer-image" alt=""><p id="viewer-caption"></p><div class="viewer-links"><a id="viewer-original" target="_blank" rel="noopener">打开原图 ↗</a><a id="viewer-source" target="_blank" rel="noopener">阅读所属原文 ↗</a></div></dialog><script src="/assets/edition-report.js" defer></script></body></html>'''
    (out/'index.html').write_text(content)
    assets=PUBLIC/'assets';assets.mkdir(exist_ok=True)
    for filename in ['edition-report.css','edition-report.js']:shutil.copy2(BASE/filename,assets/filename)
    build_receipt={'date':date,'edition':edition,'web_revision':2,'source_report_fingerprint':fingerprint,'editorial_path':'web-editorial.json' if editorial else None,'source_input_unchanged':True,'output':str(out/'index.html'),'story_count':len(stories),'built_at':dt.datetime.now(dt.timezone.utc).isoformat()}
    (out/'web-build.json').write_text(json.dumps(build_receipt,ensure_ascii=False,indent=2)+'\n')
    # The homepage is always the archive. Updating one issue must not hide the
    # other editions behind a redirect to the latest morning/evening report.
    if PUBLIC.resolve() == (ROOT/'research/evidence').resolve():
        from build_newsroom import build as build_newsroom
        build_newsroom(ROOT)
    print(json.dumps(build_receipt,ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path,required=True);build(parser.parse_args().input)
