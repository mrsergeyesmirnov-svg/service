"""Run personally in SSH/Selectel terminal. Never paste token in chat or GitHub."""
import getpass,json,os,re,subprocess,urllib.request
path='/etc/service-academy.env'
d=dict(line.rstrip('\n').split('=',1) for line in open(path) if '=' in line)
token=getpass.getpass('Токен @skill_mojo_bot (ввод скрыт): ').strip()
if not re.fullmatch(r'\d+:[A-Za-z0-9_-]{20,}',token):raise SystemExit('Неверный формат токена')
try:
 with urllib.request.urlopen('https://api.telegram.org/bot'+token+'/getMe',timeout=15) as r:bot=json.load(r)
except Exception:raise SystemExit('Не удалось проверить токен') from None
if not bot.get('ok') or bot['result'].get('username','').lower()!='skill_mojo_bot':raise SystemExit('Это токен другого бота')
owner=input('Ваш числовой Telegram ID (владелец пилота): ').strip()
if not owner.isdigit() or int(owner)<=0:raise SystemExit('Нужен положительный числовой ID')
d.update(BOT_TOKEN=token,OWNER_TELEGRAM_ID=owner)
fd=os.open(path,os.O_WRONLY|os.O_TRUNC,0o600)
with os.fdopen(fd,'w') as f:f.write(''.join(k+'='+v+'\n' for k,v in d.items()))
os.chmod(path,0o600)
print('Настройки сохранены. Запускаю пилот. Токен не выводится.')
subprocess.run(['bash','/opt/service/pilot/deploy-pilot.sh'],check=True)
print('Теперь откройте @skill_mojo_bot и нажмите Старт. Кнопка в сообщении откроет пилот.')
