"""Source-verified intermediate and complete-section menu checks for MOJO.

No model calls, no auto-publishing. Existing legacy course and assignment
attempts remain untouched. Both stages are frozen to manager-approved recipes.
"""
import uuid
from fastapi import APIRouter, HTTPException, Request
from psycopg.types.json import Jsonb
from dish_lessons import dish_chapters, map_details, reviewed_dish_signature
from quiz_cards import approved_card_questions, _ingredients
from questions import public_question, grade_questions, check

STAGES = ("intermediate", "control")


def menu_exam_questions(chapters, stage, course_id):
    if stage not in STAGES:
        raise HTTPException(422, "Неизвестный этап проверки")
    # A single unclear composition must block this section exam rather than
    # quietly disappear from the final open-answer test.
    if not chapters or any(
        p.get("kind") != "dish" or len(_ingredients(p)) < 2
        for p in chapters
    ):
        raise HTTPException(409, "У всех блюд должен быть проверенный состав минимум из двух компонентов")
    if stage == "intermediate":
        n = len(chapters)
        take = min(n, 6)
        indices = ([0] if take == 1 else
                   [round(i * (n - 1) / (take - 1)) for i in range(take)])
        return approved_card_questions([chapters[i] for i in indices], course_id)
    return [
        {
            "type": "ingredients",
            "question": f"Перечисли полный состав «{part['title']}» без подсказок.",
            "ingredients": [[name] for name in _ingredients(part)],
            "options": [],
            "allowed_extra": [],
            "explanation": "Сверь перечисление с утверждённой карточкой блюда.",
            "source": part["source"] + (
                f", стр. {part['source_page']}" if part.get("source_page") else ""
            )
        }
        for part in chapters
    ]


def make_router(db, require, manager, scope, audit):
    router = APIRouter(prefix="/api/menu-assessments")

    def setup(c, user, cid):
        row = c.execute("""SELECT id,restaurant,published,archived,pass_score,
                         reviewed_dish_signature FROM courses WHERE id=%s""", (cid,)).fetchone()
        if (not row or row["archived"] or not row["published"] or
                row["restaurant"] != user["restaurant"]):
            raise HTTPException(404, "Опубликованный раздел меню не найден")
        mapped = map_details(c, cid)
        if not mapped or not row["reviewed_dish_signature"]:
            raise HTTPException(409, "Менеджер ещё не утвердил составы и курс")
        chapters = dish_chapters(c, cid, row["restaurant"])
        if (len(chapters or []) != len(mapped) or
                reviewed_dish_signature(chapters) != row["reviewed_dish_signature"]):
            raise HTTPException(409, "Составы изменились: нужна повторная проверка менеджером")
        return row, chapters

    def state(c, uid, cid, row, chapters):
        saved = c.execute(
            "SELECT chapter_ids FROM learning_progress WHERE staff_id=%s AND course_id=%s",
            (uid, cid)).fetchone()
        read = bool(saved and {p["id"] for p in chapters} <= set(saved["chapter_ids"]))
        result = c.execute("""SELECT stage,score FROM menu_assessment_attempts
            WHERE staff_id=%s AND course_id=%s AND signature=%s AND passed
            ORDER BY id""", (uid, cid, row["reviewed_dish_signature"])).fetchall()
        passed = {item["stage"] for item in result}
        next_stage = (None if not read else
                      "intermediate" if "intermediate" not in passed else
                      "control" if "control" not in passed else None)
        return read, passed, next_stage

    @router.get("/{cid}")
    def status(cid: int, request: Request):
        with db() as c:
            u = require(c, request)
            row, chapters = setup(c, u, cid)
            read, passed, stage = state(c, u["id"], cid, row, chapters)
            # Assert validity for *all* dishes, including those beyond the first six.
            menu_exam_questions(chapters, "control", cid)
            qs = menu_exam_questions(chapters, stage, cid) if stage else []
            return {
                "course_id": cid,
                "title": chapters[0]["section"] if chapters else "",
                "chapters": len(chapters),
                "all_read": read,
                "intermediate_passed": "intermediate" in passed,
                "control_passed": "control" in passed,
                "next_stage": stage,
                "questions": [public_question(q) for q in qs],
                "pass_score": row["pass_score"]
            }

    @router.post("/{cid}/{stage}/submit")
    async def submit(cid: int, stage: str, request: Request):
        if stage not in STAGES:
            raise HTTPException(404, "Этап не найден")
        d = await request.json()
        if not isinstance(d, dict):
            raise HTTPException(422, "Некорректный ответ")
        try:
            rid = uuid.UUID(d["request_id"])
        except (TypeError, KeyError, ValueError, AttributeError):
            raise HTTPException(422, "Некорректный номер попытки")
        with db() as c:
            u = require(c, request)
            row, chapters = setup(c, u, cid)
            # Only one grading transaction for this student at a time.
            c.execute("SELECT id FROM staff WHERE id=%s FOR UPDATE", (u["id"],))
            old = c.execute("""SELECT * FROM menu_assessment_attempts
                WHERE staff_id=%s AND course_id=%s AND stage=%s AND request_id=%s""",
                (u["id"], cid, stage, rid)).fetchone()
            if old:
                return result_from_attempt(old)
            read, passed, next_stage = state(c, u["id"], cid, row, chapters)
            if not read:
                raise HTTPException(409, "Сначала изучи все карточки раздела")
            if stage in passed:
                raise HTTPException(409, "Этап уже сдан. Повторение доступно в учебных карточках.")
            if next_stage != stage:
                raise HTTPException(409, "Сначала пройди промежуточный тест")
            questions = menu_exam_questions(chapters, stage, cid)
            answers = d.get("answers")
            score = grade_questions(questions, answers)
            passed_now = score >= row["pass_score"]
            attempt = c.execute("""INSERT INTO menu_assessment_attempts
                  (staff_id,course_id,stage,request_id,signature,questions,answers,score,passed)
                  VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""", (
                u["id"], cid, stage, rid, row["reviewed_dish_signature"],
                Jsonb(questions), Jsonb(answers), score, passed_now
            )).fetchone()
            audit(c, u["id"], "menu:assessment:"+stage, attempt["id"])
            return result_from_attempt(attempt)

    def result_from_attempt(row):
        return {
            "score": row["score"], "passed": row["passed"], "stage": row["stage"],
            "review": [
                dict(q, answer=a, assessment=check(q, a))
                for q, a in zip(row["questions"], row["answers"])
            ],
        }

    return router
