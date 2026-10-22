"""Read-only production preflight for the Academy; prints aggregates, never secrets.

Run inside Academy API container: python pilot_readiness.py
This is an automated gate, NOT a substitute for restoring a backup or an iPhone test.
"""
import os

from question_quality import quality_issues
from server import db


def evaluate(s):
    checks = [
        ("Telegram подключён", bool(s["telegram_configured"])),
        ("Есть активный менеджер", s["managers"] >= 1),
        ("WOW опубликован", s["wow"] >= 1),
        ("SMILE опубликован", s["smile"] >= 1),
        ("Есть курс меню из утверждённых карточек", s["mapped_menu"] >= 1),
        ("Есть минимум 3 опубликованных кейса", s["cases"] >= 3),
        ("В опубликованных тестах нет очевидных предупреждений", s["weak_quizzes"] == 0),
        ("Yandex AI Studio настроен", bool(s["ai_configured"])),
    ]
    return checks


def counts():
    with db() as c:
        courses = c.execute(
            "SELECT id,title,kind,questions FROM courses "
            "WHERE published AND NOT archived"
        ).fetchall()
        mapped = {
            row["course_id"] for row in c.execute(
                "SELECT DISTINCT course_id FROM course_dishes"
            ).fetchall()
        }
        qcount = sum(bool(quality_issues(course["questions"])) for course in courses)
        people = c.execute(
            "SELECT role,active,count(*) AS n FROM staff GROUP BY role,active"
        ).fetchall()
        cases = c.execute(
            "SELECT count(*) AS n FROM case_scenarios WHERE published AND NOT archived"
        ).fetchone()["n"]
        cards = c.execute(
            "SELECT count(*) AS n FROM dish_cards WHERE published AND NOT archived"
        ).fetchone()["n"]
        queue = c.execute(
            "SELECT count(*) AS n FROM outbox WHERE state='failed'"
        ).fetchone()["n"]
    return {
        "telegram_configured": bool(os.getenv("BOT_TOKEN") and os.getenv("OWNER_TELEGRAM_ID")),
        "ai_configured": bool(os.getenv("YANDEX_API_KEY") and os.getenv("YANDEX_FOLDER_ID")),
        "managers": sum(r["n"] for r in people if r["role"] in ("manager","local") and r["active"]),
        "pending": sum(r["n"] for r in people if not r["active"]),
        "active_staff": sum(r["n"] for r in people if r["active"]),
        "courses": len(courses),
        "wow": sum("WOW" in r["title"].upper() or "ВАУ" in r["title"].upper() for r in courses),
        "smile": sum("SMILE" in r["title"].upper() for r in courses),
        "mapped_menu": sum(r["id"] in mapped and
                           ("КУХНЯ" in r["title"].upper() or "МЕНЮ" in r["title"].upper())
                           for r in courses),
        "cases": cases,
        "cards": cards,
        "weak_quizzes": qcount,
        "outbox_failed": queue,
    }


if __name__ == "__main__":
    try:
        snapshot = counts()
    except Exception as exc:
        # No DB connection strings, personal info or exception details.
        print("BLOCK: проверка базы данных не завершена (" + type(exc).__name__ + ")")
        raise SystemExit(2)
    checks = evaluate(snapshot)
    print("MOJO — проверка готовности пилота (без персональных данных)")
    print(f"Курсов: {snapshot['courses']} · карточек: {snapshot['cards']} · "
          f"кейсов: {snapshot['cases']} · активных аккаунтов: {snapshot['active_staff']}")
    print(f"Заявок на подтверждение: {snapshot['pending']} · "
          f"ошибок уведомлений: {snapshot['outbox_failed']}")
    for name, good in checks:
        print(("OK   " if good else "BLOCK") + " " + name)
    print("ОТДЕЛЬНО ПРОВЕРИТЬ ВРУЧНУЮ: живой ответ ИИ, HTTPS/права доступа, "
          "резервная копия вне Selectel и пробное восстановление, "
          "полный сценарий на iPhone, работу уведомлений.")
    if not all(good for _,good in checks):
        print("РЕЗУЛЬТАТ: НЕ ГОТОВО к пилоту на реальных сотрудниках.")
        raise SystemExit(1)
    print("Технические критерии содержимого пройдены. Нужна ручная приёмка на сервере и iPhone.")
