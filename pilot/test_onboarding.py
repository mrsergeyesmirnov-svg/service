"""Isolated PostgreSQL tests for the two-day MOJO journey and manager quest editing."""
import hashlib
import os
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi.testclient import TestClient
import server


def approved_questions():
    return [
        {"type":"single","question":"What do you do when unsure?",
         "options":["Ask manager","Guess","Ignore"],"correct":0,
         "explanation":"Ask a manager instead of guessing.","source":"Reviewed synthetic standard"},
        {"type":"multiple","question":"What are suitable actions?",
         "options":["Check source","Listen","Make up facts"],"correct":[0,1],
         "explanation":"Check the source and listen.","source":"Reviewed synthetic standard"},
        {"type":"single","question":"Which action is appropriate?",
         "options":["Clarify","Dismiss","Invent"],"correct":0,
         "explanation":"Clarify a request.","source":"Reviewed synthetic standard"},
    ]


@unittest.skipUnless(os.getenv("DATABASE_URL"), "PostgreSQL test service required")
class TwoDayJourney(unittest.TestCase):
    def setUp(self):
        self.schema="onboard_test_"+uuid.uuid4().hex
        self.original=server.db
        with self.original() as c:
            c.execute("CREATE SCHEMA "+self.schema)

        def connect():
            return psycopg.connect(os.environ["DATABASE_URL"],
                     row_factory=dict_row,options="-c search_path="+self.schema)
        self.connect=connect
        self.guard=patch.object(server,"db",connect)
        self.guard.start()
        with connect() as c:
            c.execute((Path(__file__).parent/"schema.sql").read_text())
            c.execute("""INSERT INTO staff(id,name,role,restaurant,bot_started) VALUES
                (101,'MOJO student','trainee','MOJO',true),
                (102,'Second student','trainee','MOJO',true),
                (103,'Other local manager','local','OTHER',true),
                (104,'Other student','trainee','OTHER',true),
                (999,'MOJO manager','manager','MOJO',true)""")
            for uid in (101,102,103,104,999):
                c.execute("""INSERT INTO sessions(token_hash,staff_id,expires_at)
                    VALUES(%s,%s,now()+interval '1 hour')""",
                    (hashlib.sha256(("student-"+str(uid)).encode()).hexdigest(),uid))
        self.client=TestClient(server.app)

    def tearDown(self):
        self.guard.stop()
        with self.original() as c:
            c.execute("DROP SCHEMA "+self.schema+" CASCADE")

    def headers(self,uid=101):
        return {"Authorization":"Bearer student-"+str(uid)}

    def get(self,path,uid=101):
        return self.client.get("/api/onboarding/"+path,headers=self.headers(uid))

    def post(self,path,payload=None,uid=101):
        return self.client.post("/api/onboarding/"+path,json=payload or {},headers=self.headers(uid))

    def edit(self,key,payload,uid=999):
        return self.client.put("/api/onboarding/quests/manage/"+key,json=payload,headers=self.headers(uid))

    def complete_day1(self):
        self.assertEqual(self.get("me").status_code,200)
        for key in ("team","place","allergens","greeting"):
            r=self.post("quests/"+key+"/submit",{"answer":"Учусь вместе с командой."})
            self.assertEqual(r.status_code,200,r.text)
        final=self.post("day1/feedback",{"rating":5,"clarity":4,"comment":"Спасибо"})
        self.assertEqual(final.status_code,200,final.text)

    def test_manager_edits_scoped_and_existing_answers_preserved(self):
        row=self.get("quests/manage",999)
        self.assertEqual(row.status_code,200,row.text)
        self.assertEqual(len(row.json()["quests"]),4)
        self.assertEqual(self.get("quests/manage").status_code,403)

        change={"title":"Поговори с командой","instruction":"Найди коллегу и попроси показать учебные материалы.",
                "prompt":"Что узнал?","review":False}
        self.assertEqual(self.edit("team",change,101).status_code,403)
        updated=self.edit("team",change)
        self.assertEqual(updated.status_code,200,updated.text)
        self.assertEqual(self.get("me").json()["quests"][0]["title"],change["title"])

        r=self.post("quests/team/submit",{"answer":"Нашёл учебные материалы."})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()["status"],"done")
        change["title"]="Новое название для следующего запуска"
        self.assertEqual(self.edit("team",change).status_code,200)
        refreshed=self.get("me").json()["quests"][0]
        self.assertEqual(refreshed["title"],change["title"])
        self.assertEqual(refreshed["answer"],"Нашёл учебные материалы.")
        self.assertEqual(refreshed["status"],"done")

        flip=dict(change,review=True)
        self.assertEqual(self.edit("team",flip).status_code,200)
        self.assertFalse(self.get("me").json()["quests"][0]["review"])
        critical={"title":"Аллергены","instruction":"Уточни безопасный порядок у менеджера.",
                  "prompt":"Что ты сделал?","review":False}
        self.assertEqual(self.edit("allergens",critical).status_code,200)

        # A local manager cannot see or edit the MOJO restaurant's attempts.
        self.assertEqual(self.get("team/101",103).status_code,403)
        other=self.get("quests/manage",103)
        self.assertEqual(other.status_code,200)
        self.assertNotEqual(other.json()["quests"][0]["title"],change["title"])

    def test_day1_self_completion_and_friendly_reflection(self):
        payload={"reflection":{"day":"Хорошо","team":"Команда зала","continue":"no"}}
        self.assertEqual(self.post("day1/feedback",payload).status_code,409)
        for key in ("team","place","allergens","greeting"):
            r=self.post("quests/"+key+"/submit",{"answer":"Выполнено"})
            self.assertEqual(r.json()["status"],"done")
        with self.connect() as c:
            c.execute("UPDATE onboarding_quest_attempts SET status='pending' WHERE staff_id=101 AND quest_key='allergens'")
        self.assertTrue(all(q["status"]=="done" and not q["review"] for q in self.get("me").json()["quests"]))
        result=self.post("day1/feedback",payload)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(self.get("me").json()["stage"],"day2")
        feedback=self.get("team/101",999).json()["feedback"]
        self.assertEqual(feedback["reflection"],payload["reflection"])
        self.assertIsNone(feedback["rating"])
        self.assertEqual(self.get("team/101",103).status_code,403)
        self.assertTrue(self.post("day1/feedback",payload).json()["duplicate"])

    def test_day2_reuses_manager_approved_courses_no_auto_admission(self):
        self.complete_day1()
        levels={"service":"know","menu":"partial","allergens":"new"}
        self.assertEqual(self.post("self-assessment",{"levels":levels}).status_code,200)
        self.assertEqual(self.get("diagnostics/service").status_code,409)
        ids=[]
        with self.connect() as c:
            for i in range(3):
                row=c.execute("""INSERT INTO courses
                    (author,restaurant,title,kind,body,source,questions,pass_score,published)
                    VALUES(999,'MOJO',%s,'service','Synthetic','Reviewed synthetic',
                           %s,80,true) RETURNING id""",
                     ("Reviewed "+str(i),Jsonb(approved_questions()))).fetchone()
                ids.append(row["id"])
        for key,cid in zip(("service","menu","allergens"),ids):
            self.assertEqual(self.client.put("/api/onboarding/topics/"+key,
                json={"course_id":cid,"reviewed":True},headers=self.headers(103)).status_code,409)
            r=self.client.put("/api/onboarding/topics/"+key,
                json={"course_id":cid,"reviewed":True},headers=self.headers(999))
            self.assertEqual(r.status_code,200,r.text)
        rubric=self.get("diagnostics/service")
        self.assertEqual(rubric.status_code,200,rubric.text)
        self.assertNotIn("correct",str(rubric.json()["questions"]))
        sent=[]
        for key,cid in zip(("service","menu","allergens"),ids):
            rid=str(uuid.uuid4())
            sent.append(rid)
            result=self.post("diagnostics/"+key+"/submit",{
                "course_id":cid,"request_id":rid,"answers":[2,[2],2]
            })
            self.assertEqual(result.status_code,200,result.text)
            self.assertFalse(result.json()["passed"])
        self.assertEqual(self.get("me").json()["stage"],"main")
        self.assertEqual(len(self.get("me").json()["recommendations"]),3)
        retry=self.post("diagnostics/service/submit",{
            "course_id":ids[0],"request_id":sent[0],"answers":[0,[0,1],0]
        })
        self.assertTrue(retry.json()["duplicate"])
        good=self.post("diagnostics/service/submit",{
            "course_id":ids[0],"request_id":str(uuid.uuid4()),"answers":[0,[0,1],0]
        })
        self.assertEqual(good.json()["score"],100)
        self.assertEqual(len(self.get("me").json()["recommendations"]),2)
        with self.connect() as c:
            for table in ("attempts","learning_attempts","menu_assessment_attempts"):
                self.assertEqual(c.execute("SELECT count(*) AS n FROM "+table).fetchone()["n"],0)
            self.assertEqual(c.execute("SELECT count(*) AS n FROM onboarding_diagnostic_attempts").fetchone()["n"],4)

    def test_deadline_scoped_and_persistent(self):
        r=self.client.patch("/api/onboarding/team/101",
             json={"target_date":"2026-11-02"},headers=self.headers(103))
        self.assertEqual(r.status_code,403,r.text)
        r=self.client.patch("/api/onboarding/team/101",
             json={"target_date":"2026-11-02"},headers=self.headers(999))
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(str(self.get("me").json()["target_date"]),"2026-11-02")


if __name__=="__main__":
    unittest.main()
