import hashlib,hmac,json,os,time,unittest,uuid
from urllib.parse import urlencode
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import psycopg
from psycopg.rows import dict_row
import server,worker

def signed(uid=101,age=0):
    d={'auth_date':str(int(time.time())-age),'user':json.dumps({'id':uid})}
    secret=hmac.new(b'WebAppData',b'test-token',hashlib.sha256).digest()
    d['hash']=hmac.new(secret,'\n'.join(f'{k}={v}' for k,v in sorted(d.items())).encode(),hashlib.sha256).hexdigest()
    return urlencode(d)

class Core(unittest.TestCase):
    def test_multiple_and_ingredient_recall(self):
        from questions import check,public_question
        multi={'type':'multiple','question':'Select','options':['A','B','C'],'correct':[0,2]}
        self.assertEqual(check(multi,[2,0])['fraction'],1)
        self.assertEqual(check(multi,[0,1,2])['fraction'],0)
        recall={'type':'ingredients','question':'Recall','ingredients':[['Test A','Alias A'],['Test B']]}
        self.assertEqual(check(recall,' ALIAS A\nTest B')['fraction'],1)
        self.assertEqual(check(recall,'Test A\nTest B\nInvented')['extra'],['invented'])
        self.assertEqual(check(recall,'Test A')['missing'],['Test B'])
        self.assertNotIn('ingredients',public_question(recall))
        with self.assertRaises(server.HTTPException):check(multi,[True])
        with self.assertRaises(server.HTTPException):check(multi,[0,0])

    def test_telegram_network_timeouts_are_bounded(self):
        from unittest.mock import MagicMock
        fake=MagicMock()
        fake.__enter__.return_value.read.return_value=b'{"ok":true,"result":[]}'
        with patch.object(worker.urllib.request,'urlopen',return_value=fake) as call:
            self.assertEqual(worker.telegram('getUpdates',offset=1,timeout=2),[])
            self.assertEqual(call.call_args.kwargs['timeout'],10)
            worker.telegram('sendMessage',chat_id=123,text='ok')
            self.assertEqual(call.call_args.kwargs['timeout'],15)

    def test_auth(self):
        self.assertEqual(server.validate_init(signed(),'test-token')['id'],101)
        for raw in [signed(age=4000),signed(age=-100),signed()+'&user=bad',signed().replace('101','102')]:
            with self.assertRaises((ValueError,KeyError)):server.validate_init(raw,'test-token')
    def test_grade(self):
        qs=[{'options':['a','b'],'correct':0},{'options':['a','b'],'correct':1}]
        self.assertEqual(server.grade(qs,[0,1]),100)
        self.assertEqual(server.grade(qs,[1,1]),50)
        for answers in [[0],[-1,1],[True,1],[0,9]]:
            with self.assertRaises(server.HTTPException):server.grade(qs,answers)

@unittest.skipUnless(os.getenv('DATABASE_URL'),'requires disposable PostgreSQL test schema')
class Integration(unittest.TestCase):
    def setUp(self):
        self.schema='pilot_test_'+uuid.uuid4().hex
        self.original=server.db
        with self.original() as c:c.execute('CREATE SCHEMA '+self.schema)
        def connect():return psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row,options='-c search_path='+self.schema)
        self.patches=[patch.object(server,'db',connect),patch.object(worker,'db',connect),patch.object(server,'TOKEN','test-token'),patch.object(server,'OWNER',999),patch.object(worker,'OWNER',999)]
        for p in self.patches:p.start()
        with connect() as c:
            c.execute((Path(__file__).parent/'schema.sql').read_text())
            c.execute("INSERT INTO staff(id,name,role,restaurant,bot_started) VALUES (101,'Student','trainee','MOJO',true),(102,'Other','trainee','MOJO',true),(103,'Local','local','OTHER',true),(999,'Owner','manager','MOJO',true)")
        self.client=TestClient(server.app)
    def tearDown(self):
        for p in self.patches:p.stop()
        with self.original() as c:c.execute('DROP SCHEMA '+self.schema+' CASCADE')
    def auth(self,uid):
        r=self.client.post('/api/login',json={'initData':signed(uid)});self.assertEqual(r.status_code,200,r.text)
        return {'Authorization':'Bearer '+r.json()['token']}
    def test_curated_text_chapters_for_coffee_with_server_progress(self):
        m=self.auth(999);s=self.auth(101);local=self.auth(103)
        payload=dict(title='Coffee 01',kind='service',body='RAW old coffee PDF',
                     source='Synthetic coffee source',pass_score=80,
                     questions=[dict(question='Check theory',options=['A','B'],
                                     correct=0,explanation='Synthetic',source='Lesson')])
        created=self.client.post('/api/courses',json=payload,headers=m)
        self.assertEqual(created.status_code,200,created.text)
        cid=created.json()['id']
        self.client.post(f'/api/courses/{cid}/publish',json={'reviewed':True},headers=m)
        route=f'/api/learning/{cid}/text-chapters'
        self.assertEqual(self.client.get(route,headers=s).status_code,403)
        self.assertEqual(self.client.put(route,json={'chapters':[]},headers=local).status_code,403)
        chapters=[dict(title='Coffee basics',body='Coffee is a prepared beverage',
                       source='Synthetic chapter p1'),
                  dict(title='Presentation',body='Describe the verified origin and method',
                       source='Synthetic chapter p2')]
        result=self.client.put(route,json={'chapters':chapters},headers=m)
        self.assertEqual(result.status_code,200,result.text)
        detail=self.client.get(f'/api/learning/{cid}',headers=s).json()
        self.assertEqual(len(detail['chapters']),2)
        self.assertTrue(all(x['kind']=='text' for x in detail['chapters']))
        self.assertNotIn('RAW old coffee PDF',str(detail['chapters']))
        for ch in detail['chapters']:
            self.assertEqual(self.client.post(f'/api/learning/{cid}/read',
                json={'chapter_id':ch['id']},headers=s).status_code,200)
        attempt=self.client.post(f'/api/learning/{cid}/submit',json={
            'request_id':str(uuid.uuid4()),'answers':[0]},headers=s)
        self.assertEqual(attempt.status_code,200,attempt.text)
        updated=[chapters[0],dict(title='Presentation',body='Revised verified presentation',
                                  source='Synthetic chapter p2')]
        self.assertEqual(self.client.put(route,json={'chapters':updated},headers=m).status_code,200)
        new=self.client.get(f'/api/learning/{cid}',headers=s).json()
        self.assertEqual(new['chapters'][0]['id'],detail['chapters'][0]['id'])
        self.assertNotEqual(new['chapters'][1]['id'],detail['chapters'][1]['id'])
        self.assertEqual(len(new['history']),1)
        self.assertEqual(self.client.post(f'/api/learning/{cid}/submit',json={
            'request_id':str(uuid.uuid4()),'answers':[0]},headers=s).status_code,409)
        self.assertEqual(self.client.put(route,json={'chapters':[dict(title='',body='bad')]},headers=m).status_code,422)

    def test_curated_dish_lessons_preserve_courses_and_scope(self):
        from PIL import Image
        from io import BytesIO
        m=self.auth(999);s=self.auth(101);local=self.auth(103)
        q=[dict(question='Which presentation is right?',options=['Correct','Wrong'],
                correct=0,explanation='Approved recipe',source='Manager')]
        payload=dict(title='KITCHEN 02',kind='ttk',body='Legacy big PDF text',
                     source='Synthetic PDF',questions=q,pass_score=80)
        cid=self.client.post('/api/courses',json=payload,headers=m).json()['id']
        self.client.post(f'/api/courses/{cid}/publish',json={'reviewed':True},headers=m)
        create=self.client.post('/api/dishes',json={
            'title':'MOJO avocado roll','section':'Cold rolls',
            'ingredients':['Avocado','Rice'],'description':'Only synthetic test ingredients'
        },headers=m)
        self.assertEqual(create.status_code,200,create.text)
        did=create.json()['id']
        photo=BytesIO()
        Image.new('RGB',(200,120)).save(photo,'JPEG')
        self.assertEqual(self.client.put(f'/api/dishes/{did}/photo',content=photo.getvalue(),headers=m).status_code,200)
        published=self.client.post(f'/api/dishes/{did}/publish',json={'reviewed':True},headers=m)
        self.assertEqual(published.status_code,200,published.text)
        map_url=f'/api/learning/{cid}/dish-map'
        self.assertEqual(self.client.get(map_url,headers=s).status_code,403)
        self.assertEqual(self.client.put(map_url,json={'dish_ids':[did]},headers=s).status_code,403)
        self.assertEqual(self.client.put(map_url,json={'dish_ids':[did]},headers=local).status_code,403)
        added=self.client.put(map_url,json={'dish_ids':[did]},headers=m)
        self.assertEqual(added.status_code,200,added.text)
        self.assertEqual(added.json()['dish_ids'],[did])
        detail=self.client.get(f'/api/learning/{cid}',headers=s).json()
        self.assertEqual(len(detail['chapters']),1)
        chapter=detail['chapters'][0]
        self.assertEqual(chapter['title'],'MOJO avocado roll')
        self.assertEqual(chapter['kind'],'dish')
        self.assertNotIn('Legacy big PDF',str(chapter))
        self.assertNotIn('correct',detail['questions'][0])
        self.assertTrue(chapter['has_photo'])
        self.assertEqual(self.client.post(f'/api/learning/{cid}/submit',json={
            'request_id':str(uuid.uuid4()),'answers':[0]},headers=s).status_code,409)
        with patch.dict(os.environ,{'YANDEX_API_KEY':'synthetic-key','YANDEX_FOLDER_ID':'synthetic-folder'}):
            with patch('learning.evaluate_with_yandex',return_value={
                'summary':'Useful effort','strengths':'Checked ingredients',
                'improvements':'Clarify guest preference','next_step':'Repeat briefly'}):
                req={'dish_id':did,'request_id':str(uuid.uuid4()),
                     'answer':'I will explain the checked composition and ask what the guest likes.'}
                practice=self.client.post(f'/api/learning/{cid}/dish-practice',json=req,headers=s)
                self.assertEqual(practice.status_code,200,practice.text)
                self.assertEqual(practice.json()['summary'],'Useful effort')
                retry=self.client.post(f'/api/learning/{cid}/dish-practice',json=req,headers=s)
                self.assertEqual(retry.status_code,200,retry.text)
                records=self.client.get(f'/api/learning/{cid}/dish-practice/{did}',headers=s)
                self.assertEqual(len(records.json()),1)
                self.assertEqual(len(self.client.get(f'/api/learning/{cid}/dish-practice/{did}',headers=self.auth(102)).json()),0)
                self.assertEqual(self.client.post(f'/api/learning/{cid}/dish-practice',
                    json={**req,'request_id':str(uuid.uuid4()),
                          'answer':'Please contact example@example.com before bringing this dish.'},
                    headers=s).status_code,422)
                self.assertEqual(self.client.post(f'/api/learning/{cid}/dish-practice',json=req,headers=local).status_code,404)
        marked=self.client.post(f'/api/learning/{cid}/read',json={'chapter_id':chapter['id']},headers=s)
        self.assertEqual(marked.status_code,200,marked.text)
        attempt=self.client.post(f'/api/learning/{cid}/submit',json={
            'request_id':str(uuid.uuid4()),'answers':['Avocado\nRice']},headers=s)
        self.assertEqual(attempt.status_code,200,attempt.text)
        self.assertEqual(attempt.json()['score'],100)
        # Changing a published recipe invalidates the current lesson until re-approved.
        updated=self.client.put(f'/api/dishes/{did}',json={
            'title':'MOJO avocado roll','section':'Cold rolls',
            'ingredients':['Avocado','Rice'],'description':'Updated by the manager'
        },headers=m)
        self.assertEqual(updated.status_code,200,updated.text)
        missing=self.client.get(f'/api/learning/{cid}',headers=s).json()
        self.assertEqual(missing['chapters'],[])
        self.assertEqual(self.client.post(f'/api/learning/{cid}/submit',json={
            'request_id':str(uuid.uuid4()),'answers':[0]},headers=s).status_code,409)
        self.client.post(f'/api/dishes/{did}/publish',json={'reviewed':True},headers=m)
        fresh=self.client.get(f'/api/learning/{cid}',headers=s).json()
        self.assertNotEqual(chapter['id'],fresh['chapters'][0]['id'])
        self.assertEqual(len(fresh['history']),1)
        self.assertEqual(self.client.post(f'/api/learning/{cid}/read',
            json={'chapter_id':chapter['id']},headers=s).status_code,422)

    def test_self_study_persistence_and_scope(self):
        m=self.auth(999); s=self.auth(101); other=self.auth(102); local=self.auth(103)
        payload=dict(title='Learning test',kind='service',body='Introduction\n1. Chapter. Read this.',source='Synthetic source',pass_score=80,questions=[dict(question='Choose',options=['Correct','Wrong'],correct=0,explanation='Explanation',source='Chapter 1')])
        cid=self.client.post('/api/courses',json=payload,headers=m).json()['id']
        path=f'/api/learning/{cid}'
        self.assertEqual(self.client.get(path,headers=s).status_code,404)
        self.client.post(f'/api/courses/{cid}/publish',json={'reviewed':True},headers=m)
        self.assertEqual(self.client.get(path,headers=local).status_code,404)
        data=self.client.get(path,headers=s).json()
        self.assertNotIn('correct',data['questions'][0])
        attempt={'request_id':str(uuid.uuid4()),'answers':[1]}
        self.assertEqual(self.client.post(path+'/submit',json=attempt,headers=s).status_code,409)
        for ch in data['chapters']:
            self.assertEqual(self.client.post(path+'/read',json={'chapter_id':ch['id']},headers=s).status_code,200)
        result=self.client.post(path+'/submit',json=attempt,headers=s)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['score'],0)
        self.assertEqual(result.json()['review'][0]['explanation'],'Explanation')
        self.client.post(path+'/submit',json=attempt,headers=s)
        attempt={'request_id':str(uuid.uuid4()),'answers':[0]}
        self.assertTrue(self.client.post(path+'/submit',json=attempt,headers=s).json()['passed'])
        fresh=self.auth(101)
        restored=self.client.get(path,headers=fresh).json()
        self.assertEqual(len(restored['history']),2)
        self.assertEqual(len(restored['read']),len(data['chapters']))
        self.assertEqual(self.client.get(path,headers=other).json()['history'],[])
        self.assertEqual(self.client.get(path+'/results',headers=s).status_code,403)
        self.assertEqual(self.client.get(path+'/results',headers=local).status_code,403)
        self.assertEqual(len(self.client.get(path+'/results',headers=m).json()),2)
        self.assertEqual(self.client.get('/api/assignments',headers=s).json(),[])

    def test_new_question_formats_persist(self):
        m=self.auth(999);s=self.auth(101)
        qs=[dict(type='multiple',question='Choose all',options=['A','B','C'],correct=[0,2],explanation='Synthetic',source='Test'),dict(type='ingredients',question='Recall',ingredients=[['Test A','Alias A'],['Test B']],explanation='Synthetic',source='Test')]
        payload=dict(title='Synthetic recall test',kind='ttk',body='Read',source='Synthetic',pass_score=80,questions=qs)
        result=self.client.post('/api/courses',json=payload,headers=m)
        self.assertEqual(result.status_code,200,result.text)
        cid=result.json()['id'];path=f'/api/learning/{cid}'
        self.client.post(f'/api/courses/{cid}/publish',json={'reviewed':True},headers=m)
        d=self.client.get(path,headers=s).json()
        self.assertNotIn('ingredients',d['questions'][1])
        for ch in d['chapters']:self.client.post(path+'/read',json={'chapter_id':ch['id']},headers=s)
        r=self.client.post(path+'/submit',json={'request_id':str(uuid.uuid4()),'answers':[[0,2],'Alias A\nTest B']},headers=s)
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['score'],100)
        self.assertEqual(self.client.get(path,headers=self.auth(101)).json()['history'][0]['score'],100)

    def test_end_to_end(self):
        m=self.auth(999);s=self.auth(101);other=self.auth(102);local=self.auth(103)
        payload=dict(title='Test',kind='service',body='Lesson',source='Approved document p1',pass_score=80,questions=[dict(question='Choose',options=['Correct','Wrong'],correct=0,explanation='Because',source='p1')])
        self.assertEqual(self.client.post('/api/courses',json=payload,headers=s).status_code,403)
        cid=self.client.post('/api/courses',json=payload,headers=m).json()['id']
        self.assertEqual(self.client.post(f'/api/courses/{cid}/publish',json={'reviewed':True},headers=local).status_code,403)
        self.assertEqual(self.client.post(f'/api/courses/{cid}/publish',json={},headers=m).status_code,422)
        self.assertEqual(self.client.post(f'/api/courses/{cid}/publish',json={'reviewed':True},headers=m).status_code,200)
        self.assertEqual(self.client.put(f'/api/courses/{cid}',json=payload,headers=m).status_code,409)
        assignment={'course_id':cid,'staff_ids':[101],'deadline':'2099-11-01','max_attempts':3}
        aid=self.client.post('/api/assignments',json=assignment,headers=m).json()['created'][0]
        self.assertEqual(self.client.post('/api/assignments',json=assignment,headers=m).json()['created'],[])
        self.assertEqual(self.client.get(f'/api/assignments/{aid}',headers=other).status_code,404)
        question=self.client.get(f'/api/assignments/{aid}',headers=s).json()['questions'][0]
        self.assertNotIn('correct',question);self.assertNotIn('explanation',question)
        submit={'request_id':str(uuid.uuid4()),'answers':[1]}
        self.assertEqual(self.client.post(f'/api/assignments/{aid}/submit',json=submit,headers=s).status_code,409)
        self.client.post(f'/api/assignments/{aid}/acknowledge',headers=s)
        result=self.client.post(f'/api/assignments/{aid}/submit',json=submit,headers=s)
        self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['score'],0)
        self.assertEqual(self.client.post(f'/api/assignments/{aid}/submit',json=submit,headers=s).json(),result.json())
        self.assertEqual(self.client.get(f'/api/assignments/{aid}',headers=s).json()['review'],[])
        submit={'request_id':str(uuid.uuid4()),'answers':[0]}
        self.assertTrue(self.client.post(f'/api/assignments/{aid}/submit',json=submit,headers=s).json()['passed'])
        reviewed=self.client.get(f'/api/assignments/{aid}',headers=s).json()
        self.assertTrue(reviewed['finished']);self.assertEqual(reviewed['review'][0]['explanation'],'Because')
        submit['request_id']=str(uuid.uuid4())
        self.assertEqual(self.client.post(f'/api/assignments/{aid}/submit',json=submit,headers=s).status_code,409)
        self.assertEqual(self.client.get(f'/api/assignments/{aid}/results',headers=local).status_code,403)
        self.assertEqual(len(self.client.get(f'/api/assignments/{aid}/results',headers=m).json()['attempts']),2)
        with patch.object(worker,'telegram',return_value={'message_id':123}) as tg:
            worker.deliver();self.assertEqual(tg.call_args.kwargs['chat_id'],101)
        with server.db() as c:self.assertEqual(c.execute('SELECT state FROM outbox').fetchone()['state'],'sent')
    def test_bulk_import_private_drafts(self):
        m=self.auth(999);s=self.auth(101)
        course=dict(title='MOJO menu lesson',kind='ttk',body='Ingredient, sauce and service details.',
                    source='MOJO station cards p.14',pass_score=80,
                    questions=[dict(question='What comes separately?',options=['Sauce','None'],
                                    correct=0,explanation='Sauce served separately',source='p.14')])
        url='/api/courses/import'
        self.assertEqual(self.client.post(url,json=[course],headers=s).status_code,403)
        result=self.client.post(url,json=[course],headers=m)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['status'],'draft')
        self.assertEqual(len(result.json()['created']),1)
        self.assertEqual(self.client.post(url,json=[course],headers=m).json()['skipped'],1)
        with server.db() as c:
            self.assertEqual(c.execute('SELECT count(*) n FROM courses').fetchone()['n'],1)
            self.assertFalse(c.execute('SELECT published FROM courses').fetchone()['published'])
            self.assertEqual(c.execute('SELECT count(*) n FROM outbox').fetchone()['n'],0)
        scenario=dict(title='Guest has food allergies',competency='Guest care',
                      action='Confirm ingredients',scenario='Guest asks about unknown ingredients.',
                      source='MOJO ServiceBook 2026 p.7',
                      criteria=['Never guess ingredients','Ask kitchen to check current recipe'])
        url='/api/cases/import'
        self.assertEqual(self.client.post(url,json=[scenario],headers=s).status_code,403)
        created=self.client.post(url,json=[scenario],headers=m)
        self.assertEqual(created.status_code,200,created.text)
        self.assertEqual(len(created.json()['created']),1)
        self.assertEqual(self.client.post(url,json=[scenario],headers=m).json()['skipped'],1)
        self.assertEqual(self.client.get('/api/cases',headers=s).json(),[])
        self.assertEqual(len(self.client.get('/api/cases',headers=m).json()),1)

    def test_case_practice_permissions_quota_and_concurrency(self):
        import cases_api
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        m=self.auth(999);s=self.auth(101);other=self.auth(102);local=self.auth(103)
        scenario=dict(title='Training scenario',competency='Care',action='Confirm details',
            scenario='A guest asks about ingredients.',source='Synthetic test only',
            criteria=['Ask kitchen','Never guess'])
        cid=self.client.post('/api/cases',json=scenario,headers=m).json()['id']
        url=f'/api/cases/{cid}'
        payload={'request_id':str(uuid.uuid4()),'answer':'I will ask the kitchen to confirm the ingredients before answering the guest.'}
        self.assertEqual(self.client.post(url+'/practice',json=payload,headers=s).status_code,404)
        self.assertEqual(self.client.post(url+'/publish',json={'reviewed':True},headers=local).status_code,403)
        self.assertEqual(self.client.post(url+'/publish',json={'reviewed':True},headers=m).status_code,200)
        feedback={k:'Training feedback' for k in ('summary','strengths','improvements','next_step')}
        started=Event();release=Event()
        def evaluate(*args):
            started.set()
            if not release.wait(10):raise RuntimeError('Concurrent request timed out')
            return feedback
        with patch.object(cases_api,'evaluate_with_yandex',side_effect=evaluate) as ai:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first=pool.submit(self.client.post,url+'/practice',json=payload,headers=s)
                self.assertTrue(started.wait(5))
                try:
                    second=self.client.post(url+'/practice',json=payload,headers=s)
                    self.assertEqual(second.status_code,409,second.text)
                finally:release.set()
                self.assertEqual(first.result().status_code,200)
            self.assertEqual(self.client.post(url+'/practice',json=payload,headers=s).json(),feedback)
            self.assertEqual(ai.call_count,1)
        self.assertEqual(self.client.get(url+'/results',headers=s).status_code,403)
        self.assertEqual(self.client.get(url+'/results',headers=local).status_code,403)
        self.assertEqual(len(self.client.get(url+'/results',headers=m).json()),1)
        self.assertEqual(self.client.get(url+'/history',headers=other).json(),[])
        with patch.object(cases_api,'evaluate_with_yandex',return_value=feedback) as ai:
            for _ in range(4):
                payload['request_id']=str(uuid.uuid4())
                self.assertEqual(self.client.post(url+'/practice',json=payload,headers=s).status_code,200)
            payload['request_id']=str(uuid.uuid4())
            self.assertEqual(self.client.post(url+'/practice',json=payload,headers=s).status_code,429)
            self.assertEqual(ai.call_count,4)
        # Replaced published scenarios must not remain available to employees.
        self.assertEqual(self.client.post(url+'/archive',json={'confirmed':True},headers=local).status_code,403)
        self.assertEqual(self.client.post(url+'/archive',json={'confirmed':True},headers=m).status_code,200)
        self.assertEqual(self.client.get('/api/cases',headers=s).json(),[])
        admin_cases=self.client.get('/api/cases',headers=m).json()
        self.assertTrue(admin_cases[0]['archived'])
        self.assertEqual(self.client.post(url+'/practice',json=payload,headers=s).status_code,404)
        self.assertEqual(self.client.post(url+'/publish',json={'reviewed':True},headers=m).status_code,409)
        self.assertEqual(len(self.client.get(url+'/results',headers=m).json()),5)

    def test_invite_contact_and_permissions(self):
        m=self.auth(999)
        invite=self.client.post('/api/invites',json={'role':'waiter'},headers=m).json()['url'].split('=')[1]
        message=lambda uid,txt:{'update_id':uid,'message':{'chat':{'id':uid,'type':'private'},'from':{'id':uid,'first_name':'New'},'text':txt}}
        worker.process(message(201,'/start '+invite))
        with patch.object(worker,'telegram') as tg:worker.process(message(202,'/start '+invite));self.assertEqual(tg.call_count,1)
        with server.db() as c:
            self.assertEqual(c.execute('SELECT role FROM staff WHERE id=201').fetchone()['role'],'waiter')
            self.assertIsNone(c.execute('SELECT * FROM staff WHERE id=202').fetchone())
        contact=message(201,'');contact['message']['contact']={'user_id':202,'phone_number':'fake'};worker.process(contact)
        with server.db() as c:self.assertIsNone(c.execute('SELECT phone FROM staff WHERE id=201').fetchone()['phone'])
        self.assertEqual(self.client.post('/api/invites',json={'role':'manager'},headers=m).status_code,422)

if __name__=='__main__':unittest.main(verbosity=2)
