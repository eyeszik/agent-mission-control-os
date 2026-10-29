/**
 * Python 3.11 `textwrap.dedent`, rebuilt line by line.
 *
 * It is not done with a multiline JS RegExp: JS `^`/`$` with the `m` flag also
 * break lines at `\r`, U+2028 and U+2029, while Python's break only at `\n`.
 * Only space and tab count as indentation, and they never match each other.
 */

const LEADING_INDENT = /^([ \t]*)[^ \t]/;

function narrowMargin(margin: string, indent: string): string {
  if (indent.startsWith(margin)) return margin;
  if (margin.startsWith(indent)) return indent;
  let i = 0;
  while (i < margin.length && i < indent.length && margin[i] === indent[i]) i += 1;
  return margin.slice(0, i);
}

/** Longest run of spaces/tabs common to every line that has other content. */
function commonMargin(lines: readonly string[]): string {
  let margin: string | null = null;
  for (const line of lines) {
    const indent = LEADING_INDENT.exec(line)?.[1];
    if (indent === undefined) continue;
    margin = margin === null ? indent : narrowMargin(margin, indent);
  }
  return margin ?? '';
}

/** Python `textwrap.dedent(text)`: whitespace-only lines become empty, then the common margin goes. */
export function pyDedent(text: string): string {
  const lines = text.split('\n').map((line) => (/^[ \t]+$/.test(line) ? '' : line));
  const margin = commonMargin(lines);
  if (margin === '') return lines.join('\n');
  return lines.map((line) => (line.startsWith(margin) ? line.slice(margin.length) : line)).join('\n');
}
