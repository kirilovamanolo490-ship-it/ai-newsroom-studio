"""Repeatable local production from reviewed editorial data, never external publishing."""
from pathlib import Path
import argparse,subprocess,sys,json,shutil,datetime as dt,atexit
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from media_runtime import resolve_media_tools, resolve_node
from edition_contract import report_fingerprint,validate_report_window,report_namespace,validate_narration_order
from completion_gate import check_video,should_render
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--date',required=True)
parser.add_argument('--edition',choices=['morning','evening','briefing'],help='Optional edition namespace; morning/evening use fixed 12-hour windows, briefing uses the reviewed report window')
parser.add_argument('--namespace',help='Separate briefing-* output folder for another supplemental video on the same date')
parser.add_argument('--narration',type=Path,help='Original edited scene narration JSON')
parser.add_argument('--collect-due',action='store_true',help='First collect due sources using their own configured cadence; partial failures retain watermarks')
parser.add_argument('--render-video',action='store_true',default=None,help='Regenerate local voice/subtitles and render an original MP4 (default for morning/evening)')
parser.add_argument('--web-only-maintenance',action='store_true',help='Build web output only; explicitly records maintenance and never marks the issue completed')
parser.add_argument('--verify-only',action='store_true',help='Recheck the existing video and playback receipt without TTS, rendering, or web generation')
parser.add_argument('--preview-frames',action='store_true',help='Render every scene still before rendering')
parser.add_argument('--voice-rate',type=int,default=200)
args=parser.parse_args();dt.date.fromisoformat(args.date)
args.render_video=should_render(args.edition,args.render_video,args.web_only_maintenance,args.verify_only)
namespace=report_namespace({'edition':args.edition},args.namespace)
out=ROOT/'research/evidence'/args.date
if namespace: out=out/namespace
report=out/'report.json'
stages=[]
active_stage='startup'
run_record={'date':args.date,'edition':args.edition,'output_namespace':namespace,'status':'running','stages':stages}
def save_run():
    out.mkdir(parents=True,exist_ok=True)
    run_record.update({'ran_at':dt.datetime.now(dt.timezone.utc).isoformat(),'stages':stages})
    tmp=out/'production-run.json.tmp';tmp.write_text(json.dumps(run_record,ensure_ascii=False,indent=2)+'\n');tmp.replace(out/'production-run.json')
def checkpoint():
    if not args.web_only_maintenance and args.edition in ('morning','evening','briefing') and run_record.get('status')=='running':
        run_record.update(status='failed',failure={'stage':active_stage,'reason':'interrupted_or_failed'})
        save_run()
atexit.register(checkpoint)
d=None
if not report.exists():
    raise FileNotFoundError(f'First curate and review this edition into {report}; unreviewed raw candidates are not automatically published')
def run(label,command,cwd=ROOT,allow_partial=False):
    global active_stage
    active_stage=label
    stages.append({'stage':label,'status':'running'});save_run()
    print(json.dumps({'stage':label,'state':'started'},ensure_ascii=False),flush=True)
    result=subprocess.run([str(v) for v in command],cwd=cwd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if result.returncode and not (allow_partial and result.returncode==2):
        stages[-1].update(exit_code=result.returncode,status='failed');save_run()
        raise RuntimeError(f'{label} failed with code {result.returncode}')
    stages[-1].update(exit_code=result.returncode,status='partial_source_coverage' if result.returncode==2 else 'completed');save_run()
d=json.loads(report.read_text())
expected_status_batches=1 if args.edition=='briefing' else 6
assert d['date']==args.date and (d.get('stories') or (d.get('report_kind')=='status_only' and d.get('stories')==[] and d.get('status_summary',{}).get('batch_count')==expected_status_batches))
report_namespace(d,namespace)
if args.edition == 'briefing' and d.get('edition') != args.edition:
    raise ValueError(f"Report edition {d.get('edition')!r} does not match requested edition {args.edition!r}")
validate_report_window(d)
if args.edition == 'briefing':
    brief_start=dt.datetime.fromisoformat(d['window_start'].replace('Z','+00:00'))
    brief_end=dt.datetime.fromisoformat(d['window_end'].replace('Z','+00:00'))
    if brief_end-brief_start != dt.timedelta(hours=2):
        raise ValueError('Briefing reports must cover exactly one two-hour batch')
fingerprint=report_fingerprint(d)
project=ROOT/'prototypes/daily-brief-video'
ffprobe=resolve_media_tools(project).get('ffprobe')
if args.edition in ('morning','evening','briefing') and not args.web_only_maintenance and not ffprobe:
    raise RuntimeError('Install FFmpeg on PATH or the platform Remotion compositor package before media verification')
own_manifest=out/'own-video.json'
reused_video=False
if args.edition in ('morning','evening','briefing') and not args.web_only_maintenance:
    try:
        existing=json.loads(own_manifest.read_text()) if own_manifest.is_file() else {}
        if existing.get('status')=='verified' and existing.get('source_report_fingerprint')==fingerprint:
            media=check_video(d,own_manifest,ROOT/'research/evidence',ffprobe)
            reused_video=True
    except (ValueError,json.JSONDecodeError):
        if args.verify_only: raise
if args.verify_only:
    if not reused_video: raise SystemExit('Existing video did not pass completion gate')
    record=run_record;record.update(status='completed',source_report_fingerprint=fingerprint,media_verified=media,verification_only=True)
    save_run();print(json.dumps({'status':'completed','reused_video':True,'external_publication':False},ensure_ascii=False));sys.exit(0)
brand_sync=subprocess.run([sys.executable,str(ROOT/'tools/brand_assets.py'),'sync','--report',str(report)],cwd=ROOT,capture_output=True,text=True)
if brand_sync.returncode: raise RuntimeError('local_brand_asset_sync failed')
brand_receipt=json.loads(brand_sync.stdout)
stages.append({'stage':'local_brand_asset_sync','exit_code':0,'status':brand_receipt.get('status','completed'),'pending_report_assets':brand_receipt.get('pending_report_assets',[])})
if brand_receipt.get('pending_report_assets'):
    raise RuntimeError('Brand assets need local-cache review before production: '+', '.join(brand_receipt['pending_report_assets']))
node=resolve_node()
if not args.web_only_maintenance and not reused_video:
    assert node and (project/'node_modules/remotion').exists(), 'Install Node.js on PATH and run npm ci in the Remotion project first'
    assert ffprobe, 'Install FFmpeg on PATH or install the platform Remotion compositor package'
if args.collect_due:
    run('collect_due_sources',[sys.executable,ROOT/'tools/source_watch.py'],allow_partial=True)
if args.render_video and not reused_video:
    narration=args.narration or (out/'narration-draft.json' if (out/'narration-draft.json').is_file() else out/'narration.json')
    assert narration.exists(), 'Original edited narration is required; reference videos are not production footage'
    draft=json.loads(narration.read_text())
    # Reject a script that jumps between navigation groups before paid synthesis.
    validate_narration_order(d, draft.get('scenes', []))
    if draft.get('voice',{}).get('provider')=='seed':
        seed_command=[sys.executable,ROOT/'tools/synthesize_seed_voice.py','--narration',narration,'--output',out/'voice-v2']
        if args.edition:seed_command.extend(['--manifest',out/'voice-v2/run.json'])
        run('whole_scene_seed_voice',seed_command)
    prepare=[sys.executable,project/'prepare-episode.py','--date',args.date,'--narration',narration,'--rate',args.voice_rate]
    if args.edition: prepare.extend(['--edition',args.edition])
    if args.namespace: prepare.extend(['--namespace',args.namespace])
    run('original_voice_and_captions',prepare)
    run('typescript_check',[node,project/'node_modules/typescript/bin/tsc','--noEmit'],project)
    if args.preview_frames:
        preview=[node,project/'render-episode.cjs',args.date,'preview']+([args.edition] if args.edition else [])+([args.namespace] if args.namespace else [])
        run('scene_previews',preview,project)
    render=[node,project/'render-episode.cjs',args.date,'render']+([args.edition] if args.edition else [])+([args.namespace] if args.namespace else [])
    run('original_video_render',render,project)
run('same_data_web_report',[sys.executable,ROOT/'research/report-redesign/build_report.py','--input',report])
record=run_record
record.update({'window_start':d.get('window_start'),'window_end':d.get('window_end'),'source_report_fingerprint':fingerprint,'evidence_cutoff':d['evidence_cutoff'],'report':str(report.relative_to(ROOT)),'web_url':f'http://127.0.0.1:4311/{args.date}/'+(f'{namespace}/' if namespace else ''),'external_publication':False,'boundary':'Video and web report are separate production stages. Completion requires a verified original video for every scheduled video slot.'})
video_stem='ai-daily-'+args.date+(f'-{args.edition}' if args.edition else '')
own_manifest=out/'own-video.json'
own=json.loads(own_manifest.read_text()) if own_manifest.exists() else {}
video_present=bool(own.get('path') and (ROOT/'research/evidence'/own['path'].lstrip('/')).is_file())
if args.edition in ('morning','evening','briefing') and not args.web_only_maintenance:
    active_stage='completion_gate'
    try: media=check_video(d,own_manifest,ROOT/'research/evidence',ffprobe)
    except ValueError as exc:
        record.update(status='incomplete',failure={'stage':active_stage,'reason':str(exc)})
        save_run()
        print(json.dumps({'status':'incomplete','reason':str(exc),'web_url':record['web_url'],'external_publication':False},ensure_ascii=False),flush=True)
        sys.exit(2)
    record['media_verified']=media;record['status']='completed'
else:
    record.update(status='maintenance_only' if args.web_only_maintenance else 'completed')
save_run()
print(json.dumps({'status':record['status'],'web_url':record['web_url'],'video_present':video_present,'external_publication':False},ensure_ascii=False),flush=True)
