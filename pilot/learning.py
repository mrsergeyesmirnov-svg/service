"""Self-study of approved immutable materials, separate from mandatory exams."""
import hashlib
import re
import uuid
from questions import public_question, check
from dish_lessons import dish_chapters, map_details, save_mapping
from fastapi import APIRouter, HTTPException, Request
from psycopg.types.json import Jsonb


def chapters(body):
    """Preserve source text verbatim; use existing numbered headings, never infer facts."""
    blocks = re.split(r'\n(?=\d+[.)]\s|=== |ПРАКТИКА:|ИСТОЧНИК:)' , body.strip())
    result = []
    for block in blocks:
        # Long legacy documents remain readable in bounded pieces without dropping text.
        while block:
            end = len(block) if len(block) <= 2200 else max(block.rfind('\n', 0, 2200), block.rfind(' ', 0, 2200), 1)
            part, block = block[:end].strip(), block[end:].strip()
            if not part:
                continue
            title = re.split(r'\n|(?<=\.)\s', part, maxsplit=1)[0]
            result.append({'id': hashlib.sha256(part.encode()).hexdigest()[:20],
                           'title': title[:110], 'body': part})
    return result


def category(title):
    title = title.lower()
    if 'коф' in title: return 'coffee'
    if any(w in title for w in ('бар', 'коктейл', 'напит', 'чай')): return 'bar'
    if any(w in title for w in ('сервис', 'обслуж', 'стандарт')): return 'service'
    return 'menu'


def make_learning_router(db, require, manager, scope, grade, audit):
    router = APIRouter(prefix='/api/learning')

    def course(c, u, cid):
        row = c.execute('SELECT * FROM courses WHERE id=%s AND published AND restaurant=%s',
                        (cid, u['restaurant'])).fetchone()
        if not row: raise HTTPException(404, 'Утверждённый курс не найден')
        return row

    def course_chapters(c, r):
        mapped = dish_chapters(c, r['id'], r['restaurant'])
        return chapters(r['body']) if mapped is None else mapped

    def progress(c, uid, cid):
        row = c.execute('SELECT chapter_ids FROM learning_progress WHERE staff_id=%s AND course_id=%s', (uid, cid)).fetchone()
        return row['chapter_ids'] if row else []

    @router.get('')
    def catalog(request: Request):
        with db() as c:
            u = require(c, request)
            rows = c.execute('''SELECT c.*,p.chapter_ids,
                EXISTS(SELECT 1 FROM learning_attempts a WHERE a.course_id=c.id AND a.staff_id=%s AND a.passed) AS passed,
                (SELECT max(score) FROM learning_attempts a WHERE a.course_id=c.id AND a.staff_id=%s) AS best_score
                FROM courses c LEFT JOIN learning_progress p ON p.course_id=c.id AND p.staff_id=%s
                WHERE c.published AND c.restaurant=%s ORDER BY c.id''', (u['id'], u['id'], u['id'], u['restaurant'])).fetchall()
            result = []
            for r in rows:
                parts = course_chapters(c, r)
                result.append(dict(
                    id=r['id'], title=r['title'], category=category(r['title']),
                    chapters=len(parts), read=len(set(r['chapter_ids'] or []) & {p['id'] for p in parts}),
                    passed=r['passed'], best_score=r['best_score'], questions=len(r['questions']),
                    structured=bool(parts and parts[0].get('kind')=='dish')
                ))
            return result

    @router.get('/{cid}')
    def detail(cid: int, request: Request):
        with db() as c:
            u = require(c, request); r = course(c, u, cid)
            return dict(id=r['id'], title=r['title'], source=r['source'], pass_score=r['pass_score'],
                        chapters=course_chapters(c,r), read=progress(c, u['id'], cid),
                        questions=[public_question(q) for q in r['questions']],
                        history=c.execute('SELECT id,score,passed,created_at FROM learning_attempts WHERE staff_id=%s AND course_id=%s ORDER BY id DESC', (u['id'], cid)).fetchall())

    @router.post('/{cid}/read')
    async def mark_read(cid: int, request: Request):
        d = await request.json()
        with db() as c:
            u = require(c, request); r = course(c, u, cid)
            chapter = d.get('chapter_id')
            if chapter not in {p['id'] for p in course_chapters(c,r)}: raise HTTPException(422, 'Глава не найдена')
            c.execute('INSERT INTO learning_progress(staff_id,course_id) VALUES(%s,%s) ON CONFLICT DO NOTHING', (u['id'], cid))
            row = c.execute('SELECT chapter_ids FROM learning_progress WHERE staff_id=%s AND course_id=%s FOR UPDATE', (u['id'], cid)).fetchone()
            ids = list(dict.fromkeys(row['chapter_ids'] + [chapter]))
            c.execute('UPDATE learning_progress SET chapter_ids=%s,updated_at=now() WHERE staff_id=%s AND course_id=%s', (Jsonb(ids), u['id'], cid))
            return {'read': ids}

    @router.post('/{cid}/submit')
    async def submit(cid: int, request: Request):
        d = await request.json()
        try: rid = uuid.UUID(d['request_id'])
        except (KeyError, ValueError, TypeError, AttributeError): raise HTTPException(422, 'Некорректный номер попытки')
        with db() as c:
            u = require(c, request); r = course(c, u, cid)
            if not r['questions']: raise HTTPException(422, 'У этого материала нет теста')
            lesson_parts = course_chapters(c,r)
            if not lesson_parts:
                raise HTTPException(409, 'Курс готовится: менеджер проверяет карточки')
            if not {p['id'] for p in lesson_parts} <= set(progress(c, u['id'], cid)):
                raise HTTPException(409, 'Сначала изучите все главы')
            score = grade(r['questions'], d.get('answers'))
            row = c.execute('''INSERT INTO learning_attempts(staff_id,course_id,request_id,answers,score,passed)
                VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(staff_id,course_id,request_id) DO NOTHING RETURNING *''',
                (u['id'], cid, rid, Jsonb(d['answers']), score, score >= r['pass_score'])).fetchone()
            if row: audit(c, u['id'], 'learning:submit', row['id'])
            else: row = c.execute('SELECT * FROM learning_attempts WHERE staff_id=%s AND course_id=%s AND request_id=%s', (u['id'], cid, rid)).fetchone()
            return {'score': row['score'], 'passed': row['passed'], 'review': [dict(q, answer=a, assessment=check(q,a)) for q,a in zip(r['questions'], row['answers'])]}


    @router.get('/{cid}/dish-map')
    def get_dish_map(cid:int,request:Request):
        with db() as c:
            u=require(c,request);manager(u)
            r=c.execute('SELECT * FROM courses WHERE id=%s',(cid,)).fetchone()
            if not r:raise HTTPException(404,'Курс не найден')
            scope(u,r['restaurant'])
            return {'course_id':cid,'title':r['title'],'dish_ids':map_details(c,cid)}

    @router.put('/{cid}/dish-map')
    async def put_dish_map(cid:int,request:Request):
        d=await request.json()
        if not isinstance(d,dict): raise HTTPException(422,'Неверный формат')
        with db() as c:
            u=require(c,request);manager(u)
            r=c.execute('SELECT * FROM courses WHERE id=%s FOR UPDATE',(cid,)).fetchone()
            if not r:raise HTTPException(404,'Курс не найден')
            scope(u,r['restaurant'])
            save_mapping(c,r,d.get('dish_ids'))
            audit(c,u['id'],'learning:dish-map',cid)
            return {'ok':True,'dish_ids':map_details(c,cid)}

    @router.get('/{cid}/results')
    def results(cid: int, request: Request):
        with db() as c:
            u = require(c, request); manager(u)
            r = c.execute('SELECT restaurant FROM courses WHERE id=%s', (cid,)).fetchone()
            if not r: raise HTTPException(404)
            scope(u, r['restaurant'])
            return c.execute('''SELECT a.id,s.name,a.score,a.passed,a.created_at FROM learning_attempts a
                JOIN staff s ON s.id=a.staff_id WHERE a.course_id=%s AND (%s OR s.restaurant=%s)
                ORDER BY a.id DESC LIMIT 200''', (cid, u['role']=='manager', u['restaurant'])).fetchall()

    return router
