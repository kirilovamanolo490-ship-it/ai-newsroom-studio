import React from 'react';
import {AbsoluteFill,interpolate,staticFile,useCurrentFrame,useVideoConfig} from 'remotion';
import {Audio} from '@remotion/media';
import type {VisualProps} from './types';
import {palette} from './shared';
import {BrandMark} from './BrandMark';

export const EpisodeFrame:React.FC<VisualProps&{children:React.ReactNode}>=({scene,episode,children})=>{
 const f=useCurrentFrame();const {fps}=useVideoConfig();const now=f/fps*1000;
 const caption=episode.posterMode?undefined:scene.captions.find(c=>now>=c.startMs&&now<c.endMs);
 const hero=scene.id==='opening'||scene.id==='closing';
 const issueGroups=(episode.presentation?.groups||[]).map((g,i)=>({id:g.id||`group-${i}`,label:g.label,ids:g.story_ids}));
 const navigation=[{id:'opening',label:'导读',ids:['opening']},...issueGroups,{id:'closing',label:'回顾',ids:['closing']}];
 const progress=Math.min(1,(scene.startFrame+f)/episode.durationInFrames);
 const titleAlpha=interpolate(f,[0,12],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp'});
 const background=(episode.presentation?.version||0)>=8?'#fffefa':palette.paper;
 if(episode.posterMode&&scene.id==='opening')return <AbsoluteFill style={{background,color:palette.ink,fontFamily:'PingFang SC, Helvetica Neue, sans-serif'}}><div style={{position:'absolute',left:72,right:72,top:90,bottom:90}}>{children}</div></AbsoluteFill>;
 return <AbsoluteFill style={{background,color:palette.ink,fontFamily:'PingFang SC, Helvetica Neue, sans-serif',overflow:'hidden'}}>
  <Audio src={staticFile(scene.audio)}/>
  <div data-zone="category-navigation" style={{position:'absolute',left:64,right:64,top:28,height:56,display:'flex',gap:6}}>
   {navigation.map(g=>{const active=g.ids.includes(scene.id);return <div key={g.id} style={{flex:(g.id==='opening'||g.id==='closing') ? 0.65 : 1.6,display:'flex',justifyContent:'center',alignItems:'center',fontSize:28,fontWeight:active?700:500,borderRadius:5,background:active?palette.orange:'#ebe8df',color:active?'white':palette.muted}}>{g.label}</div>;})}
  </div>
  {!hero&&<div data-zone="headline" style={{position:'absolute',left:72,right:72,top:126,height:78,display:'flex',alignItems:'center',gap:20,opacity:titleAlpha}}>
   <BrandMark episode={episode} id={scene.brand_id} maxWidth={['cloudflare','elevenlabs','qoder'].includes(scene.brand_id||'')?210:132} maxHeight={76}/>
   <div style={{fontSize:62,lineHeight:1.16,fontWeight:730,letterSpacing:-1.5}}>{scene.title}</div>
  </div>}
  <div data-zone="story-content" style={{position:'absolute',left:72,right:72,top:hero?139:234,height:hero?732:652}}>{children}</div>
  <div data-zone="captions" style={{position:'absolute',left:80,right:80,top:894,height:96,display:'flex',alignItems:'center',justifyContent:'center'}}>
   {caption&&<div style={{fontSize:caption.text.length>42?34:40,lineHeight:1.18,fontWeight:550,textAlign:'center',textWrap:'balance',padding:'6px 22px',color:'#fff',background:'#36372feb',borderRadius:6,maxWidth:1730}}>{caption.text}</div>}
  </div>
  <div data-zone="story-navigation" style={{position:'absolute',left:64,right:64,top:1001,height:50,display:'flex',gap:5}}>
   {episode.scenes.map(s=>{const active=s.id===scene.id;const label=s.short_label||s.title;return <div key={s.id} style={{flex:active?1.15:1,minWidth:0,display:'flex',alignItems:'center',justifyContent:'center',borderRadius:4,background:active?'#f0dfcf':'#ebe8df',color:active?palette.orange:palette.muted,fontWeight:active?700:500,fontSize:episode.scenes.length>11||label.length>9?20:25,whiteSpace:'nowrap'}}>{label}</div>;})}
  </div>
  <div style={{position:'absolute',left:64,right:64,top:1063,height:4,background:palette.line}}><div style={{height:'100%',width:`${progress*100}%`,background:palette.orange}}/></div>
 </AbsoluteFill>;
};
