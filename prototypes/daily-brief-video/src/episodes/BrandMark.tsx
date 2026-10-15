import React from 'react';
import {CanvasImage,Img,staticFile} from 'remotion';
import type {Episode} from './types';

// The exact cached source file is fitted to its measured aspect ratio.
export const BrandMark:React.FC<{episode:Episode;id?:string;maxWidth?:number;maxHeight?:number}>=({episode,id,maxWidth=180,maxHeight=76})=>{
 const asset=episode.brand_assets?.find(a=>a.id===id);
 if(!asset)return null;
 const dimensions=episode.asset_dimensions?.[asset.path];
 const w=dimensions?.width||asset.width;
 const h=dimensions?.height||asset.height;
 const scale=w&&h?Math.min(maxWidth/w,maxHeight/h):1;
 // SVGs must rasterize at display size; CanvasImage uses the tiny intrinsic bitmap size.
 const ImageComponent=asset.path.endsWith('.svg')?Img:CanvasImage;
 return <ImageComponent data-brand-id={id} src={staticFile(asset.path)} style={{display:'block',flexShrink:0,width:w?w*scale:maxWidth,height:h?h*scale:maxHeight,objectFit:'contain'}}/>;
};
