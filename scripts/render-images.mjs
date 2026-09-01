// Рендерит HTML-макеты картинок в PNG через headless Chrome в 2× (retina).
//
// Закрывает шаг 10 ранбука (`docs/RUNBOOK.md`), правила визуалов — `docs/VISUALS.md`.
// Размер кадра берётся из самого макета (data-w/data-h на <body> или .frame в CSS),
// поэтому один и тот же исходник нельзя случайно отрендерить в чужом формате.
//
// Запуск:
//   node scripts/render-images.mjs templates/img/big-number.html [...ещё html]
//   node scripts/render-images.mjs content/posts/<slug>/img/*.html
//   CHROME="C:/Program Files/Google/Chrome/Application/chrome.exe" node scripts/render-images.mjs ...
//
// PNG кладётся рядом с HTML под тем же именем. По умолчанию 1080×1080 (в файле 2160×2160).
//
// Почему сложнее, чем «сделай скриншот»: у обычного Chrome в новом headless окно шире
// вьюпорта на высоту служебной полосы, поэтому нижняя часть кадра обрезается. Скрипт
// это компенсирует: рендерит с запасом и отрезает лишние строки прямо в PNG (без
// внешних зависимостей). Если рядом найден chrome-headless-shell, он точнее и берётся
// первым: npx @puppeteer/browsers install chrome-headless-shell@stable
import { readFileSync, writeFileSync, existsSync, statSync, readdirSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { resolve, dirname, basename, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { inflateSync, deflateSync } from "node:zlib";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const SCALE = 2;          // retina
const PAD = 260;          // запас по высоте для обычного Chrome, лишнее отрезаем

function safeLs(dir) { try { return readdirSync(dir); } catch { return []; } }

// chrome-headless-shell (точный) → обычный Chrome (с компенсацией) → Edge.
function findBrowser() {
  const shells = [], full = [];
  if (process.env.CHROME && existsSync(process.env.CHROME)) {
    const p = process.env.CHROME;
    (/headless[-_]shell/i.test(p) ? shells : full).push(p);
  }
  const caches = [
    join(process.env.HOME ?? process.env.USERPROFILE ?? "", ".cache/puppeteer"),
    join(process.env.LOCALAPPDATA ?? "", "puppeteer"),
    join(process.env.TMPDIR ?? "/tmp", "chrome"),
    "/opt/pw-browsers",
  ];
  for (const cache of caches) {
    for (const dir of safeLs(cache)) {
      const base = join(cache, dir);
      for (const ver of [".", ...safeLs(base)]) {
        const cand = [
          ["chrome-headless-shell-win64", "chrome-headless-shell.exe"],
          ["chrome-headless-shell-mac-arm64", "chrome-headless-shell"],
          ["chrome-headless-shell-linux64", "chrome-headless-shell"],
          ["chrome-linux", "headless_shell"],
        ];
        for (const [d, f] of cand) {
          const p = join(base, ver, d, f);
          if (existsSync(p)) shells.push(p);
        }
        const fulls = [
          join(base, ver, "chrome-win64", "chrome.exe"),
          join(base, ver, "chrome-linux64", "chrome"),
          join(base, ver, "chrome-mac-arm64", "Google Chrome for Testing.app", "Contents", "MacOS", "Google Chrome for Testing"),
          join(base, ver, "chrome-linux", "chrome"),
        ];
        for (const p of fulls) if (existsSync(p)) full.push(p);
      }
    }
  }
  full.push(
    // Windows
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    join(process.env.LOCALAPPDATA ?? "", "Google", "Chrome", "Application", "chrome.exe"),
    join(process.env.LOCALAPPDATA ?? "", "Microsoft", "Edge", "Application", "msedge.exe"),
    // macOS
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    // Linux
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
  );
  const shell = shells.find(existsSync);
  if (shell) return { bin: shell, exact: true };
  const bin = full.find(existsSync);
  return bin ? { bin, exact: false } : null;
}

const BROWSER = findBrowser();
if (!BROWSER) {
  console.error("✗ Chrome не найден. Поставь его один раз:");
  console.error("    npx @puppeteer/browsers install chrome-headless-shell@stable");
  console.error("  либо укажи путь явно: CHROME=<путь к chrome> node scripts/render-images.mjs ...");
  process.exit(1);
}

const files = process.argv.slice(2);
if (files.length === 0) {
  console.error("Использование: node scripts/render-images.mjs <файл.html> [...]");
  process.exit(1);
}

// Размер кадра: data-w/data-h на body или width/height у .frame в CSS.
function frameSize(html) {
  const attr = html.match(/data-w=["'](\d+)["']\s+data-h=["'](\d+)["']/);
  if (attr) return { w: +attr[1], h: +attr[2] };
  const css = html.match(/\.frame\s*\{[^}]*?width:\s*(\d+)px[^}]*?height:\s*(\d+)px/s);
  if (css) return { w: +css[1], h: +css[2] };
  return { w: 1080, h: 1080 };
}

// --- PNG: чтение размера и обрезка лишних строк снизу ---------------------
const CRC = (() => {
  const t = new Int32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c;
  }
  return (buf) => {
    let c = -1;
    for (const b of buf) c = t[(c ^ b) & 0xff] ^ (c >>> 8);
    return (c ^ -1) >>> 0;
  };
})();

function pngChunks(buf) {
  const out = [];
  let off = 8;
  while (off < buf.length) {
    const len = buf.readUInt32BE(off);
    const type = buf.toString("ascii", off + 4, off + 8);
    out.push({ type, data: buf.subarray(off + 8, off + 8 + len) });
    off += 12 + len;
  }
  return out;
}

function chunk(type, data) {
  const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4); crc.writeUInt32BE(CRC(body));
  return Buffer.concat([len, body, crc]);
}

function pngSize(p) {
  const b = readFileSync(p);
  return { w: b.readUInt32BE(16), h: b.readUInt32BE(20) };
}

// Оставляем первые targetH строк. Фильтры строк ссылаются только на строки выше,
// поэтому хвост можно отрезать без распаковки-перепаковки пикселей.
function cropRows(path, targetH) {
  const buf = readFileSync(path);
  const chunks = pngChunks(buf);
  const ihdr = chunks.find((c) => c.type === "IHDR").data;
  const w = ihdr.readUInt32BE(0), h = ihdr.readUInt32BE(4);
  const bitDepth = ihdr[8], colorType = ihdr[9], interlace = ihdr[12];
  if (h === targetH) return true;
  if (h < targetH || interlace !== 0 || bitDepth !== 8) return false;
  const channels = { 0: 1, 2: 3, 3: 1, 4: 2, 6: 4 }[colorType];
  if (!channels) return false;
  const stride = 1 + w * channels;
  const raw = inflateSync(Buffer.concat(chunks.filter((c) => c.type === "IDAT").map((c) => c.data)));
  if (raw.length < stride * targetH) return false;
  const newIhdr = Buffer.from(ihdr);
  newIhdr.writeUInt32BE(targetH, 4);
  const parts = [buf.subarray(0, 8), chunk("IHDR", newIhdr)];
  for (const c of chunks) {
    if (["IHDR", "IDAT", "IEND"].includes(c.type)) continue;
    parts.push(chunk(c.type, c.data));
  }
  parts.push(chunk("IDAT", deflateSync(raw.subarray(0, stride * targetH), { level: 9 })));
  parts.push(chunk("IEND", Buffer.alloc(0)));
  writeFileSync(path, Buffer.concat(parts));
  return true;
}

// --- рендер ---------------------------------------------------------------
let failed = 0;
for (const f of files) {
  const html = resolve(f);
  if (!existsSync(html)) { console.error(`✗ нет файла: ${f}`); failed++; continue; }
  const { w, h } = frameSize(readFileSync(html, "utf-8"));
  const png = join(dirname(html), basename(html).replace(/\.html$/, ".png"));
  const winH = BROWSER.exact ? h : h + PAD;
  try {
    execFileSync(BROWSER.bin, [
      "--headless", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
      `--force-device-scale-factor=${SCALE}`,
      "--default-background-color=ffffffff",
      `--window-size=${w},${winH}`,
      `--screenshot=${png}`,
      "--virtual-time-budget=6000",   // даём догрузиться шрифтам из сети
      pathToFileURL(html).href,
    ], { stdio: ["ignore", "ignore", "pipe"] });
  } catch (e) {
    console.error(`✗ рендер упал: ${basename(html)}\n${e.stderr?.toString().slice(0, 300) ?? e.message}`);
    failed++; continue;
  }
  if (!existsSync(png)) { console.error(`✗ PNG не создан: ${basename(png)}`); failed++; continue; }
  if (!cropRows(png, h * SCALE)) console.error(`⚠ не удалось обрезать ${basename(png)} до ${h * SCALE} строк`);
  const { w: gw, h: gh } = pngSize(png);
  const ok = gw === w * SCALE && gh === h * SCALE;
  console.log(`${ok ? "✓" : "⚠"} ${basename(png)} — ${gw}×${gh} (ожидалось ${w * SCALE}×${h * SCALE}), ${(statSync(png).size / 1024).toFixed(0)} КБ`);
  if (!ok) failed++;
}

console.log(failed ? `\n--- ${failed} проблем(ы) ---` : `\n--- готово: ${files.length} PNG ---`);
console.log("Дальше: посмотреть PNG глазами, положить рядом с постом в content/posts/<slug>/");
process.exit(failed ? 1 : 0);
