#!/usr/bin/env python3
"""
Валидатор постов канала @kaiten_ru: автономная механическая проверка перед публикацией.

Проверяет правила из references/gold-standard.md и docs/DIVERSITY.md:
  - длинные тире (em dash, en dash, минус)
  - запрещённые обороты «не X, а Y» (флип « а не ») и «не только … но и»
  - вклеенные инлайн-стили из копипаста (font-family, <span>, &nbsp;, color:rgb, var(--)…)
  - хештеги (канал их не использует)
  - длина поста: лимит Телеграма 4096 знаков
  - первая строка: до 90 знаков видно в пуше, в них нужен крючок (цифра, вопрос или имя)
  - глубина продукта: минимум 2 абзаца с продуктовой конкретикой
  - ссылка (можно отключить флагом --no-link, например для дайджеста)
  - разнообразие внутри набора: похожесть вариантов по 3-граммам, одинаковые первые строки

ICP-сверку скрипт НЕ делает - это шаг рассуждения агента, скрипт про неё напоминает.

Формат файла: варианты лежат в блоках ```post ... ``` внутри разделов ## Вариант N · <жанр>.
Всё, что вне таких блоков (заметки, источники, баллы), не проверяется.

Запуск:
    python scripts/validate-post.py content/posts/<slug>/post.md
    python scripts/validate-post.py content/posts/<slug>/post.md --no-link
"""
import sys
import re
from pathlib import Path

TG_LIMIT = 4096
HOOK_LIMIT = 90
SIMILARITY_LIMIT = 0.35

PRODUCT_KW = [
    "kaiten", "кайтен", "доск", "wip", "гант", "портфел", "спринт", "метрик", "накопительн",
    "время цикла", "база знаний", "документ", "импорт", "тариф", "интеграц", "канбан",
    "процентил", "пропускн", "свимлайн", "реестр", "on-prem", "152-фз", "учёт времени",
    "загрузк", "дашборд", "отчёт", "аналитик", "воронк", "онбординг", "адаптац", "чек-лист",
    "автоматизац", "service desk", "сервис-деск", "узких мест", "блокировок", "заявк",
    "шаблон", "простран", "карточк", "итерац", "уведомлен", "каталог",
]
JUNK = ["font-family", "color:rgb", "<span", "<h4", "&nbsp;", "var(--", "font-size",
        "letter-spacing", "caret-color", "text-decoration-"]
DASHES = {"—": "em dash", "–": "en dash", "−": "минус"}


def strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def parse_variants(md: str):
    """Возвращает [(имя, текст)] из блоков ```post ... ```."""
    out = []
    pattern = re.compile(r"^##+\s*(.+?)\s*$(.*?)(?=^##+\s|\Z)", re.M | re.S)
    for name, body in pattern.findall(md):
        for block in re.findall(r"```post\s*\n(.*?)```", body, re.S):
            out.append((name.strip(), block.strip("\n")))
    if not out:  # запасной вариант: весь файл как один пост
        blocks = re.findall(r"```post\s*\n(.*?)```", md, re.S)
        out = [(f"блок {i + 1}", b.strip("\n")) for i, b in enumerate(blocks)]
    return out


def ngrams(text: str, n: int = 3):
    words = re.findall(r"\w+", text.lower())
    return {tuple(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}


def similarity(a: str, b: str) -> float:
    ga, gb = ngrams(a), ngrams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / min(len(ga), len(gb))


def check(name: str, html: str, need_link: bool):
    fails, warns = [], []
    plain = strip_tags(html)
    low = plain.lower()

    for ch, label in DASHES.items():
        if ch in plain:
            fails.append(f"длинное тире ({label})")

    if " а не " in plain:
        fails.append("оборот « а не » (флип «не X, а Y»)")
    if re.search(r"не только\b.{0,60}?\bно и\b", low):
        fails.append("оборот «не только … но и»")

    junk = [j for j in JUNK if j in html.lower()]
    if junk:
        fails.append("вклеенные инлайн-стили: " + ", ".join(junk))

    tags = re.findall(r"(?<!\w)#[А-Яа-яA-Za-z][\w_]{2,}", plain)
    if tags:
        fails.append("хештеги (канал их не использует): " + ", ".join(tags[:4]))

    if len(plain) > TG_LIMIT:
        fails.append(f"длина {len(plain)} знаков, лимит Телеграма {TG_LIMIT}")

    first = plain.strip().split("\n")[0].strip()
    if len(first) > HOOK_LIMIT:
        warns.append(f"первая строка {len(first)} знаков, в пуш попадут первые ~{HOOK_LIMIT}")
    if not (re.search(r"\d", first) or "?" in first or ":" in first):
        warns.append("в первой строке нет ни цифры, ни вопроса - крючок слабый (см. hook-bank.md)")

    paras = [p for p in re.split(r"\n\s*\n", plain) if p.strip()]
    deep = [p for p in paras if sum(k in p.lower() for k in PRODUCT_KW) >= 2]
    if len(deep) < 2:
        fails.append(f"глубина продукта: абзацев с конкретикой {len(deep)}, нужно 2")

    if need_link and not re.search(r"kaiten\.ru|t\.me/|habr\.com", low):
        fails.append("нет ссылки (отключается флагом --no-link)")

    if not re.search(r"[?]\s*$", plain.strip()) and not re.search(r"kaiten\.ru", low):
        warns.append("нет ни вопроса-вовлечения в конце, ни ссылки")

    return fails, warns


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    need_link = "--no-link" not in sys.argv
    if not args:
        print(__doc__)
        sys.exit(2)

    total_fails = 0
    for path in args:
        p = Path(path)
        if not p.exists():
            print(f"[X] нет файла: {path}")
            total_fails += 1
            continue
        md = p.read_text(encoding="utf-8")
        variants = parse_variants(md)
        print(f"\n=== {p} : вариантов {len(variants)} ===")
        if not variants:
            print("[X] не найдено ни одного блока ```post ... ```")
            total_fails += 1
            continue

        for name, text in variants:
            fails, warns = check(name, text, need_link)
            mark = "[OK]" if not fails else "[X] "
            print(f"\n{mark} {name} ({len(strip_tags(text))} знаков)")
            for f in fails:
                print(f"   FAIL: {f}")
            for w in warns:
                print(f"   warn: {w}")
            total_fails += len(fails)

        # разнообразие набора
        if len(variants) > 1:
            print("\n--- разнообразие набора ---")
            firsts = {}
            for i, (n1, t1) in enumerate(variants):
                head = strip_tags(t1).strip().split("\n")[0][:40].lower()
                firsts.setdefault(head, []).append(n1)
                for n2, t2 in variants[i + 1:]:
                    s = similarity(strip_tags(t1), strip_tags(t2))
                    if s > SIMILARITY_LIMIT:
                        print(f"   FAIL: «{n1}» и «{n2}» похожи на {s:.0%} (порог {SIMILARITY_LIMIT:.0%})")
                        total_fails += 1
            for head, names in firsts.items():
                if len(names) > 1:
                    print(f"   FAIL: одинаковое начало у вариантов: {', '.join(names)}")
                    total_fails += 1
            if total_fails == 0:
                print("   OK: клонов не найдено")

    print("\n" + "=" * 60)
    if total_fails:
        print(f"[X] нарушений: {total_fails}. Правим и запускаем снова, пока не будет 0.")
    else:
        print("[OK] 0 нарушений.")
    print("Осталось руками: ICP-сверка. Для каждого варианта назвать роль и боль "
          "дословно из references/icp-kaiten.md. Мимо ICP - переписать.")
    sys.exit(1 if total_fails else 0)


if __name__ == "__main__":
    main()
