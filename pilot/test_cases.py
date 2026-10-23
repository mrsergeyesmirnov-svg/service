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
    def test_generated_recall_requires_the_complete_named_composition(self):
        from quiz_cards import approved_card_questions
        from questions import check, public_question
        cards=[dict(kind='dish',title='Training dish',source='Synthetic',dish_id=1,
                    ingredients=['Alpha','Beta','Gamma','Delta','Epsilon','Zeta'])]
        q=approved_card_questions(cards,1)[0]
        self.assertEqual(len(q['ingredients']),6)
        self.assertIn('все компоненты (6)',q['question'])
        self.assertEqual(check(q,'Zeta;Epsilon;Delta;Gamma;Beta;Alpha')['fraction'],1)
        self.assertLess(check(q,'Alpha;Beta;Gamma;Delta;Epsilon')['fraction'],1)
        self.assertNotIn('ingredients',public_question(q))

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

    def test_voice_normalization_rejects_unknown_media(self):
        from voice import normalize_audio
        with self.assertRaises(HTTPException) as exc:
            normalize_audio(b"x"*1500,"text/plain")
        self.assertEqual(exc.exception.status_code,422)
        sample=b"\x00\x00\x00\x18ftyp"+b"x"*1300
        from unittest.mock import MagicMock
        converted=MagicMock(returncode=0,stdout=b"OggS"+b"0"*400)
        with patch("voice.subprocess.run",return_value=converted) as ffmpeg:
            result=normalize_audio(sample,"audio/mp4")
        self.assertTrue(result.startswith(b"OggS"))
        self.assertIn("-c:a",ffmpeg.call_args.args[0])
        self.assertIn("libopus",ffmpeg.call_args.args[0])

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

    def test_uncertainty_recommends_only_real_published_courses(self):
        response=MagicMock()
        client=MagicMock()
        client.post.return_value=response
        cm=MagicMock()
        cm.__enter__.return_value=client
        base={"summary":"Не все критерии подтверждены","strengths":"Уточнил пожелание",
              "improvements":"Проверить полный состав","next_step":"Повтори порядок проверки",
              "needs_review":True,"focus_topic":"Ограничения питания"}
        available=[{"id":7,"title":"Сервис WOW"}]
        with patch.dict(os.environ,{"YANDEX_API_KEY":"test-not-real","YANDEX_FOLDER_ID":"test-folder"}):
            with patch("cases_api.httpx.Client",return_value=cm):
                response.json.return_value={"choices":[{"message":{"content":json.dumps({
                    **base,"recommended_course_id":7})}}]}
                matched=evaluate_with_yandex(CASE,"Уточню у кухни.",available)
                self.assertTrue(matched["needs_review"])
                self.assertEqual(matched["recommended_course_id"],7)
                source=json.loads(client.post.call_args.kwargs["json"]["messages"][1]["content"])
                self.assertEqual(source["published_courses"],available)
                response.json.return_value={"choices":[{"message":{"content":json.dumps({
                    **base,"recommended_course_id":901})}}]}
                untrusted=evaluate_with_yandex(CASE,"Уточню у кухни.",available)
                self.assertEqual(untrusted["recommended_course_id"],0)
                response.json.return_value={"choices":[{"message":{"content":json.dumps({
                    **base,"needs_review":False,"recommended_course_id":7})}}]}
                confident=evaluate_with_yandex(CASE,"Уточню у кухни.",available)
                self.assertEqual(confident["recommended_course_id"],0)
        with self.assertRaises(ValueError):
            interpret({**base,"recommended_course_id":False})

if __name__=="__main__":unittest.main(verbosity=2)
