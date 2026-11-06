export function sceneAt(request, frame) {
  const fraction = request.clock.total_frames > 1 ? frame / (request.clock.total_frames - 1) : 0;
  const motion = request.motion || { x: 0, y: 0 };
  return request.scene.primitives.map(p => ({...p, x: p.x + motion.x * fraction, y: p.y + motion.y * fraction}));
}
export function canvas(request) {
  const element = document.createElement('canvas');
  element.width = request.dimensions.width; element.height = request.dimensions.height;
  document.body.replaceChildren(element); return element;
}
