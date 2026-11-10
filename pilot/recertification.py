"""Waiter-only, frozen 30-question main-menu recertification."""
import random
import uuid
from fastapi import APIRouter, HTTPException, Request
from psycopg.types.json import Jsonb
from menu_assessments import menu_exam_questions
from questions import public_question, check, normalize
from recertification_ai import evaluate_attempt

SECTIONS = ('Роллы', 'Азия', 'Салаты', 'Закуски', 'Супы', 'Горячее', 'Гриль')
COUNT = 30
PASS_SCORE = 80


def waiter(user):
    if user['role'] != 'waiter':
        raise HTTPException(403, 'Переаттестация доступна только действующим официантам')


def choose_questions(cards, rng=None):
    rng = rng or random.SystemRandom()
    groups = {s: [] for s in SECTIONS}
    names = {normalize(s): s for s in SECTIONS}
    # The published menu uses 'Роллы и суши'; the exam labels it 'Роллы'.
    names[normalize('Роллы и суши')] = 'Роллы'
    seen = set()
    for card in cards:
        section = names.get(normalize(card['section']))
        if section and card['dish_id'] not in seen:
            groups[section].append(card)
            seen.add(card['dish_id'])
    if any(not items for items in groups.values()) or len(seen) < COUNT:
        raise HTTPException(409, 'Нужны минимум 30 утверждённых блюд и все 7 разделов основного меню')
    for items in groups.values():
        rng.shuffle(items)
    selected = []
    # Balanced coverage, filling from other sections if a small section runs out.
    while len(selected) < COUNT:
        order = list(SECTIONS)
        rng.shuffle(order)
        for section in order:
            if groups[section] and len(selected) < COUNT:
                selected.append(groups[section].pop())
    rng.shuffle(selected)
    questions = menu_exam_questions(selected, 'control', 0)
    for q, card in zip(questions, selected):
        q.update(section=card['section'], dish_id=card['dish_id'], lenient_recall=True)
    return questions


def make_router(db, require, manager, scope, audit):
    router = APIRouter(prefix='/api/recertification')

    def bank(c, user):
        """Published restaurant recipes form the recertification bank.

        A course's reviewed signature gates its own course exam, not this
        restaurant-wide waiter recertification. Keep unpublished, archived
        and incomplete recipes out of the question bank.
        """
        from quiz_cards import _ingredients

        rows = c.execute("""SELECT id,title,section,ingredients,source_name,source_page
            FROM dish_cards
            WHERE restaurant=%s AND published AND NOT archived
            ORDER BY id""", (user['restaurant'],)).fetchall()
        return [
            dict(kind='dish', dish_id=row['id'], title=row['title'],
                 section=row['section'], ingredients=row['ingredients'],
                 source=row['source_name'] or 'Карточка блюда',
                 source_page=row['source_page'])
            for row in rows
            if isinstance(row['ingredients'], list)
            and len(_ingredients({'ingredients': row['ingredients']})) >= 2
        ]

    def public(row):
        return dict(id=str(row['id']), pass_score=row['pass_score'],
                    questions=[dict(public_question(q), section=q['section']) for q in row['questions']],
                    answers=row['answers'], score=row['score'], passed=row['passed'],
                    submitted=row['submitted_at'] is not None, mode=row['mode'])

    def own(c, user, aid):
        row = c.execute('''SELECT * FROM recertification_attempts
            WHERE id=%s AND staff_id=%s AND restaurant=%s FOR UPDATE''',
            (aid, user['id'], user['restaurant'])).fetchone()
        if not row:
            raise HTTPException(404, 'Попытка не найдена')
        return row

    @router.post('/assign')
    async def assign(request: Request):
        d = await request.json()
        if not isinstance(d, dict) or type(d.get('staff_id')) is not int:
            raise HTTPException(422, 'Выбери сотрудника')
        with db() as c:
            u = require(c, request)
            manager(u)
            target = c.execute('SELECT * FROM staff WHERE id=%s FOR UPDATE', (d['staff_id'],)).fetchone()
            if not target: raise HTTPException(404, 'Сотрудник не найден')
            scope(u, target['restaurant'])
            if not target['active'] or target['role'] != 'waiter':
                raise HTTPException(422, 'Назначение доступно только активным официантам')
            choose_questions(bank(c, target))
            row = c.execute('''INSERT INTO recertification_assignments(staff_id,restaurant,assigned_by)
                VALUES(%s,%s,%s) ON CONFLICT(staff_id) DO UPDATE
                SET assigned_by=excluded.assigned_by,restaurant=excluded.restaurant,assigned_at=now(),completed_at=NULL
                WHERE recertification_assignments.completed_at IS NOT NULL RETURNING staff_id''',
                (target['id'], target['restaurant'], u['id'])).fetchone()
            audit(c, u['id'], 'recertification:assigned', target['id'])
            return {'assigned': True}

    @router.get('/assignment')
    def assignment(request: Request):
        with db() as c:
            u = require(c, request)
            waiter(u)
            return c.execute('SELECT assigned_at,completed_at FROM recertification_assignments WHERE staff_id=%s AND restaurant=%s',
                (u['id'], u['restaurant'])).fetchone()

    @router.get('/results')
    def results(request: Request):
        with db() as c:
            u = require(c, request)
            manager(u)
            return c.execute('''SELECT a.id,s.name,a.restaurant,a.created_at,a.submitted_at,
                a.score,a.passed FROM recertification_attempts a JOIN staff s ON s.id=a.staff_id
                WHERE a.mode='official' AND a.submitted_at IS NOT NULL AND (%s OR a.restaurant=%s) ORDER BY a.created_at DESC LIMIT 200''',
                (u['role'] == 'manager', u['restaurant'])).fetchall()

    @router.post('/start')
    async def start(request: Request):
        raw = await request.body()
        d = await request.json() if raw else {}
        if not isinstance(d, dict) or d.get('mode', 'practice') not in ('practice', 'official'):
            raise HTTPException(422, 'Выбери режим прохождения')
        mode = d.get('mode', 'practice')
        with db() as c:
            u = require(c, request)
            waiter(u)
            c.execute('SELECT id FROM staff WHERE id=%s FOR UPDATE', (u['id'],))
            if mode == 'official' and not c.execute(
                "SELECT 1 FROM recertification_attempts WHERE staff_id=%s AND restaurant=%s AND mode='practice' AND submitted_at IS NOT NULL",
                (u['id'], u['restaurant'])).fetchone():
                raise HTTPException(409, 'Сначала заверши пробное прохождение для себя')
            row = c.execute('''SELECT * FROM recertification_attempts
                WHERE staff_id=%s AND restaurant=%s AND mode=%s AND submitted_at IS NULL''',
                (u['id'], u['restaurant'], mode)).fetchone()
            if not row:
                questions = choose_questions(bank(c, u))
                row = c.execute('''INSERT INTO recertification_attempts
                    (id,staff_id,restaurant,questions,answers,pass_score,mode)
                    VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *''',
                    (uuid.uuid4(), u['id'], u['restaurant'], Jsonb(questions),
                     Jsonb([None] * COUNT), PASS_SCORE, mode)).fetchone()
                audit(c, u['id'], 'recertification:start', row['id'])
            return public(row)

    @router.post('/{aid}/answer')
    async def answer(aid: uuid.UUID, request: Request):
        d = await request.json()
        if (not isinstance(d, dict) or type(d.get('index')) is not int
                or not 0 <= d['index'] < 40 or not isinstance(d.get('answer'), str)
                or len(d['answer']) > 3000):
            raise HTTPException(422, 'Некорректный ответ')
        with db() as c:
            u = require(c, request)
            waiter(u)
            row = own(c, u, aid)
            if row['submitted_at']:
                raise HTTPException(409, 'Тест уже завершён')
            if d['index'] >= len(row['questions']):
                raise HTTPException(422, 'Некорректный номер вопроса')
            answers = row['answers']
            answers[d['index']] = d['answer']
            c.execute('UPDATE recertification_attempts SET answers=%s WHERE id=%s',
                      (Jsonb(answers), aid))
            return {'saved': True}

    @router.post('/{aid}/submit')
    def submit(aid: uuid.UUID, request: Request):
        with db() as c:
            u = require(c, request)
            waiter(u)
            row = own(c, u, aid)
            if not row['submitted_at']:
                if any(not isinstance(a, str) or not a.strip() for a in row['answers']):
                    raise HTTPException(422, f"Ответь на все {len(row['questions'])} вопросов")
                score, assessments = evaluate_attempt(row['questions'], row['answers'])
                frozen_questions = [dict(q, ai_assessment=assessment)
                                    for q, assessment in zip(row['questions'], assessments)]
                row = c.execute('''UPDATE recertification_attempts
                    SET score=%s,passed=%s,questions=%s,submitted_at=now() WHERE id=%s RETURNING *''',
                    (score, score >= row['pass_score'], Jsonb(frozen_questions), aid)).fetchone()
                if row['mode'] == 'official' and row['passed']:
                    c.execute('UPDATE recertification_assignments SET completed_at=now() WHERE staff_id=%s AND restaurant=%s AND completed_at IS NULL',
                              (u['id'], u['restaurant']))
                audit(c, u['id'], 'recertification:submit', aid)
            return dict(public(row), review=[dict(q, answer=a, assessment=q.get('ai_assessment') or check(dict(q, lenient_recall=True), a))
                for q, a in zip(row['questions'], row['answers'])])

    return router
