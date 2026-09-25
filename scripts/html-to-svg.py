#!/usr/bin/env python3
"""
HTML-макет карточки -> SVG с живым текстом, для правки в Фигме.

Фигма импортирует SVG и превращает <text> в настоящие текстовые слои, а <rect>
в фигуры. Шрифт, кегль, цвет и сам текст правятся руками, PNG для этого не нужен.

Как работает: в копию макета подмешивается scripts/lib/svg-export.js, headless Chrome
открывает страницу, скрипт обходит DOM и собирает SVG по реальной геометрии вёрстки.
Дальше картинки вшиваются в base64, логотип подставляется вектором.

⚠️ Экспортёр работает синхронно, при разборе страницы: под --dump-dom Chrome снимает
DOM раньше, чем сработает onload. Поэтому размеры картинок берутся не из загрузки,
а из aspect-ratio, который проставляется здесь заранее по заголовкам файлов.

SVG кладётся рядом с HTML под тем же именем.

Запуск:
    python scripts/html-to-svg.py content/posts/<slug>/img/*.html
"""
import base64
import html as html_mod
import mimetypes
import re
import subprocess
import sys
import tempfile
from glob import glob
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
_render = import_module("render-images")
find_chrome = _render.find_chrome

EXPORTER = Path(__file__).parent / "lib" / "svg-export.js"
MARK = "@@" + "KAITEN-SVG" + "@@"


def natural_size(path):
    """Своя ширина и высота файла: из заголовка PNG или из viewBox у SVG."""
    if path.suffix.lower() == ".svg":
        m = re.search(r'viewBox="([\d.\-\s]+)"', path.read_text(encoding="utf-8"))
        if m:
            parts = [float(v) for v in m.group(1).split()]
            if len(parts) == 4 and parts[2] and parts[3]:
                return parts[2], parts[3]
        return None
    return _render.png_size(path)


def aspect_style(html, base):
    """CSS с aspect-ratio на каждую картинку макета.

    Экспорт идёт синхронно, файлы к этому моменту ещё не скачаны, и у <img>
    нулевая высота. aspect-ratio задаёт высоту из разметки, до загрузки.
    """
    rules = []
    for src in dict.fromkeys(re.findall(r'<img[^>]+src="([^"]+)"', html)):
        path = (base / src).resolve()
        if not path.exists():
            continue
        size = natural_size(path)
        if size:
            rules.append('img[src="%s"] { aspect-ratio: %s / %s; }' % (src, size[0], size[1]))
    if not rules:
        return ""
    return "<style>\n" + "\n".join(rules) + "\n</style>"


def font_style(html_path):
    """Ссылки на шрифты для <style> внутри SVG.

    Из самой страницы их не достать: у стилей с file:// закрыт доступ к cssRules.
    Поэтому @import вычитывается прямо из подключённых к макету CSS-файлов.
    Браузер по этим ссылкам покажет карточку как в вёрстке, Фигма @import
    игнорирует и подставит шрифты, установленные локально.
    """
    html = html_path.read_text(encoding="utf-8")
    urls = []
    for href in re.findall(r'<link[^>]+href="([^"]+\.css)"', html):
        css_path = (html_path.parent / href).resolve()
        if css_path.exists():
            urls += re.findall(r'@import url\("(https://fonts\.googleapis[^"]+)"\)',
                               css_path.read_text(encoding="utf-8"))
    if not urls:
        return ""
    # SVG это XML: голый & в адресе шрифта ломает разбор файла целиком
    rules = "\n".join('@import url("%s");' % u.replace("&", "&amp;")
                      for u in dict.fromkeys(urls))
    return '<style>\n%s\n</style>\n' % rules


def build_svg(html_path, chrome, profile):
    src = html_path.read_text(encoding="utf-8")
    injected = src.replace("</head>", aspect_style(src, html_path.parent) + "\n</head>")
    script = "<script>\n%s\n</script>\n</body>" % EXPORTER.read_text(encoding="utf-8")
    injected = injected.replace("</body>", script)

    tmp = html_path.with_name(".svgexport-%s.html" % html_path.stem)
    tmp.write_text(injected, encoding="utf-8")
    try:
        cmd = [
            chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
            "--virtual-time-budget=10000", "--dump-dom", "--user-data-dir=%s" % profile,
            tmp.as_uri(),
        ]
        dom = subprocess.run(cmd, check=True, capture_output=True,
                             timeout=180).stdout.decode("utf-8", "replace")
    finally:
        tmp.unlink(missing_ok=True)

    parts = dom.split(MARK)
    if len(parts) < 3:
        raise RuntimeError("экспортёр не отдал SVG: проверьте, что в макете есть .frame")
    svg = html_mod.unescape(parts[1])
    if svg.startswith("ОШИБКА ЭКСПОРТА"):
        raise RuntimeError(svg.splitlines()[0])
    return svg.replace("@@FONTS@@", font_style(html_path))


def embed_assets(svg, base):
    """Картинки в base64, логотип вектором вместо <g data-logo>."""

    def img(match):
        src = html_mod.unescape(match.group(1))
        path = (base / src).resolve()
        if not path.exists():
            print("    [!] нет картинки: %s" % src)
            return match.group(0)
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        data = base64.b64encode(path.read_bytes()).decode()
        return '<image xlink:href="data:%s;base64,%s"' % (mime, data)

    svg = re.sub(r'<image data-img="([^"]+)"', img, svg)

    def logo(match):
        src, attrs = html_mod.unescape(match.group(1)), match.group(2)
        path = (base / src).resolve()
        geo = dict(re.findall(r'(x|y|width|height)="([\d.]+)"', attrs))
        if not path.exists() or len(geo) < 4:
            return match.group(0)
        raw = path.read_text(encoding="utf-8")
        size = natural_size(path)
        inner = re.sub(r"(?is)^.*?<svg[^>]*>|</svg>\s*$", "", raw).strip()
        sx = float(geo["width"]) / size[0] if size else 1.0
        sy = float(geo["height"]) / size[1] if size else 1.0
        return '<g transform="translate(%s,%s) scale(%.5f,%.5f)">%s</g>' % (
            geo["x"], geo["y"], sx, sy, inner)

    return re.sub(r'<g data-logo="([^"]+)"([^>]*)></g>', logo, svg)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(2)

    files = []
    for arg in args:
        matched = sorted(glob(arg))
        files.extend(matched if matched else [arg])
    files = [f for f in files if not Path(f).name.startswith(".svgexport-")]

    chrome = find_chrome()
    profile = Path(tempfile.gettempdir()) / "kaiten-tg-chrome-profile"
    failed = 0

    for f in files:
        path = Path(f).resolve()
        if not path.exists():
            print("[X] нет файла: %s" % f)
            failed += 1
            continue
        try:
            svg = embed_assets(build_svg(path, chrome, profile), path.parent)
        except Exception as e:
            print("[X] %s: %s" % (path.name, e))
            failed += 1
            continue

        want = len(re.findall(r"<img[^>]", path.read_text(encoding="utf-8")))
        got = svg.count("<image ") + svg.count('<g transform="translate')
        dest = path.with_suffix(".svg")
        dest.write_text(svg, encoding="utf-8")
        note = ""
        if got < want:
            note = "   [!] потеряна картинка"
            failed += 1
        print("[OK] %s - %d КБ, текстовых слоев: %d, картинок: %d/%d%s" % (
            dest.name, len(svg) // 1024, svg.count("<text "), got, want, note))

    print("\n--- готово: %d SVG ---" % (len(files) - failed))
    print("Дальше: перетащить SVG в Фигму. Текст импортируется слоями, шрифт правится там же.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
