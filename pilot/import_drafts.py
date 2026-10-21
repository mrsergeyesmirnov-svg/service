"""Import private course JSON from stdin. Do not commit material payloads."""
import hashlib,json,sys
from server import db,OWNER,course_data,audit,Jsonb
raw=sys.stdin.read();items=json.loads(raw)
if not isinstance(items,list) or not 1<=len(items)<=20:raise SystemExit('Expected 1..20 courses')
validated=[course_data(d) for d in items]
key='course_import:'+hashlib.sha256(raw.encode()).hexdigest()
with db() as c:
 c.execute('SELECT pg_advisory_xact_lock(823410)')
 if c.execute('SELECT 1 FROM settings WHERE key=%s',(key,)).fetchone():raise SystemExit('Already imported')
 owner=c.execute("SELECT * FROM staff WHERE id=%s AND role='manager' AND active",(OWNER,)).fetchone()
 if not owner:raise SystemExit('Owner must press Start in the bot before importing')
 for title,kind,body,source,qs,score in validated:
  row=c.execute('INSERT INTO courses(author,restaurant,title,kind,body,source,questions,pass_score) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id',(OWNER,owner['restaurant'],title,kind,body,source,Jsonb(qs),score)).fetchone()
  audit(c,OWNER,'course:import-draft',row['id'])
 c.execute('INSERT INTO settings(key,value) VALUES(%s,%s)',(key,str(len(items))))
print('Drafts imported:',len(items))
