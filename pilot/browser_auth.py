"""Browser fallback for the Academy. Never trust a Telegram ID supplied by a browser."""
import hashlib
import hmac
import secrets
import time
from fastapi import APIRouter, HTTPException, Request

router = APIRouter()
ITERATIONS = 310000

def password_hash(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        raise HTTPException(422, "Пароль должен содержать от 12 до 128 символов")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return salt.hex() + ":" + digest.hex()

def verify(password, stored):
    try:
        salt, expected = stored.split(":")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS)
        return hmac.compare_digest(digest, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False

def attach(app, db, require, manager, audit):
    @app.post("/api/browser/register")
    async def register(request: Request):
        d = await request.json()
        name = d.get("name", "")
        code = d.get("invite", "")
        password = d.get("password", "")
        if not isinstance(name, str) or not 2 <= len(name.strip()) <= 120:
            raise HTTPException(422, "Укажи имя и фамилию")
        if not isinstance(code, str) or not 10 <= len(code) <= 200:
            raise HTTPException(422, "Неверное приглашение")
        stored = password_hash(password)
        with db() as c:
            invitation = c.execute(
                "SELECT * FROM invites WHERE token=%s AND used_by IS NULL AND NOT revoked AND expires_at>now() FOR UPDATE",
                (code,)
            ).fetchone()
            if not invitation:
                raise HTTPException(403, "Приглашение использовано или срок истёк")
            # Negative identifiers cannot collide with positive Telegram IDs.
            for _ in range(5):
                staff_id = -secrets.randbelow(2**60-1)-1
                if not c.execute("SELECT 1 FROM staff WHERE id=%s", (staff_id,)).fetchone():
                    break
            else:
                raise HTTPException(503, "Повтори регистрацию")
            c.execute(
                "INSERT INTO staff(id,name,role,restaurant,active,bot_started) VALUES(%s,%s,%s,%s,false,false)",
                (staff_id,name.strip(),invitation["role"],invitation["restaurant"])
            )
            c.execute(
                "INSERT INTO browser_credentials(staff_id,password_hash) VALUES(%s,%s)",
                (staff_id,stored)
            )
            c.execute("UPDATE invites SET used_by=%s WHERE token=%s",(staff_id,code))
            audit(c,staff_id,"browser:registered",invitation["restaurant"])
        return {"pending": True, "staff_id": staff_id, "message": "Заявка отправлена. Дождись подтверждения менеджера."}

    @app.post("/api/browser/login")
    async def browser_login(request: Request):
        d = await request.json()
        staff_id = d.get("staff_id")
        password = d.get("password", "")
        if not isinstance(staff_id, str) or not staff_id.lstrip("-").isdigit() or len(staff_id)>20 or not isinstance(password,str) or len(password)>128:
            raise HTTPException(401, "Неверный номер сотрудника или пароль")
        with db() as c:
            credential = c.execute(
                """SELECT b.password_hash,b.failed_attempts,b.locked_until,s.id,s.active FROM browser_credentials b JOIN staff s ON s.id=b.staff_id
                   WHERE b.staff_id=%s FOR UPDATE""",(int(staff_id),)
            ).fetchone()
            if credential and credential["locked_until"] and credential["locked_until"].timestamp()>time.time():
                raise HTTPException(429, "Слишком много попыток. Повтори через 15 минут")
            # Do equivalent work for missing users to reduce account enumeration.
            valid = verify(password, credential["password_hash"] if credential else "00"*16 + ":" + "00"*32)
            if not credential or not valid:
                if credential:
                    attempts = credential["failed_attempts"]+1
                    c.execute(
                        """UPDATE browser_credentials SET failed_attempts=%s,
                           locked_until=CASE WHEN %s>=5 THEN now()+interval '15 minutes' ELSE NULL END
                           WHERE staff_id=%s""",(attempts,attempts,int(staff_id))
                    )
                raise HTTPException(401, "Неверный номер сотрудника или пароль")
            if not credential["active"]:
                raise HTTPException(403, "Ожидается подтверждение менеджера")
            c.execute("UPDATE browser_credentials SET failed_attempts=0,locked_until=NULL WHERE staff_id=%s",(int(staff_id),))
            session = secrets.token_urlsafe(32)
            c.execute("INSERT INTO sessions(token_hash,staff_id,expires_at) VALUES(%s,%s,now()+interval '8 hours')",
                      (hashlib.sha256(session.encode()).hexdigest(),int(staff_id)))
            member = c.execute("SELECT * FROM staff WHERE id=%s",(int(staff_id),)).fetchone()
        return {"token":session,"user":member}

    @app.post("/api/browser/enable")
    async def enable_browser(request: Request):
        d=await request.json()
        stored=password_hash(d.get("password"))
        with db() as c:
            u=require(c,request)
            # A logged-in user may add browser access only to their own account.
            c.execute(
                """INSERT INTO browser_credentials(staff_id,password_hash) VALUES(%s,%s)
                   ON CONFLICT(staff_id) DO UPDATE SET password_hash=EXCLUDED.password_hash,
                   failed_attempts=0,locked_until=NULL""",(u["id"],stored)
            )
            audit(c,u["id"],"browser:enabled",u["id"])
        return {"staff_id":u["id"]}
