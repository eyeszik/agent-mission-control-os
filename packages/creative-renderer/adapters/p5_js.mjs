import p5 from 'p5';
import {sceneAt} from './common.mjs';
export async function prepare(request) {
  let ready;
  const wait = new Promise(resolve => {ready = resolve;});
  const sketch = new p5(p => {
    p.setup = () => {p.pixelDensity(1); p.createCanvas(request.dimensions.width, request.dimensions.height); p.noLoop(); ready();};
  });
  await wait;
  return async frame => {
    sketch.randomSeed(request.seed); sketch.noiseSeed(request.seed);
    sketch.background(request.scene.background);
    for (const p of sceneAt(request, frame)) {
      sketch.fill(p.fill); sketch.stroke(p.stroke); sketch.strokeWeight(p.stroke_width);
      if (p.kind === 'rectangle') sketch.rect(p.x,p.y,p.width,p.height);
      else if (p.kind === 'ellipse') sketch.ellipse(p.x,p.y,p.width,p.height);
      else sketch.line(p.x,p.y,p.x+p.width,p.y+p.height);
    }
  };
}
