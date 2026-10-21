"""Temporary, capability-protected setup. Never logs requests or credentials."""
import hashlib, hmac, json, os, re, secrets, time, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
ROOT=Path('/setup-state')
ORIGIN='https://service.139.100.239.232.sslip.io'
PAGE='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Подключение Академии</title><style>body{font:17px system-ui;background:#f5f6f0;color:#203b32;max-width:460px;margin:60px auto;padding:24px}input,button{box-sizing:border-box;width:100%;padding:16px;margin:10px 0 22px;border:1px solid #bdc9c1;border-radius:12px;font:inherit}button{background:#203b32;color:white}p{line-height:1.5}</style><h1>Подключить бота</h1><p>Токен отправляется непосредственно на ваш сервер Selectel. Ссылка действует один час и закрывается после сохранения.</p><form id="form"><label>Токен @skill_mojo_bot<input id="token" type="password" autocomplete="off" required></label><label>Ваш числовой Telegram ID<input id="owner" inputmode="numeric" pattern="[0-9]+" required></label><button>Подключить</button></form><p id="status" role="status"></p><script>const key=location.hash.slice(1);history.replaceState(null,'',location.pathname);const form=document.getElementById('form'),status=document.getElementById('status');if(!key){form.hidden=true;status.textContent='Нужна полная одноразовая ссылка.'}form.onsubmit=async e=>{e.preventDefault();const button=form.querySelector('button');button.disabled=true;status.textContent='Проверяем бота…';try{const r=await fetch('/setup/save',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+key},body:JSON.stringify({token:document.getElementById('token').value,owner:document.getElementById('owner').value})});const d=await r.json();status.textContent=d.message;if(r.ok){form.reset();form.hidden=true}else{button.disabled=false}}catch(e){status.textContent='Не удалось получить ответ. Проверьте соединение; если данные уже сохранены, бот подключится автоматически.';button.disabled=false}};</script></html>'''
def settings():
    return dict(line.rstrip('\n').split('=',1) for line in Path('/config/service-academy.env').read_text().splitlines() if '=' in line)
def check_bot(token):
    for method in ('getMe','getWebhookInfo'):
        with urllib.request.urlopen('https://api.telegram.org/bot'+token+'/'+method,timeout=15) as r: d=json.load(r)
        if not d.get('ok'):raise ValueError()
        if method=='getMe' and d['result'].get('username','').lower()!='skill_mojo_bot':raise ValueError()
        if method=='getWebhookInfo' and d['result'].get('url'):raise ValueError()
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,code,body,kind='application/json'):
        data=(body if isinstance(body,str) else json.dumps(body,ensure_ascii=False)).encode()
        self.send_response(code)
        for k,v in {'Content-Type':kind+'; charset=utf-8','Content-Length':str(len(data)),'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Content-Security-Policy':"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'"}.items():self.send_header(k,v)
        self.end_headers();self.wfile.write(data)
    def do_GET(self):
        if self.path!='/setup/':return self.reply(404,{'message':'Не найдено'})
        if time.time()>self.server.expires or (ROOT/'done').exists():return self.reply(410,{'message':'Страница настройки закрыта.'})
        self.reply(200,PAGE,'text/html')
    def do_POST(self):
        if self.path!='/setup/save':return self.reply(404,{})
        if time.time()>self.server.expires or (ROOT/'done').exists():return self.reply(410,{'message':'Ссылка уже закрыта.'})
        key=self.headers.get('Authorization','').removeprefix('Bearer ')
        if not hmac.compare_digest(hashlib.sha256(key.encode()).hexdigest(),self.server.keyhash):return self.reply(403,{'message':'Неверная ссылка.'})
        if self.headers.get('Origin')!=ORIGIN:return self.reply(403,{'message':'Откройте страницу по исходной ссылке.'})
        if time.time()<self.server.next_try:return self.reply(429,{'message':'Подождите несколько секунд.'})
        self.server.next_try=time.time()+5
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=2048:raise ValueError()
            d=json.loads(self.rfile.read(size));token=d['token'].strip();owner=str(d['owner']).strip()
            if not re.fullmatch(r'\d+:[A-Za-z0-9_-]{20,}',token) or not owner.isdigit() or not 0<int(owner)<2**63:raise ValueError()
            cfg=settings()
            if cfg.get('BOT_TOKEN'):return self.reply(409,{'message':'Бот уже настроен; замена через эту страницу запрещена.'})
            check_bot(token)
        except Exception:return self.reply(422,{'message':'Проверьте токен и числовой ID. Нужен @skill_mojo_bot без подключённого webhook.'})
        cfg.update(BOT_TOKEN=token,OWNER_TELEGRAM_ID=owner)
        target=Path('/config/service-academy.env');tmp=target.with_suffix('.tmp')
        fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:
            f.write(''.join(k+'='+v+'\n' for k,v in cfg.items()));f.flush();os.fsync(f.fileno())
        os.replace(tmp,target)
        (ROOT/'done').touch(mode=0o600)
        self.reply(200,{'message':'Настройки сохранены. Запуск займёт около минуты. Затем откройте @skill_mojo_bot и нажмите Старт.'})
if __name__=='__main__':
    state=json.loads((ROOT/'access.json').read_text())
    server=HTTPServer(('0.0.0.0',8765),Handler);server.keyhash=state['hash'];server.expires=state['expires'];server.next_try=0
    server.serve_forever()
