import os
import random
import unittest
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
        with self.connect() as c:
            c.execute('DELETE FROM course_dishes WHERE course_id=%s',(self.cid,))
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
        r=self.client.post(base+'/'+aid+'/submit',headers=wait);self.assertEqual(r.status_code,200,r.text)
        self.assertTrue(r.json()['passed']);self.assertEqual(r.json()['score'],100)
        self.assertEqual(self.client.post(base+'/'+aid+'/submit',headers=wait).json(),r.json())
        self.assertEqual(self.client.get(base+'/results',headers=trainee).status_code,403)
        self.assertEqual(len(self.client.get(base+'/results',headers=manager).json()),0)
        official=self.client.post(base+'/start',headers=wait,json={'mode':'official'}).json()
        self.assertEqual(official['mode'],'official')
        oid=official['id']
        for i in range(30):
            self.assertEqual(self.client.post(base+'/'+oid+'/answer',headers=wait,json={'index':i,'answer':'Рис, Нори'}).status_code,200)
        self.assertEqual(self.client.post(base+'/'+oid+'/submit',headers=wait).status_code,200)
        self.assertEqual(len(self.client.get(base+'/results',headers=manager).json()),1)
        self.assertIsNotNone(self.client.get(base+'/assignment',headers=wait).json()['completed_at'])
        self.assertNotEqual(self.client.post(base+'/start',headers=wait,json={'mode':'official'}).json()['id'],oid)
        self.assertNotEqual(self.client.post(base+'/start',headers=wait).json()['id'],aid)
        with self.connect() as c:c.execute("UPDATE staff SET role='trainee' WHERE id=102")
        self.assertEqual(self.client.post(base+'/'+aid+'/submit',headers=wait).status_code,403)

