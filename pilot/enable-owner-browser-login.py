"""One-time local setup for the existing Academy owner. Run only on Selectel with DATABASE_URL configured."""
import getpass
import os
import psycopg
from browser_auth import password_hash

owner = int(os.environ["OWNER_TELEGRAM_ID"])
if owner <= 0:
    raise SystemExit("OWNER_TELEGRAM_ID is required")
print("Enabling browser login for existing owner ID:", owner)
password = getpass.getpass("New browser password (min 12 characters): ")
repeat = getpass.getpass("Repeat password: ")
if password != repeat:
    raise SystemExit("Passwords do not match")
hashed = password_hash(password)
with psycopg.connect(os.environ["DATABASE_URL"]) as c:
    found = c.execute("SELECT id,role FROM staff WHERE id=%s AND active", (owner,)).fetchone()
    if not found or found[1] != "manager":
        raise SystemExit("Active owner manager record not found. No account created.")
    c.execute("""INSERT INTO browser_credentials(staff_id,password_hash)
                 VALUES(%s,%s) ON CONFLICT(staff_id) DO UPDATE
                 SET password_hash=EXCLUDED.password_hash,failed_attempts=0,locked_until=NULL""",
              (owner,hashed))
print("Browser credentials configured. Login with existing owner ID.")
