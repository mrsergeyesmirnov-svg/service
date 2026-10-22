"""Lightweight tests for MOJO dish-card PDF import. Run: python -m unittest test_dishes."""
import io
import unittest

import fitz
from PIL import Image
from fastapi import HTTPException
from dish_extract import extract_pdf
from dishes import validate_card,jpg_thumbnail

class DishCards(unittest.TestCase):
    def test_pdf_extracts_image_and_ingredients(self):
        pdf=fitz.open()
        page=pdf.new_page(width=960,height=540)
        page.insert_text((400,40),"SALADS",fontsize=40)
        page.insert_text((40,100),"Caprese salad",fontsize=32)
        for i,name in enumerate(("Tomato","Mozzarella","Basil")):
            page.insert_text((63,190+24*i),name,fontsize=16)
        image=io.BytesIO()
        Image.new("RGB",(500,350),(220,100,40)).save(image,"JPEG")
        page.insert_image(fitz.Rect(550,110,920,350),stream=image.getvalue())
        cards=extract_pdf(pdf.tobytes())
        self.assertEqual(len(cards),1)
        self.assertEqual(cards[0]["title"],"Caprese salad")
        self.assertIn("Mozzarella",cards[0]["ingredients"])
        self.assertGreater(len(cards[0]["photo"]),150)

    def test_reject_invalid_pdf(self):
        with self.assertRaises(ValueError):
            extract_pdf(b"not pdf")

    def test_validate_card(self):
        c=validate_card({"title":"Салат","section":"Салаты","ingredients":["Томаты","Сыр"],"description":"Подача"})
        self.assertEqual(len(c["ingredients"]),2)
        with self.assertRaises(HTTPException):
            validate_card({"title":"","section":"Салаты","ingredients":[],"description":""})

    def test_image_resize(self):
        f=io.BytesIO()
        Image.new("RGB",(4000,1000)).save(f,"PNG")
        data=jpg_thumbnail(f.getvalue())
        with Image.open(io.BytesIO(data)) as im:
            self.assertLessEqual(im.width,900)

@unittest.skipUnless(__import__("os").getenv("DATABASE_URL"),"needs disposable PostgreSQL test schema")
class DishIntegration(unittest.TestCase):
    def setUp(self):
        import os,uuid,psycopg,server
        from pathlib import Path
        from psycopg.rows import dict_row
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        self.schema="dish_test_"+uuid.uuid4().hex
        self.original=server.db
        with self.original() as c:c.execute("CREATE SCHEMA "+self.schema)
        def connect():
            return psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row,
                                   options="-c search_path="+self.schema)
        self.connect=connect
        self.patch=patch.object(server,"db",connect)
        self.patch.start()
        with connect() as c:
            c.execute((Path(__file__).parent/"schema.sql").read_text())
            c.execute("""INSERT INTO staff(id,name,role,restaurant,bot_started) VALUES
              (10,'Owner','manager','MOJO',true),
              (11,'Trainee','trainee','MOJO',true),
              (12,'Other','local','OTHER',true)""")
            for uid in (10,11,12):
                c.execute("""INSERT INTO sessions(token_hash,staff_id,expires_at)
                  VALUES(%s,%s,now()+interval '1 hour')""",
                  (__import__("hashlib").sha256(("test-"+str(uid)).encode()).hexdigest(),uid))
        self.client=TestClient(server.app)

    def tearDown(self):
        self.patch.stop()
        with self.original() as c:c.execute("DROP SCHEMA "+self.schema+" CASCADE")

    def headers(self,uid):
        return {"Authorization":"Bearer test-"+str(uid)}

    def sample_pdf(self):
        doc=fitz.open()
        p=doc.new_page(width=960,height=540)
        p.insert_text((400,40),"SALADS",fontsize=40)
        p.insert_text((40,100),"Caprese salad",fontsize=32)
        for i,name in enumerate(("Tomato","Mozzarella","Basil")):
            p.insert_text((63,190+i*24),name,fontsize=16)
        pic=io.BytesIO();Image.new("RGB",(500,350),(180,80,40)).save(pic,"JPEG")
        p.insert_image(fitz.Rect(550,110,920,350),stream=pic.getvalue())
        return doc.tobytes()

    def test_manager_import_review_photo_and_archive(self):
        data=self.sample_pdf()
        h={**self.headers(10),"Content-Type":"application/pdf"}
        endpoint="/api/dishes/import"
        self.assertEqual(self.client.post(endpoint,content=data,headers=self.headers(11)|{"Content-Type":"application/pdf"}).status_code,403)
        created=self.client.post(endpoint,content=data,headers=h)
        self.assertEqual(created.status_code,200,created.text)
        self.assertEqual(created.json()["created"],1)
        again=self.client.post(endpoint,content=data,headers=h)
        self.assertEqual(again.json()["skipped"],1)
        cards=self.client.get("/api/dishes",headers=self.headers(10)).json()
        self.assertEqual(len(cards),1)
        card=cards[0]
        cid=card["id"]
        self.assertFalse(card["published"])
        self.assertEqual(self.client.get("/api/dishes",headers=self.headers(11)).json(),[])
        self.assertEqual(self.client.get(f"/api/dishes/{cid}/photo",headers=self.headers(11)).status_code,404)
        self.assertEqual(self.client.get(f"/api/dishes/{cid}/photo",headers=self.headers(10)).status_code,200)
        self.assertEqual(self.client.post(f"/api/dishes/{cid}/publish",headers=self.headers(11),json={"reviewed":True}).status_code,403)
        edit={"title":"Caprese salad","section":"SALADS","ingredients":["Tomato","Mozzarella","Basil"],
              "description":"Manager-reviewed synthetic description"}
        self.assertEqual(self.client.put(f"/api/dishes/{cid}",json=edit,headers=self.headers(12)).status_code,404)
        self.assertEqual(self.client.put(f"/api/dishes/{cid}",json=edit,headers=self.headers(10)).status_code,200)
        self.assertEqual(self.client.post(f"/api/dishes/{cid}/publish",json={"reviewed":True},headers=self.headers(10)).status_code,200)
        self.assertEqual(len(self.client.get("/api/dishes",headers=self.headers(11)).json()),1)
        self.assertEqual(self.client.delete(f"/api/dishes/{cid}",headers=self.headers(10)).status_code,200)
        self.assertEqual(self.client.get("/api/dishes",headers=self.headers(11)).json(),[])

    def test_ai_practice_failure_retry_is_idempotent(self):
        import uuid
        from unittest.mock import patch
        from fastapi import HTTPException
        from psycopg.types.json import Jsonb
        with self.connect() as c:
            cid=c.execute("""INSERT INTO courses(author,restaurant,title,kind,body,source,
                questions,pass_score,published)
                VALUES (10,'MOJO','Тестовый курс','ttk','Состав','Синтетический',
                        %s,80,true) RETURNING id""",(Jsonb([]),)).fetchone()["id"]
            did=c.execute("""INSERT INTO dish_cards(restaurant,created_by,title,section,
              ingredients,description,photo,published)
              VALUES('MOJO',10,'Салат','Салаты',%s,'Подаём охлаждённым',%s,true)
              RETURNING id""",(Jsonb(["Томаты","Сыр"]),b"test-photo")).fetchone()["id"]
            c.execute("INSERT INTO course_dishes(course_id,dish_id,position) VALUES(%s,%s,0)",(cid,did))
        uri=f"/api/learning/{cid}/dish-practice"
        rid=str(uuid.uuid4())
        payload={"dish_id":did,"request_id":rid,"answer":"Сначала уточню ограничения гостя, затем расскажу о проверенном составе блюда."}
        feedback={"summary":"Разбор","strengths":"Верно","improvements":"Сверяй ТТК","next_step":"Повторить"}
        with patch.dict(__import__("os").environ,{"YANDEX_API_KEY":"test-only","YANDEX_FOLDER_ID":"test-folder"}):
            with patch("learning.evaluate_with_yandex",side_effect=[HTTPException(502,"No provider"),feedback]) as call:
                first=self.client.post(uri,json=payload,headers=self.headers(11))
                self.assertEqual(first.status_code,502,first.text)
                second=self.client.post(uri,json=payload,headers=self.headers(11))
                self.assertEqual(second.status_code,200,second.text)
                self.assertEqual(second.json(),feedback)
                third=self.client.post(uri,json=payload,headers=self.headers(11))
                self.assertEqual(third.json(),feedback)
                self.assertEqual(call.call_count,2)
        with self.connect() as c:
            row=c.execute("SELECT status,tries FROM dish_practice_attempts WHERE request_id=%s",(rid,)).fetchone()
            self.assertEqual((row["status"],row["tries"]),("done",2))

    def test_curated_quiz_replaces_legacy_and_saves_question_snapshot(self):
        import uuid
        from psycopg.types.json import Jsonb
        from quiz_cards import approved_card_questions
        from dish_lessons import dish_chapters
        old=[dict(type="single",question="Какой компонент прямо указан в станционке?",options=["Томат","Сыр","Укроп"],correct=1,explanation="Сыр",source="старый тест")]
        with self.connect() as c:
            cid=c.execute("""INSERT INTO courses(author,restaurant,title,kind,body,source,questions,pass_score,published)
                VALUES(10,'MOJO','Кухня. Салаты','ttk','Состав блюд','Синтетический пример',%s,80,true)
                RETURNING id""",(Jsonb(old),)).fetchone()["id"]
            for i,(title,ingredients) in enumerate([
                ("Салат с томатами",["Томаты","Сыр","Оливковое масло","Руккола","Базилик","Соль"]),
                ("Салат с огурцами",["Огурцы","Укроп","Сметана","Яйцо","Горчица","Петрушка"]),
            ]):
                did=c.execute("""INSERT INTO dish_cards(restaurant,created_by,title,section,ingredients,description,photo,published)
                    VALUES('MOJO',10,%s,'Салаты',%s,'Утверждённая подача',%s,true)
                    RETURNING id""",(title,Jsonb(ingredients),b'photo')).fetchone()["id"]
                c.execute("INSERT INTO course_dishes(course_id,dish_id,position) VALUES(%s,%s,%s)",(cid,did,i))
            expected=approved_card_questions(dish_chapters(c,cid,'MOJO'),cid)
        course=self.client.get(f"/api/learning/{cid}",headers=self.headers(11))
        self.assertEqual(course.status_code,200,course.text)
        details=course.json()
        kinds={q["type"] for q in details["questions"]}
        self.assertEqual(kinds,{"ingredients","multiple"})
        self.assertNotIn("прямо указан",str(details["questions"]))
        for ch in details["chapters"]:
            result=self.client.post(f"/api/learning/{cid}/read",headers=self.headers(11),json={"chapter_id":ch["id"]})
            self.assertEqual(result.status_code,200,result.text)
        responses=[
            "\n".join(group[0] for group in q["ingredients"]) if q["type"]=="ingredients" else q["correct"]
            for q in expected
        ]
        result=self.client.post(f"/api/learning/{cid}/submit",headers=self.headers(11),json={
            "request_id":str(uuid.uuid4()),"answers":responses
        })
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()["score"],100)
        self.assertEqual(len(result.json()["review"]),len(expected))
        with self.connect() as c:
            stored=c.execute("SELECT questions FROM learning_attempts WHERE course_id=%s",(cid,)).fetchone()
            self.assertEqual(len(stored["questions"]),len(expected))
        # All approved ingredients are valid in free answers, not just the selected subset.
        from questions import check
        first=next(q for q in expected if q["type"]=="ingredients")
        answer="\n".join([g[0] for g in first["ingredients"]]+first["allowed_extra"])
        self.assertEqual(check(first,answer)["fraction"],1)

    def test_voice_route_requires_login_and_does_not_store_audio(self):
        from unittest.mock import patch
        endpoint="/api/voice/transcribe"
        media=b"\x00\x00\x00\x00ftyp" + b"0"*1024
        with patch("voice.normalize_audio",return_value=b"OggS-test"),patch("voice.yandex_recognize",return_value="Я уточню предпочтения гостя.") as provider:
            denied=self.client.post(endpoint,content=media,headers={"Content-Type":"audio/mp4"})
            self.assertEqual(denied.status_code,401)
            response=self.client.post(endpoint,content=media,headers=self.headers(11)|{"Content-Type":"audio/mp4"})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()["text"],"Я уточню предпочтения гостя.")
            self.assertFalse(response.json()["audio_saved"])
            self.assertEqual(provider.call_count,1)
        with self.connect() as c:
            log=c.execute("SELECT staff_id FROM voice_transcriptions").fetchall()
            self.assertEqual(log,[{"staff_id":11}])

if __name__=="__main__":
    unittest.main()
