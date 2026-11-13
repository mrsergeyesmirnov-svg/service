import os
import random
import unittest
from unittest.mock import patch
from recertification_ai import validate
from fastapi import HTTPException
from psycopg.types.json import Jsonb
from recertification import choose_questions, waiter, SECTIONS
from dish_lessons import dish_chapters, reviewed_dish_signature
from test_menu_assessments import StageIntegration, chapter

class Selection(unittest.TestCase):
    def test_random_balanced_unique_and_no_desserts(self):
        cards=[]
        for n in range(84):
            card=chapter(n);card['section']=SECTIONS[n%7];cards.append(card)
        dessert=chapter(200);dessert['section']='Десерты';cards.append(dessert)
        a=choose_questions(cards+cards,random.Random(1))
        b=choose_questions(cards,random.Random(2))
        self.assertEqual(len(a),30)
        self.assertEqual(len({q['dish_id'] for q in a}),30)
        self.assertEqual({q['section'] for q in a},set(SECTIONS))
        self.assertNotEqual(a,b)
        self.assertTrue(all(4<=sum(q['section']==s for q in a)<=5 for s in SECTIONS))
    def test_insufficient_and_missing_sections_block(self):
        with self.assertRaises(HTTPException):choose_questions([chapter(i) for i in range(50)])
    def test_only_waiter(self):
        waiter({'role':'waiter'})
        for role in ('trainee','local','manager'):
            with self.assertRaises(HTTPException):waiter({'role':role})

@unittest.skipUnless(os.environ.get("DATABASE_URL"), "PostgreSQL integration required")
class RecertificationIntegration(unittest.TestCase):
    tearDown = StageIntegration.tearDown
    auth = StageIntegration.auth
    def setUp(self):
        StageIntegration.setUp(self)
        def assessment(q, answer):
            return validate({'components': [dict(id=i, status='recognized', evidence=g[0],
                occurrence=0, reason='Назван компонент') for i,g in enumerate(q['ingredients'])],
                'contradictions': []}, q, answer)
        self.ai = patch('recertification.evaluate_question', side_effect=assessment)
        self.mock_ai = self.ai.start()
        self.addCleanup(self.ai.stop)
        with self.connect() as c:
            c.execute('DELETE FROM course_dishes WHERE course_id=%s',(self.cid,))
            c.execute('DELETE FROM dish_cards')
            for i in range(49):
                did=c.execute('''INSERT INTO dish_cards(restaurant,created_by,title,section,ingredients,published)
                  VALUES('MOJO',999,%s,%s,%s,true) RETURNING id''',
                  (f'Блюдо {i}',SECTIONS[i%7],Jsonb(['Рис','Нори']))).fetchone()['id']
                c.execute('INSERT INTO course_dishes(course_id,dish_id,position) VALUES(%s,%s,%s)',(self.cid,did,i))
            c.execute('UPDATE courses SET reviewed_dish_signature=%s WHERE id=%s',
                      (reviewed_dish_signature(dish_chapters(c,self.cid,'MOJO')),self.cid))

    def test_published_cards_do_not_require_course_review_signature(self):
        with self.connect() as c:
            c.execute('UPDATE courses SET reviewed_dish_signature=NULL WHERE id=%s', (self.cid,))
        waiter_headers = self.auth(102)
        response = self.client.post('/api/recertification/start', headers=waiter_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()['questions']), 30)
        self.assertEqual({q['section'] for q in response.json()['questions']}, set(SECTIONS))

    def test_recertification_access_freezing_resume_and_submit(self):
        trainee=self.auth(101);wait=self.auth(102);manager=self.auth(999)
        base='/api/recertification'
        self.assertEqual(self.client.post(base+'/assign',headers=trainee,json={'staff_id':102}).status_code,403)
        self.assertEqual(self.client.post(base+'/assign',headers=self.auth(103),json={'staff_id':102}).status_code,403)
        self.assertEqual(self.client.post(base+'/assign',headers=manager,json={'staff_id':101}).status_code,422)
        self.assertEqual(self.client.post(base+'/assign',headers=manager,json={'staff_id':102}).status_code,200)
        self.assertIsNone(self.client.get(base+'/assignment',headers=wait).json()['completed_at'])
        self.assertEqual(self.client.post(base+'/start',headers=trainee).status_code,403)
        self.assertEqual(self.client.post(base+'/start',headers=wait,json={'mode':'official'}).status_code,409)
        r=self.client.post(base+'/start',headers=wait);self.assertEqual(r.status_code,200,r.text)
        data=r.json();aid=data['id'];self.assertEqual(len(data['questions']),30)
        self.assertFalse(any('ingredients' in q or 'correct' in q for q in data['questions']))
        self.assertEqual(self.client.post(base+'/start',headers=wait).json()['id'],aid)
        self.assertEqual(self.client.post(base+'/'+aid+'/submit',headers=wait).status_code,422)
        for i in range(30):
            r=self.client.post(base+'/'+aid+'/answer',headers=wait,json={'index':i,'answer':'Рис, Нори'})
            self.assertEqual(r.status_code,200,r.text)
        resumed=self.client.post(base+'/start',headers=wait).json()
        self.assertEqual(resumed['answers'],['Рис, Нори']*30)
        r=self.finish(aid, wait);self.assertEqual(r.status_code,200,r.text)
        self.assertTrue(r.json()['passed']);self.assertEqual(r.json()['score'],100)
        self.assertEqual(self.client.post(base+'/'+aid+'/submit',headers=wait).json(),r.json())
        self.assertEqual(self.client.get(base+'/results',headers=trainee).status_code,403)
        self.assertEqual(len(self.client.get(base+'/results',headers=manager).json()),0)
        official=self.client.post(base+'/start',headers=wait,json={'mode':'official'}).json()
        self.assertEqual(official['mode'],'official')
        oid=official['id']
        for i in range(30):
            self.assertEqual(self.client.post(base+'/'+oid+'/answer',headers=wait,json={'index':i,'answer':'Рис, Нори'}).status_code,200)
        self.assertEqual(self.finish(oid, wait).status_code,200)
        self.assertEqual(len(self.client.get(base+'/results',headers=manager).json()),1)
        self.assertIsNotNone(self.client.get(base+'/assignment',headers=wait).json()['completed_at'])
        self.assertNotEqual(self.client.post(base+'/start',headers=wait,json={'mode':'official'}).json()['id'],oid)
        self.assertNotEqual(self.client.post(base+'/start',headers=wait).json()['id'],aid)
        with self.connect() as c:c.execute("UPDATE staff SET role='trainee' WHERE id=102")
        self.assertEqual(self.client.post(base+'/'+aid+'/submit',headers=wait).status_code,403)

    def finish(self, aid, headers):
        for _ in range(40):
            response=self.client.post('/api/recertification/'+aid+'/submit',headers=headers)
            if response.status_code != 200 or response.json()['submitted']:
                return response
        self.fail('Grading never completed')

    def prepared(self):
        headers=self.auth(102)
        aid=self.client.post('/api/recertification/start',headers=headers).json()['id']
        for i in range(30):
            self.client.post('/api/recertification/'+aid+'/answer',headers=headers,
                             json={'index':i,'answer':'Рис, Нори'})
        return aid, headers

    def test_provider_failure_keeps_answers_and_cached_grades(self):
        aid, headers=self.prepared()
        base='/api/recertification/'+aid
        first=self.client.post(base+'/submit',headers=headers)
        self.assertEqual(first.json()['evaluation']['graded'],1)
        calls=self.mock_ai.call_count
        original=self.mock_ai.side_effect
        self.mock_ai.side_effect=HTTPException(503,'unavailable')
        self.assertEqual(self.client.post(base+'/submit',headers=headers).status_code,503)
        saved=self.client.get(base,headers=headers).json()
        self.assertEqual(saved['answers'],['Рис, Нори']*30)
        self.assertIsNone(saved['score'])
        self.assertEqual(saved['evaluation']['graded'],1)
        self.assertEqual(self.client.post(base+'/answer',headers=headers,json={'index':0,'answer':'изменено'}).status_code,409)
        self.mock_ai.side_effect=original
        self.assertEqual(self.finish(aid,headers).json()['score'],100)
        self.assertEqual(self.mock_ai.call_count,calls+1+29)
        completed_calls=self.mock_ai.call_count
        self.client.post(base+'/submit',headers=headers)
        self.assertEqual(self.mock_ai.call_count,completed_calls)

    def test_official_disputes_wait_for_scoped_manager_and_are_idempotent(self):
        aid, headers=self.prepared()
        self.finish(aid,headers)
        manager=self.auth(999)
        self.client.post('/api/recertification/assign',headers=manager,json={'staff_id':102})
        oid=self.client.post('/api/recertification/start',headers=headers,json={'mode':'official'}).json()['id']
        for i in range(30):
            self.client.post('/api/recertification/'+oid+'/answer',headers=headers,json={'index':i,'answer':'Рис, Нори'})
        original=self.mock_ai.side_effect
        def disputed(q,a):
            r=original(q,a)
            raw={'components':[{k:c[k] for k in ('id','status','evidence','occurrence','reason')} for c in r['components']], 'contradictions':[]}
            raw['components'][0]['status']='uncertain'
            return validate(raw,q,a)
        self.mock_ai.side_effect=disputed
        result=self.finish(oid,headers).json()
        self.assertIsNone(result['score']);self.assertIsNone(result['passed'])
        self.assertEqual(result['evaluation']['provisional_score'],50)
        self.assertEqual(result['evaluation']['score_upper'],100)
        self.assertIsNone(self.client.get('/api/recertification/assignment',headers=headers).json()['completed_at'])
        self.assertEqual(self.client.post('/api/recertification/start',headers=headers,json={'mode':'official'}).json()['id'],oid)
        url='/api/recertification/'+oid+'/review'
        payload={'questions':[{'index':i,'components':[dict(id=0,status='recognized',evidence='Рис',occurrence=0,reason='Продукт назван')]} for i in range(30)]}
        self.assertEqual(self.client.post(url,headers=headers,json=payload).status_code,403)
        self.assertEqual(self.client.post(url,headers=self.auth(103),json=payload).status_code,403)
        self.assertEqual(self.client.post(url,headers=manager,json={'questions':[]}).status_code,422)
        reviewed=self.client.post(url,headers=manager,json=payload)
        self.assertEqual(reviewed.status_code,200,reviewed.text)
        self.assertEqual(reviewed.json()['score'],100)
        self.assertEqual(self.client.post(url,headers=manager,json=payload).json(),reviewed.json())
        self.assertIsNotNone(self.client.get('/api/recertification/assignment',headers=headers).json()['completed_at'])
        self.assertTrue(self.client.get('/api/recertification/'+oid,headers=headers).json()['passed'])

    def test_concurrent_submit_does_not_call_provider_twice(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        aid, headers=self.prepared()
        entered, release=Event(),Event()
        original=self.mock_ai.side_effect
        def slow(q,a):
            entered.set()
            if not release.wait(10):raise RuntimeError('test timed out')
            return original(q,a)
        self.mock_ai.side_effect=slow
        url='/api/recertification/'+aid+'/submit'
        with ThreadPoolExecutor(max_workers=2) as executor:
            first=executor.submit(self.client.post,url,headers=headers)
            try:
                self.assertTrue(entered.wait(5))
                self.assertEqual(self.client.post(url,headers=headers).status_code,409)
            finally:release.set()
            self.assertEqual(first.result().status_code,200)
        self.assertEqual(self.mock_ai.call_count,1)

