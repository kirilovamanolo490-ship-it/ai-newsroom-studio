"""Carry verified source identities forward; queue new publishers without pretending verification."""
from pathlib import Path
import argparse,datetime,hashlib,json
from urllib.parse import urlsplit
from juya_sources import x_account

ROOT=Path(__file__).resolve().parents[1]
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data-dir',type=Path,required=True);args=parser.parse_args();folder=args.data_dir
    raw_path=folder/'raw-links.json';raw_bytes=raw_path.read_bytes();raw=json.loads(raw_bytes);registry=ROOT/'sources/juya-directory-mappings.json'
    if not registry.exists():raise SystemExit('Initial directory review must be integrated first')
    entries=json.loads(registry.read_text());unique={x['url'] for x in raw['links']};mapped={u for e in entries for u in e['covered_urls']};new=unique-mapped;queued=[]
    for url in sorted(new):
        host=urlsplit(url).netloc;handle=x_account(url);match=None
        if handle:match=next((e for e in entries if e['kind']=='x' and e['entry_url'].rstrip('/').split('/')[-1].lower()==handle.lower()),None)
        if match:match['covered_urls'].append(url);continue
        # Same domain may contain different publishers and sections; never merge on host alone.
        suffix=hashlib.sha256(url.encode()).hexdigest()[:12]
        e={'id':'pending-'+suffix,'name':'@'+handle if handle else host+' · 新来源待定位','kind':'x' if handle else 'web','category':'新发现待核','role':'unknown','entry_url':'https://x.com/'+handle if handle else 'https://'+host+'/','index_kind':'profile' if handle else 'unresolved','recommended':False,'verification':'unresolved','http_status':None,'title':'','index_samples':[],'feed_urls':[],'reason':'新增引用已保留；尚需核验发布账号或实际文章目录。首页仅作候选，不视为已找到目录。','origin_hosts':[host],'covered_urls':[url]}
        e['pending_resolution']=True
        entries.append(e);queued.append(e)
    # Keep entries present in the rolling month, while the master retains prior sources.
    registry.write_text(json.dumps(entries,ensure_ascii=False,indent=2)+'\n')
    month=[]
    for e in entries:
        refs=[u for u in e['covered_urls'] if u in unique]
        if refs:month.append({**e,'covered_urls':refs})
    (folder/'directories-carried.json').write_text(json.dumps(month,ensure_ascii=False,indent=2)+'\n')
    # Keep unresolved current-month publishers visible on a later refresh too.
    # Once an unresolved row is added to the registry, its URLs are technically
    # mapped and therefore absent from `new`; clearing the review queue there
    # would confuse “assigned to a pending record” with “source verified”.
    pending_by_id={}
    for e in month:
        if e.get('pending_resolution') or e.get('verification')=='unresolved':
            pending_by_id[e['id']]=e
    queued=list(pending_by_id.values())
    new_pending=[e for e in queued if any(u in new for u in e.get('covered_urls',[]))]
    mapped_now={u for e in month for u in e.get('covered_urls',[])}
    queue={'new_urls':len(new),'pending':queued,'pending_url_count':len({u for e in queued for u in e.get('covered_urls',[])}),
        'new_pending':new_pending,'new_pending_url_count':len({u for e in new_pending for u in e.get('covered_urls',[]) if u in new}),
        'current_unique_urls':len(unique),'unassigned_url_count':len(unique-mapped_now),
        'raw_links_checked_at':raw.get('checked_at'),'raw_links_sha256':hashlib.sha256(raw_bytes).hexdigest(),
        'refreshed_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    (folder/'new-sources-pending.json').write_text(json.dumps(queue,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'new_urls':len(new),'current_pending_publishers_or_sections':len(queued),'pending_urls':queue['pending_url_count'],'new_pending_urls':queue['new_pending_url_count'],'unassigned_urls':queue['unassigned_url_count'],'monthly_sources':len(month)}))
if __name__=='__main__':main()
