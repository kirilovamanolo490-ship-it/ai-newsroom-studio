"""Discover public source updates; no publishing, private messages or Firecrawl calls.

State and raw responses stay outside the public preview directory. Each account has
its own cursor. Partial or failed reads never advance a successful time watermark.
"""
from pathlib import Path
import argparse, concurrent.futures, copy, datetime as dt, fcntl, hashlib, json, os, re, sys
from urllib.parse import urljoin, urlsplit, urlunsplit, unquote
from xml.etree import ElementTree
import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

ROOT=Path(__file__).resolve().parents[1]
UTC=dt.timezone.utc
X_QUERY_FORMAT='epoch_seconds_v1'

def source_due(source,health,now):
    checked=timestamp(health.get('checked_at'))
    if not checked:return True
    interval=source.get('interval_hours',2)
    if health.get('status') in ('failed','partial'):interval=min(interval,2)
    return timestamp(now)-checked>=dt.timedelta(hours=interval)

def timestamp(value):
    if not value: return None
    try:
        parsed=parse_date(value)
        return parsed.astimezone(UTC) if parsed.tzinfo else None
    except (ValueError,TypeError,OverflowError): return None

def reconcile(previous, result, now):
    if result.get('error'): return copy.deepcopy(previous),[]
    state=copy.deepcopy(previous)
    seen=state.setdefault('seen',{})
    baseline=not state.get('baseline_at')
    events=[]
    for item in result.get('items',[]):
        when=timestamp(item.get('published_at'))
        if when and when>timestamp(now): continue
        key=item['key']
        digest=hashlib.sha256((item.get('title','')+'\n'+item.get('content','')).encode()).hexdigest()
        prior=seen.get(key)
        if not baseline and prior!=digest:
            change='content_updated' if prior else 'new_item' if when else 'discovered_undated'
            events.append({**item,'change':change,'observed_at':now})
        seen[key]=digest
    if result.get('complete'):
        state['last_success_at']=result.get('window_end',now)
        state.setdefault('baseline_at',now)
        state.pop('resume',None)
    elif result.get('resume'):
        state['resume']=result['resume']
    if result.get('query_format'):
        state['x_query_format']=result['query_format']
        if result.get('coverage_recovery'):
            state['x_coverage_recovery_pending']=not result.get('complete')
            if result.get('complete'):state['x_coverage_recovered_at']=now
    return state,events

def x_window(source, previous, now):
    pending=previous.get('resume',{})
    recovery=bool(previous.get('baseline_at')) and previous.get('x_query_format')!=X_QUERY_FORMAT
    if pending.get('query_format')==X_QUERY_FORMAT:
        return {**pending,'coverage_recovery':pending.get('coverage_recovery',False)}
    # Legacy date-time strings returned empty results for valid same-day windows.
    # Re-read the bounded initial window without erasing hashes or moving the old
    # watermark backwards. It becomes trustworthy only after the recovery ends.
    anchor=timestamp(previous.get('baseline_at')) if recovery else timestamp(previous.get('last_success_at'))
    if recovery or not anchor:start=(anchor or timestamp(now))-dt.timedelta(hours=source.get('bootstrap_hours',48)+1)
    else:start=anchor-dt.timedelta(hours=1)
    start=dt.datetime.fromtimestamp(int(start.timestamp()),UTC)
    end=dt.datetime.fromtimestamp(int(timestamp(now).timestamp()),UTC)
    query='from:'+source['handle']+(' -filter:replies' if source.get('roots_only') else '')+f' since_time:{int(start.timestamp())} until_time:{int(end.timestamp())}'
    return {'query':query,'cursor':'','since':start.isoformat(),'until':end.isoformat(),'query_format':X_QUERY_FORMAT,'coverage_recovery':recovery}

def parse_html(source, body):
    soup=BeautifulSoup(body,'html.parser')
    title=soup.title.get_text(' ',strip=True) if soup.title else ''
    for node in soup(['script','style','noscript','svg','nav','footer']): node.decompose()
    main=soup.select_one(source.get('selector','main')) or soup.body or soup
    text=main.get_text(' ',strip=True)
    blocked=re.search(r'Security Verification|Just a moment|Access Denied|Author Not Found',title,re.I)
    blocked=blocked or (len(text)<1200 and re.search(r'正在进行安全检测|enable javascript|请开启.*javascript|机器之心.?数据服务',text,re.I))
    expected=source.get('expect',[])
    if blocked or len(text)<source.get('min_chars',250) or (expected and not any(t.lower() in text.lower() for t in expected)):
        return {'error':'semantic_content_unavailable','complete':False,'title':title,'text_length':len(text),'excerpt':text[:250]}
    normalized=re.sub(r'\bUpdated (yesterday|today|this week|in the last hour|\d+ \w+ ago)\b','Updated [relative]',text,flags=re.I)
    items=[{'key':source['url'],'url':source['url'],'title':title or source.get('name','官方页面'),'content':normalized,'published_at':None,'item_type':'page_snapshot'}]
    found={source['url']}
    for a in main.select('a[href]'):
        url=urljoin(source['url'],a['href'])
        bits=urlsplit(url); url=urlunsplit((bits.scheme,bits.netloc,bits.path,bits.query,''))
        label=a.get_text(' ',strip=True)
        if not label or url in found or bits.scheme not in ('http','https'): continue
        if source.get('link_pattern') and re.search(source['link_pattern'],url):
            found.add(url)
            items.append({'key':url,'url':url,'title':label,'content':label,'published_at':None,'item_type':'discovered_link'})
    return {'complete':True,'items':items,'title':title,'text_length':len(text)}

def parse_sitemap(source, body):
    root=ElementTree.fromstring(body)
    if root.tag.rsplit('}',1)[-1]!='urlset':
        return {'error':'sitemap_is_index_or_unexpected_xml; child maps require traversal','complete':False}
    items=[]
    for row in root:
        fields={node.tag.rsplit('}',1)[-1]:(node.text or '').strip() for node in row}
        url=fields.get('loc','')
        if not url.startswith(('https://','http://')):continue
        if source.get('url_pattern') and not re.search(source['url_pattern'],url):continue
        changed=fields.get('lastmod') or None
        items.append({'key':url,'url':url,'title':unquote(urlsplit(url).path.rsplit('/',1)[-1]).replace('-',' '),'content':changed or url,'published_at':None,'modified_at':changed,'item_type':'sitemap_entry'})
    if not items:return {'error':'sitemap_has_no_matching_urls','complete':False}
    return {'complete':True,'items':items}

def fetch_source(source, previous, now, key):
    session=requests.Session()
    session.headers['User-Agent']='AI-Daily-SourceWatch/1.0 (public news discovery)'
    proxy=os.environ.get('AI_NEWS_PROXY')
    session.trust_env=False
    if proxy:session.proxies.update({'http':proxy,'https':proxy})
    raw=[]
    def get(url,params=None,x=False):
        response=session.get(url,params=params,headers={'X-API-Key':key} if x else {},timeout=20)
        if len(response.content)>source.get('max_bytes',8_000_000):raise ValueError('response exceeds configured byte limit')
        if response.encoding=='ISO-8859-1':response.encoding='utf-8'
        raw.append({'url':response.url,'http_status':response.status_code,'content_type':response.headers.get('Content-Type'),'body':response.text})
        response.raise_for_status()
        return response
    result={'id':source['id'],'name':source['name'],'url':source['url'],'kind':source['kind'],'checked_at':now}
    try:
        kind=source['kind']
        if kind=='x':
            if not key:raise ValueError('TWITTERAPI_IO_KEY unavailable')
            window=x_window(source,previous,now)
            query=window['query'];cursor=window['cursor'];until=window['until'];items=[];complete=False
            for page in range(source.get('max_pages',3)):
                params={'query':query,'queryType':'Latest'}
                if cursor:params['cursor']=cursor
                data=get('https://api.twitterapi.io/twitter/tweet/advanced_search',params,True).json()
                if 'tweets' not in data or data.get('status')=='error':raise ValueError('X API unsuccessful payload')
                for post in data['tweets']:
                    when=timestamp(post.get('createdAt'));author=(post.get('author') or {}).get('userName')
                    if not when or not timestamp(window['since'])<=when<timestamp(until):raise ValueError('X API returned a post outside the requested time window')
                    if not author or author.lower()!=source['handle'].lower():raise ValueError('X API returned an unverified or different author')
                    items.append({'key':post['id'],'url':post.get('url') or 'https://x.com/'+source['handle']+'/status/'+post['id'],'title':post.get('text','')[:180],'content':post.get('text',''),'published_at':post.get('createdAt'),'item_type':'x_post','author':author,'reply_to':post.get('inReplyToId'),'quoted_id':(post.get('quoted_tweet') or {}).get('id'),**({'discovery_context':'x_time_filter_recovery'} if window['coverage_recovery'] else {})})
                cursor=data.get('next_cursor','')
                if not data.get('has_next_page'):complete=True;break
                if not cursor:raise ValueError('X API pagination flag has no continuation cursor')
            result.update(items=items,complete=complete,pages=page+1,window_end=until,query_start_at=window['since'],query_format=X_QUERY_FORMAT,coverage_recovery=window['coverage_recovery'])
            if not complete:
                result['resume']={**window,'cursor':cursor}
                result['coverage_warning']='x_recovery_pagination_incomplete' if window['coverage_recovery'] else 'x_pagination_incomplete'
        elif kind=='rss':
            feed=feedparser.parse(get(source['url'],source.get('feed_params')).content)
            if not feed.entries:raise ValueError('RSS returned no parseable items')
            items=[]
            for entry in feed.entries:
                url=entry.get('link',''); date=entry.get('published') or entry.get('updated')
                items.append({'key':entry.get('id') or url,'url':url,'title':entry.get('title',''),'content':BeautifulSoup(entry.get('summary',''),'html.parser').get_text(' ',strip=True),'published_at':date,'item_type':'feed_entry'})
            times=[timestamp(x.get('published_at')) for x in items];times=[t for t in times if t and t<=timestamp(now)]
            gap=bool(previous.get('last_success_at') and times and min(times)>timestamp(previous['last_success_at']))
            result.update(items=items,complete=not gap,oldest_item_at=min(times).isoformat() if times else None)
            if gap:result['coverage_warning']='feed_window_does_not_reach_previous_success; recover archive before advancing'
        elif kind=='github':
            start=timestamp(previous.get('last_success_at')) or timestamp(now)-dt.timedelta(days=3)
            data=get('https://api.github.com/repos/'+source['repository']+'/commits',{'since':(start-dt.timedelta(hours=1)).isoformat(),'per_page':100}).json()
            if not isinstance(data,list):raise ValueError('GitHub commits response is not a list')
            result.update(complete=len(data)<100,items=[{'key':x['sha'],'url':x['html_url'],'title':x['commit']['message'].split('\n')[0],'content':x['commit']['message'],'published_at':x['commit']['committer']['date'],'item_type':'repository_commit'} for x in data])
            if len(data)==100:result['coverage_warning']='commit_page_limit_reached; manual pagination required'
        elif kind=='github_org':
            owner=source['owner'].lower()
            pending=previous.get('resume',{})
            if pending.get('kind')!='github_org' or pending.get('owner')!=owner:pending={}
            since=pending.get('since') or previous.get('last_success_at')
            anchor=timestamp(since)
            until=pending.get('until',now)
            next_page=int(pending.get('next_page',1))
            if next_page<1:raise ValueError('Invalid GitHub continuation page')
            items=[];complete=False;oldest=None;warning=None;pages=0
            for _ in range(max(1,int(source.get('max_pages',3)))):
                pages+=1
                try:
                    data=get('https://api.github.com/users/'+source['owner']+'/repos',{'sort':'updated','direction':'desc','per_page':100,'page':next_page}).json()
                    if not isinstance(data,list):raise ValueError('GitHub organization response is not a list')
                    page_items=[{'key':x['full_name'],'url':x['html_url'],'title':x['full_name'],'content':str(x.get('description'))+' '+str(x.get('pushed_at')),'published_at':x.get('created_at'),'modified_at':x.get('pushed_at'),'item_type':'repository_revision'} for x in data]
                except Exception as exc:
                    if not items:raise
                    warning='github_org_page_read_failed: '+(str(exc).replace(key,'[redacted]') if key else str(exc))
                    break
                items.extend(page_items)
                times=[timestamp(x.get('updated_at')) for x in data];times=[t for t in times if t]
                if times:oldest=min(times)
                next_page+=1
                # First intake remains a bounded baseline. Later intakes must
                # reach the previous successful window, even beyond page one.
                if not anchor or len(data)<100 or (oldest and oldest<=anchor):
                    complete=True;break
            result.update(complete=complete,items=items,pages=pages,window_end=until,query_start_at=since,oldest_updated_at=oldest.isoformat() if oldest else None)
            if not complete:
                result['resume']={'kind':'github_org','owner':owner,'since':since,'until':until,'next_page':next_page}
                result['coverage_warning']=warning or 'github_org_pagination_incomplete'
        elif kind=='hf':
            data=get('https://huggingface.co/api/models',{'author':source['author'],'sort':'lastModified','direction':-1,'limit':100,'full':'true'}).json()
            if not isinstance(data,list):raise ValueError('Hugging Face response is not a list')
            all_times=[timestamp(x.get('lastModified')) for x in data];all_times=[t for t in all_times if t]
            limit_gap=bool(len(data)==100 and previous.get('last_success_at') and all_times and min(all_times)>timestamp(previous['last_success_at']))
            result.update(complete=not limit_gap,items=[{'key':x['id'],'url':'https://huggingface.co/'+x['id'],'title':x['id'],'content':str(x.get('sha',''))+' '+str(x.get('lastModified','')),'published_at':x.get('createdAt'),'modified_at':x.get('lastModified'),'item_type':'model_revision'} for x in data if not source.get('filter') or re.search(source['filter'],x['id'],re.I)])
            if limit_gap:result['coverage_warning']='model_list_limit_reached; manual pagination required'
        elif kind=='html':
            result.update(parse_html(source,get(source['url']).text))
        elif kind=='sitemap':
            result.update(parse_sitemap(source,get(source['url']).content))
        else:raise ValueError('unknown source kind')
    except Exception as exc:
        result.update(error=str(exc).replace(key,'[redacted]') if key else str(exc),complete=False)
    result['raw_responses']=raw
    return result

def atomic_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    temp.replace(path)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--only',nargs='*',help='Run selected source IDs without touching other watermarks')
    parser.add_argument('--force',action='store_true',help='Ignore per-source intervals for an explicit verification run')
    args=parser.parse_args()
    config=json.loads((ROOT/'sources/official-watchlist.json').read_text())
    configured=[s for s in config['sources'] if s.get('enabled',True)]
    selected=[s for s in configured if not args.only or s['id'] in args.only]
    if not selected:raise SystemExit('No matching sources')
    home=ROOT/'research/source-watch';home.mkdir(exist_ok=True)
    with (home/'watch.lock').open('w') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit('Another source watch is running; no duplicate run started')
        state_file=home/'state.json'
        state=json.loads(state_file.read_text()) if state_file.exists() else {'sources':{}}
        now=dt.datetime.now(UTC).isoformat();run_id=dt.datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')
        if 'health' not in state:
            state['health']={}
            for receipt in sorted((home/'runs').glob('*/report.json')):
                old=json.loads(receipt.read_text())
                for row in old.get('sources',[]):state['health'][row['id']]={**row,'checked_at':row.get('checked_at',old['checked_at'])}
        sources=[s for s in selected if args.only or args.force or source_due(s,state['health'].get(s['id'],{}),now) or (s['kind']=='x' and state['sources'].get(s['id'],{}).get('x_query_format')!=X_QUERY_FORMAT)]
        if not sources:
            print(json.dumps({'status':'not_due','sources_configured':len(configured),'note':'No source interval has elapsed; successful watermarks unchanged'}));return 0
        run=home/'runs'/run_id;run.mkdir(parents=True)
        key=''
        credential_file=ROOT/'.secrets/providers.env'
        if any(s['kind']=='x' for s in sources) and credential_file.exists():
            for line in credential_file.read_text().splitlines():
                if line.startswith('TWITTERAPI_IO_KEY='):key=line.split('=',1)[1].strip().strip('"').strip("'")
        statuses=[];events=[]
        def collect(source):return source,fetch_source(source,state['sources'].get(source['id'],{}),now,key)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            for source,result in pool.map(collect,sources):
                encoded=json.dumps(result,ensure_ascii=False)
                if key and key in encoded:raise RuntimeError('Refusing to save credential-bearing response')
                atomic_json(run/(source['id']+'.json'),result)
                before=state['sources'].get(source['id'],{})
                after,found=reconcile(before,result,now)
                state['sources'][source['id']]=after
                events.extend({**e,'source_id':source['id'],'source_name':source['name'],'evidence_role':source.get('role','official'),'content':e.get('content','')[:600]} for e in found)
                status='failed' if result.get('error') else 'partial' if not result.get('complete') else 'baseline' if not before.get('baseline_at') else 'ok'
                row={'id':source['id'],'name':source['name'],'url':source['url'],'checked_at':now,'status':status,'items':len(result.get('items',[])),'changes':len(found),'error':result.get('error'),'coverage_warning':result.get('coverage_warning'),'last_success_at':after.get('last_success_at'),'query_format':after.get('x_query_format') if source['kind']=='x' else None,'snapshot':str(run/(source['id']+'.json'))}
                statuses.append(row)
                state['health'][source['id']]=row
                print(json.dumps({k:row[k] for k in ('id','status','items','changes','error')},ensure_ascii=False),flush=True)
        for source in configured:
            if source['kind']=='x' and state['sources'].get(source['id'],{}).get('x_query_format')!=X_QUERY_FORMAT:
                row=state['health'].get(source['id'])
                if row and row['status'] not in ('failed','partial'):state['health'][source['id']]={**row,'status':'partial','coverage_warning':'legacy_x_time_filter_unverified; recovery required'}
        atomic_json(state_file,state)
        all_statuses=[state['health'].get(s['id'],{'id':s['id'],'name':s['name'],'url':s['url'],'status':'pending','items':0,'changes':0}) for s in configured]
        report={'run_id':run_id,'checked_at':now,'checked_source_ids':[s['id'] for s in statuses],'sources':all_statuses,'changes':events,'status':'partial' if any(s['status'] in ('failed','partial','pending') for s in all_statuses) else 'ok','note':'Each row retains its own check time. First read is a baseline; discovered changes need editorial/date verification. No screenshots or external publication are performed.'}
        atomic_json(run/'report.json',report);atomic_json(home/'latest.json',report)
        lines=['# 来源新增检测',f'本次运行时间（UTC）：{now}','',f'本次检查 {len(statuses)} 个到期来源；总配置 {len(configured)} 个；发现 {len(events)} 项变化。各来源按自己的读取时间保存状态。首次读取仅建立基线；正文变化不等同新发布。','', '| 来源 | 最近结果 | 读取时间 | 条目 |', '|---|---|---|---:|']
        lines += [f"| [{s['name']}]({s['url']}) | {s['status']} | {s.get('checked_at','未运行')} | {s['items']} |" for s in all_statuses]
        lines += ['','## 待核变化','']+[f"- [{e['title'][:180]}]({e['url']}) — {e['change']}；{e['source_name']}" for e in events]
        lines += ['','## 抓取缺口','']+[f"- {s['name']}：{s.get('error') or s.get('coverage_warning') or '翻页未完成，已保留游标'}" for s in all_statuses if s['status'] in ('failed','partial')]
        (home/'latest.md').write_text('\n'.join(lines)+'\n')
        print(json.dumps({'report':str(home/'latest.json'),'sources':len(statuses),'changes':len(events),'status':report['status']},ensure_ascii=False))
        return 2 if report['status']=='partial' else 0

if __name__=='__main__':sys.exit(main())
