"""Private admin-only JSON draft import via stdin. Never commit real course text."""
import hashlib,json,sys
from cases_api import case_payload
from server import db,OWNER,audit,Jsonb

raw=sys.stdin.read()
data=json.loads(raw)
if not isinstance(data,list) or not 1<=len(data)<=20:
    raise SystemExit("Expected 1..20 cases")
items=[case_payload(item) for item in data]
key="cases_import:"+hashlib.sha256(raw.encode()).hexdigest()
with db() as c:
    c.execute("SELECT pg_advisory_xact_lock(823411)")
    if c.execute("SELECT 1 FROM settings WHERE key=%s",(key,)).fetchone():
        raise SystemExit("Already imported")
    owner=c.execute("SELECT * FROM staff WHERE id=%s AND role='manager' AND active",(OWNER,)).fetchone()
    if not owner:
        raise SystemExit("Owner must press Start in the bot first")
    for item in items:
        row=c.execute("""INSERT INTO case_scenarios
            (author,restaurant,title,competency,action,scenario,source,criteria)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (OWNER,owner["restaurant"],item["title"],item["competency"],item["action"],
            item["scenario"],item["source"],Jsonb(item["criteria"]))).fetchone()
        audit(c,OWNER,"case:import-draft",row["id"])
    c.execute("INSERT INTO settings(key,value) VALUES(%s,%s)",(key,str(len(items))))
print("Draft cases imported:",len(items))
