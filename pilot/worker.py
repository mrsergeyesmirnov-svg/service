"""One polling worker, persistent update offset and notification outbox."""
import json, time, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta
from server import db, TOKEN, OWNER, URL, audit

class TelegramError(Exception):
    def __init__(self,code,retry=60):self.code=code;self.retry=retry

def telegram(method,**data):
    req=urllib.request.Request(f'https://api.telegram.org/bot{TOKEN}/{method}',data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=40) as r:out=json.load(r)
    except urllib.error.HTTPError as e:
        try: out=json.load(e)
        except Exception:out={}
        raise TelegramError(e.code,out.get('parameters',{}).get('retry_after',60)) from None
    except (OSError,TimeoutError):raise TelegramError(0) from None
    if not out.get('ok'):raise TelegramError(out.get('error_code',0))
    return out['result']

def queue(c,sid,message,key,aid=None):
    c.execute('INSERT INTO outbox(recipient,message,dedupe,assignment_id) VALUES(%s,%s,%s,%s) ON CONFLICT(dedupe) DO NOTHING',(sid,message,key,aid))

def process(update):
    msg=update.get('message',{}); chat=msg.get('chat',{});sender=msg.get('from',{})
    if chat.get('type')!='private' or sender.get('id')!=chat.get('id'):return
    sid=sender['id']; name=' '.join(filter(None,[sender.get('first_name'),sender.get('last_name')]))[:200] or str(sid)
    txt=msg.get('text',''); key=f'update:{update["update_id"]}'
    with db() as c:
        u=c.execute('SELECT * FROM staff WHERE id=%s FOR UPDATE',(sid,)).fetchone()
        if sid==OWNER and not u:
            c.execute("INSERT INTO staff(id,name,role,bot_started) VALUES(%s,%s,'manager',true)",(sid,name));u={'active':True}
        if txt.startswith('/start'):
            if not u:
                invite=txt.split(maxsplit=1)[1] if len(txt.split(maxsplit=1))==2 else ''
                i=c.execute('SELECT * FROM invites WHERE token=%s AND NOT revoked AND used_by IS NULL AND expires_at>now() FOR UPDATE',(invite,)).fetchone()
                if not i:
                    # No membership is created without a valid invitation.
                    telegram('sendMessage',chat_id=sid,text='Для входа нужна действующая ссылка-приглашение от руководителя.');return
                c.execute('INSERT INTO staff(id,name,role,restaurant,bot_started) VALUES(%s,%s,%s,%s,true)',(sid,name,i['role'],i['restaurant']))
                c.execute('UPDATE invites SET used_by=%s WHERE token=%s',(sid,invite));audit(c,sid,'invite:accepted',i['restaurant'])
                u={'active':True}
            if not u['active']:return
            c.execute('UPDATE staff SET bot_started=true WHERE id=%s',(sid,))
            queue(c,sid,'Добро пожаловать в Академию сервиса. Здесь будут приходить обязательные уроки и тесты. Откройте приложение кнопкой ниже.\nЧтобы привязать номер телефона, отправьте /phone.',key)
        elif u and u['active'] and txt=='/phone':
            telegram('sendMessage',chat_id=sid,text='Если вы согласны передать свой номер для профиля сотрудника, нажмите кнопку. Без передачи номера обучение остаётся доступным.',reply_markup={'keyboard':[[{'text':'Передать мой номер','request_contact':True}]],'resize_keyboard':True,'one_time_keyboard':True})
        elif u and u['active'] and msg.get('contact',{}).get('user_id')==sid:
            c.execute('UPDATE staff SET phone=%s WHERE id=%s',(msg['contact']['phone_number'],sid));audit(c,sid,'phone:shared',sid)
            queue(c,sid,'Номер добавлен в ваш профиль.',key)

def deliver():
    # Single worker: transaction holds row lock while sending. A network timeout
    # after Telegram accepted a message can produce a duplicate on retry.
    with db() as c:
        row=c.execute("SELECT * FROM outbox WHERE state='pending' AND next_try<=now() ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1").fetchone()
        if not row:return
        link=URL+(f'?assignment={row["assignment_id"]}' if row['assignment_id'] else '')
        try:
            telegram('sendMessage',chat_id=row['recipient'],text=row['message'],reply_markup={'inline_keyboard':[[{'text':'Открыть Академию','web_app':{'url':link}}]]})
            c.execute("UPDATE outbox SET state='sent',sent_at=now(),error=NULL WHERE id=%s",(row['id'],))
        except TelegramError as e:
            tries=row['tries']+1
            status='failed' if e.code in (400,403) or tries>=10 else 'pending'
            delay=max(e.retry,min(3600,30*2**min(tries,7)))
            c.execute('UPDATE outbox SET state=%s,tries=%s,next_try=%s,error=%s WHERE id=%s',(status,tries,datetime.now(timezone.utc)+timedelta(seconds=delay),f'Telegram {e.code}',row['id']))

if __name__=='__main__':
    if not TOKEN or not OWNER:raise SystemExit('Telegram not configured; worker disabled')
    identity=telegram('getMe')
    if identity.get('username','').lower()!='skill_mojo_bot':raise SystemExit('Wrong bot: expected skill_mojo_bot')
    if telegram('getWebhookInfo').get('url'):raise SystemExit('Existing webhook detected; not changing it automatically')
    print('Worker ready',flush=True)
    while True:
        try:
            with db() as c:
                item=c.execute("SELECT value FROM settings WHERE key='telegram_offset'").fetchone()
                offset=int(item['value']) if item else 0
            updates=telegram('getUpdates',offset=offset,timeout=2,allowed_updates=['message'])
            for update in updates:
                process(update)
                with db() as c:c.execute("INSERT INTO settings VALUES('telegram_offset',%s) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(update['update_id']+1),))
            for _ in range(10):deliver()
        except Exception as e:
            # Never log exception text: HTTP errors may contain the bot token.
            print('Worker retry: '+type(e).__name__,flush=True);time.sleep(5)
