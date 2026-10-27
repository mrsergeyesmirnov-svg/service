"""Regression checks for closed course generation, no live provider calls."""
import os
import json
import unittest
from unittest.mock import patch, MagicMock

import httpx
from fastapi import HTTPException
from course_ai import dish_review_chapters, excerpt_chapters, generate_review_drafts, validate_generated, _one_question, _generate_one_batch, planned_question_count


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

    def test_one_ai_request_contains_one_question_and_no_case(self):
        chapter=dish_review_chapters([reviewed()])[0]
        response=model_reply(json.dumps({
            "type":"single","question":"Что уточнить перед рекомендацией?",
            "options":["Состав по ТТК","Срок доставки","Номер смены"],
            "correct":[0],"explanation":"Уточнить по утверждённой ТТК"
        },ensure_ascii=False))
        with patch.dict(os.environ,{"YANDEX_API_KEY":"synthetic","YANDEX_FOLDER_ID":"synthetic"}):
            with patch("course_ai.httpx.Client") as client:
                client.return_value.__enter__.return_value.post.return_value=response
                q=_one_question(chapter,0)
                payload=client.return_value.__enter__.return_value.post.call_args.kwargs["json"]
        self.assertEqual(q["correct"],0)
        self.assertEqual(q["source"],"MOJO ТТК, стр. 14")
        self.assertEqual(client.return_value.__enter__.return_value.post.call_count,1)
        self.assertIn("type",payload["response_format"]["json_schema"]["schema"]["properties"])
        self.assertNotIn("cases",payload["response_format"]["json_schema"]["schema"]["properties"])

    def test_one_bad_answer_does_not_erase_three_good_questions(self):
        chapters=dish_review_chapters([
            dict(reviewed(),title=f"Ролл {i}") for i in range(16)
        ])
        calls=[]
        def fake_one(chapter,variant):
            calls.append((chapter["title"],variant))
            if variant==1:
                raise HTTPException(502,"ИИ дважды вернул некорректный вопрос")
            return {"type":"single","question":f"{chapter['title']} — вопрос {variant}",
                "options":["А","Б","В"],"correct":0,
                "explanation":"Проверить по ТТК","source":chapter["source"]}
        with patch("course_ai._one_question",side_effect=fake_one):
            with patch("course_ai._one_case",side_effect=HTTPException(502,"bad case")):
                questions,cases=_generate_one_batch(chapters)
        self.assertEqual(len(questions),4)
        self.assertEqual(cases,[])
        self.assertEqual(len(calls),5)
        self.assertEqual(planned_question_count(chapters),4)

    def test_all_question_failures_raise_not_a_fake_published_test(self):
        chapters=dish_review_chapters([reviewed()])
        with patch("course_ai._one_question",side_effect=HTTPException(502,
                "ИИ дважды вернул некорректный вопрос")) as single:
            with patch("course_ai._one_case") as cases:
                with self.assertRaises(HTTPException) as e:
                    generate_review_drafts(chapters)
        self.assertEqual(e.exception.status_code,502)
        self.assertIn("Недостаточно",e.exception.detail)
        self.assertEqual(single.call_count,5)
        cases.assert_not_called()

    def test_malformed_single_question_is_retried_once(self):
        chapter=dish_review_chapters([reviewed()])[0]
        valid={"type":"single","question":"Что проверим?",
            "options":["Источник","Догадку","Сплетни"],
            "correct":[0],"explanation":"По источнику"}
        with patch.dict(os.environ,{"YANDEX_API_KEY":"synthetic","YANDEX_FOLDER_ID":"synthetic"}):
            with patch("course_ai.httpx.Client") as client:
                client.return_value.__enter__.return_value.post.side_effect=[
                    model_reply('{"type":'),
                    model_reply(json.dumps(valid,ensure_ascii=False))
                ]
                question=_one_question(chapter)
        self.assertEqual(question["correct"],0)
        self.assertEqual(client.return_value.__enter__.return_value.post.call_count,2)

    def test_bad_correct_index_remains_blocked_after_retry(self):
        chapter=dish_review_chapters([reviewed()])[0]
        bad={"type":"single","question":"Что выбрать?",
            "options":["А","Б","В"],"correct":[99],"explanation":"По ТТК"}
        with patch.dict(os.environ,{"YANDEX_API_KEY":"synthetic","YANDEX_FOLDER_ID":"synthetic"}):
            with patch("course_ai.httpx.Client") as client:
                client.return_value.__enter__.return_value.post.return_value=model_reply(
                    json.dumps(bad,ensure_ascii=False))
                with self.assertRaises(HTTPException) as e:
                    _one_question(chapter)
        self.assertEqual(e.exception.status_code,502)
        self.assertEqual(client.return_value.__enter__.return_value.post.call_count,2)

    def test_provider_timeout_explained_without_leaking_source(self):
        chapter=dish_review_chapters([reviewed()])[0]
        with patch.dict(os.environ, {"YANDEX_API_KEY":"synthetic","YANDEX_FOLDER_ID":"synthetic"}):
            with patch("course_ai.httpx.Client") as client:
                client.return_value.__enter__.return_value.post.side_effect=httpx.ReadTimeout("internal")
                with self.assertRaises(HTTPException) as e:
                    _one_question(chapter)
        self.assertEqual(e.exception.status_code,504)
        self.assertIn("35 секунд",e.exception.detail)
        self.assertNotIn("internal",e.exception.detail)



if __name__ == "__main__":
    unittest.main()
