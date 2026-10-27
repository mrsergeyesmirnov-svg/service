"""Regression checks for closed course generation, no live provider calls."""
import os
import json
import unittest
from unittest.mock import patch, MagicMock

import httpx
from fastapi import HTTPException
from course_ai import dish_review_chapters, excerpt_chapters, generate_review_drafts, validate_generated


def reviewed(ingredients=None, description=""):
    return {
        "kind": "dish", "title": "Ролл MOJO", "section": "Роллы",
        "ingredients": ingredients if ingredients is not None else ["Рис", "Нори", "Лосось"],
        "description": description, "allergens": "", "source": "MOJO ТТК", "source_page": 14,
    }


def sample_generation(valid_case=True):
    return {
        "questions":[
            {"type":"single","question":f"Проверенный вопрос {i}",
             "options":["Ответ А","Ответ Б","Ответ В"],
             "correct":[0],"explanation":"Сверить с ТТК","chapter":0}
            for i in range(3)
        ],
        "cases":[{
            "title":"Гость уточняет заказ",
            "competency":"Общение с гостем",
            "action":"Уточняет запрос и сверяет сведения с ТТК",
            "scenario":"Гость хочет уточнить состав блюда.",
            "criteria":["Уточняет пожелания","Обращается к утверждённому источнику"]
                if valid_case else ["Только один критерий"],
            "chapter":0
        }]
    }


def model_reply(content):
    response=MagicMock()
    response.json.return_value={"choices":[{"message":{"content":content}}]}
    return response


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

    def test_case_with_one_bad_criterion_does_not_discard_valid_quiz(self):
        chapters=dish_review_chapters([reviewed()])
        questions,cases=validate_generated(sample_generation(valid_case=False),chapters)
        self.assertEqual(len(questions),3)
        self.assertEqual(len(cases),0)
        self.assertTrue(all(q["source"]=="MOJO ТТК, стр. 14" for q in questions))

    def test_single_index_integer_is_safe_to_normalize(self):
        chapters=dish_review_chapters([reviewed()])
        raw=sample_generation()
        raw["questions"][0]["correct"]=0
        questions,cases=validate_generated(raw,chapters)
        self.assertEqual(questions[0]["correct"],0)
        self.assertEqual(len(cases),1)

    def test_malformed_json_automatically_retries_once_and_recovers(self):
        chapters=dish_review_chapters([reviewed()])
        with patch.dict(os.environ,{"YANDEX_API_KEY":"synthetic","YANDEX_FOLDER_ID":"synthetic"}):
            with patch("course_ai.httpx.Client") as client:
                client.return_value.__enter__.return_value.post.side_effect=[
                    model_reply('{"questions": ['),
                    model_reply(json.dumps(sample_generation(),ensure_ascii=False))
                ]
                questions,cases=generate_review_drafts(chapters)
                calls=client.return_value.__enter__.return_value.post.call_args_list
        self.assertEqual(len(calls),2)
        self.assertEqual(len(questions),3)
        self.assertEqual(len(cases),1)
        self.assertEqual(calls[1].kwargs["json"]["temperature"],0)
        self.assertIn("ПРЕДЫДУЩИЙ ОТВЕТ",calls[1].kwargs["json"]["messages"][0]["content"])

    def test_invalid_question_answer_retries_without_weaker_validation(self):
        chapters=dish_review_chapters([reviewed()])
        bad=sample_generation()
        bad["questions"][0]["correct"]=[99]
        with patch.dict(os.environ,{"YANDEX_API_KEY":"synthetic","YANDEX_FOLDER_ID":"synthetic"}):
            with patch("course_ai.httpx.Client") as client:
                response=model_reply(json.dumps(bad,ensure_ascii=False))
                client.return_value.__enter__.return_value.post.return_value=response
                with self.assertRaises(HTTPException) as e:
                    generate_review_drafts(chapters)
                calls=client.return_value.__enter__.return_value.post.call_count
        self.assertEqual(calls,2)
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
        self.assertIn("дважды",e.exception.detail)
        self.assertEqual(client.return_value.__enter__.return_value.post.call_count,2)


if __name__ == "__main__":
    unittest.main()
