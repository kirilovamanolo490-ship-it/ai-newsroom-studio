import React from 'react';
import {interpolate,useCurrentFrame} from 'remotion';
import type {Episode,EpisodeScene,VisualProps} from './types';
import {BrandMark} from './BrandMark';
import {palette} from './shared';
import {EditorialCoverV8} from './EditorialCoverV8';

const editionTitle=(episode:Episode)=>{
 const edition=(episode.edition||'').toLowerCase();
 return /晚|evening|night|pm/.test(edition)?'AI晚报':'AI早报';
};
const editionTime=(episode:Episode)=>editionTitle(episode)==='AI晚报'?'20:00':'08:00';
const coverStories=(episode:Episode):EpisodeScene[]=>{
 const candidates=episode.presentation?.cover_story_ids?.length
  ?episode.presentation.cover_story_ids
  :(episode.presentation?.groups||[]).flatMap(group=>group.story_ids);
 const ids=candidates.length?candidates:episode.scenes.filter(s=>s.id!=='opening'&&s.id!=='closing').map(s=>s.id);
 const seen=new Set<string>();
 return ids.map(id=>episode.scenes.find(s=>s.id===id)).filter((s):s is EpisodeScene=>!!s&&s.id!=='opening'&&s.id!=='closing'&&!seen.has(s.id)&&!!seen.add(s.id)).slice(0,6);
};

export const CleanCoverV6:React.FC<VisualProps>=(props)=>{
 const {episode}=props;
 const frame=useCurrentFrame();
 if((episode.presentation?.version||0)>=8)return <EditorialCoverV8 {...props}/>;
 const stories=coverStories(episode);
 const [year,month,day]=episode.date.split('-');
 const dateHeading=`${year}年${Number(month)}月${Number(day)}日 ${editionTitle(episode)}`;
 const showScheduleTime=episode.presentation?.show_schedule_time??true;
 if(episode.report_kind==='status_only'){
  const status=episode.status_summary?.coverage_text||episode.status_summary?.narration||'已核查本期采集批次，确认新增可发布消息0条。';
  return <div style={{height:'100%',minHeight:0,display:'flex',flexDirection:'column',padding:'0 10px',boxSizing:'border-box',color:palette.ink,fontFamily:'PingFang SC, Helvetica Neue, sans-serif'}}>
   <div style={{flex:'0 0 auto',borderBottom:`2px solid ${palette.ink}`,padding:'0 4px 18px',marginBottom:24}}>
    <div style={{fontSize:88,lineHeight:1.08,fontWeight:700,letterSpacing:-2}}>{dateHeading}</div>
    {showScheduleTime&&<div style={{fontSize:42,lineHeight:1.05,fontWeight:600,color:palette.muted,marginTop:8}}>{editionTime(episode)}</div>}
   </div>
   <div style={{flex:'1 1 auto',display:'flex',flexDirection:'column',justifyContent:'center',alignItems:'center',textAlign:'center',padding:'0 64px'}}>
    <div style={{fontSize:40,fontWeight:650,color:palette.orange,marginBottom:28}}>本期采集状态</div>
    <div style={{fontSize:58,lineHeight:1.35,fontWeight:700,textWrap:'balance'}}>{status}</div>
    <div style={{fontSize:30,color:palette.muted,marginTop:30}}>本期新增可发布消息：0 条</div>
   </div>
  </div>;
 }
 if((episode.presentation?.version||0)>=7&&episode.presentation?.issue_title&&stories.length===3){
  const issueHeading=`${year}年${Number(month)}月${Number(day)}日 ${episode.presentation.issue_title}`;
  return <div style={{height:'100%',minHeight:0,display:'flex',flexDirection:'column',padding:'0 6px',boxSizing:'border-box',color:palette.ink,fontFamily:'PingFang SC, Helvetica Neue, sans-serif'}}>
   <div style={{flex:'0 0 auto',display:'flex',alignItems:'center',justifyContent:'flex-start',borderBottom:`2px solid ${palette.ink}`,padding:'0 4px 18px',marginBottom:12}}>
    <div style={{fontSize:104,lineHeight:1.08,fontWeight:700,letterSpacing:-2,whiteSpace:'nowrap'}}>{issueHeading}</div>
   </div>
   <div style={{flex:'1 1 auto',minHeight:0,display:'grid',gridTemplateColumns:'repeat(3,minmax(0,1fr))',gridTemplateRows:'minmax(0,1fr)',rowGap:0}}>
    {stories.map((story,index)=>{
     const coverTitle=story.visual?.cover_title||story.title;
     const lines=coverTitle.split(/\r?\n/).filter(Boolean);
     return <div key={story.id} style={{minWidth:0,minHeight:0,display:'flex',flexDirection:'column',alignItems:'center',justifyContent:'center',padding:'24px 22px',boxSizing:'border-box',borderLeft:index>0?`1px solid ${palette.line}`:undefined,opacity:interpolate(frame,[index*4,index*4+16],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp'})}}>
      <div style={{width:'100%',height:210,display:'flex',alignItems:'center',justifyContent:'center',flexShrink:0}}><BrandMark episode={episode} id={story.brand_id} maxWidth={210} maxHeight={200}/></div>
      <div style={{display:'flex',flexDirection:'column',alignItems:'center',gap:16,marginTop:24,minWidth:0,maxWidth:'100%',textAlign:'center'}}>
       {lines.map((line,lineIndex)=><div key={`${story.id}-${lineIndex}`} style={{minWidth:0,maxWidth:'100%',fontSize:lineIndex===0&&lines.length>1?54:64,lineHeight:1.18,fontWeight:lineIndex===0&&lines.length>1?620:700,letterSpacing:-.5,color:lineIndex===0&&lines.length>1?palette.orange:palette.ink,textWrap:'balance',overflowWrap:'break-word'}}>{line}</div>)}
      </div>
     </div>;
    })}
   </div>
  </div>;
 }
 return <div style={{height:'100%',minHeight:0,display:'flex',flexDirection:'column',padding:'0 6px',boxSizing:'border-box',color:palette.ink,fontFamily:'PingFang SC, Helvetica Neue, sans-serif'}}>
  <div style={{flex:'0 0 auto',display:'flex',alignItems:'center',justifyContent:'space-between',borderBottom:`2px solid ${palette.ink}`,padding:'0 4px 18px',marginBottom:12}}>
   {(episode.presentation?.version||0)>=7?<div style={{display:'flex',flexDirection:'column',alignItems:'flex-start',gap:8}}>
    <div style={{fontSize:88,lineHeight:1.08,fontWeight:700,letterSpacing:-2,whiteSpace:'nowrap'}}>{dateHeading}</div>
    {showScheduleTime&&<div style={{fontSize:42,lineHeight:1.05,fontWeight:600,color:palette.muted,fontVariantNumeric:'tabular-nums'}}>{editionTime(episode)}</div>}
   </div>:<>
   <div style={{fontSize:110,lineHeight:1,fontWeight:700,letterSpacing:-3,whiteSpace:'nowrap'}}>{editionTitle(episode)}</div>
   <div style={{display:'flex',flexDirection:'column',alignItems:'flex-end',gap:2,paddingBottom:2}}>
    <div style={{fontSize:64,lineHeight:1.05,fontWeight:650,letterSpacing:0,whiteSpace:'nowrap',fontVariantNumeric:'tabular-nums'}}>{episode.date.replace(/-/g,'.')}</div>
    {showScheduleTime&&<div style={{fontSize:52,lineHeight:1.05,fontWeight:650,letterSpacing:1,whiteSpace:'nowrap',fontVariantNumeric:'tabular-nums'}}>{editionTime(episode)}</div>}
   </div>
   </>}
  </div>
  <div style={{flex:'1 1 auto',minHeight:0,display:'grid',gridTemplateColumns:'1fr 1fr',gridTemplateRows:'repeat(3,minmax(0,1fr))',columnGap:42,rowGap:0}}>
   {stories.map((story,index)=><div key={story.id} style={{minWidth:0,minHeight:0,display:'grid',gridTemplateColumns:'175px minmax(0,1fr)',columnGap:22,alignItems:'center',padding:'8px 6px',boxSizing:'border-box',borderBottom:index<4?`1px solid ${palette.line}`:undefined,opacity:interpolate(frame,[index*4,index*4+16],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp'})}}>
    <div style={{minWidth:0,display:'flex',alignItems:'center',justifyContent:'flex-start'}}><BrandMark episode={episode} id={story.brand_id} maxWidth={170} maxHeight={96}/></div>
    <div style={{minWidth:0,fontSize:44,lineHeight:1.23,fontWeight:620,letterSpacing:-.2,textWrap:'balance',whiteSpace:'pre-line',overflow:'hidden',display:'-webkit-box',WebkitLineClamp:2,WebkitBoxOrient:'vertical',overflowWrap:'break-word'}}>{story.visual?.cover_title||story.title}</div>
   </div>)}
  </div>
 </div>;
};
