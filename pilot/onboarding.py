"""Two-day MOJO onboarding without a second LMS, mentors, or generated standards.

Day 1 is a short list of real-world tasks. The only factual claims about service
standards come from manager-reviewed, published courses in Day 2. Onboarding
does not alter existing attempts, course releases, or in-person admission.
"""
from datetime import date, timedelta
from uuid import UUID
from fastapi import APIRouter, HTTPException, Request
from psycopg.types.json import Jsonb
from questions import public_question, check

QUESTS = (
    dict(key="team", title="Познакомься с командой", review=False,
         instruction="Представься коллегам на смене и выясни, к кому обратиться за помощью. Не вписывай чужие личные данные.",
         prompt="Что теперь тебе понятно о работе команды?"),
    dict(key="place", title="Осмотрись в ресторане", review=False,
         instruction="С разрешения руководителя найди рабочие зоны и место с учебными материалами. Не заходи в зоны с ограниченным доступом.",
         prompt="Какие зоны тебе показали?"),
    dict(key="allergens", title="Безопасность и аллергены", review=True,
         instruction="Уточни у менеджера порядок действий, если гость спрашивает про аллерген. Не делай выводов о составе блюда самостоятельно.",
         prompt="Как ты передашь такой вопрос руководителю? Покажи ответ менеджеру."),
    dict(key="greeting", title="Попробуй встретить гостя", review=True,
         instruction="В спокойной обстановке продемонстрируй приветствие менеджеру. Это тренировка, а не самостоятельное обслуживание гостей.",
         prompt="Что ты сделал во время тренировки?"),
)
TOPICS = (
    ("service", "Общение и стандарты сервиса"),
    ("menu", "Знание меню"),
    ("allergens", "Аллергены и безопасность"),
)
TOPIC_KEYS = {x[0] for x in TOPICS}
QUEST_BY_KEY = {x["key"]: x for x in QUESTS}
LEVELS = {"know", "partial", "new"}


def checked_text(data, field, limit=1200, required=True):
    value = data.get(field)
    if value is None and not required: return ""
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise HTTPException(422, "Проверь поле: " + field)
    return value.strip()


def track(c, staff, create=True):
    if create:
        c.execute("""INSERT INTO onboarding_tracks(staff_id,restaurant,target_date)
           VALUES(%s,%s,CURRENT_DATE + 2) ON CONFLICT(staff_id) DO NOTHING""",
                  (staff["id"], staff["restaurant"]))
    return c.execute("SELECT * FROM onboarding_tracks WHERE staff_id=%s", (staff["id"],)).fetchone()


def attempted_quests(c, staff_id):
    rows = c.execute("""SELECT quest_key,answer,status,review_comment,submitted_at
        FROM onboarding_quest_attempts WHERE staff_id=%s""", (staff_id,)).fetchall()
    found = {r["quest_key"]: r for r in rows}
    return [dict(**q, status=found[q["key"]]["status"] if q["key"] in found else "todo",
                 answer=found[q["key"]]["answer"] if q["key"] in found else "",
                 review_comment=found[q["key"]]["review_comment"] if q["key"] in found else "")
            for q in QUESTS]


def completed_quests(quests):
    return all(q["status"] == "done" for q in quests)


def mapped_topics(c, restaurant):
    rows = c.execute("""SELECT m.topic_key,m.course_id,c.title,c.questions
         FROM onboarding_topic_courses m JOIN courses c ON c.id=m.course_id
         WHERE m.restaurant=%s AND c.restaurant=%s AND c.published AND NOT c.archived""",
         (restaurant, restaurant)).fetchall()
    return {r["topic_key"]: r for r in rows if isinstance(r["questions"],list) and len(r["questions"]) >= 3}


def collect(c, staff):
    t = track(c,staff)
    quests = attempted_quests(c,staff["id"])
    levels = {r["topic_key"]:r["self_level"] for r in c.execute(
        "SELECT topic_key,self_level FROM onboarding_self_assessments WHERE staff_id=%s",
        (staff["id"],)).fetchall()}
    maps = mapped_topics(c,staff["restaurant"])
    attempts = c.execute("""SELECT DISTINCT ON(topic_key) topic_key,course_id,score,passed,created_at
         FROM onboarding_diagnostic_attempts WHERE staff_id=%s
         ORDER BY topic_key,created_at DESC,id DESC""", (staff["id"],)).fetchall()
    last = {r["topic_key"]:r for r in attempts}
    topics=[]
    for key, name in TOPICS:
        mapping=maps.get(key)
        attempt=last.get(key)
        if attempt and mapping and attempt["course_id"] != mapping["course_id"]:
            # Changing the mapped course requires a fresh diagnosis, not a reused pass.
            attempt=None
        topics.append({"key":key,"title":name,"level":levels.get(key),
                       "course_id":mapping["course_id"] if mapping else None,
                       "course_title":mapping["title"] if mapping else None,
                       "score":attempt["score"] if attempt else None,
                       "passed":attempt["passed"] if attempt else None,
                       "diagnosed":bool(attempt)})
    stage = ("day1" if not t["day1_completed_at"] else
             "day2" if not t["day2_completed_at"] else "main")
    recommendations=[dict(topic=x["key"],course_id=x["course_id"],
                          title=x["course_title"],required=True)
                     for x in topics
                     if x["course_id"] and (x["level"]!="know" or x["passed"] is not True)]
    return {"available":True,"stage":stage,"started_at":t["started_at"],
            "target_date":t["target_date"],"day1_complete":bool(t["day1_completed_at"]),
            "day2_complete":bool(t["day2_completed_at"]), "quests":quests,
            "topics":topics,"recommendations":recommendations,
            "requires_manager_setup":any(x["course_id"] is None for x in topics)}


def make_onboarding_router(db, require, manager, scope, grade, audit):
    router = APIRouter(prefix="/api/onboarding")

    def learner(u):
        if u["role"] != "trainee":
            raise HTTPException(403, "Адаптация доступна стажёрам")

    def get_topic_course(c, u, key):
        if key not in TOPIC_KEYS: raise HTTPException(404, "Тема не найдена")
        row=mapped_topics(c,u["restaurant"]).get(key)
        if not row:raise HTTPException(409, "Менеджер ещё не назначил утверждённый учебный материал по теме")
        return row

    @router.get("/me")
    def mine(request: Request):
        with db() as c:
            u=require(c,request)
            if u["role"]!="trainee":return {"available":False}
            return collect(c,u)

    @router.post("/quests/{key}/submit")
    async def submit_quest(key: str, request: Request):
        q=QUEST_BY_KEY.get(key)
        if not q:raise HTTPException(404, "Задание не найдено")
        data=await request.json()
        answer=checked_text(data,"answer")
        with db() as c:
            u=require(c,request);learner(u)
            t=track(c,u)
            if t["day1_completed_at"]:
                raise HTTPException(409,"Первый день уже завершён")
            existing=c.execute("""SELECT * FROM onboarding_quest_attempts
                WHERE staff_id=%s AND quest_key=%s FOR UPDATE""",(u["id"],key)).fetchone()
            if existing and existing["status"]=="done":
                return {"status":"done","duplicate":True}
            if existing and existing["status"]=="pending":
                raise HTTPException(409,"Задание уже передано менеджеру на проверку")
            status="pending" if q["review"] else "done"
            c.execute("""INSERT INTO onboarding_quest_attempts
                (staff_id,quest_key,answer,status)
                VALUES(%s,%s,%s,%s)
                ON CONFLICT(staff_id,quest_key) DO UPDATE SET
                  answer=EXCLUDED.answer,status=EXCLUDED.status,
                  submitted_at=now(),reviewed_by=NULL,reviewed_at=NULL,review_comment=''""",
                 (u["id"],key,answer,status))
            audit(c,u["id"],"onboarding:quest:"+status,key)
            return {"status":status,"duplicate":False}

    @router.post("/day1/feedback")
    async def first_feedback(request: Request):
        data=await request.json()
        if not isinstance(data,dict):raise HTTPException(422,"Укажи отзыв")
        rating,clarity=data.get("rating"),data.get("clarity")
        if type(rating)!=int or type(clarity)!=int or not(1<=rating<=5 and 1<=clarity<=5):
            raise HTTPException(422,"Оцени день и понятность обучения от 1 до 5")
        comment=checked_text(data,"comment",1000,required=False)
        with db() as c:
            u=require(c,request);learner(u)
            t=track(c,u)
            if t["day1_completed_at"]:return {"day1_complete":True,"duplicate":True}
            if not completed_quests(attempted_quests(c,u["id"])):
                raise HTTPException(409,"Сначала заверши задания, ожидающие проверки менеджера")
            c.execute("""INSERT INTO onboarding_feedback(staff_id,day,rating,clarity,comment)
                VALUES(%s,1,%s,%s,%s) ON CONFLICT(staff_id,day) DO NOTHING""",
                      (u["id"],rating,clarity,comment))
            c.execute("""UPDATE onboarding_tracks SET day1_completed_at=now(),
                updated_at=now() WHERE staff_id=%s AND day1_completed_at IS NULL""",(u["id"],))
            audit(c,u["id"],"onboarding:day1-completed",u["id"])
            return {"day1_complete":True,"duplicate":False}

    @router.post("/self-assessment")
    async def self_assess(request: Request):
        data=await request.json()
        if not isinstance(data,dict) or not isinstance(data.get("levels"),dict):
            raise HTTPException(422,"Укажи самооценку по трём темам")
        levels=data["levels"]
        if set(levels)!=TOPIC_KEYS or any(v not in LEVELS for v in levels.values()):
            raise HTTPException(422,"Для каждой темы выбери: знаю, частично или не знаю")
        with db() as c:
            u=require(c,request);learner(u)
            t=track(c,u)
            if not t["day1_completed_at"]:
                raise HTTPException(409,"Сначала заверши первый день")
            if t["day2_completed_at"]:
                raise HTTPException(409,"Второй день уже завершён, оценки сохранены")
            for key,level in levels.items():
                c.execute("""INSERT INTO onboarding_self_assessments(staff_id,topic_key,self_level)
                   VALUES(%s,%s,%s) ON CONFLICT(staff_id,topic_key)
                   DO UPDATE SET self_level=EXCLUDED.self_level,updated_at=now()""",
                   (u["id"],key,level))
            audit(c,u["id"],"onboarding:self-assessment",u["id"])
            return {"saved":True}

    @router.get("/diagnostics/{key}")
    def diagnostic(key: str, request: Request):
        with db() as c:
            u=require(c,request);learner(u)
            t=track(c,u)
            if not t["day1_completed_at"]:
                raise HTTPException(409,"Сначала заверши первый день")
            if not c.execute("""SELECT 1 FROM onboarding_self_assessments
                 WHERE staff_id=%s AND topic_key=%s""",(u["id"],key)).fetchone():
                raise HTTPException(409,"Сначала оцени свои навыки")
            row=get_topic_course(c,u,key)
            questions=row["questions"][:3]
            return {"topic":key,"course_id":row["course_id"],
                    "title":row["title"],"questions":[public_question(q) for q in questions]}

    @router.post("/diagnostics/{key}/submit")
    async def submit_diagnostic(key: str, request: Request):
        data=await request.json()
        if not isinstance(data,dict) or not isinstance(data.get("answers"),list):
            raise HTTPException(422,"Ответь на вопросы диагностики")
        try:
            request_id=UUID(str(data.get("request_id","")))
        except (ValueError,TypeError,AttributeError):
            raise HTTPException(422,"Неверный идентификатор отправки")
        with db() as c:
            u=require(c,request);learner(u)
            t=track(c,u)
            if not t["day1_completed_at"]:raise HTTPException(409,"Сначала заверши первый день")
            if not c.execute("""SELECT 1 FROM onboarding_self_assessments
                WHERE staff_id=%s AND topic_key=%s""",(u["id"],key)).fetchone():
                raise HTTPException(409,"Сначала оцени свои навыки")
            old=c.execute("""SELECT id,score,passed FROM onboarding_diagnostic_attempts
                WHERE staff_id=%s AND topic_key=%s AND request_id=%s""",
                (u["id"],key,request_id)).fetchone()
            if old:return {"score":old["score"],"passed":old["passed"],"duplicate":True}
            row=get_topic_course(c,u,key)
            if type(data.get("course_id")) is not int or data["course_id"]!=row["course_id"]:
                raise HTTPException(409,"Проверочные материалы обновлены, открой диагностику заново")
            questions=row["questions"][:3]
            answers=data["answers"]
            if len(answers)!=len(questions):raise HTTPException(422,"Ответь на все три вопроса")
            score=grade(questions,answers)
            passed=score>=80
            c.execute("""INSERT INTO onboarding_diagnostic_attempts
                (staff_id,topic_key,course_id,request_id,questions,answers,score,passed)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                (u["id"],key,row["course_id"],request_id,Jsonb(questions),Jsonb(answers),score,passed))
            audit(c,u["id"],"onboarding:diagnostic",key)
            ready=c.execute("""SELECT count(DISTINCT topic_key) AS n
                FROM onboarding_diagnostic_attempts WHERE staff_id=%s AND
                (topic_key,course_id) IN (
                  SELECT m.topic_key,m.course_id FROM onboarding_topic_courses m
                  JOIN courses cr ON cr.id=m.course_id
                  WHERE m.restaurant=%s AND cr.restaurant=%s AND cr.published AND NOT cr.archived)""",
                (u["id"],u["restaurant"],u["restaurant"])).fetchone()["n"]
            if ready==len(TOPICS):
                c.execute("""UPDATE onboarding_tracks SET day2_completed_at=COALESCE(day2_completed_at,now()),
                    updated_at=now() WHERE staff_id=%s""",(u["id"],))
            return {"score":score,"passed":passed,"duplicate":False,
                    "explanations":[{"question":q["question"],"explanation":q["explanation"],
                                     "source":q["source"],"correct":check(q,a)["fraction"]==1}
                                    for q,a in zip(questions,answers)],
                    "day2_complete":ready==len(TOPICS)}

    @router.get("/team")
    def team(request: Request):
        with db() as c:
            u=require(c,request);manager(u)
            rows=c.execute("""SELECT s.id,s.name,s.restaurant,s.role,
                t.day1_completed_at,t.day2_completed_at,t.target_date,t.started_at,
                (SELECT count(*) FROM onboarding_quest_attempts a
                   WHERE a.staff_id=s.id AND a.status='pending') AS pending,
                (SELECT count(*) FROM onboarding_quest_attempts a
                   WHERE a.staff_id=s.id AND a.status='done') AS quests_done
                FROM staff s LEFT JOIN onboarding_tracks t ON t.staff_id=s.id
                WHERE s.role='trainee' AND s.active AND (%s OR s.restaurant=%s)
                ORDER BY t.day2_completed_at NULLS FIRST,s.name LIMIT 200""",
                (u["role"]=="manager",u["restaurant"])).fetchall()
            return rows

    @router.get("/team/{staff_id}")
    def team_detail(staff_id:int,request: Request):
        with db() as c:
            u=require(c,request);manager(u)
            staff=c.execute("""SELECT * FROM staff WHERE id=%s AND active AND role='trainee'""",(staff_id,)).fetchone()
            if not staff:raise HTTPException(404,"Стажёр не найден")
            scope(u,staff["restaurant"])
            state=collect(c,staff)
            feedback=c.execute("""SELECT rating,clarity,comment,created_at
                 FROM onboarding_feedback WHERE staff_id=%s AND day=1""",(staff_id,)).fetchone()
            return dict(state,staff_id=staff_id,name=staff["name"],restaurant=staff["restaurant"],
                        feedback=feedback)

    @router.post("/quests/{key}/review")
    async def review_quest(key: str,request: Request):
        if key not in QUEST_BY_KEY or not QUEST_BY_KEY[key]["review"]:
            raise HTTPException(404,"Задание не требует подтверждения")
        data=await request.json()
        staff_id=data.get("staff_id") if isinstance(data,dict) else None
        decision=data.get("decision") if isinstance(data,dict) else None
        if type(staff_id) is not int or decision not in ("approve","revise"):
            raise HTTPException(422,"Выбери стажёра и решение")
        comment=checked_text(data,"comment",600,required=decision=="revise")
        with db() as c:
            u=require(c,request);manager(u)
            staff=c.execute("SELECT id,restaurant FROM staff WHERE id=%s AND active AND role='trainee'",(staff_id,)).fetchone()
            if not staff:raise HTTPException(404,"Стажёр не найден")
            scope(u,staff["restaurant"])
            row=c.execute("""SELECT status FROM onboarding_quest_attempts
                WHERE staff_id=%s AND quest_key=%s FOR UPDATE""",(staff_id,key)).fetchone()
            if not row:raise HTTPException(404,"Ответ не отправлен")
            target="done" if decision=="approve" else "revise"
            if row["status"]==target:return {"status":target,"duplicate":True}
            if row["status"]!="pending":raise HTTPException(409,"Задание не ожидает проверки")
            c.execute("""UPDATE onboarding_quest_attempts SET status=%s,
                reviewed_by=%s,reviewed_at=now(),review_comment=%s WHERE staff_id=%s AND quest_key=%s""",
                (target,u["id"],comment,staff_id,key))
            audit(c,u["id"],"onboarding:quest-reviewed:"+decision,staff_id)
            return {"status":target,"duplicate":False}

    @router.patch("/team/{staff_id}")
    async def edit_deadline(staff_id:int, request:Request):
        data=await request.json()
        raw=data.get("target_date") if isinstance(data,dict) else None
        try: due=date.fromisoformat(raw)
        except (ValueError,TypeError):raise HTTPException(422,"Укажи дату YYYY-MM-DD")
        if due<date.today()-timedelta(days=30) or due>date.today()+timedelta(days=366):
            raise HTTPException(422,"Дата вне допустимого периода")
        with db() as c:
            u=require(c,request);manager(u)
            staff=c.execute("SELECT id,restaurant FROM staff WHERE id=%s AND active AND role='trainee'",(staff_id,)).fetchone()
            if not staff:raise HTTPException(404,"Стажёр не найден")
            scope(u,staff["restaurant"])
            track(c,staff)
            c.execute("""UPDATE onboarding_tracks SET target_date=%s,updated_at=now()
                WHERE staff_id=%s""",(due,staff_id))
            audit(c,u["id"],"onboarding:deadline",staff_id)
            return {"target_date":due.isoformat()}

    @router.get("/topics")
    def manager_topics(request: Request):
        with db() as c:
            u=require(c,request);manager(u)
            return {"topics":[{"key":key,"title":name} for key,name in TOPICS],
                    "mapped":[{"topic":key,"course_id":row["course_id"],"title":row["title"]}
                              for key,row in mapped_topics(c,u["restaurant"]).items()],
                    "courses":c.execute("""SELECT id,title FROM courses
                       WHERE restaurant=%s AND published AND NOT archived
                         AND jsonb_array_length(questions)>=3 ORDER BY title""",
                        (u["restaurant"],)).fetchall()}

    @router.put("/topics/{key}")
    async def set_topic(key:str,request:Request):
        if key not in TOPIC_KEYS:raise HTTPException(404,"Тема не найдена")
        data=await request.json()
        if not isinstance(data,dict) or type(data.get("course_id")) is not int or data.get("reviewed") is not True:
            raise HTTPException(422,"Выбери курс и подтверди проверку вопросов по теме")
        with db() as c:
            u=require(c,request);manager(u)
            found=c.execute("""SELECT id FROM courses WHERE id=%s AND restaurant=%s
                 AND published AND NOT archived AND jsonb_array_length(questions)>=3""",
                 (data["course_id"],u["restaurant"])).fetchone()
            if not found:raise HTTPException(409,"Нужен опубликованный курс с минимум тремя проверенными вопросами")
            c.execute("""INSERT INTO onboarding_topic_courses
                (restaurant,topic_key,course_id,reviewed_by)
                VALUES(%s,%s,%s,%s) ON CONFLICT(restaurant,topic_key)
                DO UPDATE SET course_id=EXCLUDED.course_id,reviewed_by=EXCLUDED.reviewed_by,updated_at=now()""",
                (u["restaurant"],key,found["id"],u["id"]))
            audit(c,u["id"],"onboarding:topic-mapped:"+key,found["id"])
            return {"saved":True,"topic":key,"course_id":found["id"]}

    return router
