"""Local owner bootstrap. --web issues a 30-minute single-use mobile setup link."""
import getpass
import hashlib
import os
import secrets
import sys
from urllib.parse import urlsplit
import psycopg
from browser_auth import password_hash

owner = int(os.environ["OWNER_TELEGRAM_ID"])
if owner <= 0:
    raise SystemExit("OWNER_TELEGRAM_ID is required")
with psycopg.connect(os.environ["DATABASE_URL"]) as c:
    found = c.execute("SELECT id,role FROM staff WHERE id=%s AND active", (owner,)).fetchone()
    if not found or found[1] != "manager":
        raise SystemExit("Active owner manager record not found. No account created.")
    if "--web" in sys.argv:
        url = urlsplit(os.environ.get("PUBLIC_URL", "https://service.139.100.239.232.sslip.io/pilot/"))
        if url.scheme != "https" or not url.netloc:
            raise SystemExit("PUBLIC_URL must use HTTPS")
        token = secrets.token_urlsafe(32)
        c.execute("""INSERT INTO browser_password_setup(staff_id,token_hash,expires_at)
            VALUES(%s,%s,now()+interval '30 minutes') ON CONFLICT(staff_id) DO UPDATE
            SET token_hash=EXCLUDED.token_hash,expires_at=EXCLUDED.expires_at""",
            (owner, hashlib.sha256(token.encode()).hexdigest()))
        c.commit()
        print(url.scheme+"://"+url.netloc+"/pilot/setup-password#"+token)
    else:
        print("Enabling browser login for existing owner ID:", owner)
        password = getpass.getpass("New browser password (min 12 characters): ")
        repeat = getpass.getpass("Repeat password: ")
        if password != repeat:
            raise SystemExit("Passwords do not match")
        hashed = password_hash(password)
        c.execute("""INSERT INTO browser_credentials(staff_id,password_hash) VALUES(%s,%s)
            ON CONFLICT(staff_id) DO UPDATE SET password_hash=EXCLUDED.password_hash,
            failed_attempts=0,locked_until=NULL""", (owner,hashed))
        c.execute("DELETE FROM sessions WHERE staff_id=%s", (owner,))
        c.execute("DELETE FROM browser_password_setup WHERE staff_id=%s", (owner,))
        print("Browser credentials configured. Login with existing owner ID.")
