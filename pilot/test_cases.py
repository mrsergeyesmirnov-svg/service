import json,os,unittest
from unittest.mock import patch,MagicMock
from fastapi import HTTPException
from cases_api import case_payload,interpret,evaluate_with_yandex,PRIVATE_DATA,public_case
from question_quality import quality_issues

CASE=dict(
    title="Помочь выбрать",competency="Забота о госте",
    action="Выяснять предпочтения",scenario="Гость просит рекомендацию",
    source="MOJO ServiceBook 2026 с. 9",criteria=[
        "Задать несколько вопросов","Предложить с учётом ответов"
    ])

class Cases(unittest.TestCase):
    def test_public_cases_hide_rubrics(self):
        row=dict(id=5,title="Паста",scenario="Гость просит пасту.",source="ServiceBook",published=True,
                 competency="Проактивная забота",action="Уточняет предпочтения",
                 criteria=["Уточняет пожелания","Проверяет изменения с кухней"],archived=False)
        shown=public_case(row)
        self.assertNotIn("criteria",shown)
        self.assertNotIn("competency",shown)
        self.assertNotIn("action",shown)
        self.assertEqual(public_case(row,True)["criteria"],row["criteria"])
    def test_question_quality_flags(self):
        questions=[
         {"question":"Какой компонент прямо указан в станционке ▤?","options":["Замес краба","Бриошь","Шпинат"],"source":"MOJO"},
         {"question":"Что ты спросишь гостя перед рекомендацией?","options":["Предпочтения гостя","Список аллергенов","Согласование с кухней"],"source":"MOJO"}
        ]
        issues=quality_issues(questions)
        self.assertTrue(any(w["question"]==1 and "Повреждённые" in w["message"] for w in issues))
        self.assertFalse(any(w["question"]==2 for w in issues))

    def test_validation(self):
        self.assertEqual(case_payload(CASE)["criteria"][0],"Задать несколько вопросов")
        with self.assertRaises(HTTPException):
            case_payload({**CASE,"criteria":["Повтор","повтор"]})
        with self.assertRaises(HTTPException):
            case_payload({**CASE,"criteria":["Один"]})
    def test_privacy_regex(self):
        self.assertTrue(PRIVATE_DATA.search("email me example@example.com"))
        self.assertTrue(PRIVATE_DATA.search("guest +79991234567"))
        self.assertFalse(PRIVATE_DATA.search("Сначала уточню предпочтения гостя."))
    def test_feedback_shape(self):
        answer={"summary":"Неплохо","strengths":"Уточнил","improvements":"Добавить","next_step":"Повтори"}
        self.assertEqual(interpret(answer),answer)
        with self.assertRaises(ValueError):interpret({"summary":"только"})
    def test_unconfigured(self):
        with patch.dict(os.environ,{"YANDEX_API_KEY":"","YANDEX_FOLDER_ID":""}):
            with self.assertRaises(HTTPException) as e:
                evaluate_with_yandex(CASE,"Сначала уточню пожелания гостя.")
            self.assertEqual(e.exception.status_code,503)
    def test_request_is_rubric_grounded(self):
        response=MagicMock()
        response.json.return_value={"choices":[{"message":{"content":json.dumps({
            "summary":"Разбор","strengths":"Уточнил","improvements":"Проверить состав",
            "next_step":"Ролевая тренировка"})}}]}
        client=MagicMock()
        client.post.return_value=response
        cm=MagicMock()
        cm.__enter__.return_value=client
        with patch.dict(os.environ,{"YANDEX_API_KEY":"test-not-real","YANDEX_FOLDER_ID":"test-folder"}):
            with patch("cases_api.httpx.Client",return_value=cm):
                result=evaluate_with_yandex(CASE,"Я уточню, чего хочет гость.")
        self.assertEqual(result["next_step"],"Ролевая тренировка")
        req=client.post.call_args
        self.assertIn("approved_criteria",req.kwargs["json"]["messages"][1]["content"])
        self.assertNotIn("staff_id",req.kwargs["json"]["messages"][1]["content"])

if __name__=="__main__":unittest.main(verbosity=2)
