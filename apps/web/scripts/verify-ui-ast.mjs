#!/usr/bin/env node
// AST gate for frontend token consumption (companion to scripts/verify_design_tokens.py).
//
// The Python gate scans lines; this one parses TSX with the TypeScript compiler
// already in devDependencies (no new packages) and catches what a line regex
// cannot see reliably:
//   1. visual properties in JSX `style={{...}}` objects (color, background,
//      border, shadow, fill, stroke, font, ...) -- styling bypasses tokens;
//   2. raw colors (#hex, rgb/hsl/oklch/color()) anywhere inside a style object;
//   3. arbitrary color values in class strings (`bg-[#...]`, `text-[rgb(...)]`);
//   4. a second AI provenance root: only AITrustEnvelope may render the
//      `aria-label="AI provenance"` scope.
// Escape hatch, as in the Python gate: a line containing `amc-allow-hex`.

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

const WEB_ROOT = fileURLToPath(new URL('..', import.meta.url));
const SCAN_DIRS = ['app', 'components', 'lib'];
const SKIP_DIRS = new Set(['node_modules', '.next', 'tests', 'e2e', '__tests__']);
const AI_TRUST_ROOT = ['components', 'mission-control', 'AITrustEnvelope.tsx'].join(sep);

const VISUAL_STYLE_PROPS = new Set([
  'color', 'background', 'backgroundColor', 'backgroundImage', 'border', 'borderColor',
  'borderTop', 'borderRight', 'borderBottom', 'borderLeft', 'borderBlock', 'borderInline',
  'boxShadow', 'textShadow', 'outline', 'outlineColor', 'fill', 'stroke', 'caretColor',
  'accentColor', 'fontFamily', 'fontSize', 'fontWeight', 'filter', 'backdropFilter', 'opacity',
]);
const RAW_COLOR = /#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|oklch|oklab|lab|lch|color)\s*\(/;
const ARBITRARY_CLASS_COLOR = /(?:^|[\s"'`])[\w:-]*-\[(?:#[0-9a-fA-F]{3,8}|(?:rgba?|hsla?|oklch|color)\()/;

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    if (SKIP_DIRS.has(name)) continue;
    const full = join(dir, name);
    if (statSync(full).isDirectory()) yield* walk(full);
    else if (/\.(tsx|ts)$/.test(name) && !/\.d\.ts$/.test(name)) yield full;
  }
}

function lineOf(sourceFile, node) {
  return sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1;
}

export function scanSource(fileName, text) {
  const problems = [];
  const lines = text.split('\n');
  const allowed = (line) => (lines[line - 1] ?? '').includes('amc-allow-hex');
  const sourceFile = ts.createSourceFile(fileName, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const report = (node, message) => {
    const line = lineOf(sourceFile, node);
    if (!allowed(line)) problems.push(`${fileName}:${line}: ${message}`);
  };

  const visit = (node) => {
    if (ts.isJsxAttribute(node) && node.initializer && ts.isJsxExpression(node.initializer)) {
      const name = node.name.getText(sourceFile);
      const expr = node.initializer.expression;
      if (name === 'style' && expr && ts.isObjectLiteralExpression(expr)) {
        for (const prop of expr.properties) {
          const key = prop.name ? prop.name.getText(sourceFile).replace(/['"]/g, '') : '';
          if (VISUAL_STYLE_PROPS.has(key)) {
            report(prop, `inline visual style '${key}' bypasses design tokens -- use a token class`);
          }
          if (RAW_COLOR.test(prop.getText(sourceFile))) {
            report(prop, 'raw color value inside an inline style object');
          }
        }
      }
    }
    if (ts.isJsxAttribute(node) && node.name.getText(sourceFile) === 'className' && node.initializer) {
      const raw = node.initializer.getText(sourceFile);
      if (ARBITRARY_CLASS_COLOR.test(raw)) report(node, 'arbitrary color value in className -- add a token instead');
    }
    if (
      ts.isJsxAttribute(node) &&
      node.name.getText(sourceFile) === 'aria-label' &&
      node.initializer &&
      ts.isStringLiteral(node.initializer) &&
      node.initializer.text === 'AI provenance' &&
      !fileName.endsWith(AI_TRUST_ROOT)
    ) {
      report(node, 'duplicate AI provenance root -- render AITrustEnvelope instead');
    }
    ts.forEachChild(node, visit);
  };
  visit(sourceFile);
  return problems;
}

function main() {
  const problems = [];
  for (const dir of SCAN_DIRS) {
    for (const file of walk(join(WEB_ROOT, dir))) {
      problems.push(...scanSource(relative(WEB_ROOT, file), readFileSync(file, 'utf8')));
    }
  }
  if (problems.length) {
    for (const problem of problems) console.error(problem);
    console.error(`ui-ast gate: ${problems.length} violation(s)`);
    process.exit(1);
  }
  console.log('ui-ast gate: no inline visual styles, arbitrary class colors, or duplicate AI provenance roots');
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) main();
