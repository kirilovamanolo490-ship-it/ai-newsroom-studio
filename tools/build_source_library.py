"""Build a searchable local directory, complete provenance, and portable exports."""
from pathlib import Path
import argparse,csv,datetime as dt,json,re,hashlib
from collections import Counter,defaultdict
from urllib.parse import urlsplit
from juya_sources import normalize_url

ROOT=Path(__file__).resolve().parents[1]
_source_dirs=sorted(p for p in (ROOT/'research').glob('juya-sources-*') if (p/'raw-links.json').is_file())
P=_source_dirs[-1] if _source_dirs else ROOT/'research/juya-sources-2026-10-13'
OUT=ROOT/'research/evidence/source-library'
ROLE={'official':'官方与产品','media':'媒体','community':'社区','personal':'个人','reference':'参考资料','unknown':'身份待核','project':'项目发布者','research':'研究与论文','government':'政府与监管','organization':'机构'}
VERIFY={'verified_index':'目录已读取','verified_hub':'主页可读 · 目录不足','verified_profile':'账号已识别','identified_wechat':'公众号已识别 · 历史页待接通','blocked':'访问受限','unavailable':'暂不可读','unresolved':'待定位'}

def merge_entries(entries):
    merged={}
    rank={'verified_index':6,'verified_profile':6,'identified_wechat':5,'verified_hub':4,'blocked':3,'unavailable':2,'unresolved':1}
    for original in entries:
        e=dict(original)
        key=('wechat:'+e['wechat_biz']) if e.get('wechat_biz') else normalize_url(e['entry_url']).rstrip('/')
        if e['kind']=='x':key=key.lower()
        if e.get('pending_resolution') and e['verification']=='unresolved':key='pending:'+e['id']
        if key not in merged:
            merged[key]=e;continue
        prior=merged[key]
        best=e if rank.get(e['verification'],0)>rank.get(prior['verification'],0) else prior
        merged[key]={**best,'id':prior['id'],
            'covered_urls':sorted(set(prior['covered_urls'])|set(e['covered_urls'])),
            'origin_hosts':sorted(set(prior['origin_hosts'])|set(e['origin_hosts'])),
            'alias_ids':sorted((set(prior.get('alias_ids',[]))|set(e.get('alias_ids',[]))|{e['id']})-{prior['id']}),
            'feed_urls':sorted(set(prior.get('feed_urls',[]))|set(e.get('feed_urls',[])))}
    return list(merged.values())

def reconcile_registry(previous, entries, current_urls):
    # A new reviewed mapping replaces the current month's old assignment; past
    # months stay available without resurrecting superseded source identities.
    kept={}
    for e in previous:
        remaining=set(e['covered_urls'])-current_urls
        if remaining:kept[e['id']]={**e,'covered_urls':sorted(remaining)}
    for e in entries:
        past=kept.get(e['id'],{})
        kept[e['id']]={**e,'covered_urls':sorted(set(e['covered_urls'])|set(past.get('covered_urls',[])))}
    return list(kept.values())

def display_reason(e):
    reason=e.get('reason','')
    if e['kind']=='x' and e['role']=='official':return '关注已识别的产品或团队账号的新帖，并保留原帖出处。具体功能、开放范围和时间仍以原文为准。'
    if re.search(r'[\u4e00-\u9fff]',reason):return reason
    status=e['verification']
    if status=='verified_profile':return '已从原帖和发布者资料识别账号；后续关注该账号的新帖。账号主体类型单独标记。'
    if status=='verified_index':return '已读取多条内容的目录或订阅列表，可用于发现后续更新。原始引用及目录样例保留在下方。'
    if status=='verified_hub':return '主页可以读取，但尚不足以确认稳定的文章目录。保留为参考入口。'
    if status=='blocked':return '目录候选已登记，本次访问受到验证、登录或访问策略限制；未计入已验证目录。'
    if status=='unavailable':return '本次未能读取完整目录，可能为空白页面、跳转或网络错误；需继续核验。'
    return '原始链接已保留；还需定位真正持续更新的目录，当前候选不计入已验证目录。'

def health():
    latest={}
    for path in sorted((ROOT/'research/source-watch/runs').glob('*/report.json')):
        report=json.loads(path.read_text())
        for row in report.get('sources',[]):latest[row['id']]={**row,'checked_at':row.get('checked_at',report['checked_at'])}
    config=json.loads((ROOT/'sources/official-watchlist.json').read_text())
    rows=[]
    for s in config['sources']:
        if not s.get('enabled',True):continue
        row=latest.get(s['id'],{'id':s['id'],'url':s['url'],'name':s['name'],'status':'pending'})
        rows.append({k:v for k,v in {**row,'kind':s['kind'],'interval_hours':s.get('interval_hours',2),'library_source_ids':s.get('library_source_ids',[])}.items() if k!='snapshot'})
    return rows

def main():
    global P
    parser=argparse.ArgumentParser();parser.add_argument('--data-dir',type=Path);args=parser.parse_args()
    if args.data_dir:P=args.data_dir.resolve()
    else:
        complete=[p for p in sorted((ROOT/'research').glob('juya-sources-*')) if (p/'raw-links.json').exists() and list(p.glob('directories-*.json'))]
        if complete:P=complete[-1]
    OUT.mkdir(parents=True,exist_ok=True)
    raw=json.loads((P/'raw-links.json').read_text());entries=[]
    registry=ROOT/'sources/juya-directory-mappings.json'
    files=sorted(P.glob('directories-*.json'))
    if (P/'directories-carried.json').exists():files=[P/'directories-carried.json']
    if not files and registry.exists():files=[registry]
    for path in files:
        d=json.loads(path.read_text());entries.extend(d if isinstance(d,list) else d['entries'])
    for path in sorted(P.glob('*-overrides.json')):
        overrides=json.loads(path.read_text());overrides=overrides if isinstance(overrides,list) else overrides['entries']
        for replacement in overrides:
            covered=set(replacement['covered_urls']);remaining=[]
            for old in entries:
                leftover=[u for u in old['covered_urls'] if u not in covered]
                if leftover:remaining.append({**old,'covered_urls':leftover})
            entries=remaining+[replacement]
    entries=merge_entries(entries)
    unique={r['url'] for r in raw['links']};mapped={u for e in entries for u in e['covered_urls']}
    missing=unique-mapped
    if missing:raise SystemExit('Refusing incomplete library: '+str(len(missing))+' URLs not assigned; '+repr(sorted(missing)[:5]))
    previous=json.loads(registry.read_text()) if registry.exists() else []
    registry.write_text(json.dumps(reconcile_registry(previous,entries,unique),ensure_ascii=False,indent=2)+'\n')
    seenids=set();byurl=defaultdict(list);watch=health();watchurls={r['url'].rstrip('/'):r for r in watch}
    for e in entries:
        if e['id'] in seenids:e['id']+='-'+hashlib.sha256(e['entry_url'].encode()).hexdigest()[:8]
        seenids.add(e['id'])
        if e.get('wechat_biz') and e.get('wechat_account_name'):
            e.update(verification='identified_wechat',recommended=True,kind='wechat',index_kind='wechat_account',history_access='verification_required',account_entry_note='已识别同一公众号。当前按钮打开一篇可回溯原文；在微信内点击公众号名称进入账号。历史列表尚未接通自动采集。')
            e['reason']='已从原文确认公众号显示名与相同账号标识。历史列表需微信内访问；认证主体尚待独立核对。'
        refs=[r for r in raw['links'] if r['url'] in set(e['covered_urls'])]
        refs.sort(key=lambda r:(r['date'],r['news_index']),reverse=True)
        dates=sorted({r['date'] for r in refs})
        e.update(first_seen=dates[0] if dates else None,last_seen=dates[-1] if dates else None,issue_dates=dates,citation_count=len(refs),unique_link_count=len(set(e['covered_urls'])),role_label=ROLE.get(e['role'],e['role']),verification_label=VERIFY.get(e['verification'],e['verification']))
        e['citations']=[{k:r[k] for k in ('date','news_title','news_url','url','category')} for r in refs]
        e['recommended']=not e.get('exclude_from_recommended',False) and e['verification'] in ('verified_index','verified_profile','identified_wechat')
        e['display_reason']=display_reason(e)
        e['tier']='重点' if e['recommended'] and (e['role']=='official' or len(dates)>=3) else '常规' if e['recommended'] else '参考' if e['verification']=='verified_hub' else '待核'
        if e.get('kind')=='x' and e.get('role')=='personal' and len(dates)<2:e['tier']='常规'
        e['monitor']=watchurls.get(e['entry_url'].rstrip('/')) or next((w for w in watch if e['id'] in w.get('library_source_ids',[])),None)
        for u in e['covered_urls']:byurl[u].append(e['id'])
    entries.sort(key=lambda e:({'重点':0,'常规':1,'参考':2,'待核':3}[e['tier']],-len(e['issue_dates']),-e['citation_count'],e['name'].lower()))
    stats={'issues':raw['successful_days'],'expected_issues':raw['expected_days'],'link_citations':raw['total_link_citations'],'unique_urls':len(unique),'domains':len(raw['host_counts']),'sources':len(entries),'x_accounts':sum(e['kind']=='x' for e in entries),'wechat_accounts':sum(e['kind']=='wechat' for e in entries),'verified_indexes':sum(e['verification']=='verified_index' for e in entries),'verified_profiles':sum(e['verification']=='verified_profile' for e in entries),'recommended':sum(e['recommended'] for e in entries),'verification_counts':dict(Counter(e['verification'] for e in entries)),'tiers':dict(Counter(e['tier'] for e in entries)),'unassigned_urls':len(missing),'news_without_links':sum(not s['source_count'] for s in raw['stories'])}
    automation=ROOT/'research/source-watch/automation-receipt.json'
    data={'schema_version':1,'built_at':dt.datetime.now(dt.timezone.utc).isoformat(),'start':raw['start'],'end':raw['end'],'source_site':raw['site'],'scope_note':'按日报归档日期选取近一个月，含首尾；不代表每条原文均在这段时间首次发布。目录验证与自动采集启用分别记录。','stats':stats,'sources':entries,'issues':raw['issues'],'watch':watch,'automation':json.loads(automation.read_text()) if automation.exists() else {'status':'not_configured'},'unlinked_news':[s for s in raw['stories'] if not s['source_count']]}
    text=json.dumps(data,ensure_ascii=False,indent=2)+'\n'
    (OUT/'sources.json').write_text(text);(ROOT/'sources/curated-library.json').write_text(text)
    with (OUT/'sources.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['来源','长期入口','类型','主体类型','检查状态','优先级','首次见于日报','最近见于日报','引用次数','采集状态','说明'])
        for e in entries:writer.writerow([e['name'],e['entry_url'],e['index_kind'],e['role_label'],e['verification_label'],e['tier'],e['first_seen'],e['last_seen'],e['citation_count'],(e.get('monitor') or {}).get('status','未启用'),e['reason']])
    with (OUT/'citations.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['日报日期','新闻标题','日报位置','原始来源链接','归属来源ID'])
        for r in raw['links']:writer.writerow([r['date'],r['news_title'],r['news_url'],r['url'],';'.join(byurl[r['url']])])
    lines=['# AI 资讯来源库',f"范围：{raw['start']} 至 {raw['end']}，含首尾 {raw['successful_days']} 期。",'',f"共 {stats['link_citations']} 次来源引用、{stats['unique_urls']} 条不同链接、{stats['domains']} 个域名；归入 {stats['sources']} 个长期入口或待核来源，其中 {stats['x_accounts']} 个 X 账号。所有链接均保留对应关系，未归属链接 {len(missing)} 条。",'',data['scope_note'],'','入口原则：X 看发布者账号；网页看真正的文章目录、更新日志或发布者列表。产品首页、受限页面、未识别公众号保留但不列为已验证目录。','',f"已核验目录 {stats['verified_indexes']} 个，账号已识别 {stats['verified_profiles']} 个。可用性不等于官方身份；媒体、社区和个人单独标记。",'','来源验证状态：'+str(stats['verification_counts']),'','完整目录：','']
    for e in entries:
        lines.append(f"- [{e['name']}]({e['entry_url']}) — {e['role_label']}；{e['verification_label']}；{e['tier']}；出现 {len(e['issue_dates'])} 期。{e['reason']}")
    lines+=['','## 持续发现','运行 tools/source_watch.py 检查已启用来源；raw 状态与成功水位保存在 research/source-watch。首次读取是基线，不把历史内容推为新增。失败、翻页未结束、受限入口均保留状态。目录收录本身不代表所有来源已接入定时采集。','运行 tools/juya_sources.py 读取近一个月日报并保留日期、新闻和链接映射；最近两期会重新读取以发现修订。新增来源仍需核验目录，再加入注册表。']
    (OUT/'来源库说明.md').write_text('\n'.join(lines)+'\n')
    (P/'integration-audit.json').write_text(json.dumps({'stats':stats,'all_input_urls_assigned':not missing,'multiple_mappings':{u:v for u,v in byurl.items() if len(v)>1},'source_files':[str(p) for p in P.glob('directories-*.json')]},ensure_ascii=False,indent=2))
    print(json.dumps(stats,ensure_ascii=False))

if __name__=='__main__':main()
