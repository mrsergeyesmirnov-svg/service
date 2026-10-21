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
    if not isinstance(qs,list) or len(qs)>100 or (kind!='notice' and not qs): raise HTTPException(422,'Добавьте от 1 до 100 вопросов')
    clean=[]
    for q in qs:
        if not isinstance(q,dict): raise HTTPException(422,'Некорректный вопрос')
        options=q.get('options'); correct=q.get('correct')
        if not isinstance(options,list) or not 2<=len(options)<=6 or any(not isinstance(x,str) or not x.strip() or len(x)>1000 for x in options): raise HTTPException(422,'Вопросу нужны 2–6 ответов')
        if len(set(x.strip().casefold() for x in options))!=len(options): raise HTTPException(422,'Варианты ответов повторяются')
        if type(correct)!=int or not 0<=correct<len(options): raise HTTPException(422,'Выберите правильный ответ')
        clean.append(dict(question=text(q,'question',1000),options=options,correct=correct,explanation=text(q,'explanation',3000),source=text(q,'source',1000)))
    score=d.get('pass_score',80)
    if type(score)!=int or not 1<=score<=100: raise HTTPException(422,'Порог от 1 до 100')
    return title,kind,body,source,clean,score

def grade(qs, answers):
    if not isinstance(answers,list) or len(answers)!=len(qs) or any(type(a)!=int or not 0<=a<len(q['options']) for a,q in zip(answers,qs)):
        raise HTTPException(422,'Ответьте на каждый вопрос')
    return round(100*sum(a==q['correct'] for a,q in zip(answers,qs))/len(qs))

@app.middleware('http')
async def limits(request, call_next):
    if int(request.headers.get('content-length','0') or '0')>300000: return __import__('fastapi').responses.JSONResponse({'detail':'Слишком большой запрос'},status_code=413)
    response=await call_next(request)
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    return response

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
        if not member: raise HTTPException(403,'Сначала откройте приглашение руководителя и нажмите «Старт» в боте')
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
    return {'url':f'https://t.me/skill_mojo_bot?start={token}','expires_days':7,'single_use':True}

@app.get('/api/courses')
def courses(request:Request):
    with db() as c:
        u=require(c,request);manager(u)
        return c.execute('SELECT * FROM courses WHERE (%s OR restaurant=%s) ORDER BY id DESC',(u['role']=='manager',u['restaurant'])).fetchall()

@app.post('/api/courses')
async def create_course(request:Request):
    d=await request.json(); title,kind,body,source,qs,score=course_data(d)
    with db() as c:
        u=require(c,request);manager(u)
        row=c.execute('INSERT INTO courses(author,restaurant,title,kind,body,source,questions,pass_score) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id',(u['id'],u['restaurant'],title,kind,body,source,Jsonb(qs),score)).fetchone()
        audit(c,u['id'],'course:create',row['id'])
    return row

@app.put('/api/courses/{cid}')
async def edit_course(cid:int,request:Request):
    d=await request.json(); title,kind,body,source,qs,score=course_data(d)
    with db() as c:
        u=require(c,request);manager(u)
        row=c.execute('SELECT * FROM courses WHERE id=%s FOR UPDATE',(cid,)).fetchone()
        if not row: raise HTTPException(404)
        scope(u,row['restaurant'])
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
        scope(u,row['restaurant']);c.execute('UPDATE courses SET published=true WHERE id=%s',(cid,));audit(c,u['id'],'course:approved',cid)
    return {'ok':True}

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
        course=c.execute('SELECT * FROM courses WHERE id=%s AND published',(d.get('course_id'),)).fetchone()
        if not course: raise HTTPException(422,'Сначала опубликуйте курс')
        scope(u,course['restaurant']);result=[]
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
        return c.execute('''SELECT a.*,s.name,c.title,c.kind,c.pass_score,jsonb_array_length(c.questions) AS questions,
        (SELECT count(*) FROM attempts t WHERE t.assignment_id=a.id) AS attempts,
        (SELECT max(score) FROM attempts t WHERE t.assignment_id=a.id) AS best_score,
        EXISTS(SELECT 1 FROM attempts t WHERE t.assignment_id=a.id AND passed) AS passed,
        (SELECT state FROM outbox o WHERE o.assignment_id=a.id ORDER BY id LIMIT 1) AS notification
        FROM assignments a JOIN courses c ON c.id=a.course_id JOIN staff s ON s.id=a.staff_id
        WHERE (a.staff_id=%s OR (%s AND (%s OR s.restaurant=%s))) ORDER BY a.deadline,a.id''',(u['id'],u['role'] in ('manager','local'),u['role']=='manager',u['restaurant'])).fetchall()

@app.get('/api/assignments/{aid}')
def assignment(aid:int,request:Request):
    with db() as c:
        u=require(c,request)
        row=c.execute('SELECT a.*,c.title,c.body,c.source,c.questions,c.pass_score FROM assignments a JOIN courses c ON a.course_id=c.id WHERE a.id=%s AND a.staff_id=%s',(aid,u['id'])).fetchone()
        if not row: raise HTTPException(404)
        row['questions']=[{'question':q['question'],'options':q['options']} for q in row['questions']]
        row['history']=c.execute('SELECT id,score,passed,created_at FROM attempts WHERE assignment_id=%s ORDER BY id',(aid,)).fetchall()
        return row

@app.post('/api/assignments/{aid}/acknowledge')
def acknowledge(aid:int,request:Request):
    with db() as c:
        u=require(c,request)
        row=c.execute('UPDATE assignments SET acknowledged_at=coalesce(acknowledged_at,now()) WHERE id=%s AND staff_id=%s RETURNING id',(aid,u['id'])).fetchone()
        if not row: raise HTTPException(404)
    return {'ok':True}

@app.post('/api/assignments/{aid}/submit')
async def submit(aid:int,request:Request):
    d=await request.json()
    try: rid=uuid.UUID(d['request_id'])
    except (KeyError,ValueError,TypeError): raise HTTPException(422,'Некорректный идентификатор попытки')
    with db() as c:
        u=require(c,request)
        row=c.execute('SELECT a.*,c.questions,c.pass_score FROM assignments a JOIN courses c ON c.id=a.course_id WHERE a.id=%s AND a.staff_id=%s FOR UPDATE OF a',(aid,u['id'])).fetchone()
        if not row: raise HTTPException(404)
        old=c.execute('SELECT id,score,passed FROM attempts WHERE assignment_id=%s AND request_id=%s',(aid,rid)).fetchone()
        if old:return old
        if c.execute('SELECT EXISTS(SELECT 1 FROM attempts WHERE assignment_id=%s AND passed) AS done',(aid,)).fetchone()['done']:
            raise HTTPException(409,'Тест уже сдан')
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

if __name__=='__main__':
    with db() as c:c.execute((BASE/'schema.sql').read_text())
    import uvicorn
    uvicorn.run(app,host='0.0.0.0',port=8000,access_log=False)
