"""Extract cited source URLs from Juya issues, preserving date/story provenance.

Only links in news-item sections are sources. Overview duplicates, the publisher's
own video/contact links, screenshots, and site navigation never become news feeds.
"""
from pathlib import Path
import argparse, concurrent.futures, datetime as dt, hashlib, json, re, os
from collections import Counter
from urllib.parse import urlsplit,urlunsplit,urljoin,parse_qsl,urlencode
from zoneinfo import ZoneInfo
from dateutil.relativedelta import relativedelta
import requests
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parents[1]
BASE='https://daily.juya.uk'

def normalize_url(url):
    b=urlsplit(url.strip());host=b.netloc.lower()
    if host in ('twitter.com','www.twitter.com','www.x.com','mobile.twitter.com'):host='x.com'
    pairs=[(k,v) for k,v in parse_qsl(b.query,keep_blank_values=True) if not k.lower().startswith('utm_') and k.lower() not in ('ref','ref_src','ref_url','fbclid','gclid') and not (host=='x.com' and k in ('s','t'))]
    return urlunsplit(('https' if b.scheme in ('http','https') else b.scheme,host,b.path.rstrip('/') or '/',urlencode(pairs),''))

def x_account(url):
    b=urlsplit(url)
    if b.hostname not in ('x.com','twitter.com','www.x.com','www.twitter.com','mobile.twitter.com'):return None
    p=b.path.strip('/').split('/');name=p[0]
    if name.lower() in ('i','search','home','explore','intent','share','messages','settings') or not re.fullmatch(r'[A-Za-z0-9_]{1,15}',name):return None
    return name

def extract_issue(body,date):
    soup=BeautifulSoup(body,'html.parser');sections=soup.select('main .news-item')
    if not sections:raise ValueError('No news-item sections; refusing empty/challenge page')
    links=[];excluded=[];stories=[]
    for i,section in enumerate(sections,1):
        h=section.select_one('h3');heading=BeautifulSoup(str(h),'html.parser')
        for a in heading.select('.article-ref'):a.decompose()
        title=heading.get_text(' ',strip=True)
        category=section.find_previous('h2');category=category.get_text(' ',strip=True) if category else ''
        news_url=f'{BASE}/issues/{date}/'+('#'+h['id'] if h and h.get('id') else '')
        seen=set();n=0
        for a in section.select('a[href]'):
            original=urljoin(BASE,a['href']);b=urlsplit(original)
            if b.scheme not in ('http','https') or b.hostname=='daily.juya.uk':continue
            url=normalize_url(original)
            if url in seen:continue
            seen.add(url)
            item={'date':date,'issue_url':f'{BASE}/issues/{date}/','news_url':news_url,'news_index':i,'news_title':title,'category':category,'url':url,'original_url':original,'label':a.get_text(' ',strip=True)}
            media=b.hostname=='assets.juya.uk' or re.search(r'\.(png|jpe?g|webp|gif|mp4|webm|svg)(?:$|\?)',original,re.I)
            if media:excluded.append({**item,'reason':'image_or_video_asset'});continue
            links.append(item);n+=1
        stories.append({'date':date,'news_title':title,'news_url':news_url,'source_count':n})
    return {'date':date,'links':links,'excluded':excluded,'stories':stories}

def main():
    today=dt.datetime.now(ZoneInfo('Asia/Shanghai')).date()
    parser=argparse.ArgumentParser();parser.add_argument('--start',default=str(today-relativedelta(months=1)));parser.add_argument('--end',default=str(today));parser.add_argument('--refresh',action='store_true');parser.add_argument('--refresh-recent',type=int,default=2);args=parser.parse_args()
    start=dt.date.fromisoformat(args.start);end=dt.date.fromisoformat(args.end)
    if start>end:raise SystemExit('start must precede end')
    out=ROOT/'research'/f'juya-sources-{end}';raw=out/'raw';raw.mkdir(parents=True,exist_ok=True)
    def get(url):
        session=requests.Session();session.trust_env=False
        proxy=os.environ.get('AI_NEWS_PROXY')
        if proxy:session.proxies.update({'http':proxy,'https':proxy})
        r=session.get(url,timeout=30,headers={'User-Agent':'AI-Daily-SourceResearch/1.0'});r.raise_for_status();r.encoding='utf-8';return r.text
    archive=get(BASE+'/archive/');(out/'archive.html').write_text(archive)
    available={m.group(1) for a in BeautifulSoup(archive,'html.parser').select('a[href]') if (m:=re.search(r'/issues/(\d{4}-\d{2}-\d{2})/?',a['href']))}
    dates=[str(start+dt.timedelta(days=i)) for i in range((end-start).days+1)]
    def collect(date):
        try:
            if date not in available:return {'date':date,'error':'not_in_archive'}
            p=raw/(date+'.html')
            if not p.exists() and not args.refresh and (end-dt.date.fromisoformat(date)).days>=args.refresh_recent:
                earlier=sorted((ROOT/'research').glob('juya-sources-*/raw/'+date+'.html'))
                if earlier:p.write_text(earlier[-1].read_text())
            cached=p.exists() and not args.refresh and (end-dt.date.fromisoformat(date)).days>=args.refresh_recent
            body=p.read_text() if cached else get(BASE+'/issues/'+date+'/')
            data=extract_issue(body,date)
            if not cached:p.write_text(body)
            return {**data,'sha256':hashlib.sha256(body.encode()).hexdigest(),'status':'ok'}
        except Exception as exc:return {'date':date,'error':str(exc),'status':'failed'}
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(collect,dates):
            results.append(result);print(json.dumps({'date':result['date'],'links':len(result.get('links',[])),'error':result.get('error')},ensure_ascii=False),flush=True)
    links=[x for r in results for x in r.get('links',[])];unique={x['url'] for x in links}
    hosts=Counter(urlsplit(x).netloc for x in unique);accounts=Counter(x_account(x).lower() for x in unique if x_account(x))
    report={'site':BASE,'start':str(start),'end':str(end),'date_basis':'日报归档日期；不是原始新闻发布日期','checked_at':dt.datetime.now(dt.timezone.utc).isoformat(),'expected_days':len(dates),'successful_days':sum(r.get('status')=='ok' for r in results),'total_link_citations':len(links),'unique_urls':len(unique),'x_accounts':len(accounts),'host_counts':dict(hosts.most_common()),'issues':[{k:v for k,v in r.items() if k not in ('links','excluded','stories')} for r in results],'links':links,'stories':[x for r in results for x in r.get('stories',[])],'excluded_assets':[x for r in results for x in r.get('excluded',[])]}
    (out/'raw-links.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    byhost=[]
    for host,count in hosts.most_common():
        urls=sorted(u for u in unique if urlsplit(u).netloc==host)
        byhost.append({'host':host,'unique_urls':count,'urls':urls,'examples':[x for x in links if urlsplit(x['url']).netloc==host][:6]})
    (out/'hosts.json').write_text(json.dumps(byhost,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('successful_days','expected_days','total_link_citations','unique_urls','x_accounts','host_counts')},ensure_ascii=False))
    return 0 if report['successful_days']==len(dates) else 2

if __name__=='__main__':raise SystemExit(main())
