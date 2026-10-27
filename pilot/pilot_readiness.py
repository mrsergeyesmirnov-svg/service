"""Read-only production preflight for the Academy; prints aggregates, never secrets.

Run inside Academy API container: python pilot_readiness.py
This is an automated gate, NOT a substitute for restoring a backup or an iPhone test.
"""
import os

from question_quality import quality_issues
from dish_lessons import dish_chapters, reviewed_dish_signature
from server import db


def evaluate(s):
    checks = [
        ("Telegram подключён", bool(s["telegram_configured"])),
        ("Есть активный менеджер", s["managers"] >= 1),
        ("Базовый курс сервиса опубликован с проверяемым тестом", s.get("service_ready", 0) >= 1),
        ("WOW опубликован", s["wow"] >= 1),
        ("SMILE опубликован", s["smile"] >= 1),
        ("Есть курс меню из утверждённых карточек", s["mapped_menu"] >= 1),
        ("Нет устаревших утверждённых тестов по изменённым блюдам", s.get("stale_reviewed", 0) == 0),
        ("Есть минимум 3 опубликованных кейса", s["cases"] >= 3),
        ("В опубликованных тестах нет очевидных предупреждений", s["weak_quizzes"] == 0),
        ("Yandex AI Studio настроен", bool(s["ai_configured"])),
    ]
    return checks


def counts():
    with db() as c:
        courses = c.execute(
            "SELECT id,title,kind,body,questions,restaurant,reviewed_dish_signature FROM courses "
            "WHERE published AND NOT archived"
        ).fetchall()
        approved_outlines = {item['course_id'] for item in c.execute(
            "SELECT course_id FROM course_text_outline WHERE jsonb_array_length(chapters)>0"
        ).fetchall()}
        service_ready = sum(
            row['kind'] == 'service' and
            any(word in row['title'].casefold() for word in
                ('сервис', 'обслуживан', 'service book', 'servicebook')) and
            len(row['questions'] or []) >= 3 and
            (row['id'] in approved_outlines or len(row['body'] or '') >= 120)
            for row in courses
        )
        mapped = {
            row["course_id"] for row in c.execute(
                "SELECT DISTINCT course_id FROM course_dishes"
            ).fetchall()
        }
        qcount = sum(bool(quality_issues(course["questions"])) for course in courses)
        stale_reviewed=sum(1 for course in courses if course["reviewed_dish_signature"] and
                           reviewed_dish_signature(dish_chapters(c,course["id"],course["restaurant"]) or []) !=
                           course["reviewed_dish_signature"])
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
        "service_ready": service_ready,
        "wow": sum("WOW" in r["title"].upper() or "ВАУ" in r["title"].upper() for r in courses),
        "smile": sum("SMILE" in r["title"].upper() for r in courses),
        "mapped_menu": sum(r["id"] in mapped and
                           ("КУХНЯ" in r["title"].upper() or "МЕНЮ" in r["title"].upper())
                           for r in courses),
        "cases": cases,
        "cards": cards,
        "weak_quizzes": qcount,
        "stale_reviewed": stale_reviewed,
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
    print(f"Базовых проверяемых курсов сервиса: {snapshot['service_ready']}")
    print(f"Курсов: {snapshot['courses']} · карточек: {snapshot['cards']} · "
          f"кейсов: {snapshot['cases']} · активных аккаунтов: {snapshot['active_staff']}")
    print(f"Заявок на подтверждение: {snapshot['pending']} · "
          f"ошибок уведомлений: {snapshot['outbox_failed']} · "
          f"устаревших тестов по карточкам: {snapshot['stale_reviewed']}")
    for name, good in checks:
        print(("OK   " if good else "BLOCK") + " " + name)
    print("ОТДЕЛЬНО ПРОВЕРИТЬ ВРУЧНУЮ: живой ответ ИИ, HTTPS/права доступа, "
          "резервная копия вне Selectel и пробное восстановление, "
          "полный сценарий на iPhone, работу уведомлений.")
    if not all(good for _,good in checks):
        print("РЕЗУЛЬТАТ: НЕ ГОТОВО к пилоту на реальных сотрудниках.")
        raise SystemExit(1)
    print("Технические критерии содержимого пройдены. Нужна ручная приёмка на сервере и iPhone.")
