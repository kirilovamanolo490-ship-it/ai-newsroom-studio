"""Resolve cited platform links into account, organization, and repository indexes."""
from pathlib import Path
import concurrent.futures,datetime as dt,hashlib,json,re,os
from urllib.parse import urlsplit,parse_qs,urljoin
from collections import defaultdict
import requests
from bs4 import BeautifulSoup
from juya_sources import x_account

ROOT=Path(__file__).resolve().parents[1]
configured_source_dir=os.environ.get('AI_NEWS_JUYA_SOURCE_DIR')
available_source_dirs=sorted((ROOT/'research').glob('juya-sources-*'))
P=Path(configured_source_dir).expanduser() if configured_source_dir else (available_source_dirs[-1] if available_source_dirs else ROOT/'research')
CACHE=P/'platform-cache';CACHE.mkdir(exist_ok=True)
def get(url,json_mode=False):
    path=CACHE/(hashlib.sha256(url.encode()).hexdigest()[:20]+'.json')
    if path.exists():return json.loads(path.read_text())
    try:
        session=requests.Session();session.trust_env=False
        proxy=os.environ.get('AI_NEWS_PROXY')
        if proxy:session.proxies.update({'http':proxy,'https':proxy})
        r=session.get(url,headers={'User-Agent':'AI-SourceDirectory/1.0'},timeout=14);r.encoding='utf-8'
        data={'url':url,'final_url':r.url,'status':r.status_code,'body':r.text,'checked_at':dt.datetime.now(dt.timezone.utc).isoformat()}
    except Exception as e:data={'url':url,'error':str(e)}
    path.write_text(json.dumps(data,ensure_ascii=False));return data

def entry(id,name,url,kind,urls,**kw):
    return dict(id=id,name=name,entry_url=url,kind=kind,category='账号与开源',role='unknown',index_kind='profile',recommended=True,verification='unresolved',http_status=None,title=name,index_samples=[],feed_urls=[],reason='',origin_hosts=sorted({urlsplit(x).netloc for x in urls}),covered_urls=sorted(urls),**kw)

def main():
    data=json.loads((P/'raw-links.json').read_text());urls=sorted({r['url'] for r in data['links']})
    entries=[];xgroups=defaultdict(list)
    for url in urls:
        if x_account(url):xgroups[x_account(url).lower()].append(url)
    authors={k.lower():v for k,v in json.loads((P/'x-profiles/authors.json').read_text()).items()}
    for name in ('DeepSeekHarness','AravSrinivas'):
        f=P/'x-profiles'/f'{name}.json'
        if f.exists():
            d=json.loads(f.read_text()).get('payload',{}).get('data',{})
            if d.get('userName'):authors[name.lower()]=d
    product_handles='ChatGPT OpenAIDevs ClaudeDevs bot QwenDevs UnderdogAI AnthropicAI claudeai OpenAINewsroom StepFun_ai odysseyml imagine OpenAI GoogleDeepMind OpenRouter github liquidai perplexity_ai ViduAI_official NousResearch Google opencode perplexitydevs ElevenLabs ValsAI reflection_ai Aleph__Alpha trycua stitchbygoogle tavus GeminiApp cohere HeyGen ideogram_ai _inception_ai ArtificialAnlys arena Gemini_Notebook CueAgents MiniMax_AI CommandCodeAI typesafeai Meituan_LongCat antigravity cline vercel_dev ExaAILabs FishAudio AntLingAGI PixVerse Kimi_Moonshot AndroidDev vercel SpaceXAI unionalphaai Muse GoogleLabs EpochAIResearch OpenBMB qoder_ai_ide cognition cursor_ai GoogleAIStudio nebiusai DeepSeekHarness'.lower().split()
    for key,refs in xgroups.items():
        a=authors.get(key,{});handle=a.get('userName') or x_account(refs[0]);brand=key in product_handles
        e=entry('x-'+key,'@'+handle+(' · '+a['name'] if a.get('name','').lower()!=key and a.get('name') else ''),'https://x.com/'+handle,'x',refs)
        affiliation=(a.get('affiliatesHighlightedLabel') or {}).get('label',{}).get('description')
        e.update(category='X · 产品与机构' if brand else 'X · 人物与线索',role='official' if brand and (a.get('verifiedType')=='Business' or affiliation) else 'unknown' if brand else 'personal',verification='verified_profile' if a else 'unresolved',index_kind='profile',description=a.get('description',''),account_id=a.get('id'),handle=handle,identity_verification='X 返回商业认证或机构关联标识，已匹配原帖作者' if brand and (a.get('verifiedType')=='Business' or affiliation) else '已匹配原帖作者资料；身份简介为本人自述' if a else '仅由日报引用 URL 提取，资料暂未返回',reason='关注账号主页和新发布；个人账号的观点、传闻与公司公告分别核验。',recommended=bool(a))
        e['index_samples']=[{'title':'日报引用的原帖','url':u} for u in refs[:3]]
        entries.append(e)
    groups=defaultdict(list)
    for url in urls:
        b=urlsplit(url);parts=b.path.strip('/').split('/');host=b.hostname
        if host=='github.com':
            if parts[0]=='search':
                repo=re.search(r'repo:([^ /]+/[^ ]+)',parse_qs(b.query).get('q',[''])[0]);owner=repo.group(1).split('/')[0] if repo else None
            else:owner=parts[0]
            if owner:groups[('github',owner)].append(url)
        elif host=='huggingface.co':
            owner=parts[1] if parts[0] in ('spaces','collections') and len(parts)>1 else parts[1] if parts[0]=='blog' and len(parts)>2 else parts[0]
            groups[('hf',owner)].append(url)
        elif host in ('arxiv.org','gitcode.com','www.youtube.com','weibo.com'):groups[(host,url if host in ('weibo.com','www.youtube.com') else host)].append(url)
    def resolve(pair):
        (kind,owner),refs=pair
        if kind=='github':
            url='https://github.com/'+owner+'?tab=repositories';api='https://api.github.com/users/'+owner+'/repos?sort=updated&per_page=10'
            e=entry('gh-'+owner.lower(),owner+' · GitHub 仓库目录',url,'github',refs)
            raw=get(api);e['http_status']=raw.get('status');e['index_kind']='repository'
            try:
                repos=json.loads(raw.get('body','[]'))
                if raw.get('status')==200 and isinstance(repos,list) and repos:
                    e.update(verification='verified_index',role='project',index_samples=[{'title':r['name'],'url':r['html_url']} for r in repos[:5]],reason='已读取该发布者的公开仓库列表；同时保留本月被引用仓库的更新订阅。组织归属仍应与官网核对。')
                else:raise ValueError('API unavailable')
            except Exception:
                raw=get(url);soup=BeautifulSoup(raw.get('body',''),'html.parser');samples=[]
                for a in soup.select('a[itemprop="name codeRepository"],h3 a[itemprop="name codeRepository"],h3 a'):
                    href=urljoin(url,a.get('href',''))
                    if '/'+owner+'/' in href and a.get_text(' ',strip=True):samples.append({'title':a.get_text(' ',strip=True),'url':href})
                e.update(http_status=raw.get('status'),verification='verified_index' if samples else 'blocked',index_samples=samples[:5],reason='HTML 仓库目录可读' if samples else 'GitHub 目录 URL 已定位，API/网页读取受限，需浏览器复核',recommended=bool(samples))
            repos=set()
            for ref in refs:
                p=urlsplit(ref).path.strip('/').split('/')
                if len(p)>1 and p[0]!='search':repos.add('/'.join(p[:2]))
            e['feed_urls']=['https://github.com/'+r+'/releases.atom' for r in sorted(repos)]
            e['feed_verification']='按 GitHub 标准订阅格式生成，尚未逐条实测；有些仓库仅提交代码，不发 Releases'
            return e
        if kind=='hf':
            url='https://huggingface.co/'+owner;e=entry('hf-'+owner.lower(),owner+' · Hugging Face',url,'hf',refs);e['index_kind']='profile';e['role']='project'
            raw=get('https://huggingface.co/api/models?author='+owner+'&sort=lastModified&direction=-1&limit=5')
            e['http_status']=raw.get('status')
            try:
                models=json.loads(raw.get('body','[]'))
                if raw.get('status')==200 and isinstance(models,list) and models:
                    e.update(verification='verified_index',index_samples=[{'title':m['id'],'url':'https://huggingface.co/'+m['id']} for m in models],reason='已读取发布者模型列表。模型、合集、Space 的具体原链接均保留；发布主体与官方关系须独立核验。')
                else:
                    raw=get(url);soup=BeautifulSoup(raw.get('body',''),'html.parser');text=soup.get_text(' ',strip=True)
                    ok=raw.get('status')==200 and owner.lower() in text.lower() and len(text)>200
                    e.update(http_status=raw.get('status'),verification='verified_hub' if ok else 'blocked',recommended=ok,reason='账号主页可读，模型 API 暂无条目；需同时看 Spaces、合集和文章。' if ok else '账号主页或 API 暂不可读')
            except Exception:e.update(verification='unavailable',recommended=False,reason='模型列表响应无法解析')
            return e
        if kind=='arxiv.org':
            e=entry('arxiv-ai','arXiv · AI / 机器学习 / 视觉','https://arxiv.org/list/cs.AI/recent','web',refs);e.update(role='research',category='论文与评测',index_kind='research_index')
            raw=get(e['entry_url']);soup=BeautifulSoup(raw.get('body',''),'html.parser');samples=[{'title':a.get_text(' ',strip=True),'url':urljoin(e['entry_url'],a['href'])} for a in soup.select('a[title="Abstract"]')][:5]
            e.update(http_status=raw.get('status'),verification='verified_index' if samples else 'blocked',index_samples=samples,feed_urls=['https://rss.arxiv.org/rss/cs.AI','https://rss.arxiv.org/rss/cs.LG','https://rss.arxiv.org/rss/cs.CV'],reason='单篇论文归到学科新论文目录；同时关注 cs.AI、cs.LG、cs.CV，目录日期不等同论文首次提交时间。')
            return e
        if kind=='weibo.com':
            uid=urlsplit(refs[0]).path.strip('/').split('/')[0];e=entry('weibo-'+uid,'微博账号 '+uid,'https://weibo.com/u/'+uid,'web',refs);raw=get(e['entry_url']);e.update(category='社交平台待核',verification='blocked',http_status=raw.get('status'),index_kind='profile',recommended=False,reason='由原帖提取账号数字 ID；匿名读取可能需要登录，尚未确认账号名称或官方身份。');return e
        if kind=='www.youtube.com':
            raw=get('https://www.youtube.com/oembed?url='+refs[0]+'&format=json');e=entry('youtube-'+urlsplit(refs[0]).query,'YouTube 视频来源',refs[0],'web',refs)
            try:
                d=json.loads(raw.get('body','{}'));url=d.get('author_url')
                if not url:raise ValueError('author missing')
                e.update(name=d.get('author_name','YouTube')+' · 视频频道',entry_url=url,verification='verified_profile',http_status=raw.get('status'),index_kind='profile',reason='通过 YouTube oEmbed 返回的 author_url 定位发布频道；未把单支视频当长期入口。')
            except Exception:e.update(verification='blocked',recommended=False,reason='视频原链接保留，频道身份暂未解析；不能把单视频链接当目录。',index_kind='unresolved')
            return e
        e=entry('gitcode-ascend','Ascend Tribe · GitCode','https://gitcode.com/ascend-tribe','web',refs);raw=get(e['entry_url']);e.update(role='project',index_kind='repository',verification='verified_hub' if raw.get('status')==200 and len(raw.get('body',''))>1000 else 'blocked',http_status=raw.get('status'),reason='原始链接已经是组织主页；仓库列表可能需要前端渲染。');return e
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for e in pool.map(resolve,groups.items()):entries.append(e);print(e['id'],e['verification'],flush=True)
    output=P/'directories-platforms.json';output.write_text(json.dumps(entries,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'entries':len(entries),'covered_urls':len({u for e in entries for u in e['covered_urls']})}))

if __name__=='__main__':main()
