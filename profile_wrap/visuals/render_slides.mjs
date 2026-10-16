#!/usr/bin/env node
/**
 * Static lane: one HTML file with .slide (or .banner) elements -> PNGs at a device scale, and a tagged PDF.
 * Called by profile_wrap/visuals/render.py; it reads no workspace config itself. Everything arrives as flags.
 *
 *   node render_slides.mjs --html slides.html --out out --fonts-css fonts.css --families "Family A,Family B"
 *        [--icons DIR]... [--scale 2] [--scales 1,2] [--selector .slide] [--prefix slide] [--numbered]
 *        [--canvas 1080x1350] [--chrome PATH] [--node-dir DIR]... [--min-font 28] [--pdf name.pdf]
 *        [--safe-zone x,y,w,h] [--png-only]
 *
 * The last stdout line is JSON: {"ok":true,"slides":N,"files":[...],"families":[...],"warnings":[...]}.
 * Any failure exits 1 with the reason on stderr. Gates (a failure is never shipped):
 *   - every configured family loaded (no silent fallback face),
 *   - nothing overflows its slide (also from the right edge, so Arabic RTL slides are checked),
 *   - a .grow block does not spill past its space,
 *   - no visible text below the font floor,
 *   - with --safe-zone, no text box intersects the zone (banner photo overlap).
 */
import { readFile, mkdir } from 'node:fs/promises';
import { existsSync, readFileSync } from 'node:fs';
import { join, resolve, dirname, extname } from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';

function parseArgs(argv) {
  const out = { icons: [], nodeDirs: [] };
  const flags = new Set(['numbered', 'png-only']);
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith('--')) continue;
    const k = a.slice(2);
    if (flags.has(k)) { out[k.replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = true; continue; }
    const v = argv[++i];
    if (k === 'icons') out.icons.push(v);
    else if (k === 'node-dir') out.nodeDirs.push(v);
    else out[k.replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = v;
  }
  return out;
}

const fail = (msg) => { console.error(msg); process.exit(1); };
const args = parseArgs(process.argv.slice(2));
if (!args.html || !args.out) fail('usage: render_slides.mjs --html FILE --out DIR [options]');

async function loadPlaywright() {
  const here = dirname(fileURLToPath(import.meta.url));
  const roots = [...args.nodeDirs, process.env.PROFILE_WRAP_NODE_DIR, process.env.PROFILE_WRAP_DATA_DIR && join(process.env.PROFILE_WRAP_DATA_DIR, 'node'),
    process.cwd(), dirname(resolve(args.html)), here].filter(Boolean);
  for (const root of roots) {
    try {
      const req = createRequire(join(resolve(root), 'noop.js'));
      const mod = await import(pathToFileURL(req.resolve('playwright')).href);
      return mod.chromium ?? mod.default.chromium;
    } catch { /* try the next root */ }
  }
  fail('playwright is not installed. Run "profile-wrap assets fetch" (installs the pinned Playwright into the workspace), ' +
       'or set PROFILE_WRAP_NODE_DIR to a folder whose node_modules has playwright.');
}

const scales = (args.scales ?? args.scale ?? '2').split(',').map(Number).filter((n) => n > 0);
const [cw, ch] = (args.canvas ?? '1080x1350').split('x').map(Number);
const selector = args.selector ?? '.slide';
const prefix = args.prefix ?? 'slide';
const minFont = Number(args.minFont ?? 28);
const families = (args.families ?? '').split(',').map((s) => s.trim()).filter(Boolean);
const mimeOf = { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.svg': 'image/svg+xml', '.webp': 'image/webp', '.gif': 'image/gif' };
const htmlPath = resolve(args.html);
const baseDir = dirname(htmlPath);
let html = await readFile(htmlPath, 'utf8');

// Inline local images (src="..." and src='...') and CSS url(...) as data URIs: setContent cannot load file:// resources.
const dataUri = async (rel) => {
  if (/^(data:|https?:|#)/i.test(rel)) return null;
  const ext = extname(rel.split(/[?#]/)[0]).toLowerCase();
  if (!mimeOf[ext]) return null;
  const p = resolve(baseDir, rel);
  if (!existsSync(p)) throw new Error(`image not found: ${rel}`);
  return `data:${mimeOf[ext]};base64,${(await readFile(p)).toString('base64')}`;
};
for (const m of [...html.matchAll(/(src)=(["'])([^"']+)\2/gi)]) {
  const uri = await dataUri(m[3]);
  if (uri) html = html.replaceAll(m[0], `src=${m[2]}${uri}${m[2]}`);
}
for (const m of [...html.matchAll(/url\(\s*(["']?)([^)"']+)\1\s*\)/gi)]) {
  const uri = await dataUri(m[2]);
  if (uri) html = html.replaceAll(m[0], `url("${uri}")`);
}

// Vector icons: <i data-icon="bot"></i> -> inline Lucide SVG (ISC) from the first icon folder that has it.
html = html.replace(/<i([^>]*)data-icon="([a-z0-9-]+)"([^>]*)><\/i>/g, (m, a, name, b) => {
  const dir = args.icons.find((d) => existsSync(join(d, `${name}.svg`)));
  if (!dir) throw new Error(`icon not found: ${name}.svg (run: profile-wrap icons add ${name})`);
  const svg = readFileSync(join(dir, `${name}.svg`), 'utf8').replace(/<!--.*?-->/s, '').trim();
  const cls = /class="([^"]*)"/.exec(a + b)?.[1];
  return svg.replace(/class="[^"]*"/, `class="ic lucide${cls ? ' ' + cls : ''}"`).replace(/\s(width|height)="24"/g, '').replace('<svg', '<svg aria-hidden="true"');
});

if (args.fontsCss) {
  // :where() keeps the icon default (1em) at zero specificity so any page rule overrides it
  const style = `<style>${await readFile(resolve(args.fontsCss), 'utf8')}
:where(svg.ic){width:1em;height:1em}</style>`;
  html = /<\/head>/i.test(html) ? html.replace(/<\/head>/i, `${style}</head>`) : style + html;
}

const chromium = await loadPlaywright();
const out = resolve(args.out);
await mkdir(out, { recursive: true });
const browser = await chromium.launch(args.chrome ? { executablePath: resolve(args.chrome) } : {});
const warnings = [];
const files = [];
try {
  const page = await browser.newPage({ viewport: { width: cw, height: ch }, deviceScaleFactor: scales[0] });
  await page.setContent(html, { waitUntil: 'load' });

  // Gate: every configured family really loaded. A declared @font-face must report "loaded"; an undeclared (system) family must
  // measure differently from both generic fallbacks. Either way a fallback face fails the render.
  const missing = await page.evaluate(async (names) => {
    const sample = 'Hamburgefonstiv 0123456789 مرحبا العربية';
    const width = (font) => {
      const c = document.createElement('canvas').getContext('2d');
      c.font = font;
      return c.measureText(sample).width;
    };
    const bad = [];
    for (const n of names) {
      const faces = [...document.fonts].filter((f) => f.family.replace(/["']/g, '') === n);
      if (faces.length) {
        await Promise.all(faces.map((f) => f.load().catch(() => {})));
        if (!faces.every((f) => f.status === 'loaded')) bad.push(n);
        continue;
      }
      const mono = width('64px monospace'), serif = width('64px serif');
      const w1 = width(`64px "${n}", monospace`), w2 = width(`64px "${n}", serif`);
      if (w1 === mono && w2 === serif) bad.push(n);
    }
    await document.fonts.ready;
    return bad;
  }, families);
  if (missing.length) throw new Error(`fonts fell back (not loaded): ${missing.join(', ')}`);

  const problems = [];
  // Gate: nothing may overflow its slide (right edge too, so RTL slides are covered).
  problems.push(...await page.evaluate((sel) => [...document.querySelectorAll(sel)].flatMap((s, i) => {
    const r = s.getBoundingClientRect();
    return [...s.querySelectorAll('*')].filter((el) => {
      const b = el.getBoundingClientRect();
      return b.width && (b.right > r.right + 1 || b.bottom > r.bottom + 1 || b.left < r.left - 1 || b.top < r.top - 1) && !el.closest('.portrait,.bleed');
    }).slice(0, 3).map((el) => `slide ${i + 1}: <${el.tagName.toLowerCase()} class="${el.className}"> overflows`);
  }), selector));
  // Gate: a centred .grow can spill upwards without leaving the slide.
  problems.push(...await page.evaluate((sel) => [...document.querySelectorAll(sel)].flatMap((s, i) =>
    [...s.querySelectorAll('.grow')].filter((g) => g.scrollHeight > g.clientHeight + 1).map(() => `slide ${i + 1}: .grow content taller than its space`)), selector));
  // Gate: the font floor for every visible text element (opt out with class "allow-small", e.g. a legal footnote).
  problems.push(...await page.evaluate(({ sel, floor }) => [...document.querySelectorAll(sel)].flatMap((s, i) =>
    [...s.querySelectorAll('*')].filter((el) => {
      if (el.closest('.allow-small,svg')) return false;
      const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
      if (!own) return false;
      const cs = getComputedStyle(el);
      return cs.visibility !== 'hidden' && cs.display !== 'none' && parseFloat(cs.fontSize) < floor - 0.01;
    }).slice(0, 3).map((el) => `slide ${i + 1}: text "${el.textContent.trim().slice(0, 24)}" is ${getComputedStyle(el).fontSize}, below ${floor}px`)), { sel: selector, floor: minFont }));
  // Gate: a safe zone (the banner's photo overlap) stays free of text.
  if (args.safeZone) {
    const [zx, zy, zw, zh] = args.safeZone.split(',').map(Number);
    problems.push(...await page.evaluate(({ sel, z }) => [...document.querySelectorAll(sel)].flatMap((s) => {
      const r = s.getBoundingClientRect();
      return [...s.querySelectorAll('*')].filter((el) => {
        if (![...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) return false;
        const b = el.getBoundingClientRect();
        const x = b.left - r.left, y = b.top - r.top;
        return x < z[0] + z[2] && x + b.width > z[0] && y < z[1] + z[3] && y + b.height > z[1];
      }).slice(0, 3).map((el) => `text "${el.textContent.trim().slice(0, 24)}" sits in the safe zone`);
    }), { sel: selector, z: [zx, zy, zw, zh] }));
  }
  if (problems.length) throw new Error(`layout gate failed:\n  ${problems.join('\n  ')}`);

  const n = await page.locator(selector).count();
  if (n === 0) throw new Error(`no ${selector} element in ${args.html}`);
  for (const s of scales) {
    const ctx = await browser.newContext({ viewport: { width: cw, height: ch }, deviceScaleFactor: s });
    const p = await ctx.newPage();
    await p.setContent(html, { waitUntil: 'load' });
    await p.evaluate(async () => { await document.fonts.ready; });
    for (let i = 0; i < n; i++) {
      const base = args.numbered ? `${prefix}-${String(i + 1).padStart(2, '0')}` : (n > 1 ? `${prefix}-${i + 1}` : prefix);
      const file = join(out, `${base}${scales.length > 1 ? `@${s}x` : ''}.png`);
      await p.locator(selector).nth(i).screenshot({ path: file });
      files.push(file);
    }
    if (s === scales[scales.length - 1] && args.pdf && args.pdf !== 'none' && !args.pngOnly && n > 1) {
      await p.emulateMedia({ media: 'print' });
      const file = join(out, args.pdf);
      await p.pdf({ path: file, width: `${cw}px`, height: `${ch}px`, printBackground: true, margin: { top: 0, right: 0, bottom: 0, left: 0 }, tagged: true });
      files.push(file);
    }
    await ctx.close();
  }
  console.log(JSON.stringify({ ok: true, slides: n, files: files.map((f) => f.replace(/\\/g, '/')), families, warnings }));
} catch (err) {
  console.error(err.message ?? String(err));
  process.exitCode = 1;
} finally {
  await browser.close();
}
