import React from 'react';
import {interpolate,useCurrentFrame} from 'remotion';
import type {Episode,EpisodeScene,VisualProps} from './types';
import {BrandMark} from './BrandMark';

const getEditionLabel=(episode:Episode)=>{
 const edition=(episode.edition||'').toLowerCase();
 if(/briefing|此刻/.test(edition))return 'AI此刻';
 const requested=episode.presentation?.issue_title?.trim();
 if(requested)return requested;
 if(/晚|evening|night|pm/.test(edition))return 'AI晚报';
 return 'AI早报';
};

const getLead=(episode:Episode):EpisodeScene|undefined=>{
 const isStory=(scene:EpisodeScene)=>scene.id!=='opening'&&scene.id!=='closing';
 const explicit=episode.presentation?.lead_story_id;
 if(explicit){
  const selected=episode.scenes.find(scene=>scene.id===explicit&&isStory(scene));
  if(selected)return selected;
 }
 const fallbackIds=episode.presentation?.cover_story_ids||[];
 for(const id of fallbackIds){
  const selected=episode.scenes.find(scene=>scene.id===id&&isStory(scene));
  if(selected)return selected;
 }
 return episode.scenes.find(isStory);
};

const getHeadline=(episode:Episode,lead?:EpisodeScene)=>{
 const supplied=episode.presentation?.cover_headline?.trim();
 return (supplied||lead?.visual?.cover_title||lead?.title||'本期暂无头条').trim();
};

const getBrandIds=(episode:Episode,lead?:EpisodeScene)=>{
 const available=new Set((episode.brand_assets||[]).map(asset=>asset.id));
 const requested=episode.presentation?.cover_brand_ids;
 const candidates=requested?.length?requested:episode.scenes
  .filter(scene=>scene.id!=='opening'&&scene.id!=='closing')
  .map(scene=>scene.brand_id)
  .filter((id):id is string=>!!id);
 if(!candidates.length&&lead?.brand_id)candidates.push(lead.brand_id);
 return [...new Set(candidates.filter(id=>available.has(id)))].slice(0,4);
};

const characterWidth=(value:string)=>Array.from(value).reduce((sum,char)=>sum+(char.charCodeAt(0)>0xff?1:0.56),0);

export const EditorialCoverV8:React.FC<VisualProps>=({episode})=>{
 const frame=useCurrentFrame();
 const [year,month,day]=episode.date.split('-');
 const dateText=`${year}年${Number(month)}月${Number(day)}日`;
 const issueTitle=getEditionLabel(episode);
 const issueTime=episode.presentation?.issue_time?.trim();

 if(episode.report_kind==='status_only'){
  const headline=episode.presentation?.cover_headline?.trim();
  const status=headline||episode.status_summary?.coverage_text||episode.status_summary?.narration||'本时段暂无已核新增';
  const statusSize=headline?82:Math.max(48,Math.min(82,1040/characterWidth(status)));
  return <div style={{position:'relative',width:'100%',height:'100%',boxSizing:'border-box',padding:'54px 76px',display:'flex',flexDirection:'column',background:'#fffefa',color:'#25251f',fontFamily:'PingFang SC, Helvetica Neue, sans-serif'}}>
   <header style={{display:'flex',alignItems:'baseline',gap:26,flexShrink:0}}>
    <div style={{fontSize:40,fontWeight:550,color:'#77766f',fontVariantNumeric:'tabular-nums'}}>{dateText}</div>
    <div style={{fontSize:48,fontWeight:700,letterSpacing:-.6}}>{issueTitle}</div>
    {issueTime&&<div style={{marginLeft:'auto',fontSize:24,fontWeight:550,color:'#77766f'}}>{issueTime} 更新</div>}
   </header>
   <div style={{flex:1,minHeight:0,display:'flex',flexDirection:'column',justifyContent:'center',maxWidth:1330}}>
    <div style={{fontSize:24,fontWeight:600,color:'#a65b35',marginBottom:22}}>采集状态</div>
    <div style={{fontSize:statusSize,lineHeight:1.2,fontWeight:680,letterSpacing:-1,textWrap:'balance',whiteSpace:'pre-line',overflowWrap:'anywhere'}}>{status}</div>
    {episode.status_summary?.coverage_status==='partial'&&<div style={{marginTop:28,fontSize:23,color:'#77766f'}}>本期覆盖不完整</div>}
   </div>
   <div aria-hidden style={{position:'absolute',left:76,right:76,top:120,height:1.5,background:'#d9d6cf',pointerEvents:'none'}}/>
  </div>;
 }

 const lead=getLead(episode);
 const headline=getHeadline(episode,lead);
 const lines=headline.split(/\r?\n/).filter(Boolean);
 const maxLineWidth=Math.max(...lines.map(characterWidth),1);
 const headlineSize=Math.max(54,Math.min(94,Math.min(1000/maxLineWidth,560/(Math.max(lines.length,2)*1.15))));
 const brandIds=getBrandIds(episode,lead);
 const logoMax=brandIds.length===1?280:brandIds.length===2?230:210;

 return <div style={{position:'relative',width:'100%',height:'100%',boxSizing:'border-box',padding:'52px 64px',display:'grid',gridTemplateColumns:'minmax(0,1.42fr) minmax(300px,.78fr)',columnGap:42,alignItems:'stretch',background:'#fffefa',color:'#25251f',fontFamily:'PingFang SC, Helvetica Neue, sans-serif'}}>
  <div style={{minWidth:0,minHeight:0,display:'flex',flexDirection:'column'}}>
   <header style={{display:'flex',alignItems:'baseline',gap:24,flexShrink:0}}>
    <div style={{fontSize:40,fontWeight:550,color:'#77766f',fontVariantNumeric:'tabular-nums',whiteSpace:'nowrap'}}>{dateText}</div>
    <div style={{fontSize:48,fontWeight:700,letterSpacing:-.6,whiteSpace:'nowrap'}}>{issueTitle}</div>
    {issueTime&&<div style={{marginLeft:'auto',fontSize:23,fontWeight:550,color:'#77766f',whiteSpace:'nowrap'}}>{issueTime} 更新</div>}
   </header>
   <div style={{flex:1,minHeight:0,display:'flex',alignItems:'center',padding:'24px 26px 16px 0'}}>
    <div style={{maxWidth:'100%',fontSize:headlineSize,lineHeight:1.17,fontWeight:730,letterSpacing:-1.5,whiteSpace:'pre-wrap',textWrap:'balance',overflowWrap:'anywhere',wordBreak:'normal'}}>{headline}</div>
   </div>
  </div>
  <div style={{minWidth:0,minHeight:0,display:'grid',gridTemplateColumns:brandIds.length===1?'minmax(0,1fr)':'repeat(2,minmax(0,1fr))',gridTemplateRows:brandIds.length>2?'repeat(2,minmax(0,1fr))':'minmax(0,1fr)',alignItems:'center',justifyItems:'center',alignContent:'center',gap:18,padding:'92px 4px 32px'}}>
   {brandIds.map((id,index)=><div key={id} style={{width:'100%',height:'100%',minHeight:128,gridColumn:brandIds.length===3&&index===2?'1 / -1':undefined,display:'flex',alignItems:'center',justifyContent:'center',opacity:interpolate(frame,[index*5,index*5+18],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp'}),scale:interpolate(frame,[index*5,index*5+18],[.96,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp'})}}>
    <BrandMark episode={episode} id={id} maxWidth={logoMax} maxHeight={logoMax}/>
   </div>)}
  </div>
  <div aria-hidden style={{position:'absolute',left:64,right:64,top:120,height:1.5,background:'#d9d6cf',pointerEvents:'none'}}/>
  <div aria-hidden style={{position:'absolute',left:'63.2%',top:'18%',bottom:'7%',width:1,background:'#e8e5df',pointerEvents:'none'}}/>
 </div>;
};
