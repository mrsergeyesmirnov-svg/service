"""Small invitation-only Academy pilot. Published courses are immutable versions."""
import hashlib, hmac, json, os, secrets, time, uuid
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse
from cases_api import make_router
from learning import make_learning_router
from dish_lessons import dish_chapters, map_details, reviewed_dish_signature
from dishes import attach as attach_dishes
from voice import make_voice_router
from events import make_events_router
from wine_cards import make_router as make_wine_cards_router
from menu_cards import make_router as make_menu_cards_router
from questions import clean_question, public_question, grade_questions
from question_quality import quality_issues

TOKEN = os.getenv('BOT_TOKEN', '')
OWNER = int(os.getenv('OWNER_TELEGRAM_ID', '0') or '0')
URL = os.getenv('PUBLIC_URL', 'https://service.139.100.239.232.sslip.io/pilot/')
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
BASE = Path(__file__).parent

def db():
    return psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row)

def audit(c, actor, action, target):
    c.execute('INSERT INTO audit(actor,action,target) VALUES(%s,%s,%s)', (actor,action,str(target)))

def validate_init(raw, token, now=None):
    pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    d = dict(pairs)
    if len(d) != len(pairs): raise ValueError('duplicate fields')
    signature = d.pop('hash', '')
    secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    check = '\n'.join(f'{k}={v}' for k,v in sorted(d.items()))
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    age = (now if now is not None else time.time()) - int(d['auth_date'])
    if not token or not hmac.compare_digest(signature, expected) or age < -30 or age > 3600:
        raise ValueError('expired or invalid Telegram data')
    u = json.loads(d['user'])
    if type(u.get('id')) is not int or u['id'] <= 0: raise ValueError('invalid user')
    return u

def require(c, request):
    token = request.headers.get('authorization', '').removeprefix('Bearer ')
    u = c.execute('SELECT s.* FROM sessions t JOIN staff s ON s.id=t.staff_id WHERE t.token_hash=%s AND t.expires_at>now() AND s.active', (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    if not u: raise HTTPException(401, 'Откройте приложение заново из Telegram')
    return u

def manager(u):
    if u['role'] not in ('manager','local'): raise HTTPException(403, 'Доступ только руководителю')

def scope(u, restaurant):
    if u['role'] != 'manager' and u['restaurant'] != restaurant: raise HTTPException(403, 'Другая точка')

def text(d, key, limit=200):
    v = d.get(key)
    if not isinstance(v,str) or not v.strip() or len(v)>limit: raise HTTPException(422, f'Проверьте поле {key}')
    return v.strip()

def course_data(d):
    title=text(d,'title'); body=text(d,'body',100000); source=text(d,'source',2000)
    kind=d.get('kind','service')
    if kind not in ('service','ttk','notice'): raise HTTPException(422,'Неизвестный тип')
    qs=d.get('questions',[])
    if not isinstance(qs,list) or len(qs)>100: raise HTTPException(422,'Допустимо до 100 вопросов в черновике')
    clean=[]
    for q in qs:
        if not isinstance(q,dict): raise HTTPException(422,'Некорректный вопрос')
        clean.append(clean_question(q,text))
    score=d.get('pass_score',80)
    if type(score)!=int or not 1<=score<=100: raise HTTPException(422,'Порог от 1 до 100')
    return title,kind,body,source,clean,score

def ensure_dish_quiz_current(c, course_id, restaurant, signature):
    """Never assign or grade questions against a changed reviewed recipe."""
    if signature is not None:
        chapters=dish_chapters(c,course_id,restaurant)
        if reviewed_dish_signature(chapters or [])!=signature:
            raise HTTPException(409,'Рецептура изменилась после утверждения теста. Менеджер должен создать новую версию курса.')


def grade(qs, answers):
    return grade_questions(qs, answers)

@app.middleware('http')
async def limits(request, call_next):
    upload = request.url.path == '/api/dishes/import' or (request.url.path.startswith('/api/dishes/') and request.url.path.endswith('/photo'))
    limit = 20_000_000 if upload or request.url.path == '/api/learning/import-pdf' else (2_500_000 if request.url.path == '/api/voice/transcribe' else 300_000)
    try: content_len = int(request.headers.get('content-length') or '0')
    except ValueError: content_len = limit+1
    if content_len>limit: return __import__('fastapi').responses.JSONResponse({'detail':'Слишком большой запрос'},status_code=413)
    response=await call_next(request)
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    return response

app.include_router(make_router(lambda: db(), require, manager, scope, audit))
app.include_router(make_learning_router(lambda: db(), require, manager, scope, grade, audit))
app.include_router(make_wine_cards_router(lambda: db(), require, manager, scope, audit))
app.include_router(make_menu_cards_router(lambda: db(), require, manager, scope, audit))
app.include_router(attach_dishes(lambda: db(), require, manager, scope, audit))
app.include_router(make_voice_router(lambda: db(), require))
app.include_router(make_events_router(lambda: db(), require, manager, scope, audit))

@app.get('/api/health')
def health():
    with db() as c: c.execute('SELECT 1')
    return {'database':True,'telegram_configured':bool(TOKEN and OWNER)}

@app.post('/api/login')
async def login(request:Request):
    if not TOKEN or not OWNER: raise HTTPException(503,'Пилот готовится: ещё не настроен Telegram-бот')
    d=await request.json()
    try: u=validate_init(d.get('initData',''),TOKEN)
    except (ValueError,KeyError,TypeError): raise HTTPException(401,'Войдите через Telegram')
    with db() as c:
        member=c.execute('SELECT * FROM staff WHERE id=%s AND active',(u['id'],)).fetchone()
        if not member:
            pending=c.execute('SELECT id FROM staff WHERE id=%s AND NOT active',(u['id'],)).fetchone()
            if pending:raise HTTPException(403,'Заявка ожидает одобрения руководителя MOJO')
            raise HTTPException(403,'Сначала откройте приглашение руководителя и нажмите «Старт» в боте')
        session=secrets.token_urlsafe(32)
        c.execute('DELETE FROM sessions WHERE expires_at<now()')
        c.execute("INSERT INTO sessions VALUES(%s,%s,now()+interval '8 hours')",(hashlib.sha256(session.encode()).hexdigest(),u['id']))
    return {'token':session,'user':member}

@app.get('/api/me')
def me(request:Request):
    with db() as c: return require(c,request)

@app.get('/api/team')
def team(request:Request):
    with db() as c:
        u=require(c,request);manager(u)
        return c.execute('SELECT id,name,role,restaurant,phone,active,bot_started FROM staff WHERE (%s OR restaurant=%s) ORDER BY name',(u['role']=='manager',u['restaurant'])).fetchall()

@app.post('/api/team/{staff_id}/role')
async def set_role(staff_id:int,request:Request):
    d=await request.json()
    if d.get('role') not in ('trainee','waiter'): raise HTTPException(422,'Допустимы стажёр и официант')
    with db() as c:
        u=require(c,request);manager(u)
        target=c.execute('SELECT * FROM staff WHERE id=%s FOR UPDATE',(staff_id,)).fetchone()
        if not target: raise HTTPException(404)
        scope(u,target['restaurant'])
        if target['role'] in ('manager','local'): raise HTTPException(403,'Права руководителя меняет администратор')
        c.execute('UPDATE staff SET role=%s WHERE id=%s',(d['role'],staff_id));audit(c,u['id'],'role:'+d['role'],staff_id)
    return {'ok':True}

@app.post('/api/team/{staff_id}/approve')
def approve_member(staff_id:int, request:Request):
    """A forwarded invite can create a pending record, not an active account."""
    with db() as c:
        u=require(c,request);manager(u)
        target=c.execute('SELECT * FROM staff WHERE id=%s FOR UPDATE',(staff_id,)).fetchone()
        if not target:raise HTTPException(404,'Заявка не найдена')
        scope(u,target['restaurant'])
        if target['role'] not in ('trainee','waiter'):
            raise HTTPException(403,'Нельзя подтверждать руководителей через приглашение')
        if not c.execute('SELECT 1 FROM invites WHERE used_by=%s LIMIT 1',(staff_id,)).fetchone():
            raise HTTPException(409,'Учётная запись создана не через приглашение')
        if target['active']:return {'active':True,'already_approved':True}
        c.execute('UPDATE staff SET active=true WHERE id=%s',(staff_id,))
        c.execute('''INSERT INTO outbox(recipient,message,dedupe)
              VALUES(%s,%s,%s) ON CONFLICT(dedupe) DO NOTHING''',
              (staff_id,'Доступ к Академии MOJO подтверждён. Теперь можно открыть обучение в Telegram.',f'approval:{staff_id}'))
        audit(c,u['id'],'staff:approved',staff_id)
        return {'active':True,'already_approved':False}

@app.post('/api/invites')
async def invite(request:Request):
    d=await request.json()
    with db() as c:
        u=require(c,request);manager(u)
        role=d.get('role','trainee')
        if role not in ('trainee','waiter'): raise HTTPException(422,'Неверная роль')
        token=secrets.token_urlsafe(24)
        c.execute("INSERT INTO invites(token,role,restaurant,created_by,expires_at) VALUES(%s,%s,%s,%s,now()+interval '7 days')",(token,role,u['restaurant'],u['id']))
        audit(c,u['id'],'invite',hashlib.sha256(token.encode()).hexdigest()[:12])
    return {'url':f'https://t.me/skill_mojo_bot?start={token}','expires_days':7,'single_use':True,'manager_approval_required':True}

@app.get('/api/courses')
def courses(request:Request):
    with db() as c:
        u=require(c,request);manager(u)
        rows=c.execute('SELECT * FROM courses WHERE (%s OR restaurant=%s) ORDER BY archived ASC,id DESC',(u['role']=='manager',u['restaurant'])).fetchall()
        for row in rows:
            row['quality_issues']=quality_issues(row['questions'])
            row['recipe_changed']=bool(row['reviewed_dish_signature'] and
                 reviewed_dish_signature(dish_chapters(c,row['id'],row['restaurant']) or []) != row['reviewed_dish_signature'])
        return rows

@app.post('/api/courses')
async def create_course(request:Request):
    d=await request.json(); title,kind,body,source,qs,score=course_data(d)
    with db() as c:
        u=require(c,request);manager(u)
        row=c.execute('INSERT INTO courses(author,restaurant,title,kind,body,source,questions,pass_score) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id',(u['id'],u['restaurant'],title,kind,body,source,Jsonb(qs),score)).fetchone()
        audit(c,u['id'],'course:create',row['id'])
    return row

@app.post('/api/courses/import')
async def import_course_drafts(request:Request):
    """Manager-only JSON bundle import. Files stay on the academy server, not GitHub."""
    d=await request.json()
    if not isinstance(d,list) or not 1<=len(d)<=20:
        raise HTTPException(422,'Выберите JSON-файл с 1–20 курсами')
    validated=[course_data(item) for item in d]
    with db() as c:
        u=require(c,request);manager(u)
        c.execute('SELECT pg_advisory_xact_lock(823410)')
        created=[];skipped=0
        for title,kind,body,source,qs,score in validated:
            already=c.execute('''SELECT id FROM courses WHERE restaurant=%s AND title=%s AND kind=%s
                        AND body=%s AND source=%s AND questions=%s AND pass_score=%s
                        LIMIT 1''',(u['restaurant'],title,kind,body,source,Jsonb(qs),score)).fetchone()
            if already:
                skipped+=1
                continue
            row=c.execute('''INSERT INTO courses(author,restaurant,title,kind,body,source,questions,pass_score)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
                        (u['id'],u['restaurant'],title,kind,body,source,Jsonb(qs),score)).fetchone()
            created.append(row['id'])
            audit(c,u['id'],'course:import-draft',row['id'])
    return {'created':created,'skipped':skipped,'status':'draft'}


@app.put('/api/courses/{cid}')
async def edit_course(cid:int,request:Request):
    d=await request.json(); title,kind,body,source,qs,score=course_data(d)
    with db() as c:
        u=require(c,request);manager(u)
        row=c.execute('SELECT * FROM courses WHERE id=%s FOR UPDATE',(cid,)).fetchone()
        if not row: raise HTTPException(404)
        scope(u,row['restaurant'])
        if row['archived']: raise HTTPException(409,'Архивная версия неизменна. Создайте копию курса')
        if row['published']: raise HTTPException(409,'Опубликованная версия неизменна. Создайте копию курса')
        c.execute('UPDATE courses SET title=%s,kind=%s,body=%s,source=%s,questions=%s,pass_score=%s WHERE id=%s',(title,kind,body,source,Jsonb(qs),score,cid));audit(c,u['id'],'course:edit',cid)
    return {'ok':True}

@app.post('/api/courses/{cid}/publish')
async def publish(cid:int,request:Request):
    d=await request.json()
    if d.get('reviewed') is not True: raise HTTPException(422,'Подтвердите проверку материала и ответов')
    with db() as c:
        u=require(c,request);manager(u)
        row=c.execute('SELECT * FROM courses WHERE id=%s FOR UPDATE',(cid,)).fetchone()
        if not row: raise HTTPException(404)
        scope(u,row['restaurant'])
        if row['archived']: raise HTTPException(409,'Нельзя опубликовать архивную версию. Создайте копию.')
        if row['kind'] != 'notice' and not row['questions']:
            raise HTTPException(409,'Сначала добавь и проверь вопросы теста. Для курса только на чтение выбери тип «Ознакомление».')
        dish_ids=map_details(c,cid)
        signature=row['reviewed_dish_signature']
        if dish_ids and not row['published']:
            chapters=dish_chapters(c,cid,row['restaurant'])
            if len(chapters)!=len(dish_ids):
                raise HTTPException(409,'Карточки изменились или сняты с публикации. Проверь курс перед выпуском.')
            current=reviewed_dish_signature(chapters)
            if signature and signature!=current:
                raise HTTPException(409,'Рецептуры изменились после создания тестов. Подготовь новую версию вопросов.')
            signature=current
        elif signature and not dish_ids:
            raise HTTPException(409,'Утверждённые карточки были удалены из курса. Проверь содержание.')
        c.execute('UPDATE courses SET published=true,reviewed_dish_signature=%s WHERE id=%s',(signature,cid))
        audit(c,u['id'],'course:approved',cid)
    return {'ok':True}

@app.post('/api/courses/{cid}/archive')
def archive_course(cid:int,request:Request):
    """Retire an old published course and its quiz; keep all existing history."""
    with db() as c:
        u=require(c,request);manager(u)
        row=c.execute('SELECT id,title,restaurant,archived FROM courses WHERE id=%s FOR UPDATE',(cid,)).fetchone()
        if not row:raise HTTPException(404,'Материал не найден')
        scope(u,row['restaurant'])
        if row['archived']:return {'archived':True,'assignments_affected':0}
        count=c.execute('SELECT count(*) AS n FROM assignments WHERE course_id=%s',(cid,)).fetchone()['n']
        c.execute('UPDATE courses SET archived=true,published=false WHERE id=%s',(cid,))
        audit(c,u['id'],'course:archive',cid)
        return {'archived':True,'assignments_affected':count,'results_preserved':True}


@app.post('/api/assignments')
async def assign(request:Request):
    d=await request.json()
    try: deadline=date.fromisoformat(d['deadline'])
    except (ValueError,KeyError,TypeError): raise HTTPException(422,'Укажите дату')
    if deadline<date.today(): raise HTTPException(422,'Дата уже прошла')
    attempts=d.get('max_attempts',3); ids=d.get('staff_ids',[])
    if type(attempts)!=int or not 1<=attempts<=20 or not isinstance(ids,list) or not 1<=len(ids)<=20 or any(type(x)!=int for x in ids): raise HTTPException(422,'Проверьте участников и число попыток')
    with db() as c:
        u=require(c,request);manager(u)
        course=c.execute('SELECT * FROM courses WHERE id=%s AND published AND NOT archived',(d.get('course_id'),)).fetchone()
        if not course: raise HTTPException(422,'Сначала опубликуйте курс')
        scope(u,course['restaurant'])
        ensure_dish_quiz_current(c,course['id'],course['restaurant'],course['reviewed_dish_signature'])
        result=[]
        for sid in set(ids):
            person=c.execute('SELECT * FROM staff WHERE id=%s AND active',(sid,)).fetchone()
            if not person: raise HTTPException(422,'Сотрудник не найден')
            scope(u,person['restaurant'])
            row=c.execute('INSERT INTO assignments(staff_id,course_id,assigned_by,deadline,max_attempts) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(staff_id,course_id) DO NOTHING RETURNING id',(sid,course['id'],u['id'],deadline,attempts)).fetchone()
            if row:
                aid=row['id'];result.append(aid)
                msg=f'Новый обязательный урок: {course["title"]}\nСрок: {deadline.strftime("%d.%m.%Y")}\n'+('Ознакомьтесь с материалом и пройдите тест.' if course['questions'] else 'Ознакомьтесь с материалом и подтвердите прочтение.')
                c.execute('INSERT INTO outbox(recipient,message,assignment_id,dedupe) VALUES(%s,%s,%s,%s)',(sid,msg,aid,f'assignment:{aid}'))
                audit(c,u['id'],'assignment:create',aid)
    return {'created':result}

@app.get('/api/assignments')
def assignments(request:Request):
    with db() as c:
        u=require(c,request)
        return c.execute('''SELECT a.*,s.name,c.title,c.kind,c.pass_score,c.archived,jsonb_array_length(c.questions) AS questions,
        (SELECT count(*) FROM attempts t WHERE t.assignment_id=a.id) AS attempts,
        (SELECT max(score) FROM attempts t WHERE t.assignment_id=a.id) AS best_score,
        EXISTS(SELECT 1 FROM attempts t WHERE t.assignment_id=a.id AND passed) AS passed,
        (SELECT state FROM outbox o WHERE o.assignment_id=a.id ORDER BY id LIMIT 1) AS notification
        FROM assignments a JOIN courses c ON c.id=a.course_id JOIN staff s ON s.id=a.staff_id
        WHERE (a.staff_id=%s OR (%s AND (%s OR s.restaurant=%s))) AND (NOT c.archived OR %s) ORDER BY a.deadline,a.id''',(u['id'],u['role'] in ('manager','local'),u['role']=='manager',u['restaurant'],u['role'] in ('manager','local'))).fetchall()

@app.get('/api/assignments/{aid}')
def assignment(aid:int,request:Request):
    with db() as c:
        u=require(c,request)
        row=c.execute('SELECT a.*,c.title,c.body,c.source,c.questions,c.pass_score,c.archived,c.restaurant,c.reviewed_dish_signature FROM assignments a JOIN courses c ON a.course_id=c.id WHERE a.id=%s AND a.staff_id=%s',(aid,u['id'])).fetchone()
        if not row: raise HTTPException(404)
        if row['archived']: raise HTTPException(410,'Это задание архивировано руководителем')
        ensure_dish_quiz_current(c,row['course_id'],row['restaurant'],row['reviewed_dish_signature'])
        questions=row['questions']
        row['history']=c.execute('SELECT id,score,passed,created_at FROM attempts WHERE assignment_id=%s ORDER BY id',(aid,)).fetchall()
        row['finished']=any(t['passed'] for t in row['history']) or len(row['history'])>=row['max_attempts']
        row['questions']=[public_question(q) for q in questions]
        row['review']=questions if row['finished'] else []
        return row

@app.post('/api/assignments/{aid}/acknowledge')
def acknowledge(aid:int,request:Request):
    with db() as c:
        u=require(c,request)
        row=c.execute('''UPDATE assignments a SET acknowledged_at=coalesce(a.acknowledged_at,now())
          FROM courses c WHERE c.id=a.course_id AND NOT c.archived AND a.id=%s AND a.staff_id=%s
          RETURNING a.id''',(aid,u['id'])).fetchone()
        if not row: raise HTTPException(404)
    return {'ok':True}

@app.post('/api/assignments/{aid}/submit')
async def submit(aid:int,request:Request):
    d=await request.json()
    try: rid=uuid.UUID(d['request_id'])
    except (KeyError,ValueError,TypeError): raise HTTPException(422,'Некорректный идентификатор попытки')
    with db() as c:
        u=require(c,request)
        row=c.execute('SELECT a.*,c.questions,c.pass_score,c.archived,c.restaurant,c.reviewed_dish_signature FROM assignments a JOIN courses c ON c.id=a.course_id WHERE a.id=%s AND a.staff_id=%s FOR UPDATE OF a',(aid,u['id'])).fetchone()
        if not row: raise HTTPException(404)
        if row['archived']:raise HTTPException(410,'Этот тест архивирован руководителем')
        old=c.execute('SELECT id,score,passed FROM attempts WHERE assignment_id=%s AND request_id=%s',(aid,rid)).fetchone()
        if old:return old
        ensure_dish_quiz_current(c,row['course_id'],row['restaurant'],row['reviewed_dish_signature'])
        if c.execute('SELECT 1 FROM attempts WHERE assignment_id=%s AND passed LIMIT 1',(aid,)).fetchone():raise HTTPException(409,'Тест уже сдан')
        if not row['acknowledged_at']:raise HTTPException(409,'Сначала ознакомьтесь с материалом')
        if not row['questions']:raise HTTPException(422,'У этого материала нет теста')
        count=c.execute('SELECT count(*) n FROM attempts WHERE assignment_id=%s',(aid,)).fetchone()['n']
        if count>=row['max_attempts']:raise HTTPException(409,'Попытки исчерпаны. Обратитесь к руководителю')
        score=grade(row['questions'],d.get('answers'));passed=score>=row['pass_score']
        result=c.execute('INSERT INTO attempts(assignment_id,request_id,answers,score,passed) VALUES(%s,%s,%s,%s,%s) RETURNING id,score,passed',(aid,rid,Jsonb(d['answers']),score,passed)).fetchone()
        audit(c,u['id'],'attempt:submit',result['id'])
    return result

@app.get('/api/assignments/{aid}/results')
def results(aid:int,request:Request):
    with db() as c:
        u=require(c,request);manager(u)
        row=c.execute('SELECT s.restaurant,c.questions FROM assignments a JOIN staff s ON s.id=a.staff_id JOIN courses c ON c.id=a.course_id WHERE a.id=%s',(aid,)).fetchone()
        if not row:raise HTTPException(404)
        scope(u,row['restaurant'])
        return {'questions':row['questions'],'attempts':c.execute('SELECT * FROM attempts WHERE assignment_id=%s ORDER BY id',(aid,)).fetchall()}

@app.get('/pilot/')
def index():return FileResponse(BASE/'index.html')
@app.get('/pilot/pilot.js')
def script():return FileResponse(BASE/'pilot.js',media_type='application/javascript')
@app.get('/pilot/pilot.css')
def css():return FileResponse(BASE/'pilot.css',media_type='text/css')
@app.get('/pilot/learning.js')
def learning_script():return FileResponse(BASE/'learning.js',media_type='application/javascript')
@app.get('/pilot/learning.css')
def learning_styles():return FileResponse(BASE/'learning.css',media_type='text/css')

@app.get('/pilot/learner.css')
def learner_styles():return FileResponse(BASE/'learner.css',media_type='text/css')

@app.get('/pilot/menu_cards.js')
def menu_script():return FileResponse(BASE/'menu_cards.js',media_type='application/javascript')

@app.get('/pilot/wine_cards.js')
def wine_script():return FileResponse(BASE/'wine_cards.js',media_type='application/javascript')
@app.get('/pilot/wine_cards.css')
def wine_styles():return FileResponse(BASE/'wine_cards.css',media_type='text/css')

@app.get('/pilot/events.js')
def events_script():return FileResponse(BASE/'events.js',media_type='application/javascript')

@app.get('/pilot/voice.js')
def voice_script():return FileResponse(BASE/'voice.js',media_type='application/javascript')

@app.get('/pilot/dishes.js')
def dishes_script():return FileResponse(BASE/'dishes.js',media_type='application/javascript')
@app.get('/pilot/dishes.css')
def dishes_styles():return FileResponse(BASE/'dishes.css',media_type='text/css')

if __name__=='__main__':
    with db() as c:c.execute((BASE/'schema.sql').read_text())
    import uvicorn
    uvicorn.run(app,host='0.0.0.0',port=8000,access_log=False)

