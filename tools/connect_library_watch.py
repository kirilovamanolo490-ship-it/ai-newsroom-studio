"""Connect reviewed, readable directory entries to incremental source monitoring.

Account/profile access and a source's official identity are different fields.
WeChat history, blocked pages, and single product pages stay in the directory and
do not silently become enabled collectors.
"""
from pathlib import Path
import hashlib,json,re

ROOT=Path(__file__).resolve().parents[1]
def usable_feeds(urls):
    return [u for u in urls if u.startswith(('https://','http://')) and 'sitemap' not in u.lower()]

def main():
    catalog=json.loads((ROOT/'sources/curated-library.json').read_text())
    path=ROOT/'sources/official-watchlist.json';config=json.loads(path.read_text());seen={s['url'].rstrip('/').lower():s for s in config['sources']};added=[]
    for e in catalog['sources']:
        if not e.get('recommended') or e['verification'] not in ('verified_index','verified_profile') or e['kind']=='wechat' or e.get('manual_watch_only'):continue
        if e['kind']=='x':
            handle=e['entry_url'].rstrip('/').split('/')[-1]
            if e['verification']!='verified_profile' or not re.fullmatch(r'[A-Za-z0-9_]{1,15}',handle):continue
            key=e['entry_url'].rstrip('/').lower()
            if key in seen:
                old=seen[key];old.setdefault('library_source_ids',[])
                if e['id'] not in old['library_source_ids']:old['library_source_ids'].append(e['id'])
                continue
            source={'id':'x-'+handle.lower(),'name':e['name'],'url':e['entry_url'],'kind':'x','handle':handle,'role':e['role'],'enabled':True,'interval_hours':2 if e['role']=='official' else 12,'bootstrap_hours':12,'max_pages':3,'library_source_ids':[e['id']]}
            config['sources'].append(source);seen[key]=source;added.append(source)
            continue
        if e['index_kind'] in ('product','unresolved'):continue
        for sitemap in e.get('sitemap_urls',[]):
            if sitemap.rstrip('/').lower() not in seen:
                source={'id':'lib-'+hashlib.sha256(sitemap.encode()).hexdigest()[:14],'name':e['name']+' · 文档新增与修订','url':sitemap,'kind':'sitemap','role':e['role'],'interval_hours':6,'enabled':True,'library_source_ids':[e['id']],'max_bytes':12_000_000}
                if 'support.claude.com' in sitemap:source['url_pattern']='/en/articles/'
                config['sources'].append(source);seen[sitemap.rstrip('/').lower()]=source;added.append(source)
        selected=e['entry_url'];kind=e['kind'];extra={};interval=6 if e['role']=='official' else 12
        if kind=='hf':
            extra={'author':selected.rstrip('/').split('/')[-1],'collection_scope':'模型列表；新 Space / Collection 仍依靠目录和日报查漏'}
            kind='hf'
        elif kind=='github':extra={'owner':selected.split('github.com/',1)[1].split('?')[0].strip('/')};kind='github_org'
        elif e['index_kind']=='profile':continue
        else:
            feeds=usable_feeds(e.get('feed_urls') or [])
            if feeds:selected=feeds[0];kind='rss'
            elif re.search(r'(feed/?$|rss(?:\.xml|/|$)|\.atom$)',selected):kind='rss'
            else:kind='html';extra={'min_chars':180,'link_pattern':re.escape(selected.split('://',1)[1].split('/')[0])}
        if selected.rstrip('/').lower() in seen:
            old=seen[selected.rstrip('/').lower()];old.setdefault('library_source_ids',[])
            if e['id'] not in old['library_source_ids']:old['library_source_ids'].append(e['id'])
            if old['id'].startswith('lib-'):old['name']=e['name']
            continue
        source={'id':'lib-'+hashlib.sha256(selected.encode()).hexdigest()[:14],'name':e['name'],'url':selected,'kind':kind,'role':e['role'],'interval_hours':interval,'enabled':True,'library_source_ids':[e['id']],**extra}
        config['sources'].append(source);seen[selected.rstrip('/').lower()]=source;added.append(source)
    config['coverage_note']='已验证目录与账号按各自周期读取。普通产品主页、受限目录、公众号历史列表未伪装成已启用采集；日报 RSS 继续查漏新出处。'
    path.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'added':len(added),'total':len(config['sources']),'new_kinds':{k:sum(s['kind']==k for s in added) for k in {s['kind'] for s in added}}}))
if __name__=='__main__':main()
