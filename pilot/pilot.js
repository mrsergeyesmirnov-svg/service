'use strict';
const $=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let token='',user,view='home',cache=[],draft;
const roles={trainee:'Стажёр',waiter:'Официант',manager:'Менеджер по сервису',local:'Менеджер точки'};
const isManager=()=>['manager','local'].includes(user?.role);
let caseCache=[];
const btn=(label,action,id='',cls='')=>`<button class="${cls}" data-action="${action}" data-id="${id}">${label}</button>`;
function error(e){const field=$('#error');field.textContent=e.message||e;field.setAttribute('role','alert');setTimeout(()=>{if(field.textContent===(e.message||e))field.textContent=''},14000)}
async function api(path,method='GET',body){
  const controller=new AbortController(),clock=setTimeout(()=>controller.abort(),45000);
  let response;
  try{
    response=await fetch('/api/'+path,{method,signal:controller.signal,headers:{'Content-Type':'application/json',Authorization:'Bearer '+token},body:body===undefined?undefined:JSON.stringify(body)});
  }catch(e){
    if(e.name==='AbortError')throw Error('Сервер не ответил за 45 секунд. Текст сохранён на экране — проверь соединение и повтори.');
    throw Error('Нет соединения с Академией (сетевая ошибка). Твой ответ остался в поле — попробуй ещё раз.');
  }finally{clearTimeout(clock)}
  let data;
  try{data=await response.json()}catch(e){throw Error('Сервер прислал некорректный ответ. Попробуй снова или сообщи менеджеру.')}
  if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:('Ошибка сервера: '+response.status));
  return data;
}
const navSvg=(name)=>{
  name=({home:'assignments',catalog:'courses'})[name]||name;
  const paths={
    assignments:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    team:'<circle cx="9" cy="8" r="3"/><path d="M3 20v-2a6 6 0 0 1 12 0v2M17 5a3 3 0 0 1 0 6M19 14a5 5 0 0 1 2 4v2"/>',
    courses:'<path d="M12 6c-3-2-6-2-9-1v14c3-1 6-1 9 1m0-14c3-2 6-2 9-1v14c-3-1-6-1-9 1V6Z"/>',
    cases:'<path d="M8 5H5a2 2 0 0 0-2 2v13h15V7a2 2 0 0 0-2-2h-3M8 3h5v4H8zM7 11h7M7 15h9"/>',
    profile:'<circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>'
  };
  return '<svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+paths[name]+'</svg>';
};
function nav(){
 const tabs=isManager()?[['home','Мой путь'],['team','Команда'],['catalog','Курсы'],['cases','Практика'],['profile','Профиль']]:[['home','Мой путь'],['catalog','Курсы'],['assignments','Задания'],['cases','Практика'],['profile','Профиль']];
 $('#nav').innerHTML=tabs.map(([id,label])=>'<button class="nav-item '+((view===id||view==='dishes'&&id==='catalog')?'active':'')+'" data-action="nav" data-id="'+id+'" aria-label="'+label+'" aria-current="'+(view===id?'page':'false')+'">'+navSvg(id)+'<span>'+label+'</span></button>').join('');
}
const done=a=>a.questions?a.passed:!!a.acknowledged_at;
const dateLabel=s=>new Date(s+'T12:00:00').toLocaleDateString('ru-RU');
function overview(items){const n=items.filter(done).length,p=items.length?Math.round(n/items.length*100):0;return `<div class="card progress-card"><h2>${isManager()?'Назначения выполнены':'Прогресс обучения'}: ${n} из ${items.length}</h2><progress max="100" value="${p}" style="width:100%;accent-color:#25483c"></progress><p class="muted">${p}% · ${items.filter(a=>!done(a)&&new Date(a.deadline+'T23:59:59')<new Date()).length} с истёкшим сроком</p></div>`}
const status=a=>a.questions?(a.passed?'Тест сдан':a.attempts?'Нужна пересдача':a.acknowledged_at?'Можно сдавать тест':'Не начато'):(a.acknowledged_at?'Ознакомлен':'Не начато');
async function render(){nav();const root=$('#app');
if(view==='home'||view==='catalog'){await learningPage(view);return}
if(view==='dishes'){await dishesPage();return}
if(view==='cases'){await casesPage();return}
if(view==='profile'){root.innerHTML=`<h1>${esc(user.name)}</h1><div class="card"><p>${esc(roles[user.role])} · ${esc(user.restaurant)}</p><p>Телефон: ${esc(user.phone||'не указан')}</p><p>Чтобы добавить номер, отправьте боту /phone.</p><a class="button" href="https://t.me/skill_mojo_bot">Открыть бота</a></div>`;return}
if(view==='assignments'){cache=await api('assignments');root.innerHTML=`<h1>${isManager()?'Прохождение обучения':'Мои задания'}</h1>`+overview(cache)+(cache.length?cache.map(a=>`<article class="card"><span class="badge">${esc(status(a))}</span><h2>${esc(a.title)}</h2>${isManager()?`<p>${esc(a.name)}</p>`:''}<p class="muted">До ${esc(dateLabel(a.deadline))} · попыток ${a.attempts}/${a.max_attempts}${a.best_score!==null?' · лучший результат '+a.best_score+'%':''}</p>${isManager()?`<p class="muted">Уведомление в Telegram: ${esc(({sent:'отправлено',pending:'в очереди',failed:'не доставлено — проверьте, открыт ли чат с ботом'})[a.notification]||'нет')}</p>${btn('Посмотреть ответы','results',a.id)}${a.staff_id===user.id?btn('Пройти самому','lesson',a.id,'secondary'):''}`:btn('Открыть','lesson',a.id)}</article>`).join(''):'<div class="card">Пока нет назначенных материалов.</div>');return}
if(view==='team'){cache=await api('team');root.innerHTML=`<h1>Команда</h1><div class="card"><label>Пригласить как<select id="invite-role"><option value="trainee">Стажёр</option><option value="waiter">Официант</option></select></label>${btn('Создать приглашение','invite')}<div id="invite-result"></div></div>`+cache.map(s=>`<div class="card"><h2>${esc(s.name)}</h2><p>${esc(roles[s.role])} · ${esc(s.restaurant)}</p>${s.role==='trainee'?btn('Перевести в официанты','promote',s.id):''}</div>`).join('');return}
if(view==='courses'){cache=await api('courses');root.innerHTML='<h1>Обучение</h1><p>'+btn('Создать материал','new')+'</p>'+bulkImportPanel('courses')+cache.map(c=>`<div class="card"><span class="badge">${c.published?'Опубликовано':'Черновик'} · версия #${c.id}</span><h2>${esc(c.title)}</h2><p>${c.questions.length} вопросов · порог ${c.pass_score}%</p><div class="actions">${btn('Предпросмотр для сотрудника','preview',c.id,'secondary')}${c.published?btn('Назначить','assign',c.id)+btn('Создать новую версию','copy',c.id,'secondary'):btn('Редактировать','edit',c.id)+btn('Проверить и опубликовать','publish',c.id,'secondary')}</div></div>`).join('');bindBulkImport('courses');return}}
function qHtml(q,i){return `<fieldset class="question" data-question="${i}"><legend>Вопрос ${i+1}</legend><label>Формат<select name="type">${[['single','Один ответ'],['multiple','Несколько ответов'],['ingredients','Состав по памяти']].map(([v,l])=>`<option value="${v}" ${(q.type||'single')===v?'selected':''}>${l}</option>`).join('')}</select></label><label>Вопрос<input name="question" required value="${esc(q.question)}"></label><label>Варианты выбора — один на строку<textarea name="options">${esc((q.options||[]).join('\n'))}</textarea></label><label>Номера верных вариантов через запятую<input name="correct" value="${esc(q.correct===undefined?'':(Array.isArray(q.correct)?q.correct:[q.correct]).map(n=>n+1).join(', '))}"></label><label>Для состава: ингредиент на строку, допустимые названия через |<textarea name="ingredients">${esc((q.ingredients||[]).map(g=>g.join(' | ')).join('\n'))}</textarea></label><label>Объяснение<textarea name="explanation" required>${esc(q.explanation)}</textarea></label><label>Источник<input name="source" required value="${esc(q.source)}"></label>${btn('Убрать вопрос','remove-q',i,'secondary')}</fieldset>`}
function readDraft(){const f=$('#editor'),data=new FormData(f);draft={...draft,title:data.get('title'),kind:data.get('kind'),body:data.get('body'),source:data.get('source'),pass_score:Number(data.get('pass_score')),questions:[...f.querySelectorAll('[data-question]')].map(q=>{const v=n=>q.querySelector('[name='+n+']').value,type=v('type'),correct=v('correct').split(',').map(x=>Number(x.trim())-1);return {type,question:v('question'),options:v('options').split('\n').map(x=>x.trim()).filter(Boolean),correct:type==='multiple'?correct:correct[0],ingredients:v('ingredients').split('\n').filter(x=>x.trim()).map(x=>x.split('|').map(x=>x.trim()).filter(Boolean)),explanation:v('explanation'),source:v('source')}})}}
function editor(){ $('#app').innerHTML=`<h1>${draft.id?'Редактировать':'Создать'} материал</h1><form id="editor" class="card"><label>Название<input name="title" required maxlength="200" value="${esc(draft.title)}"></label><label>Тип<select name="kind">${[['service','Материал по сервису + тест'],['ttk','Технологическая карта + тест'],['notice','Обязательное ознакомление']].map(([v,l])=>`<option value="${v}" ${draft.kind===v?'selected':''}>${l}</option>`).join('')}</select></label><label>Материал<textarea name="body" class="lesson" required>${esc(draft.body)}</textarea></label><label>Документ-источник и версия<input name="source" required value="${esc(draft.source)}"></label><label>Проходной балл, %<input name="pass_score" type="number" min="1" max="100" value="${draft.pass_score}" required></label><div id="questions">${draft.questions.map(qHtml).join('')}</div><div class="actions">${btn('Добавить вопрос','add-q','','secondary')}<button type="submit">Сохранить черновик</button></div><p class="muted">Для ознакомления без теста уберите вопросы. Генерация ИИ, загрузка документов и аудио пока не подключены.</p></form>`;$('#editor').onsubmit=async e=>{e.preventDefault();readDraft();try{await api('courses'+(draft.id?'/'+draft.id:''),draft.id?'PUT':'POST',draft);view='courses';await render()}catch(e){error(e)}};$('#editor').querySelectorAll('[data-action]').forEach(b=>b.type='button')}
async function lesson(id){const a=await api('assignments/'+id);$('#app').innerHTML=`${btn('К заданиям','nav','assignments','secondary')}<h1>${esc(a.title)}</h1><div class="card"><div class="body">${esc(a.body)}</div><p class="muted">Источник: ${esc(a.source)}</p>${a.acknowledged_at?'<span class="badge">Ознакомление подтверждено</span>':btn('Я ознакомился с материалом','ack',id)}</div><p>Проходной балл: ${a.pass_score}%. Попыток осталось: ${Math.max(0,a.max_attempts-a.history.length)}.</p>${a.questions.length&&a.acknowledged_at&&a.history.length<a.max_attempts&&!a.finished?`<form id="quiz">${a.questions.map((q,i)=>`<div class="card"><h2>${i+1}. ${esc(q.question)}</h2>${questionInput(q,'q'+i)}</div>`).join('')}<button>Отправить ответы</button></form>`:''}${a.review?.length?`<div class="card"><h2>Разбор после завершения теста</h2>${a.review.map(q=>`<h3>${esc(q.question)}</h3><p>Правильный ответ: ${esc(correctLabel(q))}</p><p>${esc(q.explanation)}</p><p class="muted">${esc(q.source)}</p>`).join('')}</div>`:''}<div class="card"><h2>История попыток</h2>${a.history.map(t=>`<p>${esc(new Date(t.created_at).toLocaleString('ru-RU'))}: ${t.score}% · ${t.passed?'сдано':'не сдано'}</p>`).join('')||'<p>Попыток пока нет</p>'}</div>`;if($('#quiz')){const rid=crypto.randomUUID();$('#quiz').onsubmit=async e=>{e.preventDefault();const button=e.target.querySelector('button');button.disabled=true;try{const f=new FormData(e.target);const result=await api('assignments/'+id+'/submit','POST',{request_id:rid,answers:a.questions.map((q,i)=>readAnswer(q,f,'q'+i))});await lesson(id);alert(`Результат: ${result.score}%. ${result.passed?'Тест сдан.':'Тест не сдан.'}`)}catch(e){button.disabled=false;error(e)}}}}
async function assignForm(id){const team=await api('team');$('#app').innerHTML=`<h1>Назначить обучение</h1><form id="assign" class="card"><label>Срок<input type="date" name="deadline" required></label><label>Число попыток<input name="max_attempts" type="number" min="1" max="20" value="3" required></label><h2>Сотрудники</h2>${team.filter(s=>(['trainee','waiter'].includes(s.role)||s.id===user.id)&&s.active).map(s=>`<label><input type="checkbox" name="staff" value="${s.id}">${esc(s.name)}</label>`).join('')}<p>После назначения бот отправит каждому выбранному сотруднику сообщение в личный чат.</p><button>Назначить и уведомить</button></form>`;$('#assign').onsubmit=async e=>{e.preventDefault();const b=e.target.querySelector('button');b.disabled=true;try{const f=new FormData(e.target);const r=await api('assignments','POST',{course_id:Number(id),staff_ids:f.getAll('staff').map(Number),deadline:f.get('deadline'),max_attempts:Number(f.get('max_attempts'))});view='assignments';await render();if(!r.created.length)alert('Этот курс уже назначен выбранным сотрудникам.')}catch(e){b.disabled=false;error(e)}}}
document.addEventListener('click',async e=>{const b=e.target.closest('[data-action]');if(!b)return;const {action,id}=b.dataset;try{switch(action){case'nav':view=id;await render();break;case'case-results':await caseResults(Number(id));break;case'case-new':caseEditor();break;case'case-review':caseReview(Number(id));break;case'case-edit':caseEditor(Number(id));break;case'case-open':await caseDetail(Number(id));break;case'case-publish':if(confirm('Материал, источник и критерии проверены менеджером?')){await api('cases/'+id+'/publish','POST',{reviewed:true});await casesPage()}break;case'case-archive':if(confirm('Скрыть старую опубликованную версию от сотрудников? История ответов сохранится.')){await api('cases/'+id+'/archive','POST',{confirmed:true});await casesPage()}break;case'invite':{const r=await api('invites','POST',{role:$('#invite-role').value});$('#invite-result').innerHTML=`<p>Одноразовая ссылка, действует 7 дней:</p><input readonly value="${esc(r.url)}"><p class="muted">Отправьте сотруднику. Он должен открыть ссылку и нажать «Старт».</p>`;break}case'promote':if(confirm('Подтвердить перевод сотрудника в официанты после очного допуска?')){await api('team/'+id+'/role','POST',{role:'waiter'});await render()}break;case'preview':previewCourse(cache.find(c=>c.id==id));break;case'new':draft={title:'',body:'',source:'',kind:'service',pass_score:80,questions:[]};editor();break;case'edit':case'copy':draft=structuredClone(cache.find(x=>x.id==id));if(action==='copy')delete draft.id;editor();break;case'add-q':readDraft();draft.questions.push({question:'',options:['',''],correct:0,explanation:'',source:''});editor();break;case'remove-q':readDraft();draft.questions.splice(Number(id),1);editor();break;case'publish':{const c=cache.find(x=>x.id==id);$('#app').innerHTML=`<h1>Проверка перед публикацией</h1><div class="card"><h2>${esc(c.title)}</h2><div class="body">${esc(c.body)}</div></div>${c.questions.map(q=>`<div class="card"><h3>${esc(q.question)}</h3><ol>${(q.options||[]).map((v,j)=>`<li>${esc(v)}${(Array.isArray(q.correct)?q.correct.includes(j):j===q.correct)?' — правильный':''}</li>`).join('')}${q.type==='ingredients'?'<li>'+esc(correctLabel(q))+'</li>':''}</ol><p>${esc(q.explanation)}</p><p class="muted">${esc(q.source)}</p></div>`).join('')}${btn('Материал и ответы проверены — опубликовать','approve',id)}`;break}case'approve':await api('courses/'+id+'/publish','POST',{reviewed:true});await render();break;case'assign':await assignForm(id);break;case'lesson':await lesson(id);break;case'ack':await api('assignments/'+id+'/acknowledge','POST',{});await lesson(id);break;case'results':{const r=await api('assignments/'+id+'/results');$('#app').innerHTML='<h1>Ответы сотрудника</h1>'+r.attempts.map(t=>`<div class="card"><h2>${t.score}% · ${t.passed?'Сдано':'Не сдано'}</h2><p>${esc(new Date(t.created_at).toLocaleString('ru-RU'))}</p>${r.questions.map((q,i)=>`<p><b>${esc(q.question)}</b><br>Ответ: ${esc(answerLabel(q,t.answers[i]))}<br>Правильно: ${esc(correctLabel(q))}</p>`).join('')}</div>`).join('');break}}}catch(e){error(e)}});
(async()=>{try{const h=await api('health');if(!h.telegram_configured)throw Error('Подключение пилота ещё не завершено. Администратор настраивает бота.');const tg=window.Telegram?.WebApp;if(!tg?.initData)throw Error('Откройте Академию через личный чат с @skill_mojo_bot. Для первого входа нужна ссылка-приглашение.');tg.ready();tg.expand();const r=await api('login','POST',{initData:tg.initData});token=r.token;user=r.user;await render();const aid=new URLSearchParams(location.search).get('assignment');if(aid)await lesson(Number(aid))}catch(e){$('#app').innerHTML=`<h1>Академия сервиса</h1><div class="card"><p>${esc(e.message)}</p><a class="button" href="https://t.me/skill_mojo_bot">Открыть бота</a></div>`}})();

function previewCourse(c){
 $('#app').innerHTML=btn('К материалам','nav','courses','secondary')+'<p class="badge">Предпросмотр · результат не сохраняется</p><h1>'+esc(c.title)+'</h1><article class="card body">'+esc(c.body)+'</article><form id="preview-quiz">'+c.questions.map((q,i)=>'<article class="card"><h2>'+esc(q.question)+'</h2>'+questionInput(q,'q'+i)+'</article>').join('')+'<button>Посмотреть разбор</button></form><div id="preview-result"></div>';
 $('#preview-quiz').onsubmit=e=>{e.preventDefault();const f=new FormData(e.target);$('#preview-result').innerHTML=c.questions.map((q,i)=>reviewQuestion(q,readAnswer(q,f,'q'+i),i)).join('');$('#preview-result').scrollIntoView()};
}

async function casesPage(){
  caseCache=await api('cases');
  const root=$('#app');
  let html="<div class='section-heading'><span class='eyebrow'>MOJO / практика</span><h1>Учимся на ситуациях</h1><p class='muted'>Представь себя на смене. Опиши своё решение своими словами — без подсказок.</p></div>";
  if(isManager())html+="<p>"+btn('Создать кейс','case-new')+"</p>"+bulkImportPanel('cases');
  html+=caseCache.length?caseCache.map(c=>{
    return "<div class='card case-card'><span class='badge'>"+esc(c.archived?'Архив':c.published?'Опубликовано':'Черновик')+"</span><h2>"+esc(c.title)+"</h2>"+(isManager()?"<p class='muted'>"+esc(c.competency)+" · "+esc(c.action)+"</p>":"<p class='muted'>Реальная ситуация из смены. Подумай самостоятельно, прежде чем отвечать.</p>")+"<div class='actions'>"+(c.archived?"":c.published?btn('Решить кейс','case-open',c.id):btn('Предпросмотр и проверка','case-review',c.id))+(isManager()?(c.published&&!c.archived?btn('Снять с публикации','case-archive',c.id,'secondary'):"")+btn("Ответы команды","case-results",c.id,"secondary"):"")+"</div></div>";
  }).join(''):"<div class='card'>Пока нет утверждённых практических кейсов. Менеджер добавит ситуации на основе ServiceBook.</div>";
  root.innerHTML=html;
  if(isManager())bindBulkImport('cases');
}
function caseEditor(caseId){
  const editing=caseCache.find(c=>c.id===caseId&&!c.published&&!c.archived);
  $('#app').innerHTML="<h1>Новый практический кейс</h1><p class='muted'>До публикации менеджер проверяет источник и наблюдаемые действия. ИИ не должен оценивать личность.</p>"+
  "<form class='card' id='case-create'>"+
  "<label>Название<input name='title' required maxlength='200' placeholder='Помочь гостю выбрать'></label>"+
  "<label>Компетенция<input name='competency' required maxlength='200' placeholder='Проактивная забота о госте'></label>"+
  "<label>Наблюдаемое действие<input name='action' required maxlength='400' placeholder='Уточняет предпочтения и ограничения'></label>"+
  "<label>Ситуация<textarea name='scenario' required maxlength='2000' placeholder='Гость спрашивает...'></textarea></label>"+
  "<label>Критерии успешного действия (один на строку, 2–8)<textarea name='criteria' required placeholder='Задал не более 2–3 уточняющих вопросов\nНе придумал ингредиенты'></textarea></label>"+
  "<label>Источник, версия, страницы<input name='source' required maxlength='1000' placeholder='MOJO ServiceBook 2026, с. 9–10'></label>"+
  "<button type='submit'>Сохранить черновик</button></form>";
  if(editing){const f=$('#case-create');for(const k of ['title','competency','action','scenario','source'])f.elements.namedItem(k).value=editing[k];f.elements.namedItem('criteria').value=editing.criteria.join('\n')}
  $('#case-create').onsubmit=async e=>{
    e.preventDefault();
    const f=new FormData(e.target), data=Object.fromEntries(f);
    data.criteria=String(data.criteria).split('\n').map(x=>x.trim()).filter(Boolean);
    const b=e.target.querySelector('button');b.disabled=true;
    try{await api('cases'+(editing?'/'+editing.id:''),editing?'PUT':'POST',data);await casesPage()}
    catch(err){b.disabled=false;error(err)}
  };
}

function caseReview(id){
  const c=caseCache.find(x=>x.id===id&&!x.published&&!x.archived);
  if(!c)return;
  $('#app').innerHTML=btn('Назад к кейсам','nav','cases','secondary')+
    "<h1>Проверка кейса</h1><div class='card'><h2>"+esc(c.title)+"</h2>"+
    "<p><b>Компетенция:</b> "+esc(c.competency)+"</p>"+
    "<p><b>Действие:</b> "+esc(c.action)+"</p>"+
    "<p><b>Ситуация:</b> "+esc(c.scenario)+"</p>"+
    "<p><b>Источник:</b> "+esc(c.source)+"</p>"+
    "<h3>Критерии оценки ответов ИИ</h3><ol>"+
    c.criteria.map(x=>"<li>"+esc(x)+"</li>").join('')+"</ol>"+
    "<p class='muted'>Перед публикацией проверь актуальность документа и формулировок. ИИ не присваивает допуск.</p>"+
    btn('Отредактировать','case-edit',c.id,'secondary')+" "+
    btn('Материал проверен — опубликовать','case-publish',c.id)+"</div>";
}

async function caseDetail(id){
  const c=caseCache.find(x=>x.id===id);
  if(!c || !c.published || c.archived){await casesPage();return}
  const history=await api('cases/'+id+'/history');
  const previous=history.map(h=>
    "<article class='card'><p class='muted'>"+esc(new Date(h.created_at).toLocaleString('ru-RU'))+"</p>"+
    "<p><b>Твой ответ:</b> "+esc(h.answer)+"</p>"+
    "<p><b>Разбор:</b> "+esc(h.feedback.summary)+"</p>"+
    "<p><b>Сильные стороны:</b> "+esc(h.feedback.strengths)+"</p>"+
    "<p><b>Что улучшить:</b> "+esc(h.feedback.improvements)+"</p>"+
    "<p><b>Следующий шаг:</b> "+esc(h.feedback.next_step)+"</p></article>"
  ).join('');
  $('#app').innerHTML=btn('Все кейсы','nav','cases','secondary')+
    "<div class='section-heading'><span class='eyebrow'>Ситуационная практика</span><h1>"+esc(c.title)+"</h1><p class='muted'>Как бы ты поступил на реальной смене?</p></div>"+
    "<article class='card case-scenario'><span class='eyebrow'>Ситуация</span><p class='body case-prompt'>"+esc(c.scenario)+"</p></article>"+
    "<form id='case-answer' class='card case-answer-card'><h2>Твоё решение</h2><label>Расскажи, что ты сделаешь и что скажешь гостю<textarea name='answer' required minlength='40' maxlength='1600' placeholder='Я бы поступил так…'></textarea></label>"+
    "<p class='muted'>Не указывай имена гостей, телефоны и другие персональные данные. Ответ отправится в Yandex AI Studio для разбора. Не является экзаменом.</p>"+
    "<button type='submit' class='lime-action'>Разобрать с ИИ →</button><p id='case-request-state' class='muted' role='status' aria-live='polite'></p></form>"+
    "<section id='case-feedback'></section>"+
    (history.length?"<h2>Предыдущие разборы</h2>"+previous:"");
  let retryRequestId=null,lastAnswer='';
  $('#case-answer').onsubmit=async e=>{
    e.preventDefault();const button=e.target.querySelector('button'),status=$('#case-request-state');button.disabled=true;
    const answer=e.target.querySelector('textarea').value;
    if(answer!==lastAnswer){retryRequestId=crypto.randomUUID();lastAnswer=answer}
    status.textContent='ИИ анализирует твой ответ. Не закрывай экран.';
    try{
      const f=await api('cases/'+id+'/practice','POST',{answer,request_id:retryRequestId});
      $('#case-feedback').innerHTML="<article class='card'><h2>Разбор ситуации</h2>"+
        "<p>"+esc(f.summary)+"</p><h3>Что получилось</h3><p>"+esc(f.strengths)+"</p>"+
        "<h3>Что улучшить</h3><p>"+esc(f.improvements)+"</p>"+
        "<h3>Следующий шаг</h3><p>"+esc(f.next_step)+"</p>"+
        "<p class='muted'>Обратная связь ИИ — учебная, а не решение о допуске.</p></article>";
      status.textContent='Разбор готов. Ответ сохранён в истории обучения.';
      retryRequestId=null;lastAnswer='';
      button.disabled=false;
      $('#case-feedback').scrollIntoView({behavior:'smooth'});
    }catch(err){button.disabled=false;status.textContent='Не получилось получить обратную связь. Ответ не пропал — можно повторить.';error(err)}
  };
}


function bulkImportPanel(kind){
  const type=kind==='cases'?'кейсы':'курсы';
  return "<form class='card' id='bulk-import'>"+
    "<h2>Добавить готовые "+type+"</h2>"+
    "<p class='muted'>Выберите подготовленный JSON-файл. Импортируются только черновики — сотрудники не получат уведомлений до утверждения и назначения.</p>"+
    "<label>Файл курсов или кейсов в JSON<input id='bulk-json' type='file' accept='.json,application/json' required></label>"+
    "<button type='submit'>Добавить в Академию</button>"+
    "<p class='muted'>Загрузить можно до 20 материалов за раз. Повторная загрузка одинаковых материалов не создаёт дубликаты.</p>"+
    "</form>";
}
function bindBulkImport(kind){
  const form=$('#bulk-import');if(!form)return;
  form.onsubmit=async e=>{
    e.preventDefault();
    const f=$('#bulk-json')?.files?.[0];if(!f)return;
    if(f.size>280000){error('Пакет слишком большой. Разбейте JSON на несколько файлов до 280 КБ.');return}
    const submit=form.querySelector('button');submit.disabled=true;
    try{
      const data=JSON.parse(await f.text());
      if(!Array.isArray(data)||data.length<1||data.length>20)throw Error('Ожидается список от 1 до 20 материалов');
      const r=await api(kind+'/import','POST',data);
      alert('Добавлено черновиков: '+r.created.length+'. Уже существовали: '+r.skipped+'.');
      if(kind==='cases')await casesPage();else await render();
    }catch(e){error(e)}finally{submit.disabled=false}
  };
}


async function caseResults(id){
 const rows=await api('cases/'+id+'/results');
 $('#app').innerHTML=btn('К кейсам','nav','cases','secondary')+'<h1>Ответы команды</h1>'+ (rows.length?rows.map(r=>`<article class="card"><h2>${esc(r.name)}</h2><p class="muted">${esc(new Date(r.created_at).toLocaleString('ru-RU'))}</p><p class="body">${esc(r.answer)}</p><h3>Учебный разбор</h3><p>${esc(r.feedback.summary)}</p><p>${esc(r.feedback.strengths)}</p><p>${esc(r.feedback.improvements)}</p><h3>Следующий практический шаг</h3><p>${esc(r.feedback.next_step)}</p><p class="muted">Выполнение на смене подтверждает руководитель. Разбор ИИ не является допуском.</p></article>`).join(''):'<div class="card">Ответов пока нет.</div>');
}
