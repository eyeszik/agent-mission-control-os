// Data-only worker: no source evaluation, URLs, imports from input, or credentials.
import { readFileSync } from 'node:fs';
import rough from 'roughjs';
import paper from 'paper/dist/paper-core.js';
import { PathArray } from '@svgdotjs/svg.js';
// Headless geometry only. No Canvas, DOM, PaperScript, imported SVG or text.
new paper.Project();

export function render(spec) {
  const request = spec.request;
  if (!['rough_js', 'paper_js', 'svg_js'].includes(request.engine) || request.output_format !== 'svg') throw new Error('UNSUPPORTED_PROFILE');
  if (request.clock.total_frames !== 1 || request.scene.primitives.length > 200) throw new Error('LIMIT_EXCEEDED');
  const color = /^#[a-fA-F0-9]{6}$/;
  if (!color.test(request.scene.background)) throw new Error('INVALID_COLOR');
  const g = rough.generator();
  const paths = [];
  for (let i = 0; i < request.scene.primitives.length; i++) {
    const p = request.scene.primitives[i];
    if (!color.test(p.fill) || !color.test(p.stroke)) throw new Error('INVALID_COLOR');
    for (const key of ['x', 'y', 'width', 'height', 'stroke_width']) {
      if (!Number.isFinite(p[key]) || p[key] < 0 || p[key] > 4096) throw new Error('INVALID_GEOMETRY');
    }
    const options = { seed: ((request.seed + i) % 2147483646) + 1, fill: p.fill, stroke: p.stroke, strokeWidth: p.stroke_width };
    if (request.engine === 'svg_js') {
      let segments;
      if (p.kind === 'rectangle') segments = [['M', p.x, p.y], ['L', p.x + p.width, p.y], ['L', p.x + p.width, p.y + p.height], ['L', p.x, p.y + p.height], ['Z']];
      else if (p.kind === 'line') segments = [['M', p.x, p.y], ['L', p.x + p.width, p.y + p.height]];
      else if (p.kind === 'ellipse') segments = [['M', p.x - p.width / 2, p.y], ['A', p.width / 2, p.height / 2, 0, 1, 0, p.x + p.width / 2, p.y], ['A', p.width / 2, p.height / 2, 0, 1, 0, p.x - p.width / 2, p.y], ['Z']];
      else throw new Error('UNKNOWN_PRIMITIVE');
      const d = new PathArray(segments).toString();
      if (!/^[a-zA-Z0-9.,+\-\s]*$/.test(d)) throw new Error('INVALID_GENERATED_PATH');
      paths.push(`<path d="${d}" fill="${p.kind === 'line' ? 'none' : p.fill}" stroke="${p.stroke}" stroke-width="${p.stroke_width}"/>`);
      continue;
    }
    if (request.engine === 'paper_js') {
      let path;
      const common = { insert: false };
      if (p.kind === 'rectangle') path = new paper.Path.Rectangle({ ...common, rectangle: [p.x, p.y, p.width, p.height] });
      else if (p.kind === 'ellipse') path = new paper.Path.Ellipse({ ...common, rectangle: [p.x - p.width / 2, p.y - p.height / 2, p.width, p.height] });
      else if (p.kind === 'line') path = new paper.Path.Line({ ...common, from: [p.x, p.y], to: [p.x + p.width, p.y + p.height] });
      else throw new Error('UNKNOWN_PRIMITIVE');
      const d = path.pathData;
      if (!/^[a-zA-Z0-9.,+\-\s]*$/.test(d)) throw new Error('INVALID_GENERATED_PATH');
      paths.push(`<path d="${d}" fill="${p.kind === 'line' ? 'none' : p.fill}" stroke="${p.stroke}" stroke-width="${p.stroke_width}"/>`);
      continue;
    }
    let shape;
    if (p.kind === 'rectangle') shape = g.rectangle(p.x, p.y, p.width, p.height, options);
    else if (p.kind === 'ellipse') shape = g.ellipse(p.x, p.y, p.width, p.height, options);
    else if (p.kind === 'line') shape = g.line(p.x, p.y, p.x + p.width, p.y + p.height, options);
    else throw new Error('UNKNOWN_PRIMITIVE');
    for (const path of g.toPaths(shape)) {
      // Every value comes from the trusted generator or validated scalar colors.
      if (!/^[a-zA-Z0-9.,+\-\s]*$/.test(path.d)) throw new Error('INVALID_GENERATED_PATH');
      paths.push(`<path d="${path.d}" fill="${path.fill}" stroke="${path.stroke}" stroke-width="${path.strokeWidth}"/>`);
    }
  }
  const { width, height } = request.dimensions;
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1 || width * height > 8294400) throw new Error('INVALID_SIZE');
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}"><rect width="${width}" height="${height}" fill="${request.scene.background}"/>${paths.join('')}</svg>`;
}

if (!process.env.AMC_RENDER_IMPORT_ONLY) {
  const input = readFileSync(0, 'utf8');
  if (Buffer.byteLength(input) > 131072) throw new Error('INPUT_LIMIT');
  process.stdout.write(render(JSON.parse(input)));
}
