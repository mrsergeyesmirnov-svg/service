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

if __name__=="__main__":
    unittest.main()
