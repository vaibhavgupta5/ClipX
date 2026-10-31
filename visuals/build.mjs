import {build} from 'esbuild';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
await mkdir('dist', {recursive:true});
// Bundle the published, pinned adapter directly: the core barrel also exports server modules.
await build({entryPoints:['src/runtime.js'],bundle:true,format:'iife',outfile:'dist/runtime.js',
  alias:{'clipz-hyperframes-adapter':'./node_modules/@hyperframes/core/dist/adapters/gsap.js'}});
const fonts = {
  inter:'node_modules/@fontsource/inter/files/inter-latin-400-normal.woff2',
  bold:'node_modules/@fontsource/inter/files/inter-latin-700-normal.woff2',
  hindi:'node_modules/@fontsource/noto-sans-devanagari/files/noto-sans-devanagari-devanagari-400-normal.woff2',
  display:'node_modules/@fontsource/anton/files/anton-latin-400-normal.woff2',
  mono:'node_modules/@fontsource/jetbrains-mono/files/jetbrains-mono-latin-400-normal.woff2',
  monobold:'node_modules/@fontsource/jetbrains-mono/files/jetbrains-mono-latin-700-normal.woff2',
};
const embedded={};
for(const [name,path] of Object.entries(fonts)) embedded[name]=(await readFile(path)).toString('base64');
await writeFile('dist/fonts.json',JSON.stringify(embedded));
