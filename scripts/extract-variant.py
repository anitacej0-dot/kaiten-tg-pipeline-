#!/usr/bin/env python3
"""
Достаёт текст варианта из post.md для переноса в PUBLISH.md.

Копировать согласованный текст руками нельзя: при копипасте теряются переносы,
эмодзи и кавычки, и опубликованная версия расходится с согласованной. Этот скрипт
берёт текст ровно из блока ```post и попутно проверяет то, что чаще всего ломается.

Запуск:
    python scripts/extract-variant.py content/posts/<slug>/post.md          # список вариантов
    python scripts/extract-variant.py content/posts/<slug>/post.md 1        # текст варианта 1
    python scripts/extract-variant.py content/posts/<slug>/post.md 1 --raw  # без проверок и рамки
"""
import re
import sys
from pathlib import Path


def variants(md):
    out = []
    pattern = re.compile(r"^##+\s*(.+?)\s*$(.*?)(?=^##+\s|\Z)", re.M | re.S)
    for name, body in pattern.findall(md):
        for block in re.findall(r"```post\s*\n(.*?)```", body, re.S):
            out.append((name.strip(), block.strip("\n")))
    return out


def check(text):
    problems = []
    yo = sorted({w for w in re.findall(r"\w*[ёЁ]\w*", text)})
    if yo:
        problems.append(f"буква «ё»: {', '.join(yo)}")
    outside = re.sub(r"«[^»]*»", "", text)
    if '"' in outside:
        problems.append("прямые кавычки вместо «ёлочек»")
    if re.search(r"\s-\s", text):
        problems.append("дефис как знак препинания, нужно длинное тире")
    if re.search(r"https?://", text):
        problems.append("голый URL: канал вшивает ссылку в слово")
    return problems


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    raw = "--raw" in sys.argv
    if not args:
        print(__doc__)
        sys.exit(2)

    path = Path(args[0])
    if not path.exists():
        sys.exit(f"нет файла: {path}")
    items = variants(path.read_text(encoding="utf-8"))
    if not items:
        sys.exit("не найдено ни одного блока ```post")

    if len(args) < 2:
        print(f"Вариантов в файле: {len(items)}\n")
        for i, (name, text) in enumerate(items, 1):
            first = text.split("\n")[0]
            print(f"  {i}. {name}")
            print(f"     {len(text)} знаков · {first[:70]}")
        print("\nЧтобы получить текст: добавьте номер варианта в конец команды.")
        return

    try:
        n = int(args[1])
        name, text = items[n - 1]
    except (ValueError, IndexError):
        sys.exit(f"вариант {args[1]} не найден, всего вариантов {len(items)}")

    if raw:
        print(text)
        return

    print(f"--- {name} · {len(text)} знаков ---\n")
    print(text)
    problems = check(text)
    print()
    if problems:
        print("[X] перед переносом в PUBLISH.md править:")
        for p in problems:
            print(f"   - {p}")
        sys.exit(1)
    print("[OK] ё нет, кавычки ёлочки, тире длинное, голых URL нет.")


if __name__ == "__main__":
    main()
