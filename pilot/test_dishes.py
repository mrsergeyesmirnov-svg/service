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

if __name__=="__main__":
    unittest.main()
