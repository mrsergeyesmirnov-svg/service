"""MOJO final menu exam: manager binds 7 real sections plus desserts.

50 open-answer questions with balanced source coverage, scored deterministically.
Only staff who passed each source section's intermediate AND full control
may start. A passed exam never grants in-person certification automatically.
"""
import hashlib
import json
import uuid

from fastapi import APIRouter, HTTPException, Request
from psycopg.types.json import Jsonb
from questions import public_question, check, grade_questions
from dish_lessons import dish_chapters, map_details, reviewed_dish_signature
from menu_assessments import menu_exam_questions

SLOTS = [
    ("rolls", "Роллы"), ("asia", "Азия"), ("salads", "Салаты"),
    ("appetizers", "Закуски"), ("soups", "Супы"), ("hot", "Горячее"),
    ("grill", "Гриль"), ("desserts", "Десерты"),
]


def signature(slots, published):
    payload=[{"slot":key,"course_id":slots[key],
              "revision":published[key]["signature"]} for key,_ in SLOTS]
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,
                         sort_keys=True).encode()).hexdigest()


def select_questions(published):
    """Exactly 50, with every section represented and all source cards approved."""
    groups=[]
    for key,label in SLOTS:
        all_questions=menu_exam_questions(published[key]["chapters"],"control",
                                          published[key]["id"])
        if len(all_questions)<6:
            raise HTTPException(409,f"В разделе «{label}» нужно минимум шесть утверждённых блюд")
        groups.append((key,label,all_questions))
    # 48 baseline (six per block) + 2 extra from the largest sections.
    quotas={key:6 for key,_,_ in groups}
    priority=sorted(groups,key=lambda item:(-len(item[2]),[k for k,_ in SLOTS].index(item[0])))
    for key,_,_ in priority[:2]:quotas[key]+=1
    result=[]
    for key,label,questions in groups:
        n=len(questions);take=quotas[key]
        positions=[round(i*(n-1)/(take-1)) for i in range(take)]
        for index in positions:
            q=dict(questions[index])
            q["question"]=label+" · "+q["question"]
            result.append(q)
    assert len(result)==50
    return result


def make_router(db,require,manager,scope,audit):
    router=APIRouter(prefix="/api/menu-final")

    def course_bundle(c, u, slots):
        bundled={}
        for key,label in SLOTS:
            cid=slots.get(key)
            if type(cid)!=int or cid<=0:
                raise HTTPException(422,f"Укажи корректный курс для «{label}»")
            row=c.execute("""SELECT id,restaurant,published,archived,
                reviewed_dish_signature FROM courses WHERE id=%s""",(cid,)).fetchone()
            if (not row or row["archived"] or not row["published"] or
                    row["restaurant"]!=u["restaurant"] or
                    not row["reviewed_dish_signature"]):
                raise HTTPException(409,f"Курс «{label}» не утверждён для этой точки")
            mapped=map_details(c,cid)
            chapters=dish_chapters(c,cid,u["restaurant"])
            if not mapped or len(chapters or [])!=len(mapped) or (
                    reviewed_dish_signature(chapters)!=row["reviewed_dish_signature"]):
                raise HTTPException(409,f"В разделе «{label}» карточки изменились или не утверждены")
            bundled[key]={"id":cid,"chapters":chapters,
                          "signature":row["reviewed_dish_signature"]}
        return bundled

    def config(c,u):
        row=c.execute("SELECT * FROM menu_final_config WHERE restaurant=%s",
                      (u["restaurant"],)).fetchone()
        return row

    def passed_sections(c,uid,bundle):
        passed={}
        for key,label in SLOTS:
            item=bundle[key]
            result=c.execute("""SELECT 1 FROM menu_assessment_attempts
                WHERE staff_id=%s AND course_id=%s AND stage='control'
                  AND signature=%s AND passed LIMIT 1""",
                (uid,item["id"],item["signature"])).fetchone()
            passed[key]=bool(result)
        return passed

    @router.get("/config")
    def get_config(request:Request):
        with db() as c:
            u=require(c,request);manager(u)
            row=config(c,u)
            return {"configured":bool(row),"slots":row["slots"] if row else {},
                    "pass_score":row["pass_score"] if row else 85}

    @router.post("/config")
    async def save_config(request:Request):
        d=await request.json()
        if not isinstance(d,dict) or d.get("confirmed") is not True:
            raise HTTPException(422,"Подтверди проверку реальных курсов MOJO")
        slots=d.get("slots")
        if not isinstance(slots,dict) or set(slots)!={key for key,_ in SLOTS}:
            raise HTTPException(422,"Нужно назначить семь разделов меню и десерты")
        if any(type(x)!=int or x<=0 for x in slots.values()):
            raise HTTPException(422,"Укажи действительные идентификаторы курсов")
        if len(set(slots.values()))!=len(SLOTS):
            raise HTTPException(422,"Для каждого раздела нужен отдельный курс")
        pass_score=d.get("pass_score",85)
        if type(pass_score)!=int or not 70<=pass_score<=100:
            raise HTTPException(422,"Проходной балл финального экзамена от 70 до 100%")
        with db() as c:
            u=require(c,request);manager(u)
            bundle=course_bundle(c,u,slots)
            # Fail before touching config if fewer than 50 questions or bad sources.
            select_questions(bundle)
            c.execute("""INSERT INTO menu_final_config
               (restaurant,slots,pass_score,updated_by)
               VALUES(%s,%s,%s,%s)
               ON CONFLICT(restaurant) DO UPDATE SET
                 slots=EXCLUDED.slots,pass_score=EXCLUDED.pass_score,
                 updated_by=EXCLUDED.updated_by,updated_at=now()""",
                (u["restaurant"],Jsonb(slots),pass_score,u["id"]))
            audit(c,u["id"],"menu:final-config",u["restaurant"])
            return {"configured":True,"courses":len(slots),"questions":50}

    @router.get("/status")
    def get_status(request:Request):
        with db() as c:
            u=require(c,request)
            row=config(c,u)
            if not row:return {"configured":False,"ready":False,
                               "missing":[label for _,label in SLOTS]}
            bundle=course_bundle(c,u,row["slots"])
            done=passed_sections(c,u["id"],bundle)
            ready=all(done.values())
            digest=signature(row["slots"],bundle)
            achieved=bool(c.execute("""SELECT 1 FROM menu_final_attempts
                WHERE staff_id=%s AND signature=%s AND passed LIMIT 1""",
                (u["id"],digest)).fetchone())
            return {"configured":True,"ready":ready,"passed":achieved,
                    "missing":[label for key,label in SLOTS if not done[key]],
                    "questions":[public_question(q) for q in select_questions(bundle)] if ready and not achieved else [],
                    "pass_score":row["pass_score"]}

    @router.post("/submit")
    async def submit(request:Request):
        d=await request.json()
        if not isinstance(d,dict):raise HTTPException(422,"Некорректные ответы")
        try:rid=uuid.UUID(d["request_id"])
        except (KeyError,TypeError,ValueError,AttributeError):
            raise HTTPException(422,"Некорректный номер попытки")
        with db() as c:
            u=require(c,request)
            row=config(c,u)
            if not row:raise HTTPException(409,"Финальный экзамен ещё не настроен")
            bundle=course_bundle(c,u,row["slots"])
            digest=signature(row["slots"],bundle)
            c.execute("SELECT id FROM staff WHERE id=%s FOR UPDATE",(u["id"],))
            previous=c.execute("""SELECT * FROM menu_final_attempts
                WHERE staff_id=%s AND request_id=%s""",(u["id"],rid)).fetchone()
            if previous:
                if previous["signature"]!=digest:
                    raise HTTPException(409,"Программа изменилась, эта попытка устарела")
                return attempt_result(previous)
            if not all(passed_sections(c,u["id"],bundle).values()):
                raise HTTPException(409,"Сначала сдай все семь разделов меню и десерты")
            if c.execute("""SELECT 1 FROM menu_final_attempts
                WHERE staff_id=%s AND signature=%s AND passed LIMIT 1""",
                (u["id"],digest)).fetchone():
                raise HTTPException(409,"Этот экзамен уже сдан")
            questions=select_questions(bundle)
            answers=d.get("answers")
            score=grade_questions(questions,answers)
            outcome=score>=row["pass_score"]
            saved=c.execute("""INSERT INTO menu_final_attempts
                (staff_id,restaurant,request_id,signature,questions,answers,score,passed)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                (u["id"],u["restaurant"],rid,digest,Jsonb(questions),
                 Jsonb(answers),score,outcome)).fetchone()
            audit(c,u["id"],"menu:final-attempt",saved["id"])
            return attempt_result(saved)

    def attempt_result(row):
        return {"score":row["score"],"passed":row["passed"],"review":[
            dict(q,answer=a,assessment=check(q,a))
            for q,a in zip(row["questions"],row["answers"])
        ],"in_person_required":True}

    return router
