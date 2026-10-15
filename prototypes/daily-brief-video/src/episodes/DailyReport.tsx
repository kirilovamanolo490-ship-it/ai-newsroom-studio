import React from 'react';
import {TransitionSeries,linearTiming} from '@remotion/transitions';
import {fade} from '@remotion/transitions/fade';
import type {Episode,VisualProps} from './types';
import {EpisodeFrame} from './Frame';
import {CleanCoverV6} from './CleanCoverV6';
import {AdaptiveStoryV6} from './AdaptiveStoryV6';
import {V6Closing} from './V6Closing';

export const ReportScene:React.FC<VisualProps>=(props)=>{
  const Visual=props.scene.id==='opening'
    ?CleanCoverV6
    :props.scene.id==='closing'
      ?V6Closing
      :AdaptiveStoryV6;
  return <EpisodeFrame {...props}><Visual {...props}/></EpisodeFrame>;
};

export const DailyReport:React.FC<{episode:Episode}>=({episode})=><TransitionSeries>{episode.scenes.flatMap((scene,i)=>[
  <TransitionSeries.Sequence key={scene.id} name={scene.title} durationInFrames={scene.durationInFrames} premountFor={30}>
    <ReportScene scene={scene} episode={episode} order={i}/>
  </TransitionSeries.Sequence>,
  i<episode.scenes.length-1
    ?<TransitionSeries.Transition key={'fade-'+i} presentation={fade()} timing={linearTiming({durationInFrames:episode.transitionFrames})}/>
    :null
])}</TransitionSeries>;
