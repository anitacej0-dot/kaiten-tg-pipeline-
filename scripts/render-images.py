#!/usr/bin/env python3
"""
Рендер HTML-макетов в PNG 2x без Node.js.

Тот же результат, что у scripts/render-images.mjs: под капотом оба гоняют headless
Chrome. Этот вариант нужен там, где Node не установлен, а Chrome есть.

Размер кадра берётся из макета: атрибуты data-w и data-h на <body>, иначе размеры
.frame в CSS. PNG кладётся рядом с HTML под тем же именем.

Chrome ищется по стандартным путям Windows, macOS и Linux, либо берётся из переменной
окружения CHROME.

Запуск:
    python scripts/render-images.py templates/img/big-number.html
    python scripts/render-images.py content/posts/<slug>/img/*.html
"""
import os
import re
import struct
import subprocess
import sys
import tempfile
from glob import glob
from pathlib import Path

SCALE = 2

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]


def find_chrome() -> str:
    env = os.environ.get("CHROME")
    if env and Path(env).exists():
        return env
    for path in CHROME_CANDIDATES:
        if path and Path(path).exists():
            return path
    sys.exit(
        "Chrome не найден. Укажите путь в переменной CHROME, например:\n"
        '    CHROME="C:/Program Files/Google/Chrome/Application/chrome.exe"'
    )


def frame_size(html: str):
    """Размер кадра: data-w/data-h на body или width/height у .frame в CSS."""
    attr = re.search(r'data-w=["\'](\d+)["\']\s+data-h=["\'](\d+)["\']', html)
    if attr:
        return int(attr.group(1)), int(attr.group(2))
    css = re.search(r"\.frame\s*\{[^}]*?width:\s*(\d+)px[^}]*?height:\s*(\d+)px", html, re.S)
    if css:
        return int(css.group(1)), int(css.group(2))
    return 1080, 1080


def png_size(path: Path):
    with open(path, "rb") as f:
        head = f.read(33)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", head[16:24])


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(2)

    files = []
    for arg in args:
        matched = glob(arg)
        files.extend(matched if matched else [arg])

    chrome = find_chrome()
    profile = Path(tempfile.gettempdir()) / "kaiten-tg-chrome-profile"
    failed = 0

    for f in files:
        html_path = Path(f).resolve()
        if not html_path.exists():
            print(f"[X] нет файла: {f}")
            failed += 1
            continue

        w, h = frame_size(html_path.read_text(encoding="utf-8"))
        png_path = html_path.with_suffix(".png")

        cmd = [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--hide-scrollbars",
            f"--force-device-scale-factor={SCALE}",
            "--default-background-color=ffffffff",
            f"--window-size={w},{h}",
            f"--screenshot={png_path}",
            "--virtual-time-budget=6000",
            f"--user-data-dir={profile}",
            html_path.as_uri(),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        except subprocess.CalledProcessError as e:
            print(f"[X] рендер упал: {html_path.name}\n{e.stderr.decode(errors='replace')[:300]}")
            failed += 1
            continue
        except subprocess.TimeoutExpired:
            print(f"[X] рендер завис: {html_path.name}")
            failed += 1
            continue

        if not png_path.exists():
            print(f"[X] PNG не создан: {png_path.name}")
            failed += 1
            continue

        size = png_size(png_path)
        want = (w * SCALE, h * SCALE)
        ok = size == want
        kb = png_path.stat().st_size / 1024
        mark = "[OK]" if ok else "[!] "
        got = f"{size[0]}x{size[1]}" if size else "не PNG"
        print(f"{mark} {png_path.name} - {got} (ожидалось {want[0]}x{want[1]}), {kb:.0f} КБ")
        if not ok:
            failed += 1

    print(f"\n--- {failed} проблем(ы) ---" if failed else f"\n--- готово: {len(files)} PNG ---")
    print("Дальше: посмотреть PNG глазами. Проверить, что на макете нет буквы «ё».")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
