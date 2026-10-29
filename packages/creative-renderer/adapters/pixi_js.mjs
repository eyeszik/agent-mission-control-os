import {Application, Graphics} from 'pixi.js';
import {sceneAt} from './common.mjs';
export async function prepare(request) {
  const app = new Application();
  await app.init({width:request.dimensions.width,height:request.dimensions.height, background:request.scene.background, resolution:1, preference:'webgl', autoStart:false, antialias:true});
  document.body.replaceChildren(app.canvas);
  return async frame => {
    for (const child of app.stage.removeChildren()) child.destroy();
    for (const p of sceneAt(request,frame)) {
      const g = new Graphics();
      if (p.kind === 'rectangle') g.rect(p.x,p.y,p.width,p.height);
      else if (p.kind === 'ellipse') g.ellipse(p.x,p.y,p.width/2,p.height/2);
      else g.moveTo(p.x,p.y).lineTo(p.x+p.width,p.y+p.height);
      if (p.kind !== 'line') g.fill(p.fill);
      g.stroke({color:p.stroke,width:p.stroke_width}); app.stage.addChild(g);
    }
    app.render();
  };
}
