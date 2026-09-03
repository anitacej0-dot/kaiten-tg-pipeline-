#!/usr/bin/env python3
"""
Валидатор постов канала @kaiten_ru: механическая проверка перед публикацией.

Правила берутся из редполитики Kaiten (references/editorial-policy.md, источник -
kaiten-article-pipeline/knowledge) и из разбора корпуса канала (docs/POST-TYPES.md).

HARD (FAIL, блокирует публикацию):
  - буква «ё» где угодно в тексте
  - запрещённая лексика: функционал, для того чтобы, таск, фича, осуществили и т.д.
  - оценочные усилители без фактов: самый, лучший, всем известно, революционный
  - нейро-шлак: «живёт в сервисах», «единая среда», «Хорошая новость в том, что»
  - неверное позиционирование: «Кайтен - трекер задач», «бесплатный таск-трекер»
  - дефис или короткое тире как знак препинания (нужно длинное тире)
  - «Вы», «Ваш» с прописной буквы
  - точка в конце заголовка (первой строки)
  - вклеенные инлайн-стили из копипаста
  - нет ссылки
  - глубина продукта: меньше 2 абзацев с продуктовой конкретикой
  - обязательные элементы типа поста (см. --type)

SOFT (warn):
  - длина вне диапазона типа
  - первая строка длиннее 90 знаков (обрежется в пуше)
  - "лапки" вместо «ёлочек»
  - предложения длиннее 15 слов
  - хештеги

Разнообразие набора: похожесть вариантов по 3-граммам, одинаковые первые строки.

Формат файла: варианты в блоках ```post ... ``` внутри разделов ## Вариант N · <жанр>.
Тип поста берётся из заголовка раздела (дайджест, обновление, кейс, как сделать)
или из флага --type.

Запуск:
    python scripts/validate-post.py content/posts/<slug>/post.md
    python scripts/validate-post.py content/posts/<slug>/post.md --type=дайджест
    python scripts/validate-post.py content/posts/<slug>/post.md --no-link
"""
import re
import sys
from pathlib import Path

TG_LIMIT = 4096
HOOK_LIMIT = 90
SIMILARITY_LIMIT = 0.35
LONG_SENTENCE_WORDS = 15

# --- длины по типам, посчитаны по корпусу (docs/POST-TYPES.md) --------------
TYPE_LENGTH = {
    "дайджест": (880, 1950),
    "обновление": (750, 1550),
    "кейс": (820, 1050),
    "как сделать": (750, 1550),
}

PRODUCT_KW = [
    "kaiten", "кайтен", "доск", "wip", "гант", "портфел", "спринт", "метрик",
    "время цикла", "база знаний", "документ", "импорт", "тариф", "интеграц", "канбан",
    "пропускн", "свимлайн", "реестр", "on-prem", "152-фз", "учёт времени", "учет времени",
    "загрузк", "дашборд", "отчёт", "отчет", "аналитик", "воронк", "онбординг",
    "чек-лист", "автоматизац", "service desk", "сервис-деск", "заявк", "виджет",
    "шаблон", "простран", "карточк", "итерац", "уведомлен", "каталог", "фильтр",
]

JUNK = ["font-family", "color:rgb", "<span", "<h4", "&nbsp;", "var(--", "font-size",
        "letter-spacing", "caret-color", "text-decoration-"]

# --- HARD: лексика ----------------------------------------------------------
LEXICON = {
    r"функционал(?!ьн)": "функциональность",
    r"для того,? чтобы": "чтобы",
    r"\bтаск[аи]?\b": "задача, карточка",
    r"\bфич[аиеу]\b": "функция, возможность",
    r"провели оптимизацию": "оптимизировали",
    r"осуществил[иа]? переход": "перешли",
    r"осуществля\w+ поддержку": "поддерживали",
    r"в целях решения": "чтобы решить",
    r"мобильное приложение для смартфонов": "приложение для смартфонов",
}

EVALUATIVE = {
    r"\bсам(ый|ая|ое|ые)\s+\w+": "оценка без фактов, нужен источник или цифра",
    r"\bлучш(ий|ая|ее|ие)\b": "оценка без фактов",
    r"\bнаиболее\b": "оценка без фактов",
    r"всем известно": "нужен источник",
    r"кажд(ый|ая) сталкива": "нужен источник",
    r"революционн": "рекламное клише",
    r"инновационн": "рекламное клише",
    r"уникальн": "рекламное клише без доказательства",
}

NEURO = {
    r"жив[её]т (в сервис\w*|рядом с|в связк\w* с задач)": "по факту: «работает в связке с», «встроен в»",
    r"един(ая|ое) (сред|простран)\w*": "конкретно: какой набор инструментов и зачем",
    r"тон(ет|ут) в ": "«застревает на», «упирается в»",
    r"хорошая новость": "убрать связку, сразу по делу",
    r"проще говоря": "убрать связку, сразу пояснение",
    r"на старших тарифах": "на дорогих тарифах",
    r"типичн(ые|ых) ловушк": "частые ошибки",
    r"разворачива(ется|ются) (на|в)": "«устанавливается на серверы компании»",
    r"промах(ивают|)\w*": "«ошибаются», «выбирают не под задачу»",
}

POSITIONING = {
    r"(кайтен|kaiten)\s*[-—]\s*(трекер|таск-трекер)": "система управления проектами, задачами и командами",
    r"бесплатн\w+ таск-трекер": "не полностью бесплатный, формулировка ок только про тариф Free",
    r"кайтен для (небольших|маленьких) компан": "подходит крупным, небольшие тоже могут",
    r"бесплатн\w+ тариф\w*\s+(урезан|базов|ограничен по срок)": "бессрочный, закрывает простые процессы",
}


def strip_tags(text):
    return re.sub(r"<[^>]+>", "", text)


def detect_type(name):
    low = name.lower()
    for t in TYPE_LENGTH:
        if t in low:
            return t
    if "фича" in low or "функци" in low:
        return "обновление"
    return None


def parse_variants(md):
    out = []
    pattern = re.compile(r"^##+\s*(.+?)\s*$(.*?)(?=^##+\s|\Z)", re.M | re.S)
    for name, body in pattern.findall(md):
        for block in re.findall(r"```post\s*\n(.*?)```", body, re.S):
            out.append((name.strip(), block.strip("\n")))
    if not out:
        blocks = re.findall(r"```post\s*\n(.*?)```", md, re.S)
        out = [(f"блок {i + 1}", b.strip("\n")) for i, b in enumerate(blocks)]
    return out


def check_dashes(text):
    """Длинное тире - знак препинания. Короткое - только диапазоны. Дефис - в словах."""
    fails = []
    if re.search(r"\s-\s", text):
        fails.append("дефис как знак препинания, нужно длинное тире «—»")
    if re.search(r"\s–\s", text):
        fails.append("короткое тире как знак препинания, нужно длинное «—» (короткое только для диапазонов)")
    return fails


def check_type_rules(ptype, text, first):
    """Обязательные элементы конкретного типа поста."""
    fails, warns = [], []
    low = text.lower()
    if ptype == "дайджест":
        if not re.search(r"\d+\s*[–-]\s*\d+\s+\w+", first):
            fails.append("в заголовке дайджеста нет диапазона дат вида «17–21 августа»")
        if "uptime" not in low and "стабильность сервиса" not in low:
            fails.append("в дайджесте нет блока «Стабильность сервиса» с Uptime")
        if not re.search(r"в стать[еи]", low):
            warns.append("в дайджесте нет закрывающей ссылки «Об исправленных ошибках — в статье»")
    elif ptype == "обновление":
        if not text.rstrip().endswith("?") and not re.search(r"\n\S+\s*—\s*\w+", text.rstrip()[-160:]):
            warns.append("в конце нет вопроса-вовлечения или голосования реакциями")
    elif ptype == "кейс":
        if "опытом делится" not in low:
            fails.append("в кейсе нет подписи героя «Опытом делится <Имя>, <должность> <Компания>»")
        if not re.search(r"\d", text[:400]):
            warns.append("в первых абзацах кейса нет цифр масштаба")
    elif ptype == "как сделать":
        if not re.search(r"^\s*\d[.)]\s", text, re.M):
            warns.append("в инструкции нет нумерованных шагов")
    return fails, warns


def check_variant(name, text, need_link, forced_type):
    fails, warns = [], []
    plain = strip_tags(text)
    low = plain.lower()
    ptype = forced_type or detect_type(name)

    # --- HARD ---
    yo = re.findall(r"[ёЁ]", plain)
    if yo:
        words = sorted({w for w in re.findall(r"\w*[ёЁ]\w*", plain)})
        fails.append(f"буква «ё» ({len(yo)} шт.): {', '.join(words[:6])}")

    for pat, fix in LEXICON.items():
        m = re.search(pat, low)
        if m:
            fails.append(f"запрещено «{m.group(0)}» → {fix}")

    for pat, why in EVALUATIVE.items():
        m = re.search(pat, low)
        if m:
            fails.append(f"оценочное «{m.group(0).strip()}»: {why}")

    for pat, fix in NEURO.items():
        m = re.search(pat, low)
        if m:
            fails.append(f"нейро-шлак «{m.group(0).strip()}» → {fix}")

    for pat, fix in POSITIONING.items():
        m = re.search(pat, low)
        if m:
            fails.append(f"позиционирование «{m.group(0).strip()}» → {fix}")

    fails += check_dashes(plain)

    if re.search(r"(?<![.!?»\"]\s)(?<!^)\bВ(ы|ам|ас|ашей|аш|аши|ами)\b", plain):
        fails.append("«вы» и «ваш» пишутся со строчной буквы")

    first = plain.strip().split("\n")[0].strip()
    if first.endswith("."):
        fails.append("точка в конце заголовка, в заголовках точек не ставим")

    junk = [j for j in JUNK if j in text.lower()]
    if junk:
        fails.append(f"инлайн-стили из копипаста: {', '.join(junk)}")

    if len(plain) > TG_LIMIT:
        fails.append(f"{len(plain)} знаков, лимит Телеграма {TG_LIMIT}")

    paras = [p for p in re.split(r"\n\s*\n", plain) if p.strip()]
    # Кейс рассказывает про клиента, продукт в нём присутствует, но не разворачивается.
    # Остальные типы обязаны дать продуктовую конкретику вглубь.
    per_para = 1 if ptype == "кейс" else 2
    deep = [p for p in paras if sum(k in p.lower() for k in PRODUCT_KW) >= per_para]
    if len(deep) < 2:
        fails.append(
            f"глубина продукта: абзацев, где продукт назван "
            f"{'хотя бы раз' if per_para == 1 else 'конкретно'}, всего {len(deep)}, нужно 2"
        )

    if need_link and not re.search(r"kaiten\.ru|kaiten\.site|t\.me/|habr\.com|secrets\.tbank\.ru|github\.com", low):
        fails.append("нет ссылки (отключается флагом --no-link)")

    tf, tw = check_type_rules(ptype, plain, first)
    fails += tf
    warns += tw

    # --- SOFT ---
    if ptype:
        lo, hi = TYPE_LENGTH[ptype]
        if not lo <= len(plain) <= hi:
            warns.append(f"длина {len(plain)}, у типа «{ptype}» диапазон {lo}-{hi}")
    else:
        warns.append("тип поста не распознан, проверки по типу пропущены (см. --type)")

    if len(first) > HOOK_LIMIT:
        warns.append(f"первая строка {len(first)} знаков, в пуш попадут первые ~{HOOK_LIMIT}")

    if '"' in plain:
        warns.append('"лапки" вместо «ёлочек»')

    if re.search(r"#[А-Яа-яЁёA-Za-z]", plain):
        warns.append("хештег: канал их почти не использует")

    long_sents = []
    lines = [re.sub(r"^[^\w«]+", "", ln).strip() for ln in plain.split("\n")]
    for s in [c for ln in lines for c in re.split(r"(?<=[.!?])\s+", ln) if c.strip()]:
        n = len(s.split())
        if n > LONG_SENTENCE_WORDS:
            long_sents.append(f"{n} слов: «{s[:48]}…»")
    if long_sents:
        warns.append(f"предложения длиннее {LONG_SENTENCE_WORDS} слов ({len(long_sents)}): {long_sents[0]}")

    return ptype, fails, warns


def ngrams(text, n=3):
    words = re.findall(r"\w+", text.lower())
    return {tuple(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}


def check_set(variants):
    issues = []
    firsts = {}
    for name, text in variants:
        f = strip_tags(text).strip().split("\n")[0].strip().lower()
        firsts.setdefault(f, []).append(name)
    for f, names in firsts.items():
        if len(names) > 1:
            issues.append(f"одинаковые первые строки: {', '.join(names)}")
    for i in range(len(variants)):
        for j in range(i + 1, len(variants)):
            a, b = ngrams(variants[i][1]), ngrams(variants[j][1])
            if not a or not b:
                continue
            jac = len(a & b) / len(a | b)
            if jac > SIMILARITY_LIMIT:
                issues.append(f"клоны {variants[i][0]} и {variants[j][0]}: похожесть {jac:.0%}")
    return issues


def main():
    argv = sys.argv[1:]
    paths = [a for a in argv if not a.startswith("--")]
    need_link = "--no-link" not in argv
    forced = None
    for a in argv:
        if a.startswith("--type="):
            forced = a.split("=", 1)[1].strip().lower()
            if forced not in TYPE_LENGTH:
                sys.exit(f"неизвестный тип «{forced}», доступны: {', '.join(TYPE_LENGTH)}")
    if not paths:
        print(__doc__)
        sys.exit(2)

    total_fails = 0
    for path in paths:
        p = Path(path)
        if not p.exists():
            print(f"[X] нет файла: {path}")
            total_fails += 1
            continue
        variants = parse_variants(p.read_text(encoding="utf-8"))
        print(f"\n=== {p} : вариантов {len(variants)} ===\n")
        if not variants:
            print("[X] не найдено ни одного блока ```post ... ```")
            total_fails += 1
            continue

        for name, text in variants:
            ptype, fails, warns = check_variant(name, text, need_link, forced)
            mark = "[X]" if fails else "[OK]"
            tname = ptype or "тип не распознан"
            print(f"{mark}  {name} ({len(strip_tags(text))} знаков, {tname})")
            for f in fails:
                print(f"   FAIL: {f}")
            for w in warns:
                print(f"   warn: {w}")
            print()
            total_fails += len(fails)

        if len(variants) > 1:
            print("--- разнообразие набора ---")
            issues = check_set(variants)
            for i in issues:
                print(f"   FAIL: {i}")
            total_fails += len(issues)
            if not issues:
                print("   OK: клонов не найдено")

    print("\n" + "=" * 60)
    if total_fails:
        print(f"[X] нарушений: {total_fails}. Правим и запускаем снова, пока не будет 0.")
    else:
        print("[OK] 0 нарушений.")
    print("Осталось руками: ICP-сверка, проверка фактуры по базе знаний, пассив и инверсия.")
    sys.exit(1 if total_fails else 0)


if __name__ == "__main__":
    main()
