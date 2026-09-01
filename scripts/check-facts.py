#!/usr/bin/env python3
"""
Долги по факту: какие посты вышли, а цифры по ним не занесены.

Смотрит content/posts/*/ab-plan.json и сравнивает published_at с текущим временем:
  - прошло 24 часа, пусто в facts.t24  -> долг T+24
  - прошло 72 часа, пусто в facts.t72  -> долг T+72
  - facts заполнены, а calibration пуст -> долг по калибровке
  - есть папка поста без ab-plan.json   -> предсказание не заводили вообще

Ритуал и поля - docs/FACT-LOOP.md. Прогонять в начале рабочего дня и перед новым постом.

Запуск:
    python scripts/check-facts.py
    python scripts/check-facts.py --json      # машиночитаемо
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POSTS = ROOT / "content" / "posts"


def parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def filled(block):
    if not isinstance(block, dict):
        return False
    return any(v not in (None, "", []) for v in block.values())


def main():
    now = datetime.now(timezone.utc)
    debts, ok = [], []

    if not POSTS.exists():
        print(f"нет папки {POSTS}")
        sys.exit(0)

    for folder in sorted(p for p in POSTS.iterdir() if p.is_dir()):
        plan_path = folder / "ab-plan.json"
        if not plan_path.exists():
            debts.append({"post": folder.name, "debt": "нет ab-plan.json",
                          "hint": "предсказание заводится ДО публикации, шаблон в docs/FACT-LOOP.md"})
            continue
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            debts.append({"post": folder.name, "debt": f"битый ab-plan.json ({e})", "hint": ""})
            continue

        published = parse_dt(plan.get("published_at"))
        facts = plan.get("facts") or {}
        if not published:
            ok.append(f"{folder.name}: ещё не опубликован")
            continue

        hours = (now - published).total_seconds() / 3600
        if hours >= 24 and not filled(facts.get("t24")):
            debts.append({"post": folder.name, "debt": "T+24 не занесён",
                          "hint": f"вышел {hours:.0f} ч назад: просмотры, реакции, пересылки, комментарии, отписки"})
        if hours >= 72 and not filled(facts.get("t72")):
            debts.append({"post": folder.name, "debt": "T+72 не занесён",
                          "hint": f"вышел {hours / 24:.1f} дн назад: то же плюс клики по UTM и регистрации"})
        if filled(facts.get("t72")) and not plan.get("calibration"):
            debts.append({"post": folder.name, "debt": "калибровка не сделана",
                          "hint": "сверить факт с predictions, вердикт в calibration, уроки в lessons"})
        if not debts or debts[-1]["post"] != folder.name:
            ok.append(f"{folder.name}: петля закрыта")

    if "--json" in sys.argv:
        print(json.dumps({"debts": debts, "ok": ok}, ensure_ascii=False, indent=2))
        sys.exit(1 if debts else 0)

    if debts:
        print(f"ДОЛГИ ПО ФАКТУ: {len(debts)}\n")
        for d in debts:
            print(f"  [!] {d['post']}: {d['debt']}")
            if d["hint"]:
                print(f"      {d['hint']}")
        print("\nПока долг висит, следующий пост пишется вслепую: калибровать нечем.")
    else:
        print("Долгов по факту нет.")

    if ok:
        print("\nОстальное:")
        for line in ok:
            print(f"  - {line}")

    sys.exit(1 if debts else 0)


if __name__ == "__main__":
    main()
