"""Operational checks; no credentials or personal values are printed."""
from server import db,OWNER
from worker import telegram,TelegramError
with db() as c:
 print('owner_registered:',bool(c.execute('SELECT 1 FROM staff WHERE id=%s AND active',(OWNER,)).fetchone()))
 for table in ('staff','courses','assignments','attempts'):
  print(table+':',c.execute('SELECT count(*) n FROM '+table).fetchone()['n'])
 print('notifications:',c.execute('SELECT state,count(*) FROM outbox GROUP BY state').fetchall())
try:
 print('bot_identity_ok:',telegram('getMe').get('username')=='skill_mojo_bot')
 print('webhook_active:',bool(telegram('getWebhookInfo').get('url')))
except TelegramError as e: print('telegram_error_code:',e.code)
