import {Scene2D, Rect, Circle, Line, makeScene2D} from '@motion-canvas/2d';
import {PlaybackManager,PlaybackStatus,Logger,Vector2,SharedWebGLContext} from '@motion-canvas/core';
import {ReadOnlyTimeEvents} from '@motion-canvas/core/lib/scenes/timeEvents/ReadOnlyTimeEvents.js';
import {canvas,sceneAt} from './common.mjs';
export async function prepare(request) {
  const target=canvas(request), context=target.getContext('2d');
  const playback=new PlaybackManager(); playback.fps=request.clock.fps_numerator/request.clock.fps_denominator;
  const logger=new Logger(); const description=makeScene2D(function*(){yield;});
  description.meta.seed.set(request.seed);
  const scene=new Scene2D({...description,name:'typed-primitives',size:new Vector2(request.dimensions.width,request.dimensions.height),resolutionScale:1,logger,playback:new PlaybackStatus(playback),timeEventsClass:ReadOnlyTimeEvents,sharedWebGLContext:new SharedWebGLContext(logger)});
  return async frame=>{
    playback.frame=frame;
    scene.execute(()=>{
      const view=scene.getView();view.removeChildren();
      view.add(new Rect({width:request.dimensions.width,height:request.dimensions.height,fill:request.scene.background}));
      for(const p of sceneAt(request,frame)) {
        const x=p.x-request.dimensions.width/2,y=p.y-request.dimensions.height/2;
        const props={fill:p.fill,stroke:p.stroke,lineWidth:p.stroke_width};
        if(p.kind==='rectangle')view.add(new Rect({...props,x:x+p.width/2,y:y+p.height/2,width:p.width,height:p.height}));
        else if(p.kind==='ellipse')view.add(new Circle({...props,x,y,width:p.width,height:p.height}));
        else view.add(new Line({...props,points:[[x,y],[x+p.width,y+p.height]]}));
      }
    });
    context.setTransform(1,0,0,1,0,0);context.clearRect(0,0,target.width,target.height);
    await scene.render(context);
  };
}
