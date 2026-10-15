import React from 'react';
import {interpolate,useCurrentFrame} from 'remotion';
import {BrandMark} from './BrandMark';
import type {VisualProps} from './types';
import {palette} from './shared';

export const V6Closing:React.FC<VisualProps>=({episode})=>{
 const frame=useCurrentFrame();
 const groups=episode.presentation?.groups||[];
 const count=episode.scenes.filter(s=>s.id!=='opening'&&s.id!=='closing').length;
 const dense=groups.some(group=>group.story_ids.length>3);
 if(episode.report_kind==='status_only')return <div style={{height:'100%',display:'flex',flexDirection:'column',gap:42}}>
  <div style={{fontSize:78,fontWeight:740,paddingBottom:22,borderBottom:`2px solid ${palette.ink}`}}>本期状态</div>
  <div style={{flex:1,display:'flex',flexDirection:'column',justifyContent:'center',gap:34}}>
   <div style={{fontSize:82,fontWeight:690,lineHeight:1.25}}>待核线索已保留<br/>核实后继续补充</div>
   <div style={{fontSize:36,color:palette.muted}}>{episode.status_summary?.coverage_status==='partial'?'本期来源覆盖不完整':'本期来源覆盖完整'}</div>
  </div>
 </div>;
 return <div style={{height:'100%',display:'flex',flexDirection:'column',gap:30}}>
  <div style={{display:'flex',alignItems:'baseline',justifyContent:'space-between',paddingBottom:22,borderBottom:`2px solid ${palette.ink}`}}><div style={{fontSize:78,fontWeight:740}}>本期回顾</div><div style={{fontSize:46,fontWeight:600}}>{count}条消息</div></div>
  <div style={{display:'grid',gridTemplateColumns:`repeat(${Math.max(groups.length,1)},minmax(0,1fr))`,gap:56,flex:1,minHeight:0}}>
   {groups.map((group,index)=><div key={group.id||group.label} style={{minWidth:0,opacity:interpolate(frame,[index*5,index*5+15],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp'})}}>
    <div style={{fontSize:42,fontWeight:670,color:palette.orange,paddingBottom:20,borderBottom:`1px solid ${palette.line}`}}>{group.label}</div>
    {group.story_ids.map(id=>episode.scenes.find(s=>s.id===id)).filter(Boolean).map(story=>story&&<div key={story.id} style={{display:'flex',alignItems:'center',gap:20,minHeight:dense?126:162,padding:'16px 0',boxSizing:'border-box',borderBottom:`1px solid ${palette.line}`}}><div style={{width:dense?84:110,flexShrink:0}}><BrandMark episode={episode} id={story.brand_id} maxWidth={dense?80:105} maxHeight={60}/></div><div style={{fontSize:(story.visual?.recap_title||story.title).length>28?30:34,fontWeight:620,lineHeight:1.25,minWidth:0,textWrap:'balance'}}>{story.visual?.recap_title||story.title}</div></div>)}
   </div>)}
  </div>
 </div>;
};
