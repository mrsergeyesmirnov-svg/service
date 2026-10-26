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
    def test_entrypoint_assets_are_served(self):
        import re
        client = TestClient(server.app)
        entry = client.get('/pilot/')
        self.assertEqual(entry.status_code, 200)
        paths = re.findall(r'(?:src|href)="(/pilot/[^"?]+)', entry.text)
        self.assertIn('/pilot/learner.css', paths)
        for path in paths:
            response = client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertTrue(response.content, path)


    def test_pdf_numbered_sections_become_distinct_chapters(self):
        import fitz
        from course_pdf import course_chapters_from_pdf
        doc=fitz.open()
        headings=["1. WOW philosophy", "2. Involvement and initiative", "3. Guest atmosphere"]
        for page_index in range(2):
            page=doc.new_page()
            section_indexes=[0,1] if page_index==0 else [2]
            for j,idx in enumerate(section_indexes):
                y=80+j*260
                page.insert_text((40,y),headings[idx],fontsize=17)
                for line_index in range(4):
                    page.insert_text((45,y+30+line_index*19),
                       "Customer experience improves when the team observes guest needs and helps promptly.",
                       fontsize=10)
        chapters=course_chapters_from_pdf(doc.tobytes(),"WOW.pdf")
        self.assertEqual(len(chapters),3,[c["title"] for c in chapters])
        self.assertTrue(chapters[0]["title"].startswith("1. WOW"))
        self.assertTrue(chapters[1]["title"].startswith("2. Involvement"))
        self.assertEqual(chapters[2]["source"],"WOW.pdf, стр. 2")

    def test_ai_generation_schema_rejects_unsupported_chapters(self):
        from course_ai import validate_generated
        lesson=[{'title':'WOW','body':'Ask the guest first and listen.',
                 'source':'Synthetic source, стр. 1'}]
        question={'type':'multiple','question':'Which actions support the guest?',
                  'options':['Ask','Listen','Guess','Ignore'],'correct':[0,1],
                  'explanation':'Listen before recommending.','chapter':0}
        scenario={'title':'Guest asks for advice','competency':'Care',
                  'action':'Ask and listen','scenario':'A guest is undecided. What will you do?',
                  'criteria':['Clarify the request','Listen attentively'],'chapter':0}
        questions,cases=validate_generated({'questions':[question]*3,'cases':[scenario]},lesson)
        self.assertEqual(len(questions),3)
        self.assertEqual(questions[0]['source'],'Synthetic source, стр. 1')
        self.assertEqual(cases[0]['source'],'Synthetic source, стр. 1')
        wrong=dict(question,chapter=4)
        with self.assertRaises(ValueError):
            validate_generated({'questions':[wrong]*3,'cases':[scenario]},lesson)
        wrong=dict(question,correct=[99])
        with self.assertRaises(server.HTTPException):
            validate_generated({'questions':[wrong]*3,'cases':[scenario]},lesson)

    def test_wow_smile_pdf_courses_are_service(self):
        from learning import category
        for name in ['WOW — ценности MOJO','SMILE — философия гостеприимства','ВАУ — атмосфера']:
            self.assertEqual(category(name),'service')

    def test_pilot_readiness_gate(self):
        from pilot_readiness import evaluate
        good={'telegram_configured':True,'managers':1,'wow':1,'smile':1,
              'mapped_menu':1,'cases':3,'weak_quizzes':0,'ai_configured':True}
        self.assertTrue(all(ok for _,ok in evaluate(good)))
        good['weak_quizzes']=2
        self.assertFalse(all(ok for _,ok in evaluate(good)))
        self.assertTrue(any(not ok and 'тест' in name for name,ok in evaluate(good)))
        good['weak_quizzes']=0
        good['stale_reviewed']=1
        self.assertFalse(all(ok for _,ok in evaluate(good)))
        good['stale_reviewed']=0
        good['wow']=0
        self.assertFalse(all(ok for _,ok in evaluate(good)))

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
    def test_event_creation_role_scope_and_signups(self):
        from datetime import datetime, timedelta, timezone
        manager=self.auth(999);student=self.auth(101);other=self.auth(103)
        starts=(datetime.now(timezone.utc)+timedelta(days=3)).isoformat()
        payload={"title":"Service lesson","description":"Practice","location":"MOJO training room","starts_at":starts}
        self.assertEqual(self.client.post('/api/events',json=payload,headers=student).status_code,403)
        created=self.client.post('/api/events',json=payload,headers=manager)
        self.assertEqual(created.status_code,200,created.text)
        eid=created.json()['id']
        self.assertEqual(self.client.get('/api/events',headers=student).json(),[])
        self.assertEqual(self.client.post(f'/api/events/{eid}/publish',headers=other).status_code,403)
        self.assertEqual(self.client.post(f'/api/events/{eid}/publish',headers=manager).status_code,200)
        rows=self.client.get('/api/events',headers=student).json()
        self.assertEqual(len(rows),1)
        self.assertNotIn('created_by',rows[0])
        self.assertEqual(self.client.post(f'/api/events/{eid}/signup',headers=other).status_code,404)
        self.assertEqual(self.client.get(f'/api/events/{eid}/participants',headers=student).status_code,403)
        self.assertEqual(self.client.post(f'/api/events/{eid}/signup',headers=student).status_code,200)
        self.assertEqual(self.client.post(f'/api/events/{eid}/signup',headers=student).status_code,200)
        people=self.client.get(f'/api/events/{eid}/participants',headers=manager)
        self.assertEqual(len(people.json()),1)
        self.assertEqual(people.json()[0]['id'],101)
        self.assertEqual(self.client.delete(f'/api/events/{eid}/signup',headers=student).status_code,200)
        self.assertEqual(self.client.get(f'/api/events/{eid}/participants',headers=manager).json(),[])
        self.assertEqual(self.client.post(f'/api/events/{eid}/cancel',headers=manager).status_code,200)
        self.assertEqual(self.client.get('/api/events',headers=student).json(),[])

    def test_pdf_ai_proposals_are_private_unpublished_and_once_only(self):
        from psycopg.types.json import Jsonb
        manager=self.auth(999);student=self.auth(101);other=self.auth(103)
        with server.db() as c:
            cid=c.execute("""INSERT INTO courses
              (author,restaurant,title,kind,body,source,questions,pass_score)
              VALUES(999,'MOJO','Synthetic WOW','service','Lesson','Synthetic.pdf','[]'::jsonb,80)
              RETURNING id""").fetchone()['id']
            c.execute("INSERT INTO course_text_outline(course_id,chapters) VALUES(%s,%s)",
                (cid,Jsonb([{'title':'Care','body':'Ask the guest and listen carefully.','source':'Synthetic.pdf, стр. 1'}])))
        route=f'/api/learning/{cid}/generate'
        self.assertEqual(self.client.post(route,headers=student).status_code,403)
        self.assertEqual(self.client.post(route,headers=other).status_code,403)
        q={'type':'single','question':'How should you respond?','options':['Listen','Ignore','Rush'],
           'correct':0,'explanation':'Listen first','source':'Synthetic.pdf, стр. 1'}
        case={'title':'Guest needs help','competency':'Attentive service','action':'Ask the guest',
              'scenario':'The guest asks for guidance. Explain your actions.','source':'Synthetic.pdf, стр. 1',
              'criteria':['Clarify expectations','Avoid invented claims']}
        with patch('learning.generate_review_drafts',return_value=([q],[case])) as fake:
            proposed=self.client.post(route,headers=manager)
            self.assertEqual(proposed.status_code,200,proposed.text)
            self.assertTrue(proposed.json()['review_required'])
            self.assertEqual(proposed.json()['cases'],1)
            self.assertEqual(fake.call_count,1)
        self.assertEqual(self.client.post(route,headers=manager).status_code,409)
        material=next(c for c in self.client.get('/api/courses',headers=manager).json() if c['id']==cid)
        self.assertFalse(material['published'])
        self.assertEqual(len(material['questions']),1)
        self.assertEqual(self.client.get(f'/api/learning/{cid}',headers=student).status_code,404)
        self.assertEqual(self.client.get('/api/cases',headers=student).json(),[])
        drafts=self.client.get('/api/cases',headers=manager).json()
        self.assertEqual(len(drafts),1)
        self.assertFalse(drafts[0]['published'])

    def test_service_manager_uploads_pdf_as_editable_draft_and_adds_test(self):
        import fitz
        from course_pdf import course_chapters_from_pdf
        document = fitz.open()
        for title,body in [
            ('WOW - Involvement', 'Notice guest expectations and offer practical help.'),
            ('SMILE - Sincerity', 'Ask what matters to guests, listen before recommending.'),
        ]:
            page = document.new_page()
            page.insert_text((45,80),title,fontsize=22)
            page.insert_text((45,125),body,fontsize=13)
        raw = document.tobytes()
        chapters = course_chapters_from_pdf(raw, 'MOJO_ServiceBook.pdf')
        self.assertEqual(len(chapters),2)
        self.assertIn('Sincerity',chapters[1]['body'])
        m = self.auth(999)
        trainee = self.auth(101)
        link = '/api/learning/import-pdf?' + urlencode({
            'title':'MOJO Service philosophy', 'filename':'MOJO_ServiceBook.pdf'
        })
        denial = self.client.post(link,content=raw,headers={
            **trainee,'Content-Type':'application/pdf'
        })
        self.assertEqual(denial.status_code,403,denial.text)
        wrong = self.client.post(link,content=raw,headers={
            **m,'Content-Type':'application/octet-stream'
        })
        self.assertEqual(wrong.status_code,415,wrong.text)
        imported = self.client.post(link,content=raw,headers={
            **m,'Content-Type':'application/pdf'
        })
        self.assertEqual(imported.status_code,200,imported.text)
        result = imported.json()
        self.assertFalse(result['duplicate'])
        self.assertEqual(result['chapters'],2)
        cid = result['id']
        existing = self.client.post(link,content=raw,headers={
            **m,'Content-Type':'application/pdf'
        })
        self.assertTrue(existing.json()['duplicate'])
        self.assertEqual(existing.json()['id'],cid)
        row = next(c for c in self.client.get('/api/courses',headers=m).json() if c['id']==cid)
        self.assertFalse(row['published'])
        self.assertEqual(row['questions'],[])
        self.assertEqual(row['kind'],'service')
        readback = self.client.get(f'/api/learning/{cid}/text-chapters',headers=m)
        self.assertEqual(readback.status_code,200,readback.text)
        self.assertEqual(len(readback.json()['chapters']),2)
        self.assertEqual(self.client.post(f'/api/courses/{cid}/publish',headers=m,
            json={'reviewed':True}).status_code,409)
        self.assertEqual(self.client.get(f'/api/learning/{cid}',headers=trainee).status_code,404)
        q = dict(type='multiple',question='Which actions demonstrate care?',
                 options=['Listen','Ask','Ignore','Rush'],correct=[0,1],
                 explanation='Choose respectful and attentive actions.',
                 source='MOJO ServiceBook')
        update = {k:row[k] for k in ('title','kind','body','source','pass_score')}
        update['questions']=[q]
        edited = self.client.put(f'/api/courses/{cid}',headers=m,json=update)
        self.assertEqual(edited.status_code,200,edited.text)
        published = self.client.post(f'/api/courses/{cid}/publish',headers=m,json={'reviewed':True})
        self.assertEqual(published.status_code,200,published.text)
        details = self.client.get(f'/api/learning/{cid}',headers=trainee)
        self.assertEqual(details.status_code,200,details.text)
        self.assertEqual(len(details.json()['chapters']),2)
        self.assertEqual(details.json()['questions'][0]['type'],'multiple')

    def test_pdf_scans_and_long_documents_fail_safely(self):
        import fitz
        from course_pdf import course_chapters_from_pdf
        blank=fitz.open()
        blank.new_page()
        with self.assertRaisesRegex(ValueError, 'текст'):
            course_chapters_from_pdf(blank.tobytes(),'blank.pdf')
        for _ in range(55):
            blank.new_page()
        with self.assertRaisesRegex(ValueError, '55 страниц'):
            course_chapters_from_pdf(blank.tobytes(),'too-long.pdf')

    def test_archive_old_quiz_preserves_all_results(self):
        m=self.auth(999);s=self.auth(101)
        payload=dict(title='Legacy service',kind='service',body='Source learning',
                     source='Synthetic reference',pass_score=80,
                     questions=[dict(question='What is expected?',type='single',
                        options=['Observe','Ignore'],correct=0,explanation='Observe',source='Synthetic')])
        created=self.client.post('/api/courses',json=payload,headers=m)
        self.assertEqual(created.status_code,200,created.text)
        cid=created.json()['id']
        published=self.client.post(f'/api/courses/{cid}/publish',json={'reviewed':True},headers=m)
        self.assertEqual(published.status_code,200,published.text)
        self.assertTrue(any(x['id']==cid for x in self.client.get('/api/learning',headers=s).json()))
        assigned=self.client.post('/api/assignments',headers=m,json={
            'course_id':cid,'staff_ids':[101],'deadline':'2099-01-01','max_attempts':3})
        self.assertEqual(assigned.status_code,200,assigned.text)
        aid=assigned.json()['created'][0]
        self.assertEqual(self.client.post(f'/api/assignments/{aid}/acknowledge',headers=s).status_code,200)
        attempt=self.client.post(f'/api/assignments/{aid}/submit',headers=s,
            json={'request_id':str(uuid.uuid4()),'answers':[0]})
        self.assertEqual(attempt.status_code,200,attempt.text)
        before=self.client.get(f'/api/assignments/{aid}/results',headers=m)
        self.assertEqual(len(before.json()['attempts']),1)
        archived=self.client.post(f'/api/courses/{cid}/archive',headers=m)
        self.assertEqual(archived.status_code,200,archived.text)
        self.assertTrue(archived.json()['results_preserved'])
        self.assertEqual(archived.json()['assignments_affected'],1)
        self.assertFalse(any(x['id']==cid for x in self.client.get('/api/learning',headers=s).json()))
        self.assertEqual(self.client.get(f'/api/learning/{cid}',headers=s).status_code,404)
        self.assertFalse(any(a['id']==aid for a in self.client.get('/api/assignments',headers=s).json()))
        self.assertEqual(self.client.get(f'/api/assignments/{aid}',headers=s).status_code,410)
        self.assertEqual(self.client.post(f'/api/assignments/{aid}/submit',headers=s,
            json={'request_id':str(uuid.uuid4()),'answers':[0]}).status_code,410)
        manager_courses=self.client.get('/api/courses',headers=m).json()
        old=next(c for c in manager_courses if c['id']==cid)
        self.assertTrue(old['archived'])
        self.assertFalse(old['published'])
        manager_assignments=self.client.get('/api/assignments',headers=m).json()
        self.assertTrue(any(x['id']==aid and x['archived'] for x in manager_assignments))
        self.assertEqual(len(self.client.get(f'/api/assignments/{aid}/results',headers=m).json()['attempts']),1)
        self.assertEqual(self.client.post(f'/api/courses/{cid}/publish',headers=m,
            json={'reviewed':True}).status_code,409)
        self.assertEqual(self.client.post('/api/assignments',headers=m,json={
            'course_id':cid,'staff_ids':[102],'deadline':'2099-01-01','max_attempts':3}).status_code,422)
        self.assertEqual(self.client.post(f'/api/courses/{cid}/archive',headers=s).status_code,403)

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

    def test_approved_dish_cards_generate_reviewed_quiz_and_freeze_recipe(self):
        from io import BytesIO
        from PIL import Image
        manager=self.auth(999);trainee=self.auth(101);other=self.auth(103)
        new=self.client.post('/api/courses',headers=manager,json={
            'title':'Synthetic menu course','kind':'ttk',
            'body':'Chapters come from reviewed cards','source':'Synthetic source',
            'questions':[],'pass_score':80
        })
        self.assertEqual(new.status_code,200,new.text)
        cid=new.json()['id']
        self.assertEqual(self.client.post(f'/api/courses/{cid}/publish',
            headers=manager,json={'reviewed':True}).status_code,409)
        created=self.client.post('/api/dishes',headers=manager,json={
            'title':'Synthetic avocado roll','section':'Rolls',
            'ingredients':['Rice','Avocado','Sesame'],
            'description':'Offer with the approved serving description only'
        })
        self.assertEqual(created.status_code,200,created.text)
        did=created.json()['id']
        jpg=BytesIO()
        Image.new('RGB',(120,120)).save(jpg,'JPEG')
        self.assertEqual(self.client.put(f'/api/dishes/{did}/photo',
            headers=manager,content=jpg.getvalue()).status_code,200)
        self.assertEqual(self.client.post(f'/api/dishes/{did}/publish',
            headers=manager,json={'reviewed':True}).status_code,200)
        map_url=f'/api/learning/{cid}/dish-map'
        mapping=self.client.put(map_url,headers=manager,json={'dish_ids':[did]})
        self.assertEqual(mapping.status_code,200,mapping.text)
        self.assertTrue(mapping.json()['generation_ready'])
        route=f'/api/learning/{cid}/generate'
        self.assertEqual(self.client.post(route,headers=trainee).status_code,403)
        self.assertEqual(self.client.post(route,headers=other).status_code,403)
        question={'type':'single','question':'Which description respects the approved recipe?',
            'options':['Rice and avocado','Rice and peanuts','Unknown composition'],
            'correct':0,'explanation':'Only the reviewed components are supported.',
            'source':'Synthetic source'}
        case={'title':'Guest asks about ingredients','competency':'Accuracy',
            'action':'Explain approved ingredients',
            'scenario':'A guest asks about the dish. Explain what you would say.',
            'source':'Synthetic source',
            'criteria':['Use only approved composition','Do not invent allergens']}
        def draft(chapters):
            self.assertEqual(len(chapters),1)
            self.assertIn('Rice, Avocado, Sesame',chapters[0]['body'])
            self.assertIn('Synthetic avocado roll',chapters[0]['title'])
            return [question],[case]
        with patch('learning.generate_review_drafts',side_effect=draft):
            proposed=self.client.post(route,headers=manager)
        self.assertEqual(proposed.status_code,200,proposed.text)
        self.assertEqual(proposed.json()['review_required'],True)
        self.assertEqual(proposed.json()['questions'],1)
        self.assertEqual(proposed.json()['cases'],1)
        self.assertEqual(self.client.post(route,headers=manager).status_code,409)
        draft_course=next(x for x in self.client.get('/api/courses',
            headers=manager).json() if x['id']==cid)
        self.assertFalse(draft_course['published'])
        self.assertTrue(draft_course['reviewed_dish_signature'])
        self.assertEqual(self.client.get(f'/api/learning/{cid}',
            headers=trainee).status_code,404)
        self.assertEqual(self.client.get('/api/cases',headers=trainee).json(),[])
        # Changing a mapped draft must not silently leave stale AI questions.
        self.assertEqual(self.client.put(map_url,headers=manager,
            json={'dish_ids':[]}).status_code,409)
        # Explicit manager edits preserve the recipe snapshot.
        payload={k:draft_course[k] for k in
            ('title','kind','body','source','pass_score','questions')}
        payload['questions'][0]['explanation']='Reviewed against the approved recipe'
        self.assertEqual(self.client.put(f'/api/courses/{cid}',headers=manager,
            json=payload).status_code,200)
        self.assertEqual(self.client.post(f'/api/courses/{cid}/publish',
            headers=manager,json={'reviewed':False}).status_code,422)
        approved=self.client.post(f'/api/courses/{cid}/publish',
            headers=manager,json={'reviewed':True})
        self.assertEqual(approved.status_code,200,approved.text)
        published=self.client.get(f'/api/learning/{cid}',headers=trainee).json()
        self.assertEqual(published['questions'][0]['question'],question['question'])
        self.assertEqual(len(published['questions']),1) # not legacy ingredients quiz
        self.assertEqual(self.client.put(map_url,headers=manager,
            json={'dish_ids':[]}).status_code,409)
        chapter=published['chapters'][0]
        self.assertEqual(self.client.post(f'/api/learning/{cid}/read',
            headers=trainee,json={'chapter_id':chapter['id']}).status_code,200)
        attempt=self.client.post(f'/api/learning/{cid}/submit',headers=trainee,json={
            'request_id':str(uuid.uuid4()),'answers':[0]})
        self.assertEqual(attempt.status_code,200,attempt.text)
        self.assertEqual(attempt.json()['score'],100)
        from datetime import date,timedelta
        assigned=self.client.post('/api/assignments',headers=manager,json={
            'course_id':cid,'staff_ids':[101],
            'deadline':(date.today()+timedelta(days=3)).isoformat(),'max_attempts':2})
        self.assertEqual(assigned.status_code,200,assigned.text)
        aid=assigned.json()['created'][0]
        self.assertEqual(self.client.get(f'/api/assignments/{aid}',
            headers=trainee).status_code,200)
        self.assertEqual(self.client.post(f'/api/assignments/{aid}/acknowledge',
            headers=trainee).status_code,200)
        # A recipe edit cannot silently change a manager-approved, live quiz.
        changed=self.client.put(f'/api/dishes/{did}',headers=manager,json={
            'title':'Synthetic avocado roll','section':'Rolls',
            'ingredients':['Rice','Avocado','Sesame','Cucumber'],
            'description':'Recipe revised after quiz approval'})
        self.assertEqual(changed.status_code,200,changed.text)
        self.assertEqual(self.client.post(f'/api/dishes/{did}/publish',
            headers=manager,json={'reviewed':True}).status_code,200)
        outdated=self.client.get(f'/api/learning/{cid}',headers=trainee).json()
        self.assertEqual(outdated['chapters'],[])
        self.assertEqual(outdated['questions'],[])
        self.assertEqual(len(outdated['history']),1)
        manager_course=next(c for c in self.client.get('/api/courses',headers=manager).json()
                            if c['id']==cid)
        self.assertTrue(manager_course['recipe_changed'])
        self.assertEqual(self.client.get(f'/api/assignments/{aid}',headers=trainee).status_code,409)
        self.assertEqual(self.client.post(f'/api/assignments/{aid}/submit',
            headers=trainee,json={'request_id':str(uuid.uuid4()),'answers':[0]}).status_code,409)
        self.assertEqual(self.client.post('/api/assignments',headers=manager,json={
            'course_id':cid,'staff_ids':[102],
            'deadline':(date.today()+timedelta(days=3)).isoformat(),'max_attempts':2}).status_code,409)
        self.assertEqual(self.client.post(f'/api/learning/{cid}/submit',
            headers=trainee,json={'request_id':str(uuid.uuid4()),'answers':[0]}).status_code,409)

    def test_dish_mapping_reset_needs_manager_confirmation(self):
        from psycopg.types.json import Jsonb
        from io import BytesIO
        from PIL import Image
        m=self.auth(999)
        cid=self.client.post('/api/courses',headers=m,json={
            'title':'Synthetic draft menu','kind':'ttk','body':'Draft',
            'source':'Synthetic','questions':[],'pass_score':80
        }).json()['id']
        ids=[]
        for name in ['Synthetic one','Synthetic two']:
            card=self.client.post('/api/dishes',headers=m,json={
                'title':name,'section':'Rolls','ingredients':['Rice','Salt'],
                'description':'Approved synthetic description'}).json()['id']
            photo=BytesIO();Image.new('RGB',(100,100)).save(photo,'JPEG')
            self.client.put(f'/api/dishes/{card}/photo',headers=m,content=photo.getvalue())
            self.client.post(f'/api/dishes/{card}/publish',headers=m,json={'reviewed':True})
            ids.append(card)
        endpoint=f'/api/learning/{cid}/dish-map'
        self.assertEqual(self.client.put(endpoint,headers=m,json={'dish_ids':[ids[0]]}).status_code,200)
        with server.db() as db:
            db.execute("UPDATE courses SET questions=%s WHERE id=%s",
                (Jsonb([{'type':'single','question':'Old draft','options':['A','B'],
                         'correct':0,'explanation':'Synthetic','source':'Synthetic'}]),cid))
        denied=self.client.put(endpoint,headers=m,json={'dish_ids':ids})
        self.assertEqual(denied.status_code,409,denied.text)
        unchanged=self.client.get(endpoint,headers=m).json()
        self.assertEqual(unchanged['dish_ids'],[ids[0]])
        self.assertEqual(unchanged['questions_count'],1)
        changed=self.client.put(endpoint,headers=m,json={'dish_ids':ids,'reset_quiz':True})
        self.assertEqual(changed.status_code,200,changed.text)
        self.assertTrue(changed.json()['generation_ready'])
        self.assertEqual(self.client.get(endpoint,headers=m).json()['questions_count'],0)

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
        # Failed provider calls must leave an owner-only recoverable answer.
        with patch.object(cases_api,'evaluate_with_yandex',side_effect=server.HTTPException(502,'Unavailable')):
            self.assertEqual(self.client.post(url+'/practice',json=payload,headers=s).status_code,502)
        self.assertEqual(self.client.get(url+'/draft',headers=s).json(),payload)
        self.assertEqual(self.client.get(url+'/draft',headers=other).json(),{})
        self.assertEqual(self.client.get(url+'/draft',headers=local).json(),{})
        self.assertEqual(self.client.get(url+'/history',headers=s).json(),[])
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
        self.assertEqual(self.client.get(url+'/draft',headers=s).json(),{})
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

    def test_forwarded_invite_needs_explicit_manager_approval(self):
        manager=self.auth(999)
        outside=self.auth(103)
        token=self.client.post('/api/invites',json={'role':'trainee'},headers=manager).json()['url'].split('=')[1]
        msg=lambda uid,cmd:{'update_id':uid,'message':{'chat':{'id':uid,'type':'private'},
             'from':{'id':uid,'first_name':'Pending User'},'text':cmd}}
        worker.process(msg(401,'/start '+token))
        pending=self.client.post('/api/login',json={'initData':signed(401)})
        self.assertEqual(pending.status_code,403)
        self.assertIn('одобрения',pending.json()['detail'])
        with server.db() as c:
            staff=c.execute('SELECT role,active,bot_started FROM staff WHERE id=401').fetchone()
            self.assertEqual(staff['role'],'trainee')
            self.assertFalse(staff['active'])
            self.assertTrue(staff['bot_started'])
        self.assertEqual(self.client.post('/api/team/401/approve',headers=outside).status_code,403)
        self.assertEqual(self.client.post('/api/team/401/approve').status_code,401)
        team=self.client.get('/api/team',headers=manager).json()
        self.assertTrue(any(s['id']==401 and not s['active'] for s in team))
        approved=self.client.post('/api/team/401/approve',headers=manager)
        self.assertEqual(approved.status_code,200,approved.text)
        self.assertFalse(approved.json()['already_approved'])
        self.assertEqual(self.client.post('/api/login',json={'initData':signed(401)}).status_code,200)
        again=self.client.post('/api/team/401/approve',headers=manager)
        self.assertTrue(again.json()['already_approved'])
        with server.db() as c:
            sent=c.execute("SELECT count(*) n FROM outbox WHERE dedupe='approval:401'").fetchone()['n']
            self.assertEqual(sent,1)

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
