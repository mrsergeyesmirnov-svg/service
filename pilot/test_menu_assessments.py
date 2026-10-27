"""MOJO staged menu checks: approved sources, all dishes, independent results."""
import os
import uuid
import unittest
from pathlib import Path
from unittest.mock import patch

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi import HTTPException
from fastapi.testclient import TestClient

import server
from dish_lessons import dish_chapters, reviewed_dish_signature
from menu_assessments import menu_exam_questions
from test_pilot import signed


def chapter(index):
    return {"kind":"dish","id":f"dish-{index}-v1","dish_id":index,
            "title":f"Ролл {index}","section":"Роллы",
            "ingredients":["Рис",f"Соус {index}","Нори"],
            "source":"MOJO станционки","source_page":index}


def answers(qs):
    return ["\n".join(group[0] for group in q["ingredients"])
            if q["type"] == "ingredients" else q["correct"] for q in qs]


class StageUnit(unittest.TestCase):
    def test_control_covers_all_37_dishes_not_just_first_six(self):
        cards=[chapter(n) for n in range(1,38)]
        full=menu_exam_questions(cards,"control",7)
        self.assertEqual(len(full),37)
        self.assertIn("Ролл 37",full[-1]["question"])
        self.assertTrue(all(q["type"]=="ingredients" for q in full))
        self.assertFalse(any("компонента" in q["question"] for q in full))
        intermediate=menu_exam_questions(cards,"intermediate",7)
        self.assertLessEqual(len(intermediate),12)
        self.assertTrue(any("Ролл 37" in q["question"] for q in intermediate))
        self.assertTrue(any("Ролл 1" in q["question"] for q in intermediate))

    def test_never_silently_skip_unverified_dish(self):
        cards=[chapter(1),chapter(2)]
        cards[1]["ingredients"]=[]
        with self.assertRaises(HTTPException) as e:
            menu_exam_questions(cards,"control",7)
        self.assertEqual(e.exception.status_code,409)


@unittest.skipUnless(os.environ.get("DATABASE_URL"),"PostgreSQL integration required")
class StageIntegration(unittest.TestCase):
    def setUp(self):
        self.schema="menu_stage_"+uuid.uuid4().hex
        self.real_db=server.db
        with self.real_db() as c:c.execute("CREATE SCHEMA "+self.schema)
        def db():
            return psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row,
                                   options="-c search_path="+self.schema)
        self.connect=db
        self.patches=[patch.object(server,"db",db),patch.object(server,"TOKEN","test-token"),
                      patch.object(server,"OWNER",999)]
        for p in self.patches:p.start()
        with db() as c:
            c.execute((Path(__file__).parent/"schema.sql").read_text())
            c.execute("""INSERT INTO staff(id,name,role,restaurant,bot_started) VALUES
                (101,'Стажёр','trainee','MOJO',true),
                (102,'Другой','waiter','MOJO',true),
                (103,'Чужой','local','OTHER',true),
                (999,'Менеджер','manager','MOJO',true)""")
            self.cid=c.execute("""INSERT INTO courses
                (author,restaurant,title,kind,body,source,questions,pass_score,published)
                VALUES(999,'MOJO','Роллы','ttk','Курс','MOJO ТТК','[]',80,true)
                RETURNING id""").fetchone()["id"]
            for i in range(8):
                did=c.execute("""INSERT INTO dish_cards
                    (restaurant,created_by,title,section,ingredients,published)
                    VALUES('MOJO',999,%s,'Роллы',%s,true) RETURNING id""",
                    (f"Ролл {i+1}",Jsonb(["Рис","Нори",f"Соус {i+1}"]))).fetchone()["id"]
                c.execute("""INSERT INTO course_dishes(course_id,dish_id,position)
                    VALUES(%s,%s,%s)""",(self.cid,did,i))
            ch=dish_chapters(c,self.cid,"MOJO")
            self.signature=reviewed_dish_signature(ch)
            c.execute("UPDATE courses SET reviewed_dish_signature=%s WHERE id=%s",
                      (self.signature,self.cid))
        self.client=TestClient(server.app)

    def tearDown(self):
        for p in self.patches:p.stop()
        with self.real_db() as c:c.execute("DROP SCHEMA "+self.schema+" CASCADE")

    def auth(self,uid):
        r=self.client.post("/api/login",json={"initData":signed(uid)})
        self.assertEqual(r.status_code,200,r.text)
        return {"Authorization":"Bearer "+r.json()["token"]}

    def test_ai_practice_questions_never_disable_required_control_exam(self):
        manager=self.auth(999)
        trainee=self.auth(101)
        practice={"type":"single","question":"Что сделать при неизвестном составе?",
                  "options":["Уточнить у кухни","Угадать","Промолчать"],
                  "correct":0,"explanation":"Только по ТТК","source":"MOJO ТТК"}
        with self.connect() as c:
            c.execute("UPDATE courses SET questions=%s WHERE id=%s",
                     (Jsonb([practice]),self.cid))
        check=self.client.get(f"/api/courses/{self.cid}/publication-check",headers=manager)
        self.assertEqual(check.status_code,200,check.text)
        self.assertEqual(check.json()["mode"],"staged-menu")
        summary=next(x for x in self.client.get("/api/learning",headers=trainee).json()
                     if x["id"]==self.cid)
        self.assertTrue(summary["staged_menu"])
        self.assertFalse(summary["control_passed"])
        detail=self.client.get(f"/api/learning/{self.cid}",headers=trainee).json()
        self.assertTrue(detail["staged_menu"])
        self.assertEqual(len(detail["questions"]),1)

    def test_gates_scoped_answers_retries_and_snapshot(self):
        trainee=self.auth(101);coworker=self.auth(102);foreign=self.auth(103)
        path=f"/api/menu-assessments/{self.cid}"
        self.assertEqual(self.client.get(path,headers=foreign).status_code,404)
        status=self.client.get(path,headers=trainee)
        self.assertEqual(status.status_code,200,status.text)
        self.assertFalse(status.json()["all_read"])
        before_catalog=next(c for c in self.client.get("/api/learning",headers=trainee).json()
                            if c["id"]==self.cid)
        self.assertTrue(before_catalog["staged_menu"])
        self.assertFalse(before_catalog["control_passed"])
        self.assertEqual(before_catalog["read"],0)
        detail=self.client.get(f"/api/learning/{self.cid}",headers=trainee).json()
        self.assertTrue(detail["staged_menu"])
        self.assertFalse(detail["control_passed"])
        self.assertEqual(status.json()["questions"],[])
        early=self.client.post(path+"/control/submit",headers=trainee,json={
            "request_id":str(uuid.uuid4()),"answers":["x"]})
        self.assertEqual(early.status_code,409)
        for ch in self.client.get(f"/api/learning/{self.cid}",headers=trainee).json()["chapters"]:
            r=self.client.post(f"/api/learning/{self.cid}/read",headers=trainee,
                               json={"chapter_id":ch["id"]})
            self.assertEqual(r.status_code,200,r.text)
        progress=self.client.get(path,headers=trainee).json()
        self.assertTrue(progress["all_read"])
        self.assertEqual(progress["next_stage"],"intermediate")
        after_read=next(c for c in self.client.get("/api/learning",headers=trainee).json()
                        if c["id"]==self.cid)
        self.assertEqual(after_read["read"],after_read["chapters"])
        self.assertFalse(after_read["control_passed"])
        with self.connect() as c:ch=dish_chapters(c,self.cid,"MOJO")
        intermediate=menu_exam_questions(ch,"intermediate",self.cid)
        rid=str(uuid.uuid4())
        payload={"request_id":rid,"answers":answers(intermediate)}
        got=self.client.post(path+"/intermediate/submit",headers=trainee,json=payload)
        self.assertEqual(got.status_code,200,got.text)
        self.assertEqual(got.json()["score"],100)
        self.assertTrue(got.json()["passed"])
        repeat=self.client.post(path+"/intermediate/submit",headers=trainee,json=payload)
        self.assertEqual(repeat.json(),got.json())
        self.assertFalse(self.client.get(path,headers=coworker).json()["intermediate_passed"])
        status=self.client.get(path,headers=trainee).json()
        self.assertEqual(status["next_stage"],"control")
        after_intermediate=next(c for c in self.client.get("/api/learning",headers=trainee).json()
                                if c["id"]==self.cid)
        self.assertFalse(after_intermediate["control_passed"])
        self.assertEqual(len(status["questions"]),8)
        control=menu_exam_questions(ch,"control",self.cid)
        rid2=str(uuid.uuid4())
        result=self.client.post(path+"/control/submit",headers=trainee,json={
            "request_id":rid2,"answers":answers(control)})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()["score"],100)
        finished=self.client.get(path,headers=trainee).json()
        self.assertTrue(finished["control_passed"])
        self.assertIsNone(finished["next_stage"])
        ready=next(c for c in self.client.get("/api/learning",headers=trainee).json()
                   if c["id"]==self.cid)
        self.assertTrue(ready["control_passed"])
        self.assertTrue(self.client.get(f"/api/learning/{self.cid}",headers=trainee)
                        .json()["control_passed"])
        coworker_catalog=next(c for c in self.client.get("/api/learning",headers=coworker).json()
                              if c["id"]==self.cid)
        self.assertFalse(coworker_catalog["control_passed"])
        with self.connect() as c:
            rows=c.execute("""SELECT stage,questions,signature FROM menu_assessment_attempts
                WHERE staff_id=101 ORDER BY id""").fetchall()
            self.assertEqual([x["stage"] for x in rows],["intermediate","control"])
            self.assertEqual(len(rows[1]["questions"]),8)
            self.assertTrue(all(x["signature"]==self.signature for x in rows))
            c.execute("""UPDATE dish_cards SET ingredients=%s,
                updated_at=now()+interval '1 second' WHERE title='Ролл 8'""",
                (Jsonb(["Рис","Нори","Арахис"]),))
        stale=self.client.get(path,headers=trainee)
        self.assertEqual(stale.status_code,409)
        stale_state=next(c for c in self.client.get("/api/learning",headers=trainee).json()
                         if c["id"]==self.cid)
        self.assertTrue(stale_state["staged_menu"])
        self.assertFalse(stale_state["control_passed"])
        with self.connect() as c:
            stored=c.execute("SELECT count(*) AS n FROM menu_assessment_attempts").fetchone()["n"]
            self.assertEqual(stored,2)
        with self.connect() as c:
            c.execute("UPDATE courses SET archived=true WHERE id=%s",(self.cid,))
        self.assertEqual(self.client.get(path,headers=trainee).status_code,404)


if __name__=="__main__":
    unittest.main()
