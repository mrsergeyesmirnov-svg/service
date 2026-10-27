"""Regression checks for closed course generation, no live provider calls."""
import os
import unittest
from unittest.mock import patch, MagicMock

import httpx
from fastapi import HTTPException
from course_ai import dish_review_chapters, excerpt_chapters, generate_review_drafts


def reviewed(ingredients=None, description=""):
    return {
        "kind": "dish", "title": "Ролл MOJO", "section": "Роллы",
        "ingredients": ingredients if ingredients is not None else ["Рис", "Нори", "Лосось"],
        "description": description, "allergens": "", "source": "MOJO ТТК", "source_page": 14,
    }


class DraftGenerationTests(unittest.TestCase):
    def test_optional_description_does_not_block_verified_recipe(self):
        chapters = dish_review_chapters([reviewed(description="")])
        self.assertEqual(len(chapters), 1)
        self.assertIn("Лосось", chapters[0]["body"])
        self.assertNotIn("Описание и подача", chapters[0]["body"])
        self.assertEqual(len(excerpt_chapters(chapters)), 1)

    def test_no_ingredient_recipe_still_blocked(self):
        with self.assertRaises(HTTPException) as e:
            dish_review_chapters([reviewed(ingredients=[])])
        self.assertEqual(e.exception.status_code, 409)

    def test_large_menu_generates_batches_without_creating_more_courses(self):
        # Original MOJO roll section has 37 slide-derived cards. No real AI calls.
        chapters = dish_review_chapters([
            dict(reviewed(description=""), title=f"Ролл {i}") for i in range(37)
        ])
        calls = []
        def fake_batch(part):
            calls.append([p["title"] for p in part])
            name = part[0]["title"]
            q = dict(type="single", question=f"Вопрос по {name}",
                     options=["Верно", "Неверно"], correct=0,
                     explanation="По утверждённой ТТК", source=part[0]["source"])
            c = dict(title=f"Ситуация {name}", source=part[0]["source"])
            return [q], [c]
        with patch("course_ai._generate_one_batch", side_effect=fake_batch):
            questions, cases = generate_review_drafts(chapters)
        self.assertEqual(sorted(map(len,calls)), [5,16,16])
        self.assertEqual({title for batch in calls for title in batch},
                         {f"Ролл {i}" for i in range(37)})
        self.assertEqual(len(questions), 3)
        self.assertEqual(len(cases), 3)

    def test_full_80_dish_course_and_bounds(self):
        chapters = dish_review_chapters([
            dict(reviewed(), title=f"Позиция {i}") for i in range(80)
        ])
        lengths = []
        def fake_batch(part):
            lengths.append(len(part))
            return [dict(question=f"Q {part[0]['title']}")], []
        with patch("course_ai._generate_one_batch", side_effect=fake_batch):
            questions, _ = generate_review_drafts(chapters)
        self.assertEqual(sorted(lengths), [16] * 5)
        self.assertEqual(len(questions), 5)
        with self.assertRaises(HTTPException):
            dish_review_chapters([reviewed() for _ in range(81)])
        with self.assertRaises(HTTPException):
            generate_review_drafts([])

    def test_one_failed_batch_keeps_generator_all_or_nothing(self):
        chapters = [dict(title=f"Chapter {i}", body="Текст", source="Source")
                    for i in range(37)]
        def fake_batch(part):
            if part[0]["title"] == "Chapter 16":
                raise HTTPException(502, "Model invalid, no draft saved")
            return ([dict(question="Q")], [])
        with patch("course_ai._generate_one_batch", side_effect=fake_batch):
            with self.assertRaises(HTTPException) as e:
                generate_review_drafts(chapters)
        self.assertEqual(e.exception.status_code,502)

    def test_provider_timeout_explained_without_leaking_source(self):
        with patch.dict(os.environ, {"YANDEX_API_KEY": "synthetic", "YANDEX_FOLDER_ID": "synthetic"}):
            with patch("course_ai.httpx.Client") as client:
                client.return_value.__enter__.return_value.post.side_effect=httpx.ReadTimeout("internal")
                with self.assertRaises(HTTPException) as e:
                    generate_review_drafts(dish_review_chapters([reviewed()]))
        self.assertEqual(e.exception.status_code,504)
        self.assertIn("45 секунд",e.exception.detail)
        self.assertNotIn("internal",e.exception.detail)

    def test_invalid_answer_explained_as_validation(self):
        with patch.dict(os.environ, {"YANDEX_API_KEY": "synthetic", "YANDEX_FOLDER_ID": "synthetic"}):
            with patch("course_ai.httpx.Client") as client:
                response=MagicMock()
                response.json.return_value={"choices":[{"message":{"content":"not-json"}}]}
                client.return_value.__enter__.return_value.post.return_value=response
                with self.assertRaises(HTTPException) as e:
                    generate_review_drafts(dish_review_chapters([reviewed()]))
        self.assertEqual(e.exception.status_code,502)
        self.assertIn("структуры",e.exception.detail)


if __name__ == "__main__":
    unittest.main()
