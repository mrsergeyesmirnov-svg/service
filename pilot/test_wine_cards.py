"""Wine recall regression checks; PostgreSQL integration runs in CI."""
import os
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import psycopg
from psycopg.rows import dict_row
from fastapi import HTTPException
from fastapi.testclient import TestClient

import server
from test_pilot import signed
from wine_cards import validate_wines, recall_pairs

W1 = dict(name='Test Winery Sauvignon Blanc', grape='Sauvignon Blanc',
          country='Новая Зеландия', region='Marlborough',
          source='Тестовая винная карта, версия 1')
W2 = dict(name='Test Estate Sauvignon Blanc', grape='Sauvignon Blanc',
          country='Новая Зеландия', region='Marlborough',
          source='Тестовая винная карта, версия 1')


class WineUnit(unittest.TestCase):
    def test_wine_courses_appear_in_bar_filter(self):
        from learning import category
        self.assertEqual(category('Винная карта MOJO'), 'bar')
        self.assertEqual(category('Вина MOJO'), 'bar')
        self.assertEqual(category('Wine MOJO'), 'bar')

    def test_validation_keeps_only_reviewed_exact_source_data(self):
        self.assertEqual(validate_wines({'cards':[W1], 'reviewed':True}), [W1])
        for payload in [
            {'cards':[W1], 'reviewed':False},
            {'cards':[dict(W1, region='')], 'reviewed':True},
            {'cards':[dict(W1, country=42)], 'reviewed':True},
            {'cards':[dict(W1, fake='unsupported')], 'reviewed':True},
            {'cards':[W1, dict(W1, name=W1['name'].upper())], 'reviewed':True},
            {'cards':[dict(W1, name=f'Wine {i}') for i in range(81)], 'reviewed':True},
        ]:
            with self.subTest(payload=str(payload)[:90]), self.assertRaises(HTTPException):
                validate_wines(payload)

    def test_forward_and_reverse_ambiguous_combinations(self):
        pairs=recall_pairs([W1,W2])
        self.assertEqual(len(pairs),3)  # 2 names, one shared reverse prompt
        self.assertEqual([x['direction'] for x in pairs], ['forward','forward','reverse'])
        self.assertEqual(pairs[0]['answer'], [
            ['Сорт','Sauvignon Blanc'], ['Страна','Новая Зеландия'], ['Регион','Marlborough']])
        self.assertEqual(pairs[-1]['answer'], [
            ['Название',W1['name']],['Название',W2['name']]])
        self.assertEqual([p['id'] for p in pairs],
                         [p['id'] for p in recall_pairs([W1,W2])])

    def test_content_change_changes_reverse_key(self):
        old=recall_pairs([W1])
        new=recall_pairs([dict(W1,region='Central Otago')])
        self.assertEqual(old[0]['id'],new[0]['id'])
        self.assertNotEqual(old[1]['id'],new[1]['id'])


@unittest.skipUnless(os.getenv('DATABASE_URL'), 'PostgreSQL integration requires DATABASE_URL')
class WineIntegration(unittest.TestCase):
    def setUp(self):
        self.schema='pilot_wine_test_'+uuid.uuid4().hex
        self.orig_db=server.db
        with self.orig_db() as c:c.execute('CREATE SCHEMA '+self.schema)
        def connect():
            return psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row,
                                   options='-c search_path='+self.schema)
        self.patches=[patch.object(server,'db',connect),
                      patch.object(server,'TOKEN','test-token'),
                      patch.object(server,'OWNER',999)]
        for p in self.patches:p.start()
        with connect() as c:
            c.execute((Path(__file__).parent/'schema.sql').read_text())
            c.execute("""INSERT INTO staff(id,name,role,restaurant,bot_started) VALUES
                (101,'Learner','trainee','MOJO',true),
                (102,'Other learner','waiter','MOJO',true),
                (103,'Other venue','local','OTHER',true),
                (999,'Manager','manager','MOJO',true)""")
        self.client=TestClient(server.app)

    def tearDown(self):
        for p in self.patches:p.stop()
        with self.orig_db() as c:c.execute('DROP SCHEMA '+self.schema+' CASCADE')

    def auth(self,uid):
        r=self.client.post('/api/login',json={'initData':signed(uid)})
        self.assertEqual(r.status_code,200,r.text)
        return {'Authorization':'Bearer '+r.json()['token']}

    def test_draft_review_publication_progress_and_existing_exam(self):
        manager=self.auth(999);learner=self.auth(101)
        other=self.auth(102);foreign_manager=self.auth(103)
        body={
            'title':'Вина MOJO', 'kind':'service',
            'body':'Сверить названия и происхождение по утверждённой карте.',
            'source':'Тестовая винная карта, версия 1',
            'pass_score':80,
            'questions':[{'type':'single','question':'Контрольный вопрос',
                          'options':['Верно','Неверно'],'correct':0,
                          'explanation':'По материалу','source':'Тестовая винная карта'}]
        }
        r=self.client.post('/api/courses',headers=manager,json=body)
        self.assertEqual(r.status_code,200,r.text)
        cid=r.json()['id'];endpoint=f'/api/wine-cards/{cid}'
        self.assertEqual(self.client.get(endpoint,headers=learner).status_code,404)
        payload={'reviewed':True,'cards':[W1,W2]}
        self.assertEqual(self.client.put(endpoint,headers=learner,json=payload).status_code,403)
        self.assertEqual(self.client.put(endpoint,headers=foreign_manager,json=payload).status_code,403)
        self.assertEqual(self.client.put(endpoint,headers=manager,json={'cards':[W1]}).status_code,422)
        saved=self.client.put(endpoint,headers=manager,json=payload)
        self.assertEqual(saved.status_code,200,saved.text)
        draft=self.client.get(endpoint,headers=manager).json()
        self.assertEqual(len(draft['cards']),2)
        self.assertEqual(draft['pairs'],[])
        published=self.client.post(f'/api/courses/{cid}/publish',
                                   headers=manager,json={'reviewed':True})
        self.assertEqual(published.status_code,200,published.text)
        self.assertEqual(self.client.put(endpoint,headers=manager,json=payload).status_code,409)
        seen=self.client.get(endpoint,headers=learner).json()
        self.assertEqual(seen['cards'],[])
        self.assertEqual(len(seen['pairs']),3)
        self.assertEqual(seen['ratings'],{})
        reverse=seen['pairs'][2]
        self.assertEqual(len(reverse['answer']),2)
        correct=seen['pairs'][0]['id']
        self.assertEqual(self.client.post(endpoint+'/rating',headers=learner,
              json={'id':'fake','rating':'know'}).status_code,422)
        self.assertEqual(self.client.post(endpoint+'/rating',headers=learner,
              json={'id':correct,'rating':'mastered'}).status_code,422)
        rated=self.client.post(endpoint+'/rating',headers=learner,
                               json={'id':correct,'rating':'know'})
        self.assertEqual(rated.status_code,200,rated.text)
        self.assertEqual(self.client.get(endpoint,headers=learner).json()['ratings'],
                         {correct:'know'})
        self.assertEqual(self.client.get(endpoint,headers=other).json()['ratings'],{})
        # Rating isn't a server-graded exam and cannot rewrite existing exam scores.
        course=self.client.get(f'/api/learning/{cid}',headers=learner).json()
        for chapter in course['chapters']:
            self.assertEqual(self.client.post(f'/api/learning/{cid}/read',headers=learner,
                     json={'chapter_id':chapter['id']}).status_code,200)
        attempt=self.client.post(f'/api/learning/{cid}/submit',headers=learner,
              json={'request_id':str(uuid.uuid4()),'answers':[0]})
        self.assertEqual(attempt.status_code,200,attempt.text)
        self.assertEqual(attempt.json()['score'],100)
        self.assertTrue(attempt.json()['passed'])
        self.assertEqual(self.client.post(f'/api/courses/{cid}/archive',
                                         headers=manager).status_code,200)
        self.assertEqual(self.client.get(endpoint,headers=learner).status_code,404)
        self.assertEqual(self.client.post(endpoint+'/rating',headers=learner,
                         json={'id':correct,'rating':'know'}).status_code,404)


if __name__ == '__main__':
    unittest.main()
