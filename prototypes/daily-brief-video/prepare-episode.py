"""Reviewed report + edited speech + verified assets -> timed episode.
Neural synthesis failures stop production, never substitute the old voice.
"""
from pathlib import Path
import argparse,asyncio,json,subprocess,wave,math,hashlib,shutil,datetime as dt,difflib,sys,os
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PUBLIC=ROOT/'research/evidence'
sys.path.insert(0,str(ROOT/'tools'))
from media_runtime import resolve_media_tools
from brand_assets import dimensions as image_dimensions
from edition_contract import report_fingerprint,validate_report_window,report_namespace,navigation_story_order,validate_narration_order
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--date',required=True)
parser.add_argument('--edition',choices=['morning','evening','briefing'],help='Optional edition namespace; briefing requires explicit report window timestamps')
parser.add_argument('--namespace',help='Optional separate briefing-* output folder')
parser.add_argument('--narration',type=Path,required=True)
parser.add_argument('--rate',type=int,default=185,help='Legacy macOS words per minute')
parser.add_argument('--voice-provider',choices=['seed','edge','macos'])
parser.add_argument('--voice')
parser.add_argument('--speech-rate')
parser.add_argument('--proxy',default=os.environ.get('AI_NEWS_PROXY'))
args=parser.parse_args()
namespace=report_namespace({'edition':args.edition},args.namespace)
out=PUBLIC/args.date/namespace
report=json.loads((out/'report.json').read_text())
report_namespace(report,namespace)
assert report['date']==args.date
if args.edition == 'briefing' and report.get('edition') != 'briefing':
    raise ValueError('Briefing preparation requires a report marked edition="briefing"')
validate_report_window(report)
draft=json.loads(args.narration.read_text())
scenes=draft['scenes']
status_only=report.get('report_kind')=='status_only'
if status_only and report.get('stories') != []:
    raise ValueError('status_only episode requires an empty stories array')
story_order=navigation_story_order(report)
validate_narration_order(report, scenes)
settings=draft.get('voice',{})
provider=args.voice_provider or settings.get('provider','macos')
voice_name=args.voice or settings.get('name','zh-CN-XiaoxiaoNeural' if provider=='edge' else 'Tingting')
rate=args.speech_rate or settings.get('rate','+10%')
pitch=settings.get('pitch','+0Hz')
public=HERE/'public'/'episodes'/args.date/namespace
voice=public/('voice-v2-'+voice_name if provider in ['seed','edge'] else 'voice')
assets=public/'assets'
voice.mkdir(parents=True,exist_ok=True);assets.mkdir(parents=True,exist_ok=True)
cache_path=voice/'cache.json'
cache=json.loads(cache_path.read_text()) if cache_path.exists() else {}
media_tools=resolve_media_tools(HERE)
ffmpeg=media_tools.get('ffmpeg')
if not ffmpeg: raise RuntimeError('Install FFmpeg on PATH or install the platform Remotion compositor package')
compositor=Path(ffmpeg).parent
def copy_public(url,sha=None):
    source=(PUBLIC/url.lstrip('/')).resolve();source.relative_to(PUBLIC.resolve())
    assert source.is_file(),f'Missing verified asset: {url}'
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    assert not sha or digest==sha,f'Asset checksum mismatch: {url}'
    dest=assets/(digest[:12]+'-'+source.name)
    if not dest.exists():shutil.copy2(source,dest)
    return str(dest.relative_to(HERE/'public'))
asset_paths={a['path']:copy_public(a['path'],a['sha256']) for a in report['image_assets']}
brands=[{**a,'path':copy_public(a['path'],a.get('sha256'))} for a in report.get('brand_assets',[])]
presentation=json.loads(json.dumps(report.get('presentation',{})))
selected_cover=set(presentation.get('cover_story_ids') or story_order[:6])
presentation['cover_story_ids']=[sid for sid in story_order if sid in selected_cover][:6]
if presentation.get('cover_art'):
    art=presentation['cover_art']
    art['path']=copy_public(art['path'],art['sha256'])
story_map={s['id']:s for s in report['stories']}
brand_ids={b.get('id') for b in brands if b.get('cache_status') in (None,'cache_hit')}
missing_brands=sorted({s.get('video_brand_id') or s.get('brand_id') for s in report['stories'] if s.get('video_brand_id') or s.get('brand_id')} - brand_ids)
assert not missing_brands, 'Brand asset missing from verified local cache; review before production: '+', '.join(missing_brands)
for scene in scenes:
    story=story_map.get(scene['id'],{})
    scene['source_captures']=[{**c,'path':copy_public(c['path'],c.get('sha256'))} for c in story.get('source_captures',[])]
    scene['brand_id']=story.get('video_brand_id') or story.get('brand_id')
    scene['visual_preference']=story.get('visual_preference')
    if scene.get('visual',{}).get('phase_images'):
        scene['visual']['phase_images']=[asset_paths[url] for url in scene['visual']['phase_images']]
    if story.get('source_video'):
        video_source=story['source_video']
        scene['original_video']=copy_public(video_source['path'],video_source['sha256'])
        scene['video_start_seconds']=video_source.get('video_start_seconds',0)
async def synthesize_line(scene_id,number,line):
    display=line if isinstance(line,str) else line['text']
    speech=line if isinstance(line,str) else line.get('spoken',display)
    p=voice/f'{scene_id}-{number}.wav'
    cfg={'provider':provider,'voice':voice_name,'rate':rate if provider=='edge' else args.rate,'pitch':pitch,'sample_rate':24000,'speech':speech}
    signature=hashlib.sha256(json.dumps(cfg,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    if p.exists() and cache.get(p.name)==signature:return display,p,signature
    if provider=='macos':
        subprocess.run(['say','-v',voice_name,'-r',str(args.rate),'--data-format=LEI16@24000','-o',str(p),speech],check=True)
    else:
        import edge_tts
        mp3=voice/f'{scene_id}-{number}.mp3';pending=voice/f'{scene_id}-{number}.pending.mp3'
        for attempt in range(2):
            try:
                c=edge_tts.Communicate(speech,voice_name,rate=rate,pitch=pitch,proxy=args.proxy or None,connect_timeout=10,receive_timeout=35)
                await asyncio.wait_for(c.save(str(pending)),45)
                assert pending.stat().st_size>1000,'Empty speech result'
                pending.replace(mp3);break
            except Exception as error:
                pending.unlink(missing_ok=True)
                if attempt==1:raise RuntimeError(f'Neural speech failed for {scene_id}-{number}: {type(error).__name__}; no fallback voice used') from None
                print(json.dumps({'stage':'speech_retry','scene':scene_id,'line':number,'error_type':type(error).__name__}),flush=True)
        temp=p.with_suffix('.pending.wav')
        subprocess.run([ffmpeg,'-y','-v','error','-i',str(mp3),'-ac','1','-ar','24000','-c:a','pcm_s16le',str(temp)],check=True,cwd=compositor)
        temp.replace(p)
    with wave.open(str(p),'rb') as w:assert w.getnframes()>w.getframerate()*.3,'Speech shorter than expected'
    cache[p.name]=signature
    # Save each successful clip so interrupted synthesis resumes incrementally.
    cache_path.write_text(json.dumps(cache,ensure_ascii=False,indent=2)+'\n')
    return display,p,signature
async def prepare_voice():
    semaphore=asyncio.Semaphore(2)
    async def limited(scene_id,number,line):
        async with semaphore:return await synthesize_line(scene_id,number,line)
    return await asyncio.gather(*[limited(s['id'],i,line) for s in scenes for i,line in enumerate(s['lines'])])
def normalize(text):return ''.join(c.lower() for c in text if c.isalnum())
seed_manifest_path=out/'voice-v2'/'run.json'
seed_run=json.loads(seed_manifest_path.read_text()) if provider=='seed' else None
seed_by_id={r['scene_id']:r for r in seed_run['scenes']} if seed_run else {}
def prepare_seed(scene):
    receipt=seed_by_id[scene['id']]
    spoken='\n'.join(line if isinstance(line,str) else line.get('spoken',line['text']) for line in scene['lines'])
    assert receipt['text']==spoken, 'Seed clip does not match current narration; synthesize changed scene before preparing'
    wav=Path(receipt['wav']);assert hashlib.sha256(wav.read_bytes()).hexdigest()==receipt['wav_sha256']
    with wave.open(str(wav),'rb') as w:
        fmt=(w.getnchannels(),w.getsampwidth(),w.getframerate());pcm=w.readframes(w.getnframes())
    words=receipt['timestamps'];assert words,'Real service timestamps are required'
    transcript='';timings=[]
    for word in words:
        token=normalize(word['word']);transcript+=token
        timings.extend([(float(word['startTime']),float(word['endTime']),word.get('confidence'))]*len(token))
    expected=normalize(spoken);matcher=difflib.SequenceMatcher(None,expected,transcript,autojunk=False)
    assert matcher.ratio()>.87, f'Service text alignment too weak for {scene["id"]}: {matcher.ratio()}'
    matched={a+i:b+i for a,b,size in matcher.get_matching_blocks() for i in range(size)}
    offset=0;captions=[]
    for line in scene['lines']:
        display=line if isinstance(line,str) else line['text'];text=line if isinstance(line,str) else line.get('spoken',display)
        count=len(normalize(text));positions=[matched[j] for j in range(offset,offset+count) if j in matched]
        assert positions,f'No timed speech matches for {scene["id"]}'
        first,last=min(positions),max(positions)
        captions.append({'text':display,'startMs':round((.40+timings[first][0])*1000),'endMs':round((.40+timings[last][1])*1000),'timestampMs':None,'confidence':None})
        offset+=count
    # Preserve the entire paragraph, including all provider pauses and prosody.
    lead=round(.40*fmt[2]);trail=round(.40*fmt[2])
    audio=voice/f'{scene["id"]}.wav';voice.mkdir(parents=True,exist_ok=True)
    with wave.open(str(audio),'wb') as w:
        w.setnchannels(fmt[0]);w.setsampwidth(fmt[1]);w.setframerate(fmt[2]);w.writeframes(b'\0'*lead*fmt[0]*fmt[1]+pcm+b'\0'*trail*fmt[0]*fmt[1])
    seconds=(lead+trail+len(pcm)//(fmt[0]*fmt[1]))/fmt[2]
    return audio,captions,seconds,matcher.ratio()
clips=None if provider=='seed' else iter(asyncio.run(prepare_voice()))
offset_frames=0
for scene_index,scene in enumerate(scenes):
    buffers=[];captions=[];offset=0;fmt=None
    for number,line in enumerate(scene['lines'] if provider!='seed' else []):
        display,p,signature=next(clips)
        with wave.open(str(p),'rb') as w:
            if fmt is None:
                fmt=(w.getnchannels(),w.getsampwidth(),w.getframerate())
                lead=round(.40*fmt[2]);buffers.append(b'\0'*lead*fmt[0]*fmt[1]);offset=lead
            assert fmt==(w.getnchannels(),w.getsampwidth(),w.getframerate())
            frames=w.getnframes();buffers.append(w.readframes(frames))
            captions.append({'text':display,'startMs':round(offset/fmt[2]*1000),'endMs':round((offset+frames)/fmt[2]*1000),'timestampMs':None,'confidence':None})
            offset+=frames
            gap=round(.12*fmt[2]);buffers.append(b'\0'*gap*fmt[0]*fmt[1]);offset+=gap
    if provider=='seed':
        audio,captions,seconds,alignment=prepare_seed(scene)
        scene['caption_alignment']={'method':'Original lines aligned to actual service word timestamps by matching text, not by estimated character duration','matching_ratio':alignment}
    else:
        trail=round(.40*fmt[2]);buffers.append(b'\0'*trail*fmt[0]*fmt[1]);offset+=trail
        audio=voice/f'{scene["id"]}.wav'
        with wave.open(str(audio),'wb') as w:
            w.setnchannels(fmt[0]);w.setsampwidth(fmt[1]);w.setframerate(fmt[2]);w.writeframes(b''.join(buffers))
        seconds=offset/fmt[2]
    frames=math.ceil(seconds*30)
    story=story_map.get(scene['id'],{})
    scene.update(captions=captions,audio=str(audio.relative_to(HERE/'public')),durationInFrames=frames,startFrame=offset_frames,original_image=asset_paths.get(story.get('image','')),source_time=story.get('time',''),source_type=story.get('type',''))
    offset_frames+=frames-(12 if scene_index<len(scenes)-1 else 0)
    print(json.dumps({'scene':scene['id'],'duration_seconds':round(seconds,2),'frames':frames},ensure_ascii=False),flush=True)
fingerprint=report_fingerprint(report)
window_start,window_end=report.get('window_start'),report.get('window_end')
if args.edition and (not window_start or not window_end):
    if args.edition == 'briefing':
        raise ValueError('Briefing reports require explicit timezone-aware window_start and window_end')
    shanghai=dt.timezone(dt.timedelta(hours=8));day=dt.date.fromisoformat(args.date)
    start_day=day-dt.timedelta(days=1) if args.edition=='morning' else day
    start_hour=20 if args.edition=='morning' else 8
    end_hour=8 if args.edition=='morning' else 20
    window_start=dt.datetime.combine(start_day,dt.time(start_hour),shanghai).isoformat()
    window_end=dt.datetime.combine(day,dt.time(end_hour),shanghai).isoformat()
episode={'date':args.date,'edition':args.edition,'report_kind':report.get('report_kind','news'),'status_summary':report.get('status_summary'),'output_namespace':namespace,'window_start':window_start,'window_end':window_end,'baseurl':'/'+args.date+(('/'+namespace) if namespace else ''),'fps':30,'width':1920,'height':1080,'transitionFrames':12,'durationInFrames':offset_frames,'evidence_cutoff':report['evidence_cutoff'],'scenes':scenes,'charts':report['charts'],'images':report['image_assets'],'brand_assets':brands,'presentation':presentation,'source_report_fingerprint':fingerprint,'voice':{'name':voice_name,'provider':provider,'rate':rate if provider=='edge' else args.rate,'pitch':pitch if provider=='edge' else 'system default','sample_rate':24000,'timing':'Measured PCM per sentence; all captions and navigation use the same timeline','implementation_source':'https://github.com/rany2/edge-tts' if provider=='edge' else 'macOS say'},'created_at':dt.datetime.now(dt.timezone.utc).isoformat()}
dimensions={}
episode['sequence_contract']='navigation-groups-v1'
episode['navigation_story_order']=story_order
for file in assets.iterdir():
    if file.is_file() and file.suffix.lower() in ['.png','.svg','.jpg','.jpeg','.webp']:
        width,height=image_dimensions(file.read_bytes(),file.suffix)
        dimensions[str(file.relative_to(HERE/'public'))]={'width':width,'height':height}
episode['asset_dimensions']=dimensions
for brand in brands:
    if brand.get('width') and brand.get('height'):
        dimensions[brand['path']]={'width':brand['width'],'height':brand['height']}
if seed_run:
    episode['voice']={'provider':seed_run['provider'],'model':seed_run['model'],'resource_id':seed_run['resource_id'],'name':seed_run['speaker'],'sample_rate':24000,'method':'Whole-scene synthesis with context_texts direction, original prosody preserved','timing':'Measured WAV with captions aligned to actual service word timestamps','settings':seed_run['scenes'][0]['settings'],'receipt_manifest':str(seed_manifest_path.relative_to(ROOT))}
    draft['voice']={**draft['voice'],'name':seed_run['speaker'],'model':seed_run['model'],'resource_id':seed_run['resource_id']}
generated=HERE/'src/episodes/generated';generated.mkdir(parents=True,exist_ok=True)
if args.edition:
    generated=generated/args.date;generated.mkdir(parents=True,exist_ok=True)
    episode_json=json.dumps(episode,ensure_ascii=False,indent=2)+'\n'
    (generated/f'{namespace}.json').write_text(episode_json)
else:
    episode_json=json.dumps(episode,ensure_ascii=False,indent=2)+'\n'
    (HERE/'src/episodes/generated/latest.json').write_text(episode_json)
(out/'video-props.json').write_text(json.dumps({'episode':episode},ensure_ascii=False,indent=2)+'\n')
(out/'narration.json').write_text(json.dumps(draft,ensure_ascii=False,indent=2)+'\n')
(out/'video-chapters.json').write_text(json.dumps([{'id':s['id'],'title':s['title'],'start_seconds':round(s['startFrame']/30,3),'duration_seconds':round(s['durationInFrames']/30,3),'source_url':s['source_url']} for s in scenes],ensure_ascii=False,indent=2)+'\n')
def timestamp(ms):
    hours,ms=divmod(ms,3600000);minutes,ms=divmod(ms,60000);seconds,ms=divmod(ms,1000)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}'
srt=[];index=1
for scene in scenes:
    base_ms=round(scene['startFrame']/30*1000)
    for c in scene['captions']:
        srt.append(f'{index}\n{timestamp(base_ms+c["startMs"])} --> {timestamp(base_ms+c["endMs"])}\n{c["text"]}\n');index+=1
(out/'subtitles.srt').write_text('\n'.join(srt))
print(json.dumps({'total_seconds':offset_frames/30,'total_frames':offset_frames,'captions':index-1,'voice':episode['voice'],'props':str(out/'video-props.json')},ensure_ascii=False),flush=True)
