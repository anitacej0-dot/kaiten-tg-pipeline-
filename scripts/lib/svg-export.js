/* Экспорт свёрстанной карточки в SVG с живым текстом.
   Запускается внутри страницы, кладёт результат в textarea между маркерами.
   Маркер собирается из кусков, чтобы не встретиться в исходнике скрипта: иначе
   --dump-dom отдаёт сам скрипт, а не результат.
   Текст становится text, фоны и рамки - rect, картинки - image с data-img,
   логотип - g с data-logo. Подстановку картинок делает scripts/html-to-svg.py. */
function kaitenSvgExport() {
  const esc = s => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
                    .replace(/"/g, "&quot;");
  const r2 = n => Math.round(n * 100) / 100;
  const out = [];
  let clipId = 0;
  const defs = [];

  const root = document.querySelector(".frame");
  const rb = root.getBoundingClientRect();
  const W = Math.round(rb.width), H = Math.round(rb.height);
  const X0 = rb.left, Y0 = rb.top;

  const canvas = document.createElement("canvas").getContext("2d");
  const metricsCache = new Map();
  function fontMetrics(font) {
    if (!metricsCache.has(font)) {
      canvas.font = font;
      const m = canvas.measureText("Нg");
      metricsCache.set(font, {
        a: m.fontBoundingBoxAscent || 0,
        d: m.fontBoundingBoxDescent || 0,
      });
    }
    return metricsCache.get(font);
  }

  const visible = c => c && c !== "transparent" && !/rgba\([^)]*,\s*0\)$/.test(c);

  // ::before у галочек нельзя обойти обходом текстовых узлов - подменяем настоящим span
  document.querySelectorAll(".checks li").forEach(li => {
    const cs = getComputedStyle(li, "::before");
    const span = document.createElement("span");
    span.textContent = "✓";
    span.setAttribute("data-pseudo", "1");
    span.style.cssText = "position:absolute;left:0;top:2px;width:34px;height:34px;" +
      "border-radius:50%;background:" + cs.backgroundColor + ";color:" + cs.color +
      ";font-size:" + cs.fontSize + ";font-weight:" + cs.fontWeight +
      ";display:flex;align-items:center;justify-content:center;line-height:1";
    li.insertBefore(span, li.firstChild);
  });
  const hide = document.createElement("style");
  hide.textContent = ".checks li::before{content:none !important}";
  document.head.appendChild(hide);

  function rect(el) {
    const b = el.getBoundingClientRect();
    return { x: b.left - X0, y: b.top - Y0, w: b.width, h: b.height };
  }

  function emitBox(el, clip) {
    const s = getComputedStyle(el);
    if (s.display === "none" || s.visibility === "hidden") return;
    const b = rect(el);
    if (b.w <= 0 || b.h <= 0) return;
    const rx = parseFloat(s.borderTopLeftRadius) || 0;
    const radius = rx >= Math.min(b.w, b.h) / 2 ? Math.min(b.w, b.h) / 2 : rx;
    const cl = clip ? ` clip-path="url(#${clip})"` : "";

    if (visible(s.backgroundColor)) {
      out.push(`<rect x="${r2(b.x)}" y="${r2(b.y)}" width="${r2(b.w)}" height="${r2(b.h)}"` +
        (radius ? ` rx="${r2(radius)}"` : "") + ` fill="${s.backgroundColor}"${cl}/>`);
    }
    const bw = parseFloat(s.borderTopWidth) || 0;
    if (bw > 0 && visible(s.borderTopColor) && s.borderTopStyle !== "none") {
      const i = bw / 2;
      out.push(`<rect x="${r2(b.x + i)}" y="${r2(b.y + i)}" width="${r2(b.w - bw)}" ` +
        `height="${r2(b.h - bw)}"` + (radius ? ` rx="${r2(Math.max(radius - i, 0))}"` : "") +
        ` fill="none" stroke="${s.borderTopColor}" stroke-width="${r2(bw)}"` +
        (s.borderTopStyle === "dashed" ? ` stroke-dasharray="10 8"` : "") + `${cl}/>`);
    }
  }

  function emitImage(el, clip) {
    const b = rect(el);
    if (b.w > 0 && b.h <= 0 && el.naturalWidth) b.h = b.w * el.naturalHeight / el.naturalWidth;
    if (b.w <= 0 || b.h <= 0) { console.warn("нулевая картинка:", el.src); return; }
    const src = el.getAttribute("src") || "";
    const cl = clip ? ` clip-path="url(#${clip})"` : "";
    const attr = `x="${r2(b.x)}" y="${r2(b.y)}" width="${r2(b.w)}" height="${r2(b.h)}"`;
    if (/\.svg($|\?)/i.test(src)) {
      out.push(`<g data-logo="${esc(src)}" ${attr}${cl}></g>`);
    } else {
      out.push(`<image data-img="${esc(src)}" ${attr} preserveAspectRatio="none"${cl}/>`);
    }
  }

  function emitText(node, clip) {
    const el = node.parentElement;
    const s = getComputedStyle(el);
    if (s.display === "none" || s.visibility === "hidden") return;
    const text = node.nodeValue;
    if (!text || !text.trim()) return;
    const tt = s.textTransform;
    const shape = str => tt === "uppercase" ? str.toUpperCase()
                       : tt === "lowercase" ? str.toLowerCase() : str;

    const fs = parseFloat(s.fontSize);
    const font = `${s.fontStyle} ${s.fontWeight} ${fs}px ${s.fontFamily}`;
    const fm = fontMetrics(font);
    const ls = parseFloat(s.letterSpacing);
    const family = s.fontFamily.split(",")[0].replace(/["']/g, "").trim();
    const cl = clip ? ` clip-path="url(#${clip})"` : "";

    // Строки собираем посимвольно: у каждого символа свой прямоугольник,
    // группируем по верхней границе. Пробелы в HTML схлопываются, а в SVG при
    // xml:space="preserve" - нет, поэтому пробелы нормализуем сами, а x строки
    // берём по первому непробельному символу: отступ уже учтён в его координате.
    const lines = [];
    const rng = document.createRange();
    for (let i = 0; i < text.length; i++) {
      rng.setStart(node, i); rng.setEnd(node, i + 1);
      const r = rng.getBoundingClientRect();
      const ch = text[i];
      const blank = !ch.trim();
      if (!r.width && !r.height) {           // схлопнутый пробел или перенос строки
        if (lines.length) lines[lines.length - 1].s += " ";
        continue;
      }
      const last = lines[lines.length - 1];
      if (last && Math.abs(last.top0 - r.top) < 2) {
        last.s += ch;
        if (!blank) {
          if (last.left === null) { last.left = r.left; last.top = r.top; last.bottom = r.bottom; }
          last.right = r.right;
        }
      } else {
        lines.push({
          top0: r.top, s: ch,
          left: blank ? null : r.left,
          right: blank ? null : r.right,
          top: r.top, bottom: r.bottom,
        });
      }
    }
    for (const ln of lines) {
      const str = ln.s.replace(/\s+/g, " ").trim();
      if (!str || ln.left === null) continue;
      const lead = (ln.bottom - ln.top - (fm.a + fm.d)) / 2;
      const baseline = ln.top - Y0 + lead + fm.a;
      // textLength держит ширину строки ровно такой, какой её посчитала вёрстка:
      // без него соседние куски строки наезжают друг на друга, когда просмотрщик
      // подставляет другой шрифт. Фигма textLength игнорирует и верстает текст
      // заново по своим метрикам, поэтому правке шрифта это не мешает.
      const width = ln.right !== null ? ln.right - ln.left : 0;
      out.push(`<text x="${r2(ln.left - X0)}" y="${r2(baseline)}" ` +
        (width > 1 ? `textLength="${r2(width)}" lengthAdjust="spacing" ` : "") +
        `font-family="${esc(family)}" font-size="${r2(fs)}" font-weight="${s.fontWeight}"` +
        (s.fontStyle !== "normal" ? ` font-style="${s.fontStyle}"` : "") +
        (ls ? ` letter-spacing="${r2(ls)}"` : "") +
        ` fill="${s.color}" xml:space="preserve"${cl}>${esc(shape(str))}</text>`);
    }
  }

  function walk(el, clip) {
    if (el.nodeType === 1) {
      const s = getComputedStyle(el);
      if (s.display === "none" || s.visibility === "hidden") return;
      if (el.tagName === "IMG") { emitImage(el, clip); return; }
      emitBox(el, clip);
      let childClip = clip;
      if (s.overflow === "hidden" || s.overflowX === "hidden") {
        const b = rect(el);
        const rx = parseFloat(s.borderTopLeftRadius) || 0;
        const id = `clip${++clipId}`;
        defs.push(`<clipPath id="${id}"><rect x="${r2(b.x)}" y="${r2(b.y)}" ` +
          `width="${r2(b.w)}" height="${r2(b.h)}"${rx ? ` rx="${r2(rx)}"` : ""}/></clipPath>`);
        childClip = id;
      }
      for (const n of el.childNodes) walk(n, childClip);
    } else if (el.nodeType === 3) {
      emitText(el, clip);
    }
  }

  // Ссылки на шрифты подставляет scripts/html-to-svg.py: из страницы их не достать,
  // у file:// стилей cssRules закрыт политикой источника.
  const fontStyle = "@@FONTS@@";

  walk(root, null);

  const svg = `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" ` +
    `width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">\n${fontStyle}<defs>\n${defs.join("\n")}\n</defs>\n` +
    out.join("\n") + `\n</svg>`;

  return svg;
}

// Экспорт синхронный, прямо при разборе страницы.
//
// ⚠️ Ждать здесь нельзя ничем: под --dump-dom и --virtual-time-budget Chrome снимает
// DOM раньше, чем сработает window.onload или разрешится document.fonts.ready.
// Обе попытки проверены 18.09.2026, обе отдавали пустой DOM.
// Поэтому размеры картинок не берутся из загрузки: scripts/html-to-svg.py заранее
// проставляет каждой <img> aspect-ratio, и высота известна до того, как файл скачан.
(function () {
  const MARK = "@@" + "KAITEN-SVG" + "@@";
  const ta = document.createElement("textarea");
  ta.id = "kaiten-svg-out";
  try {
    ta.textContent = MARK + kaitenSvgExport() + MARK;
  } catch (e) {
    ta.textContent = MARK + "ОШИБКА ЭКСПОРТА: " + (e && e.stack || e) + MARK;
  }
  document.body.appendChild(ta);
})();
