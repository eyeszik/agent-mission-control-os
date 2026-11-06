import React from 'react';
import {createRoot} from 'react-dom/client';
import {Player} from '@remotion/player';
import {AbsoluteFill,useCurrentFrame} from 'remotion';
import {sceneAt} from './common.mjs';
export async function prepare(request) {
  const host=document.createElement('div'); document.body.replaceChildren(host);
  let player;
  function Composition() {
    const frame=useCurrentFrame();
    const paths=sceneAt(request,frame).map((p,i)=> {
      const common={key:i,fill:p.fill,stroke:p.stroke,strokeWidth:p.stroke_width};
      if(p.kind==='rectangle')return React.createElement('rect',{...common,x:p.x,y:p.y,width:p.width,height:p.height});
      if(p.kind==='ellipse')return React.createElement('ellipse',{...common,cx:p.x,cy:p.y,rx:p.width/2,ry:p.height/2});
      return React.createElement('line',{...common,x1:p.x,y1:p.y,x2:p.x+p.width,y2:p.y+p.height});
    });
    return React.createElement(AbsoluteFill,{style:{background:request.scene.background}},React.createElement('svg',{width:request.dimensions.width,height:request.dimensions.height},...paths));
  }
  createRoot(host).render(React.createElement(Player,{ref:ref=>{player=ref;},component:Composition,compositionWidth:request.dimensions.width,compositionHeight:request.dimensions.height,durationInFrames:request.clock.total_frames,fps:request.clock.fps_numerator/request.clock.fps_denominator,controls:false,autoPlay:false,style:{width:request.dimensions.width,height:request.dimensions.height},acknowledgeRemotionLicense:true}));
  for(let i=0;i<100 && !player;i++)await new Promise(resolve=>setTimeout(resolve,10));
  if(!player)throw new Error('REMOTION_PLAYER_NOT_READY');
  return async frame=> {player.seekTo(frame); await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));};
}
