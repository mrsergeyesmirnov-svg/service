"""Provider contract and failure safety. Semantic quality needs the live menu runner."""
import json
import os
import unittest
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from recertification_ai import validate, evaluate_question, resolve_assessment, attempt_summary


def question(*names):
    return dict(type='ingredients', question='Состав блюда?', dish_title='Контрольное блюдо',
                ingredients=[[n] for n in names])


def component(idx, status, evidence='', occurrence=0):
    return dict(id=idx, status=status, evidence=evidence, occurrence=occurrence, reason='Проверка смысла')


class ProviderContract(unittest.TestCase):
    def test_missing_uncertain_and_recognized_are_separate(self):
        q=question('Компонент A','Компонент B','Компонент C')
        result=validate({'components':[component(2,'uncertain','добавка'),component(0,'recognized','основа'),component(1,'missing')],
                         'contradictions':[]},q,'основа и добавка')
        self.assertEqual(result['recognized_ingredients'],['Компонент A'])
        self.assertEqual(result['missing'],['Компонент B'])
        self.assertEqual(result['uncertain'],['Компонент C'])
        self.assertAlmostEqual(result['fraction'],1/3)
        self.assertAlmostEqual(result['upper_fraction'],2/3)

    def test_no_fabricated_evidence_or_invalid_component_ids(self):
        q=question('A','B')
        invalid=[
            [component(0,'recognized','отсутствует'),component(1,'missing')],
            [component(0,'recognized'),component(1,'missing')],
            [component(0,'missing','текст'),component(1,'missing')],
            [component(0,'missing'),component(0,'missing')],
            [component(True,'missing'),component(1,'missing')],
            [component(2,'missing'),component(1,'missing')],
            [component(0,'missing')],
            [component(0,'recognized','текст',2),component(1,'missing')],
        ]
        for rows in invalid:
            with self.subTest(rows=rows),self.assertRaises(ValueError):
                validate({'components':rows,'contradictions':[]},q,'текст')

    def test_overlapping_evidence_cannot_credit_two_ingredients(self):
        result=validate({'components':[component(0,'recognized','особый соус'),component(1,'recognized','соус')],
                         'contradictions':[]},question('A','B'),'особый соус')
        self.assertEqual(result['recognized'],0)
        self.assertEqual(len(result['uncertain']),2)
        with self.assertRaises(ValueError):
            resolve_assessment(result,'особый соус',[
                dict(component(0,'recognized','особый соус')),dict(component(1,'recognized','соус'))])

    def test_distinct_occurrences_can_be_used(self):
        result=validate({'components':[component(0,'recognized','продукт'),component(1,'recognized','продукт',1)],
                         'contradictions':[]},question('A','B'),'продукт, продукт')
        self.assertEqual(result['recognized'],2)

    def test_manager_resolution_preserves_original_decision(self):
        q=question('A','B')
        result=validate({'components':[component(0,'uncertain','основа'),component(1,'missing')],
                         'contradictions':['Противоречие']},q,'основа')
        resolved=resolve_assessment(result,'основа',[component(0,'recognized','основа')])
        self.assertEqual(resolved['components'][0]['ai_decision']['status'],'uncertain')
        self.assertEqual(result['components'][0]['status'],'uncertain')
        self.assertFalse(resolved['needs_review'])
        self.assertEqual(resolved['reviewed_contradictions'],['Противоречие'])
        self.assertEqual(attempt_summary([dict(q,ai_assessment=resolved)])['provisional_score'],50)

    def test_provider_json_retry_privacy_and_context(self):
        calls=[]
        good={'components':[component(0,'recognized','основа')],'contradictions':[]}
        def handler(request):
            calls.append(json.loads(request.content))
            if len(calls)==1:return httpx.Response(429)
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(good)}}]})
        real_client=httpx.Client
        with patch.dict(os.environ,{'YANDEX_API_KEY':'test-key','YANDEX_FOLDER_ID':'test-folder'}),\
             patch('recertification_ai.httpx.Client',side_effect=lambda **kw:real_client(transport=httpx.MockTransport(handler),**kw)),\
             patch('recertification_ai.time.sleep'):
            q=dict(question('A'),staff_id=123,name='НЕ ОТПРАВЛЯТЬ',restaurant='НЕ ОТПРАВЛЯТЬ')
            result=evaluate_question(q,'основа')
        self.assertEqual(result['recognized'],1)
        self.assertEqual(len(calls),2)
        self.assertNotIn('НЕ ОТПРАВЛЯТЬ',json.dumps(calls,ensure_ascii=False))
        body=json.loads(calls[0]['messages'][1]['content'])
        self.assertEqual(set(body),{'dish','recipe','answer'})
        self.assertEqual(calls[0]['response_format']['type'],'json_schema')

    def test_bad_json_truncated_response_timeout_and_auth_error_never_score_zero(self):
        request=httpx.Request('POST','https://example.test')
        scenarios=[httpx.ReadTimeout('timeout'),httpx.Response(200,request=request,json={'choices':[{'finish_reason':'length','message':{'content':'{}'}}]}),
                   httpx.Response(200,request=request,json={'choices':[{'finish_reason':'stop','message':{'content':'not json'}}]}),
                   httpx.Response(401,request=request)]
        for failure in scenarios:
            with self.subTest(failure=failure),\
                 patch.dict(os.environ,{'YANDEX_API_KEY':'x','YANDEX_FOLDER_ID':'y'}),\
                 patch('recertification_ai.httpx.Client') as mock,patch('recertification_ai.time.sleep'):
                client=mock.return_value.__enter__.return_value
                if isinstance(failure,Exception):client.post.side_effect=failure
                else:client.post.return_value=failure
                with self.assertRaises(HTTPException) as exc:evaluate_question(question('A'),'основа')
                self.assertEqual(exc.exception.status_code,503)
                self.assertEqual(client.post.call_count,1 if isinstance(failure,httpx.Response) and failure.status_code==401 else 2)

    def test_unconfigured_provider_fails_explicitly(self):
        with patch.dict(os.environ,{'YANDEX_API_KEY':'','YANDEX_FOLDER_ID':''}):
            with self.assertRaises(HTTPException) as exc:evaluate_question(question('A'),'основа')
        self.assertEqual(exc.exception.status_code,503)


if __name__=='__main__':unittest.main()
