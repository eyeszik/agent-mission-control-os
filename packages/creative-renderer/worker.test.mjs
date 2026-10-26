import { test } from 'node:test';
import assert from 'node:assert/strict';
process.env.AMC_RENDER_IMPORT_ONLY = '1';
const { render } = await import('./worker.mjs');
const spec = { request: { engine: 'rough_js', output_format: 'svg', seed: 42, clock: { total_frames: 1 }, dimensions: { width: 320, height: 200 }, scene: { background: '#ffffff', primitives: [{ kind: 'rectangle', x: 20, y: 20, width: 80, height: 60, fill: '#ece6da', stroke: '#121212', stroke_width: 1 }] } } };
test('real seeded rough output is deterministic and changes with seed', () => {
  assert.equal(render(spec), render(structuredClone(spec)));
  const other = structuredClone(spec); other.request.seed++;
  assert.notEqual(render(spec), render(other));
  assert.match(render(spec), /<path d=/);
});
test('worker rejects unsupported engines and active input', () => {
  const other = structuredClone(spec); other.request.engine = 'remotion';
  assert.throws(() => render(other), /UNSUPPORTED_PROFILE/);
  other.request.engine = 'rough_js'; other.request.scene.primitives[0].fill = '\" onload=\"alert(1)';
  assert.throws(() => render(other), /INVALID_COLOR/);
});
for (const engine of ['paper_js', 'svg_js']) {
  for (const kind of ['rectangle', 'ellipse', 'line']) {
    test(`${engine} renders deterministic ${kind} paths without a browser`, () => {
      const input = structuredClone(spec);
      input.request.engine = engine;
      input.request.scene.primitives[0].kind = kind;
      const output = render(input);
      assert.equal(output, render(structuredClone(input)));
      assert.match(output, /<path d="[Mm]/);
      assert.doesNotMatch(output, /undefined|NaN|Infinity/);
    });
  }
}
