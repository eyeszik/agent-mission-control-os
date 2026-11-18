// Vite/Vitest `?raw` imports: the file's text, without node:fs.
declare module '*?raw' {
  const text: string;
  export default text;
}
