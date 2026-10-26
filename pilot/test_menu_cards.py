"""Menu recall: sourced compositions only, signed access and durable PostgreSQL ratings."""
import os
import uuid
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

import server
from menu_cards import menu_pairs
from dish_lessons import dish_chapters, reviewed_dish_signature
from test_pilot import signed


def dish(name, components, index):
    return {
        "kind": "dish", "id": "dish-"+str(index)+"-v1", "dish_id": index,
        "title": name, "ingredients": components,
        "source": "MOJO TTK verified", "source_page": index
    }


class MenuCardUnit(unittest.TestCase):
    def test_requires_real_multi_ingredient_approved_dish(self):
        cards = menu_pairs([
            dish("A", ["Лосось","Рис"],1),
            dish("Empty", [],2),
            dish("Only one", ["Лосось"],3),
            {"kind": "text", "title": "Unknown", "ingredients": ["Fake", "Items"]}
        ])
        self.assertEqual(len(cards),2)
        self.assertEqual(cards[0]["answer"],[
            ["Ингредиент","Лосось"], ["Ингредиент","Рис"]])
        self.assertEqual(cards[-1]["answer"], [["Название","A"]])

    def test_reverse_recognizes_non_unique_recipe(self):
        cards = menu_pairs([
            dish("Первое название", ["Рис", "Лосось"],1),
            dish("Второе название", ["Лосось", "Рис"],2)
        ])
        self.assertEqual(len(cards),3)
        self.assertEqual(cards[-1]["answer"],[
            ["Название","Первое название"], ["Название","Второе название"]])

    def test_recipe_version_invalidation_and_stable_ids(self):
        original = menu_pairs([dish("А",["Рис","Нори"],1)])
        repeat = menu_pairs([dish("А",["Рис","Нори"],1)])
        changed = menu_pairs([dish("А",["Рис","Авокадо"],1)])
        self.assertEqual([p["id"] for p in original],[p["id"] for p in repeat])
        self.assertNotEqual(original[0]["id"],changed[0]["id"])
        self.assertNotEqual(original[1]["id"],changed[1]["id"])


@unittest.skipUnless(os.getenv("DATABASE_URL"), "PostgreSQL integration requires DATABASE_URL")
class MenuCardIntegration(unittest.TestCase):
    def setUp(self):
        self.schema = "pilot_menu_test_"+uuid.uuid4().hex
        self.real_db = server.db
        with self.real_db() as c:
            c.execute("CREATE SCHEMA "+self.schema)
        def connect():
            return psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row,
                                   options="-c search_path="+self.schema)
        self.connect = connect
        self.patches = [
            patch.object(server,"db",connect),
            patch.object(server,"TOKEN","test-token"),
            patch.object(server,"OWNER",999)
        ]
        for p in self.patches:p.start()
        with connect() as c:
            c.execute((Path(__file__).parent/"schema.sql").read_text())
            c.execute("""INSERT INTO staff(id,name,role,restaurant,bot_started) VALUES
              (101,'Trainee','trainee','MOJO',true),
              (102,'Waiter','waiter','MOJO',true),
              (103,'Foreign','local','OTHER',true),
              (999,'Owner','manager','MOJO',true)""")
            course = c.execute("""INSERT INTO courses
              (author,restaurant,title,kind,body,source,questions,pass_score,published)
              VALUES (999,'MOJO','Основное меню','service','Курс','MOJO ТТК','[]',80,true)
              RETURNING id""").fetchone()
            self.cid = course["id"]
            ids = []
            for name,ings in [("Ролл 1",["Рис","Нори"]),("Ролл 2",["Нори","Лосось"]),("Непроверенный",[])]:
                row = c.execute("""INSERT INTO dish_cards
                  (restaurant,created_by,title,section,ingredients,published)
                  VALUES('MOJO',999,%s,'Роллы',%s,true) RETURNING id""",
                  (name,Jsonb(ings))).fetchone()
                ids.append(row["id"])
            for i,item in enumerate(ids):
                c.execute("""INSERT INTO course_dishes(course_id,dish_id,position)
                    VALUES(%s,%s,%s)""",(self.cid,item,i))
            approved = dish_chapters(c,self.cid,"MOJO")
            c.execute("UPDATE courses SET reviewed_dish_signature=%s WHERE id=%s",
                      (reviewed_dish_signature(approved),self.cid))
        self.client=TestClient(server.app)

    def tearDown(self):
        for p in self.patches:p.stop()
        with self.real_db() as c:c.execute("DROP SCHEMA "+self.schema+" CASCADE")

    def auth(self,uid):
        r=self.client.post("/api/login",json={"initData":signed(uid)})
        self.assertEqual(r.status_code,200,r.text)
        return {"Authorization":"Bearer "+r.json()["token"]}

    def test_no_leakage_persisted_progress_and_recipe_invalidation(self):
        trainee=self.auth(101);other=self.auth(102);foreign=self.auth(103)
        path=f"/api/menu-cards/{self.cid}"
        self.assertEqual(self.client.get(path,headers=foreign).status_code,404)
        data=self.client.get(path,headers=trainee)
        self.assertEqual(data.status_code,200,data.text)
        pairs=data.json()["pairs"]
        self.assertEqual(len(pairs),4)  # 2 approved dishes * 2 directions
        self.assertEqual(data.json()["ratings"],{})
        self.assertEqual(self.client.post(path+"/rating",headers=trainee,
                         json={"id":"not-real","rating":"know"}).status_code,422)
        self.assertEqual(self.client.post(path+"/rating",headers=trainee,
                         json={"id":pairs[0]["id"],"rating":"invalid"}).status_code,422)
        saved=self.client.post(path+"/rating",headers=trainee,
                              json={"id":pairs[0]["id"],"rating":"know"})
        self.assertEqual(saved.status_code,200,saved.text)
        self.assertEqual(self.client.get(path,headers=trainee).json()["ratings"],
                         {pairs[0]["id"]:"know"})
        self.assertEqual(self.client.get(path,headers=other).json()["ratings"],{})
        with self.connect() as c:
            c.execute("""UPDATE dish_cards SET ingredients=%s,updated_at=now()+interval '1 second'
                         WHERE title='Ролл 1'""", (Jsonb(["Рис","Авокадо"]),))
        stale=self.client.get(path,headers=trainee)
        self.assertEqual(stale.status_code,200,stale.text)
        self.assertEqual(stale.json()["pairs"],[])
        self.assertEqual(stale.json()["ratings"],{})
        self.assertEqual(self.client.post(path+"/rating",headers=trainee,
                          json={"id":pairs[0]["id"],"rating":"know"}).status_code,422)
        with self.connect() as c:
            c.execute("UPDATE courses SET archived=true WHERE id=%s",(self.cid,))
        self.assertEqual(self.client.get(path,headers=trainee).status_code,404)


if __name__=="__main__":
    unittest.main()
