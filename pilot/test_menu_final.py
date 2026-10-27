"""Exact 8-section final checks on disposable PostgreSQL, no provider calls."""
import os
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi import HTTPException
from fastapi.testclient import TestClient

import server
from dish_lessons import dish_chapters, reviewed_dish_signature
from menu_final import SLOTS, select_questions
from menu_assessments import menu_exam_questions
from test_pilot import signed


class FinalUnit(unittest.TestCase):
    def test_balanced_exactly_50_from_eight_blocks(self):
        source={}
        for i,(key,label) in enumerate(SLOTS):
            n=7 if key=="desserts" else 25
            source[key]={"id":i+1,"chapters":[{
                "kind":"dish","title":label+" "+str(j),"section":label,
                "ingredients":["Ингредиент 1","Ингредиент 2"],"source":"MOJO ТТК"
            } for j in range(n)]}
        questions=select_questions(source)
        self.assertEqual(len(questions),50)
        for _,label in SLOTS:
            self.assertGreaterEqual(sum(q["question"].startswith(label+" ·") for q in questions),6)
        self.assertTrue(all(q["type"]=="ingredients" for q in questions))

    def test_fails_if_a_section_has_only_five_approved_dishes(self):
        source={}
        for i,(key,label) in enumerate(SLOTS):
            source[key]={"id":i+1,"chapters":[{
                "kind":"dish","title":label+" "+str(j),"section":label,
                "ingredients":["Рис","Нори"],"source":"MOJO ТТК"
            } for j in range(5 if key=="desserts" else 7)]}
        with self.assertRaises(HTTPException) as e:select_questions(source)
        self.assertEqual(e.exception.status_code,409)


@unittest.skipUnless(os.environ.get("DATABASE_URL"),"PostgreSQL required")
class FinalIntegration(unittest.TestCase):
    def setUp(self):
        self.schema="menu_final_"+uuid.uuid4().hex
        self.original=server.db
        with self.original() as c:c.execute("CREATE SCHEMA "+self.schema)
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
                (102,'Второй','trainee','MOJO',true),
                (103,'Чужая точка','local','OTHER',true),
                (999,'Менеджер','manager','MOJO',true)""")
            self.slots={}
            self.signatures={}
            for key,label in SLOTS:
                cid=c.execute("""INSERT INTO courses
                    (author,restaurant,title,kind,body,source,questions,pass_score,published)
                    VALUES(999,'MOJO',%s,'ttk','Материал','ТТК','[]',80,true) RETURNING id""",
                    (label,)).fetchone()["id"]
                self.slots[key]=cid
                for i in range(7):
                    did=c.execute("""INSERT INTO dish_cards
                      (restaurant,created_by,title,section,ingredients,published)
                      VALUES('MOJO',999,%s,%s,%s,true) RETURNING id""",
                      (f"{label} {i+1}",label,Jsonb(["Рис","Нори",f"Соус {i+1}"]))).fetchone()["id"]
                    c.execute("INSERT INTO course_dishes(course_id,dish_id,position) VALUES(%s,%s,%s)",
                              (cid,did,i))
                sig=reviewed_dish_signature(dish_chapters(c,cid,"MOJO"))
                self.signatures[key]=sig
                c.execute("UPDATE courses SET reviewed_dish_signature=%s WHERE id=%s",(sig,cid))
        self.client=TestClient(server.app)

    def tearDown(self):
        for p in self.patches:p.stop()
        with self.original() as c:c.execute("DROP SCHEMA "+self.schema+" CASCADE")

    def auth(self,uid):
        r=self.client.post("/api/login",json={"initData":signed(uid)})
        self.assertEqual(r.status_code,200,r.text)
        return {"Authorization":"Bearer "+r.json()["token"]}

    def test_manager_mapping_gates_final_and_snapshots_without_old_attempts(self):
        m=self.auth(999);a=self.auth(101);b=self.auth(102);foreign=self.auth(103)
        url="/api/menu-final"
        self.assertFalse(self.client.get(url+"/status",headers=a).json()["configured"])
        unauthorized=self.client.post(url+"/config",headers=a,json={
            "slots":self.slots,"pass_score":85,"confirmed":True})
        self.assertEqual(unauthorized.status_code,403)
        invalid=self.client.post(url+"/config",headers=m,json={
            "slots":{**self.slots,"grill":self.slots["rolls"]},
            "pass_score":85,"confirmed":True})
        self.assertEqual(invalid.status_code,422)
        configured=self.client.post(url+"/config",headers=m,json={
            "slots":self.slots,"pass_score":85,"confirmed":True})
        self.assertEqual(configured.status_code,200,configured.text)
        self.assertEqual(configured.json()["questions"],50)
        pending=self.client.get(url+"/status",headers=a).json()
        self.assertEqual(len(pending["missing"]),8)
        self.assertFalse(pending["ready"])
        self.assertEqual(self.client.post(url+"/submit",headers=a,json={
            "request_id":str(uuid.uuid4()),"answers":[]}).status_code,409)
        with self.connect() as c:
            for key,cid in self.slots.items():
                c.execute("""INSERT INTO menu_assessment_attempts
                  (staff_id,course_id,stage,request_id,signature,questions,answers,score,passed)
                  VALUES(101,%s,'control',%s,%s,'[]','[]',100,true)""",
                  (cid,uuid.uuid4(),self.signatures[key]))
        ready=self.client.get(url+"/status",headers=a).json()
        self.assertTrue(ready["ready"])
        self.assertEqual(len(ready["questions"]),50)
        self.assertFalse(self.client.get(url+"/status",headers=b).json()["ready"])
        # No correct ingredients in pre-submit payload.
        self.assertNotIn("ingredients",ready["questions"][0])
        full_answers=["\n".join(["Рис","Нори",q["question"].split("Соус ") and
                         "Соус "+q["question"].split("Соус ")[-1]])
                      for q in []]  # Build expected answers from the verified DB source below.
        with self.connect() as c:
            from menu_final import select_questions
            from dish_lessons import dish_chapters
            groups={key:{"id":cid,"chapters":dish_chapters(c,cid,"MOJO")}
                    for key,cid in self.slots.items()}
            questions=select_questions(groups)
        full_answers=["\n".join(g[0] for g in q["ingredients"]) for q in questions]
        rid=str(uuid.uuid4())
        payload={"request_id":rid,"answers":full_answers}
        result=self.client.post(url+"/submit",headers=a,json=payload)
        self.assertEqual(result.status_code,200,result.text)
        self.assertTrue(result.json()["passed"])
        self.assertEqual(result.json()["score"],100)
        self.assertTrue(result.json()["in_person_required"])
        duplicate=self.client.post(url+"/submit",headers=a,json=payload)
        self.assertEqual(duplicate.json(),result.json())
        self.assertTrue(self.client.get(url+"/status",headers=a).json()["passed"])
        self.assertFalse(self.client.get(url+"/status",headers=b).json()["passed"])
        with self.connect() as c:
            saved=c.execute("SELECT questions,answers,signature FROM menu_final_attempts").fetchone()
            self.assertEqual(len(saved["questions"]),50)
            self.assertEqual(len(saved["answers"]),50)
            self.assertEqual(c.execute("SELECT count(*) AS n FROM learning_attempts").fetchone()["n"],0)
            c.execute("""UPDATE dish_cards SET ingredients=%s,
                updated_at=now()+interval '1 second'
                WHERE title='Десерты 1'""",(Jsonb(["Клубника","Шоколад"]),))
        self.assertEqual(self.client.get(url+"/status",headers=a).status_code,409)
        self.assertEqual(self.client.get(url+"/status",headers=foreign).json()["configured"],False)


if __name__=="__main__":
    unittest.main()
