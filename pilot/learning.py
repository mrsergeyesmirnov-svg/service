"""Self-study of approved immutable materials, separate from mandatory exams."""
import hashlib
import os
import re
import uuid
from questions import public_question, check
from dish_lessons import dish_chapters, map_details, save_mapping
from course_pdf import course_chapters_from_pdf, MAX_PDF_BYTES
from dishes import limited_body
from quiz_cards import approved_card_questions
from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from cases_api import evaluate_with_yandex, PRIVATE_DATA
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


def validate_text_chapters(raw):
    if not isinstance(raw,list) or len(raw)>60:
        raise HTTPException(422,'В курсе допускается не больше 60 глав')
    result=[]
    total=0
    for item in raw:
        if not isinstance(item,dict):
            raise HTTPException(422,'Некорректная глава')
        title=item.get('title')
        body=item.get('body')
        source=item.get('source','')
        if (not isinstance(title,str) or not title.strip() or len(title)>180 or
            not isinstance(body,str) or not body.strip() or len(body)>6000 or
            not isinstance(source,str) or len(source)>500):
            raise HTTPException(422,'Проверь название, текст и источник главы')
        title,body,source=title.strip(),body.strip(),source.strip()
        total+=len(title)+len(body)+len(source)
        result.append(dict(title=title,body=body,source=source))
    if total>120_000: raise HTTPException(413,'Материал слишком большой')
    return result

def text_outline_chapters(raw):
    result=[]
    for item in raw:
        digest=hashlib.sha256(
            (item['title']+'\n'+item['body']+'\n'+item['source']).encode()
        ).hexdigest()[:20]
        result.append(dict(id='text-'+digest,kind='text',**item))
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
        row = c.execute('SELECT * FROM courses WHERE id=%s AND published AND NOT archived AND restaurant=%s',
                        (cid, u['restaurant'])).fetchone()
        if not row: raise HTTPException(404, 'Утверждённый курс не найден')
        return row

    def course_chapters(c, r):
        mapped = dish_chapters(c, r['id'], r['restaurant'])
        if mapped is not None: return mapped
        outline=c.execute('SELECT chapters FROM course_text_outline WHERE course_id=%s',
                          (r['id'],)).fetchone()
        if outline: return text_outline_chapters(outline['chapters'])
        return chapters(r['body'])

    def course_questions(c, r, parts=None):
        parts = parts if parts is not None else course_chapters(c, r)
        if parts and parts[0].get('kind') == 'dish':
            # Curated menu lessons use verified ingredients, never the legacy
            # "which component is explicitly listed" multiple choice bank.
            return approved_card_questions(parts, r['id'])
        return r['questions']

    def progress(c, uid, cid):
        row = c.execute('SELECT chapter_ids FROM learning_progress WHERE staff_id=%s AND course_id=%s', (uid, cid)).fetchone()
        return row['chapter_ids'] if row else []

    @router.post('/import-pdf')
    async def import_theory_pdf(request: Request):
        """PDF -> manager-owned unpublished service course + editable text chapters."""
        # Authenticate before reading an untrusted document into memory.
        with db() as c:
            u = require(c, request)
            manager(u)
        title = (request.query_params.get('title') or '').strip()
        filename = (request.query_params.get('filename') or 'Материал.pdf').split('/')[-1].split('\\')[-1]
        if not 3 <= len(title) <= 180 or not 1 <= len(filename) <= 160:
            raise HTTPException(422, 'Укажи название курса и корректное имя PDF')
        if not request.headers.get('content-type', '').startswith('application/pdf'):
            raise HTTPException(415, 'Выбери PDF-документ')
        raw = await limited_body(request, MAX_PDF_BYTES)
        try:
            outline = await run_in_threadpool(course_chapters_from_pdf, raw, filename)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(422, str(exc))
        outline = validate_text_chapters(outline)
        digest = hashlib.sha256(raw).hexdigest()[:16]
        source = f'PDF: {filename}; SHA256={digest}'
        description = ('Материал загружен из PDF. Учебный текст находится в главах. '
                       'Проверь все главы и добавь вопросы перед публикацией.')
        with db() as c:
            u = require(c, request)
            manager(u)
            c.execute('SELECT pg_advisory_xact_lock(823411)')
            duplicate = c.execute("""SELECT id FROM courses
                   WHERE restaurant=%s AND title=%s AND source=%s AND NOT archived LIMIT 1""",
                   (u['restaurant'], title, source)).fetchone()
            if duplicate:
                return {'id': duplicate['id'], 'chapters': len(outline),
                        'status': 'draft', 'duplicate': True}
            item = c.execute("""INSERT INTO courses
                  (author,restaurant,title,kind,body,source,questions,pass_score,published)
                  VALUES (%s,%s,%s,'service',%s,%s,%s,80,false) RETURNING id""",
                  (u['id'],u['restaurant'],title,description,source,Jsonb([]))).fetchone()
            cid = item['id']
            c.execute("INSERT INTO course_text_outline(course_id,chapters) VALUES(%s,%s)",
                      (cid,Jsonb(outline)))
            audit(c, u['id'], 'course:pdf-draft', cid)
        return {'id': cid, 'chapters': len(outline),
                'status': 'draft', 'duplicate': False}

    @router.get('')
    def catalog(request: Request):
        with db() as c:
            u = require(c, request)
            rows = c.execute('''SELECT c.*,p.chapter_ids,
                EXISTS(SELECT 1 FROM learning_attempts a WHERE a.course_id=c.id AND a.staff_id=%s AND a.passed) AS passed,
                (SELECT max(score) FROM learning_attempts a WHERE a.course_id=c.id AND a.staff_id=%s) AS best_score
                FROM courses c LEFT JOIN learning_progress p ON p.course_id=c.id AND p.staff_id=%s
                WHERE c.published AND NOT c.archived AND c.restaurant=%s ORDER BY c.id''', (u['id'], u['id'], u['id'], u['restaurant'])).fetchall()
            result = []
            for r in rows:
                parts = course_chapters(c, r)
                result.append(dict(
                    id=r['id'], title=r['title'], category=category(r['title']),
                    chapters=len(parts), read=len(set(r['chapter_ids'] or []) & {p['id'] for p in parts}),
                    passed=r['passed'], best_score=r['best_score'], questions=len(course_questions(c, r, parts)),
                    structured=bool(parts and parts[0].get('kind')=='dish')
                ))
            return result

    @router.get('/{cid}')
    def detail(cid: int, request: Request):
        with db() as c:
            u = require(c, request); r = course(c, u, cid)
            return dict(id=r['id'], title=r['title'], source=r['source'], pass_score=r['pass_score'],
                        chapters=course_chapters(c,r), read=progress(c, u['id'], cid),
                        questions=[public_question(q) for q in course_questions(c, r)],
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
            lesson_parts = course_chapters(c,r)
            questions = course_questions(c, r, lesson_parts)
            if not questions: raise HTTPException(409, 'Тест готовится: менеджер проверяет учебный материал')
            if not lesson_parts:
                raise HTTPException(409, 'Курс готовится: менеджер проверяет карточки')
            if not {p['id'] for p in lesson_parts} <= set(progress(c, u['id'], cid)):
                raise HTTPException(409, 'Сначала изучите все главы')
            score = grade(questions, d.get('answers'))
            row = c.execute('''INSERT INTO learning_attempts(staff_id,course_id,request_id,answers,questions,score,passed)
                VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(staff_id,course_id,request_id) DO NOTHING RETURNING *''',
                (u['id'], cid, rid, Jsonb(d['answers']), Jsonb(questions), score, score >= r['pass_score'])).fetchone()
            if row: audit(c, u['id'], 'learning:submit', row['id'])
            else: row = c.execute('SELECT * FROM learning_attempts WHERE staff_id=%s AND course_id=%s AND request_id=%s', (u['id'], cid, rid)).fetchone()
            return {'score': row['score'], 'passed': row['passed'], 'review': [dict(q, answer=a, assessment=check(q,a)) for q,a in zip(row['questions'] or questions, row['answers'])]}



    @router.get('/{cid}/text-chapters')
    def get_text_chapters(cid:int,request:Request):
        with db() as c:
            u=require(c,request);manager(u)
            row=c.execute('SELECT * FROM courses WHERE id=%s',(cid,)).fetchone()
            if not row:raise HTTPException(404,'Курс не найден')
            scope(u,row['restaurant'])
            saved=c.execute('SELECT chapters FROM course_text_outline WHERE course_id=%s',(cid,)).fetchone()
            return {'title':row['title'],'source':row['source'],
                    'chapters':saved['chapters'] if saved else []}

    @router.put('/{cid}/text-chapters')
    async def put_text_chapters(cid:int,request:Request):
        d=await request.json()
        if not isinstance(d,dict):raise HTTPException(422,'Неверный формат')
        items=validate_text_chapters(d.get('chapters'))
        with db() as c:
            u=require(c,request);manager(u)
            row=c.execute('SELECT * FROM courses WHERE id=%s FOR UPDATE',(cid,)).fetchone()
            if not row:raise HTTPException(404,'Курс не найден')
            scope(u,row['restaurant'])
            if items and c.execute('SELECT 1 FROM course_dishes WHERE course_id=%s LIMIT 1',(cid,)).fetchone():
                raise HTTPException(409,'Сначала убери привязанные карточки блюд из этого курса')
            if items:
                c.execute("""INSERT INTO course_text_outline(course_id,chapters)
                       VALUES(%s,%s) ON CONFLICT(course_id) DO UPDATE
                       SET chapters=EXCLUDED.chapters,updated_at=now()""",
                       (cid,Jsonb(items)))
            else:
                c.execute('DELETE FROM course_text_outline WHERE course_id=%s',(cid,))
            audit(c,u['id'],'learning:text-outline',cid)
        return {'ok':True,'chapters':len(items)}

    @router.get('/{cid}/dish-map')
    def get_dish_map(cid:int,request:Request):
        with db() as c:
            u=require(c,request);manager(u)
            r=c.execute('SELECT * FROM courses WHERE id=%s',(cid,)).fetchone()
            if not r:raise HTTPException(404,'Курс не найден')
            scope(u,r['restaurant'])
            return {'course_id':cid,'title':r['title'],'source':r['source'],'dish_ids':map_details(c,cid)}

    @router.put('/{cid}/dish-map')
    async def put_dish_map(cid:int,request:Request):
        d=await request.json()
        if not isinstance(d,dict): raise HTTPException(422,'Неверный формат')
        with db() as c:
            u=require(c,request);manager(u)
            r=c.execute('SELECT * FROM courses WHERE id=%s FOR UPDATE',(cid,)).fetchone()
            if not r:raise HTTPException(404,'Курс не найден')
            scope(u,r['restaurant'])
            if d.get('dish_ids') and c.execute('SELECT 1 FROM course_text_outline WHERE course_id=%s',(cid,)).fetchone():
                raise HTTPException(409,'Сначала убери текстовые главы этого курса')
            save_mapping(c,r,d.get('dish_ids'))
            audit(c,u['id'],'learning:dish-map',cid)
            return {'ok':True,'dish_ids':map_details(c,cid)}


    @router.post('/{cid}/dish-practice')
    async def practice_dish(cid:int,request:Request):
        """Optional private AI coaching; never sets pass_score or admission."""
        d=await request.json()
        if not isinstance(d,dict): raise HTTPException(422,'Неверный формат ответа')
        try:
            rid=uuid.UUID(d['request_id'])
        except (KeyError,TypeError,ValueError,AttributeError):
            raise HTTPException(422,'Некорректный номер запроса')
        did=d.get('dish_id')
        answer=d.get('answer','')
        if type(did)!=int or not isinstance(answer,str) or not 40<=len(answer)<=1600:
            raise HTTPException(422,'Опиши действия и слова гостю (40–1600 символов)')
        if PRIVATE_DATA.search(answer):
            raise HTTPException(422,'Не указывай телефон, электронную почту или данные реального гостя')
        with db() as c:
            u=require(c,request);course_row=course(c,u,cid)
            # Only currently published cards assigned to this exact course are eligible.
            dish=c.execute("""SELECT d.title,d.ingredients,d.description,d.source_name,d.source_page
                 FROM course_dishes m JOIN dish_cards d ON d.id=m.dish_id
                 WHERE m.course_id=%s AND d.id=%s AND d.restaurant=%s
                   AND d.published AND NOT d.archived""",(cid,did,u['restaurant'])).fetchone()
            if not dish: raise HTTPException(404,'Карточка не доступна для практики')
            if not os.getenv('YANDEX_API_KEY') or not os.getenv('YANDEX_FOLDER_ID'):
                raise HTTPException(503,'ИИ-тренер пока не подключён. Менеджер должен настроить Yandex AI Studio.')
            # Lock this user during reservation so parallel requests cannot exceed quota.
            c.execute('SELECT id FROM staff WHERE id=%s FOR UPDATE',(u['id'],))
            existing=c.execute("""SELECT status,feedback,answer,tries,
                         updated_at < now()-interval '75 seconds' AS stale
                  FROM dish_practice_attempts
                  WHERE staff_id=%s AND course_id=%s AND dish_id=%s AND request_id=%s""",
                 (u['id'],cid,did,rid)).fetchone()
            if existing and existing['status']=='done':
                return existing['feedback']
            if existing and existing['answer']!=answer:
                raise HTTPException(409,'Для изменённого текста начни новую попытку')
            if existing and existing['status']=='pending' and not existing['stale']:
                raise HTTPException(409,'Разбор ещё обрабатывается. Повтори через минуту.')
            if existing and existing['tries']>=2:
                raise HTTPException(429,'Этот разбор уже отправлялся дважды. Начни новую попытку позже.')
            used=c.execute("""SELECT count(*) AS n FROM dish_practice_attempts
                 WHERE staff_id=%s AND created_at>now()-interval '24 hours'""",(u['id'],)).fetchone()['n']
            if used>=5 and not existing:raise HTTPException(429,'Не больше пяти ИИ-разборов за 24 часа')
            if existing:
                c.execute("""UPDATE dish_practice_attempts SET status='pending',tries=tries+1,
                      updated_at=now() WHERE staff_id=%s AND course_id=%s
                      AND dish_id=%s AND request_id=%s""",(u['id'],cid,did,rid))
            else:
                c.execute("""INSERT INTO dish_practice_attempts(staff_id,course_id,dish_id,request_id,answer)
                    VALUES(%s,%s,%s,%s,%s)""",(u['id'],cid,did,rid,answer))
            staff_id=u['id']
        reference=(
            'Утверждённый состав: '+', '.join(dish['ingredients'])+
            '. Утверждённое описание и подача: '+dish['description']
        )[:2500]
        case={
            'competency':'Знание меню MOJO и проактивная забота о госте',
            'action':'Правдиво и понятно презентовать блюдо, уточнять ограничения гостя',
            'scenario':'Гость попросил кратко презентовать «'+dish['title']+'». ',
            'criteria':[
                'Сравни ответ ТОЛЬКО с утверждённым материалом: '+reference,
                'Проверь, что важные ингредиенты и особенности подачи переданы точно',
                'Не одобряй выдуманные ингредиенты, неподтверждённые замены и обещания безопасности при аллергии',
                'Дай короткий полезный комментарий, как лучше презентовать блюдо',
                'В next_step предложи пример следующей удачной презентации своими словами, без неподтверждённых фактов'
            ]
        }
        try:
            feedback=await run_in_threadpool(evaluate_with_yandex,case,answer)
        except Exception as exc:
            with db() as c:
                c.execute("""UPDATE dish_practice_attempts SET status='failed',updated_at=now()
                    WHERE staff_id=%s AND course_id=%s AND dish_id=%s AND request_id=%s
                    AND status='pending'""",(staff_id,cid,did,rid))
            if isinstance(exc,HTTPException): raise
            raise HTTPException(502,'Не удалось получить разбор ИИ, попробуй позже') from None
        with db() as c:
            saved=c.execute("""UPDATE dish_practice_attempts SET status='done',
                   feedback=%s,updated_at=now() WHERE staff_id=%s AND course_id=%s
                   AND dish_id=%s AND request_id=%s AND status='pending' RETURNING id""",
                   (Jsonb(feedback),staff_id,cid,did,rid)).fetchone()
            if saved:audit(c,staff_id,'learning:dish-practice',saved['id'])
        return feedback

    @router.get('/{cid}/dish-practice/{did}')
    def practice_history(cid:int,did:int,request:Request):
        with db() as c:
            u=require(c,request);course(c,u,cid)
            return c.execute("""SELECT id,answer,feedback,created_at
                  FROM dish_practice_attempts WHERE staff_id=%s AND course_id=%s
                  AND dish_id=%s AND status='done' ORDER BY id DESC LIMIT 5""",
                 (u['id'],cid,did)).fetchall()

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
