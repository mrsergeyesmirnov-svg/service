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

    def test_large_course_requires_sectioning_before_ai_cost(self):
        with self.assertRaises(HTTPException) as e:
            dish_review_chapters([reviewed() for _ in range(17)])
        self.assertEqual(e.exception.status_code, 422)
        self.assertIn("1–16",e.exception.detail)

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
