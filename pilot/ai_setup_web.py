"""One-use Yandex credential intake. No access to existing application secrets."""
import hashlib
import hmac
import json
import os
import re
import time
from http.server import HTTPServer
from pathlib import Path
from setup_web import Handler as BaseHandler

ROOT = Path('/setup-state')
ORIGIN = 'https://service.139.100.239.232.sslip.io'
PAGE = '''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Подключение Yandex AI — MOJO</title><style>body{font:17px system-ui;background:#F8FAF6;color:#233F34;max-width:460px;margin:40px auto;padding:24px}input,button{box-sizing:border-box;width:100%;padding:16px;margin:8px 0 24px;border:1px solid #E6EDE8;border-radius:12px;font:inherit}button{background:#233F34;color:white}p{line-height:1.5}</style><h1>Подключить Yandex AI</h1><p>Ключ отправляется по HTTPS непосредственно на ваш сервер Selectel. Ссылка одноразовая, действует один час.</p><form id="form"><label>API-ключ Yandex AI Studio<input id="key" type="password" autocomplete="off" maxlength="512" required></label><label>ID каталога (Folder ID)<input id="folder" autocomplete="off" pattern="[a-zA-Z0-9_-]{10,64}" required></label><button>Сохранить защищённо</button></form><p id="status" role="status"></p><script>const access=location.hash.slice(1);history.replaceState(null,'',location.pathname);const form=document.getElementById('form'),status=document.getElementById('status');if(!access){form.hidden=true;status.textContent='Откройте полную одноразовую ссылку.'}form.onsubmit=async e=>{e.preventDefault();const button=form.querySelector('button');button.disabled=true;status.textContent='Сохраняем…';try{const r=await fetch('/ai-setup/save',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+access},body:JSON.stringify({key:document.getElementById('key').value,folder:document.getElementById('folder').value})});const d=await r.json();status.textContent=d.message;if(r.ok){form.reset();form.hidden=true}else button.disabled=false}catch(e){status.textContent='Нет ответа от сервера. Повторите отправку. Если ссылка уже закрыта, данные сохранены.';button.disabled=false}};</script></html>'''

def validated_settings(data):
    key = data['key'].strip()
    folder = data['folder'].strip()
    if not re.fullmatch(r'[A-Za-z0-9_.=-]{20,512}', key):
        raise ValueError('key format')
    if not re.fullmatch(r'[A-Za-z0-9_-]{10,64}', folder):
        raise ValueError('folder format')
    return f'YANDEX_API_KEY={key}\nYANDEX_FOLDER_ID={folder}\n'

class Handler(BaseHandler):
    def closed(self):
        return time.time() > self.server.expires or (ROOT / 'ai.env').exists()

    def do_GET(self):
        if self.path != '/ai-setup/':
            return self.reply(404, {})
        if self.closed():
            return self.reply(410, {'message': 'Одноразовая форма закрыта.'})
        self.reply(200, PAGE, 'text/html')

    def do_POST(self):
        if self.path != '/ai-setup/save':
            return self.reply(404, {})
        if self.closed():
            return self.reply(410, {'message': 'Форма закрыта: данные уже сохранены или срок ссылки истёк.'})
        access = self.headers.get('Authorization', '').removeprefix('Bearer ')
        if not hmac.compare_digest(hashlib.sha256(access.encode()).hexdigest(), self.server.keyhash):
            return self.reply(403, {'message': 'Неверная одноразовая ссылка.'})
        if self.headers.get('Origin') != ORIGIN:
            return self.reply(403, {'message': 'Используйте исходную страницу.'})
        if time.time() < self.server.next_try:
            return self.reply(429, {'message': 'Повторите через пять секунд.'})
        self.server.next_try = time.time() + 5
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 2048:
                raise ValueError('size')
            value = validated_settings(json.loads(self.rfile.read(size)))
        except (ValueError, KeyError, TypeError, AttributeError):
            return self.reply(422, {'message': 'Проверьте формат API-ключа и ID каталога.'})
        tmp = ROOT / 'pending'
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as output:
                output.write(value)
                output.flush()
                os.fsync(output.fileno())
            os.replace(tmp, ROOT / 'ai.env')
        except OSError:
            tmp.unlink(missing_ok=True)
            return self.reply(500, {'message': 'Не удалось сохранить. Повторите попытку.'})
        self.reply(200, {'message': 'Ключ сохранён на Selectel. Вернитесь в чат и напишите «сохранил»: следующим шагом проверим ответ Yandex и подключим Академию.'})

if __name__ == '__main__':
    state = json.loads((ROOT / 'access.json').read_text())
    server = HTTPServer(('0.0.0.0', 8765), Handler)
    server.keyhash = state['hash']
    server.expires = state['expires']
    server.next_try = 0
    server.serve_forever()
