import React from 'react';
import {CanvasImage,OffthreadVideo,interpolate,staticFile,useCurrentFrame} from 'remotion';
import type {Episode,EpisodeScene,VisualProps} from './types';
import {palette} from './shared';

const clamp={extrapolateLeft:'clamp',extrapolateRight:'clamp'} as const;
const reveal=(frame:number,start=0)=>({opacity:interpolate(frame,[start,start+14],[0,1],clamp),transform:`translateY(${interpolate(frame,[start,start+18],[12,0],clamp)}px)`});
const stage=(scene:EpisodeScene,episode:Episode,frame:number)=>{
 const now=frame/episode.fps*1000;
 const index=scene.captions.findIndex(c=>now>=c.startMs&&now<c.endMs);
 if(index>=0)return index;
 return Math.max(0,scene.captions.filter(c=>now>=c.endMs).length-1);
};
const number=(value:number)=>value>=1000000?`${value/1000000}M`:`${value/1000}k`;
const Asset:React.FC<{src?:string|null;style?:React.CSSProperties}>=({src,style})=>src?<CanvasImage src={staticFile(src)} style={{display:'block',maxWidth:'100%',maxHeight:'100%',objectFit:'contain',...style}}/>:null;
const Source:React.FC<{scene:EpisodeScene;index?:number;style?:React.CSSProperties}>=({scene,index=0,style})=><Asset src={scene.source_captures?.[index]?.path||scene.original_image} style={style}/>;
const line={borderTop:`1px solid ${palette.line}`};
const stepsFor=(scene:EpisodeScene):Array<{title:string;detail?:string}>=>scene.visual?.steps||scene.keypoints.map(title=>({title}));

const Context:React.FC<VisualProps>=({scene,episode})=>{
 const frame=useCurrentFrame();const chart=episode.charts.context;const labels=scene.visual?.labels||[];
 const index=stage(scene,episode,frame);const fee=index>=2&&labels.length>2&&(scene.source_captures?.length||0)>1;
 if(!chart)return <SourceFocus scene={scene} episode={episode} order={0}/>;
 const fill=interpolate(frame,[12,58],[0,1],clamp);
 return <div data-layout="context" style={{height:'100%',display:'grid',gridTemplateColumns:'580px minmax(0,1fr)',gap:70,alignItems:'center'}}>
  <div style={{height:'100%',display:'flex',flexDirection:'column',alignItems:'center',justifyContent:'center',gap:20}}>
   <Source scene={scene} style={{width:fee?500:580,maxHeight:fee?376:630}}/>
   {fee&&<Source scene={scene} index={1} style={{width:500,maxHeight:248,...reveal(frame,Math.floor((scene.captions[2]?.startMs||0)/1000*episode.fps))}}/>}
  </div>
  <div style={{height:'100%',display:'flex',flexDirection:'column',justifyContent:'center',gap:32}}>
   {fee?<div style={{...reveal(frame,Math.floor((scene.captions[2]?.startMs||0)/1000*episode.fps))}}><div style={{fontSize:42,marginBottom:20}}>{labels[1]}</div><div style={{fontSize:88,fontWeight:740,lineHeight:1.12,color:palette.orange}}>{labels[2]}</div></div>:<div><div style={{fontSize:38,marginBottom:12}}>{labels[0]||chart.label}</div><div style={{display:'flex',alignItems:'baseline',gap:28,fontSize:146,fontWeight:720,lineHeight:1.05,letterSpacing:-5}}><span>{number(chart.before)}</span><span style={{fontSize:70,color:palette.muted}}>→</span><span style={{color:palette.orange}}>{number(chart.after)}</span></div></div>}
   <div style={{display:'grid',gridTemplateColumns:'110px 1fr',alignItems:'center',gap:18}}>
    {[{value:chart.before,label:'此前',color:'#b9b4a8'},{value:chart.after,label:'现在',color:palette.orange}].map(row=><React.Fragment key={row.label}><div style={{fontSize:34,color:palette.muted}}>{row.label}</div><div style={{height:fee?46:64,background:'#e7e3d9',position:'relative'}}><div style={{height:'100%',width:`${row.value/chart.max*100*fill}%`,background:row.color}}/><div style={{position:'absolute',left:18,top:fee?4:12,fontSize:32,fontWeight:600}}>{number(row.value)}</div></div></React.Fragment>)}
   </div>
   <div style={{...line,paddingTop:26,display:'flex',alignItems:'baseline',gap:25}}><span style={{fontSize:70,fontWeight:690}}>{number(chart.max)}</span><span style={{fontSize:38}}>{labels[3]||'最大支持'}</span></div>
  </div>
 </div>;
};

const Workflow:React.FC<VisualProps>=({scene})=>{
 const frame=useCurrentFrame();const steps=stepsFor(scene);
 const labels=scene.visual?.labels||[];
 return <div data-layout="workflow" style={{height:'100%',display:'grid',gridTemplateRows:'430px minmax(0,1fr)',gap:28}}>
  <div style={{display:'grid',gridTemplateColumns:'1fr 640px 1fr',gap:36,alignItems:'center'}}>
   <div style={{...reveal(frame,5)}}><div style={{fontSize:94,fontWeight:740,letterSpacing:-4}}>{labels[0]||steps[0]?.title}</div><div style={{fontSize:38,color:palette.muted,marginTop:18}}>{labels[1]||steps[0]?.detail}</div></div>
   {scene.visual_preference==='original_image'&&scene.original_image?<Asset src={scene.original_image} style={{width:640,height:430}}/>:<Source scene={scene} style={{width:640,height:430}}/>}
   <div style={{textAlign:'right',...reveal(frame,12)}}><div style={{fontSize:86,fontWeight:740,color:palette.orange}}>{labels[2]||steps[1]?.title}</div><div style={{fontSize:38,color:palette.muted,marginTop:18}}>{labels[3]||steps[1]?.detail}</div></div>
  </div>
  <div style={{display:'flex',alignItems:'stretch',gap:24,...line,paddingTop:27}}>
   {steps.map((step,i)=><React.Fragment key={step.title}><div style={{flex:1,minWidth:0,...reveal(frame,18+i*10)}}><div style={{fontSize:32,color:palette.orange,marginBottom:13}}>0{i+1}</div><div style={{fontSize:42,fontWeight:650,lineHeight:1.2}}>{step.title}</div>{step.detail&&<div style={{fontSize:32,color:palette.muted,marginTop:12,lineHeight:1.3}}>{step.detail}</div>}</div>{i<steps.length-1&&<div style={{alignSelf:'center',fontSize:44,color:palette.muted}}>→</div>}</React.Fragment>)}
  </div>
 </div>;
};

const FeatureBoard:React.FC<VisualProps>=({scene})=>{
 const frame=useCurrentFrame();const steps=stepsFor(scene);
 return <div data-layout="feature-board" style={{height:'100%',display:'grid',gridTemplateColumns:'650px 1fr',gap:64,alignItems:'center'}}>
  <Source scene={scene} style={{width:650,height:640}}/>
  <div style={{height:600,display:'grid',gridTemplateColumns:'1fr 1fr',gridTemplateRows:'1fr 1fr',gap:36}}>
   {steps.slice(0,3).map((step,i)=><div key={step.title} style={{gridColumn:i===0?'span 2':undefined,display:'flex',flexDirection:'column',justifyContent:'center',borderBottom:i===0?`2px solid ${palette.ink}`:undefined,...reveal(frame,10+i*12)}}><div style={{fontSize:i===0?100:59,fontWeight:730,letterSpacing:-1.5,color:i===0?palette.orange:palette.ink,lineHeight:1.15}}>{step.title}</div>{step.detail&&<div style={{fontSize:38,color:palette.muted,marginTop:20,lineHeight:1.35}}>{step.detail}</div>}</div>)}
  </div>
 </div>;
};

const SourceFocus:React.FC<VisualProps>=({scene})=>{
 const frame=useCurrentFrame();const steps=stepsFor(scene);
 return <div data-layout="source-focus" style={{height:'100%',display:'grid',gridTemplateColumns:'minmax(0,1.25fr) minmax(0,1fr)',gap:60,alignItems:'center'}}>
  {scene.visual_preference==='original_image'&&scene.original_image?<Asset src={scene.original_image} style={{width:'100%',height:620}}/>:<Source scene={scene} style={{width:'100%',height:620}}/>}
  <div style={{height:600,display:'flex',flexDirection:'column',justifyContent:'space-between',padding:'12px 0',boxSizing:'border-box'}}>{steps.map((step,i)=><div key={step.title} style={{...reveal(frame,10+i*10),borderBottom:i<steps.length-1?`1px solid ${palette.line}`:undefined,paddingBottom:26}}><div style={{fontSize:i===0?76:60,lineHeight:1.13,fontWeight:690,color:i===0?palette.orange:palette.ink}}>{step.title}</div>{step.detail&&<div style={{fontSize:36,color:palette.muted,lineHeight:1.3,marginTop:14}}>{step.detail}</div>}</div>)}</div>
 </div>;
};

const Event:React.FC<VisualProps>=({scene})=>{
 const frame=useCurrentFrame();const metrics=scene.visual?.metrics||scene.keypoints.map(value=>({value,label:''}));
 return <div data-layout="event" style={{height:'100%',display:'grid',gridTemplateColumns:'1120px minmax(0,1fr)',gap:54,alignItems:'center'}}>
  <Asset src={scene.original_image||scene.source_captures?.[0]?.path} style={{width:1120,height:630}}/>
  <div style={{height:630,display:'flex',flexDirection:'column',justifyContent:'space-between'}}>{metrics.map((metric,i)=><div key={metric.value} style={{...reveal(frame,8+i*10),borderBottom:i<metrics.length-1?`1px solid ${palette.line}`:undefined,paddingBottom:i<metrics.length-1?22:0}}><div style={{fontSize:metric.value.length>12?54:metric.value.length>8?62:88,fontWeight:730,lineHeight:1.1,color:i===1?palette.orange:palette.ink,letterSpacing:-1.6,whiteSpace:'pre-line'}}>{metric.value}</div><div style={{fontSize:34,color:palette.muted,marginTop:15,lineHeight:1.2}}>{metric.label}</div></div>)}</div>
 </div>;
};

const Cinema:React.FC<VisualProps>=({scene,episode})=>{
 const frame=useCurrentFrame();
 return <div data-layout="cinema" style={{height:'100%',display:'grid',gridTemplateColumns:'1160px minmax(0,1fr)',gap:44,alignItems:'center'}}>
  <div style={{width:1160,height:652,overflow:'hidden',...reveal(frame,0)}}>{scene.original_video?<OffthreadVideo muted src={staticFile(scene.original_video)} trimBefore={Math.round((scene.video_start_seconds||0)*episode.fps)} style={{width:'100%',height:'100%',objectFit:'contain'}}/>:<Asset src={scene.original_image} style={{width:'100%',height:'100%'}}/>}</div>
  <Source scene={scene} style={{width:'100%',height:642}}/>
 </div>;
};

const Case:React.FC<VisualProps>=({scene,episode})=>{
 const frame=useCurrentFrame();const index=stage(scene,episode,frame);const steps=stepsFor(scene);const labels=scene.visual?.labels||[];
 if(index>=1&&scene.source_captures?.length===2)return <div data-layout="case-sources" style={{height:'100%',display:'grid',gridTemplateColumns:'470px 1fr 350px',gap:50,alignItems:'center'}}>
  <Source scene={scene} index={1} style={{width:470,height:648}}/>
  <div style={{textAlign:'center'}}><div style={{fontSize:43,color:palette.muted,marginBottom:28}}>{labels[0]||scene.source_label}</div><div style={{fontSize:88,fontWeight:730,lineHeight:1.17,whiteSpace:'pre-line'}}>{labels[1]||scene.title}</div><div style={{...line,paddingTop:30,marginTop:38,fontSize:57,color:palette.orange,fontWeight:650}}>{labels[2]}</div></div>
  <Source scene={scene} index={0} style={{width:350,height:648}}/>
 </div>;
 return <div data-layout="case" style={{height:'100%',display:'grid',gridTemplateColumns:'1130px minmax(0,1fr)',gap:54,alignItems:'center'}}>
  <Asset src={scene.visual?.phase_images?.[Math.min(index,scene.visual.phase_images.length-1)]||scene.original_image} style={{width:1130,height:636}}/>
  <div style={{height:610,display:'flex',flexDirection:'column',justifyContent:'space-around'}}>{steps.map((step,i)=><div key={step.title} style={{...reveal(frame,12+i*9)}}><div style={{fontSize:31,color:palette.orange,marginBottom:10}}>0{i+1}</div><div style={{fontSize:54,lineHeight:1.2,fontWeight:700}}>{step.title}</div>{step.detail&&<div style={{fontSize:34,color:palette.muted,marginTop:12}}>{step.detail}</div>}</div>)}</div>
 </div>;
};

const Settings:React.FC<VisualProps>=({scene})=>{
 const frame=useCurrentFrame();const steps=stepsFor(scene);
 return <div data-layout="settings" style={{height:'100%',display:'grid',gridTemplateColumns:'1fr 655px 1fr',gap:48,alignItems:'center'}}>
  <div style={{height:570,display:'flex',flexDirection:'column',justifyContent:'space-between',padding:'24px 0',boxSizing:'border-box'}}>{steps.slice(0,2).map((step,i)=><div key={step.title} style={{...reveal(frame,12+i*15)}}><div style={{fontSize:82,fontWeight:720}}>{step.title}</div><div style={{fontSize:44,color:palette.muted,marginTop:17}}>{step.detail}</div></div>)}</div>
  <Asset src={scene.original_image} style={{width:655,height:600}}/>
  {steps[2]&&<div style={{...reveal(frame,38),paddingLeft:26,borderLeft:`3px solid ${palette.orange}`}}><div style={{fontSize:100,fontWeight:720,color:palette.orange}}>{steps[2].title}</div><div style={{fontSize:47,marginTop:24,lineHeight:1.3}}>{steps[2].detail}</div></div>}
 </div>;
};

const Fallback:React.FC<VisualProps>=(props)=>{
 const {scene,episode,order}=props;
 if(scene.original_video)return <Cinema {...props}/>;
 const image=scene.original_image||scene.source_captures?.[0]?.path;
 const dim=image?episode.asset_dimensions?.[image]:undefined;
 if(image&&dim&&dim.width/dim.height>1.6)return <div style={{height:'100%',display:'grid',gridTemplateRows:'1fr auto',gap:24}}><Asset src={image} style={{width:'100%',height:'100%',minHeight:0}}/><div style={{display:'flex',gap:40,fontSize:40,fontWeight:600}}>{scene.keypoints.map(p=><div key={p} style={{flex:1}}>{p}</div>)}</div></div>;
 return <div style={{height:'100%',display:'flex',gap:65,flexDirection:order%2?'row':'row-reverse',alignItems:'center'}}><Source scene={scene} style={{width:'45%',height:'100%'}}/><div style={{flex:1,fontSize:54,lineHeight:1.3,fontWeight:600}}>{scene.keypoints.map((p,i)=><div key={p} style={{padding:'30px 0',borderTop:i?`1px solid ${palette.line}`:undefined}}>{p}</div>)}</div></div>;
};

const layouts:Record<string,React.FC<VisualProps>>={context:Context,workflow:Workflow,'feature-board':FeatureBoard,'source-focus':SourceFocus,event:Event,cinema:Cinema,case:Case,settings:Settings};
export const AdaptiveStoryV6:React.FC<VisualProps>=(props)=>{
 const Visual=layouts[props.scene.visual?.layout||'']||Fallback;
 return <Visual {...props}/>;
};
