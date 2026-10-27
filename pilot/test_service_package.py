"""Manager-only servicebook import tests, isolated to a disposable PostgreSQL schema."""
import hashlib
import os
import uuid
import unittest
from pathlib import Path
from unittest.mock import patch

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi.testclient import TestClient

import server


def synthetic_package():
    source = "Synthetic MOJO service standard v1"
    return {
        "format": "mojo-service-pilot-v1",
        "source": source,
        "pass_score": 80,
        "chapters": [
            {"title":"Встреча", "body":"Приветствие с улыбкой и помощь гостю.",
             "source":source},
            {"title":"Завершение", "body":"Поблагодари гостя и узнай впечатления.",
             "source":source},
        ],
        "questions": [
            {"type":"single","question":"Что делают при встрече?",
             "options":["Приветствуют","Игнорируют","Спорят"],"correct":0,
             "explanation":"Стандарт требует приветствия.","source":source},
            {"type":"multiple","question":"Что делать при завершении?",
             "options":["Поблагодарить","Уточнить впечатления","Не обращать внимание"],"correct":[0,1],
             "explanation":"Стандарт требует интереса и благодарности.","source":source},
            {"type":"single","question":"Как реагировать на недовольство?",
             "options":["Выслушать","Перебить","Проигнорировать"],"correct":0,
             "explanation":"Профессиональный подход — выслушать.","source":source},
        ],
        "cases":[
            {"title":"Тестовая встреча","competency":"Приветствие",
             "action":"Приветствует и предлагает помощь",
             "scenario":"Гость вошёл в ресторан и ожидает внимания.",
             "criteria":["Приветствие","Предложение помощи"],
             "source":source}
        ]
    }


@unittest.skipUnless(os.getenv("DATABASE_URL"), "requires PostgreSQL test schema")
class ServicePackageIntegration(unittest.TestCase):
    def setUp(self):
        self.schema = "mojo_service_test_" + uuid.uuid4().hex
        self.original_db = server.db
        with self.original_db() as c:
            c.execute("CREATE SCHEMA " + self.schema)

        def connect():
            return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row,
                                   options="-c search_path=" + self.schema)

        self.connect = connect
        self.patch = patch.object(server, "db", connect)
        self.patch.start()
        with connect() as c:
            c.execute((Path(__file__).parent / "schema.sql").read_text())
            c.execute("""INSERT INTO staff(id,name,role,restaurant,bot_started) VALUES
              (10,'Manager','manager','MOJO',true),
              (11,'Trainee','trainee','MOJO',true),
              (12,'Other manager','local','OTHER',true)""")
            for uid in (10,11,12):
                token = "service-" + str(uid)
                c.execute("""INSERT INTO sessions(token_hash,staff_id,expires_at)
                    VALUES(%s,%s,now()+interval '1 hour')""",
                    (hashlib.sha256(token.encode()).hexdigest(),uid))
            self.cid = c.execute("""INSERT INTO courses(author,restaurant,title,kind,body,
                source,questions,pass_score)
                VALUES(10,'MOJO','сервис бук','service','Ранее сохранённые заметки',
                       'Ранний черновик',%s,80) RETURNING id""",
                       (Jsonb([]),)).fetchone()["id"]
            self.menu_cid = c.execute("""INSERT INTO courses(author,restaurant,title,kind,body,
                source,questions,pass_score)
                VALUES(10,'MOJO','роллы','service','Ранее сохранённые заметки',
                       'Ранний черновик',%s,80) RETURNING id""",
                       (Jsonb([]),)).fetchone()["id"]
        self.client = TestClient(server.app)

    def tearDown(self):
        self.patch.stop()
        with self.original_db() as c:
            c.execute("DROP SCHEMA " + self.schema + " CASCADE")

    def headers(self, uid):
        return {"Authorization": "Bearer service-" + str(uid)}

    def url(self, cid=None):
        return "/api/learning/" + str(cid or self.cid) + "/service-package"

    def test_service_package_unblocks_existing_draft_but_never_auto_publishes(self):
        m = self.headers(10)
        bad = self.client.post("/api/courses/"+str(self.cid)+"/publish",
                               headers=m,json={"reviewed":True})
        self.assertEqual(bad.status_code,409,bad.text)

        unauthed=self.client.post(self.url(),json=synthetic_package(),headers=self.headers(11))
        self.assertEqual(unauthed.status_code,403,unauthed.text)
        foreign=self.client.post(self.url(),json=synthetic_package(),headers=self.headers(12))
        self.assertEqual(foreign.status_code,403,foreign.text)
        wrong_category=self.client.post(self.url(self.menu_cid),json=synthetic_package(),headers=m)
        self.assertEqual(wrong_category.status_code,409,wrong_category.text)

        loaded=self.client.post(self.url(),json=synthetic_package(),headers=m)
        self.assertEqual(loaded.status_code,200,loaded.text)
        self.assertEqual((loaded.json()["chapters"],loaded.json()["questions"],
                          loaded.json()["cases_created"],loaded.json()["published"]),
                         (2,3,1,False))
        with self.connect() as c:
            r=c.execute("SELECT published,questions,source FROM courses WHERE id=%s",
                        (self.cid,)).fetchone()
            self.assertFalse(r["published"])
            self.assertEqual(len(r["questions"]),3)
            row=c.execute("SELECT chapters FROM course_text_outline WHERE course_id=%s",
                          (self.cid,)).fetchone()
            self.assertEqual(len(row["chapters"]),2)
            case=c.execute("SELECT published FROM case_scenarios WHERE restaurant='MOJO'").fetchone()
            self.assertFalse(case["published"])

        same=self.client.post(self.url(),json=synthetic_package(),headers=m)
        self.assertEqual(same.status_code,200,same.text)
        self.assertTrue(same.json()["duplicate"])
        changed=synthetic_package()
        changed["questions"][0]["question"]="Изменённый вопрос"
        guard=self.client.post(self.url(),json=changed,headers=m)
        self.assertEqual(guard.status_code,409,guard.text)

        published=self.client.post("/api/courses/"+str(self.cid)+"/publish",
                                   headers=m,json={"reviewed":True})
        self.assertEqual(published.status_code,200,published.text)
        available=self.client.get("/api/learning/"+str(self.cid),headers=self.headers(11))
        self.assertEqual(available.status_code,200,available.text)
        detail=available.json()
        self.assertEqual(len(detail["chapters"]),2)
        self.assertEqual(len(detail["questions"]),3)
        self.assertNotIn("correct",detail["questions"][0])
        # Full pilot acceptance: manager assigns -> trainee studies -> quiz -> manager sees result.
        from datetime import date,timedelta
        deadline=(date.today()+timedelta(days=3)).isoformat()
        assignment=self.client.post("/api/assignments",headers=m,json={
            "course_id":self.cid,"staff_ids":[11],"deadline":deadline,"max_attempts":2})
        self.assertEqual(assignment.status_code,200,assignment.text)
        self.assertEqual(len(assignment.json()["created"]),1)
        aid=assignment.json()["created"][0]
        trainee=self.headers(11)
        early=self.client.post("/api/assignments/"+str(aid)+"/submit",headers=trainee,
              json={"request_id":str(uuid.uuid4()),"answers":[0,[0,1],0]})
        self.assertEqual(early.status_code,409,early.text)
        for chapter in detail["chapters"]:
            read=self.client.post("/api/learning/"+str(self.cid)+"/read",headers=trainee,
                                  json={"chapter_id":chapter["id"]})
            self.assertEqual(read.status_code,200,read.text)
        acknowledged=self.client.post("/api/assignments/"+str(aid)+"/acknowledge",
                                      headers=trainee)
        self.assertEqual(acknowledged.status_code,200,acknowledged.text)
        rid=str(uuid.uuid4())
        attempt=self.client.post("/api/assignments/"+str(aid)+"/submit",headers=trainee,
             json={"request_id":rid,"answers":[0,[0,1],0]})
        self.assertEqual(attempt.status_code,200,attempt.text)
        self.assertEqual((attempt.json()["score"],attempt.json()["passed"]),(100,True))
        manager_results=self.client.get("/api/assignments/"+str(aid)+"/results",headers=m)
        self.assertEqual(manager_results.status_code,200,manager_results.text)
        self.assertEqual(len(manager_results.json()["attempts"]),1)
        self.assertTrue(manager_results.json()["attempts"][0]["passed"])
        repeat=self.client.post("/api/assignments/"+str(aid)+"/submit",headers=trainee,
             json={"request_id":rid,"answers":[0,[0,1],0]})
        self.assertEqual(repeat.json(),attempt.json())
        second=self.client.post("/api/assignments/"+str(aid)+"/submit",headers=trainee,
             json={"request_id":str(uuid.uuid4()),"answers":[1,[2],1]})
        self.assertEqual(second.status_code,409,second.text)
        after=self.client.post(self.url(),json=synthetic_package(),headers=m)
        self.assertEqual(after.status_code,409,after.text)

    def test_replacement_requires_explicit_confirmation_and_does_not_duplicate_cases(self):
        first=self.client.post(self.url(),json=synthetic_package(),headers=self.headers(10))
        self.assertEqual(first.status_code,200,first.text)
        changed=synthetic_package()
        changed["chapters"][1]["body"]="Поблагодари гостей после визита."
        changed["replace"]=True
        second=self.client.post(self.url(),json=changed,headers=self.headers(10))
        self.assertEqual(second.status_code,200,second.text)
        self.assertEqual(second.json()["cases_created"],0)
        with self.connect() as c:
            self.assertEqual(c.execute("SELECT count(*) AS n FROM case_scenarios").fetchone()["n"],1)


if __name__ == "__main__":
    unittest.main()
