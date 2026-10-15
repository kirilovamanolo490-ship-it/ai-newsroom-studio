import React from 'react';
import {Composition,Folder} from 'remotion';
import {DailyReport,ReportScene} from './episodes/DailyReport';
import type {Episode} from './episodes/types';
import latest from './episodes/generated/latest.json';
import briefing1600 from './episodes/generated/2026-10-13/briefing-1600.json';

const latestEpisode=latest as unknown as Episode;
const batchEpisode=briefing1600 as unknown as Episode;

export const RemotionRoot:React.FC = () => <>
  <Composition
    id="DailyReport"
    component={DailyReport}
    durationInFrames={latestEpisode.durationInFrames}
    fps={30}
    width={1920}
    height={1080}
    defaultProps={{episode:latestEpisode}}
    calculateMetadata={({props})=>({durationInFrames:props.episode.durationInFrames})}
  />
  <Folder name="Batch-Videos">
    <Composition
      id="Briefing1600"
      component={DailyReport}
      durationInFrames={batchEpisode.durationInFrames}
      fps={30}
      width={1920}
      height={1080}
      defaultProps={{episode:batchEpisode}}
      calculateMetadata={({props})=>({durationInFrames:props.episode.durationInFrames})}
    />
  </Folder>
  <Folder name="Report-Scenes">
    {latestEpisode.scenes.map((scene,i)=><Composition
      key={scene.id}
      id={'Report-'+scene.id}
      component={ReportScene}
      durationInFrames={scene.durationInFrames}
      fps={30}
      width={1920}
      height={1080}
      defaultProps={{scene,episode:latestEpisode,order:i}}
    />)}
  </Folder>
</>;
