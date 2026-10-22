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
