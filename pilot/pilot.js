'use strict';
const $=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let token='',user,view='home',cache=[],draft,managerMode=false;
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
    events:'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4M17 3v4M3 10h18"/>',
    dashboard:'<path d="M3 12h8V3H3zM14 3h7v6h-7zM14 12h7v9h-7zM3 15h8v6H3z"/>',
    profile:'<circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>'
  };
  return '<svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+paths[name]+'</svg>';
};
function nav(){
  const m=isManager()&&managerMode;
  const tabs=m?(user.role==='manager'
    ?[['dashboard','Обзор'],['courses','Программы'],['team','Команда'],['events','Мероприятия'],['profile','Профиль']]
    :[['dashboard','Команда'],['courses','Обучение'],['events','Мероприятия'],['profile','Профиль']])
    :[['home','Мой путь'],['catalog','Курсы'],['events','Мероприятия'],['profile','Профиль']];
  $('#nav').classList.toggle('manager-nav',m);
  $('#nav').setAttribute('aria-label',m?'Управление Академией':'Разделы обучения');
  $('#nav').innerHTML=tabs.map(([id,label])=>{
    const active=view===id||(id==='catalog'&&!m&&view==='cases')||(m&&id==='courses'&&['dishes','cases'].includes(view));
    return '<button class="nav-item '+(active?'active':'')+'" data-action="nav" data-id="'+id+'" aria-label="'+label+'" aria-current="'+(active?'page':'false')+'">'+navSvg(id)+'<span>'+label+'</span></button>';
  }).join('');
}
function workspaceHeader(title,subtitle){
  return '<div class="workspace-head">'+btn('← Обзор','nav','dashboard','secondary')+
    '<span class="eyebrow">MOJO / УПРАВЛЕНИЕ</span><h1>'+esc(title)+'</h1><p class="muted">'+esc(subtitle)+'</p></div>';
}
async function managerDashboard(){
  const [team,courses,assignments,events]=await Promise.all([api('team'),api('courses'),api('assignments'),api('events')]);
  const pending=team.filter(s=>!s.active).length,active=team.filter(s=>s.active).length;
  const actual=assignments.filter(a=>!a.archived),complete=actual.filter(done).length;
  const approved=courses.filter(c=>c.published&&!c.archived).length,upcoming=events.filter(e=>e.published&&!e.cancelled&&new Date(e.starts_at)>new Date());
  $('#app').innerHTML='<span class="eyebrow">MOJO / АКАДЕМИЯ СЕРВИСА</span><h1>'+(user.role==='manager'?'Обзор Академии':'Моя команда')+'</h1>'+
    '<p class="muted">Обучение, сотрудники и ближайшие мероприятия.</p>'+
    '<div class="manager-stats"><div><strong>'+active+'</strong><span>сотрудников</span></div>'+
      '<div><strong>'+approved+'</strong><span>программ</span></div>'+
      '<div><strong>'+complete+'/'+actual.length+'</strong><span>выполнено</span></div></div>'+
    (pending?'<div class="card manager-urgent"><h2>Заявки на доступ: '+pending+'</h2>'+
      '<p class="muted">Проверь личности сотрудников перед подтверждением.</p>'+btn('Проверить заявки','nav','team','lime-action')+'</div>':'')+
    '<section class="card manager-home-primary"><span class="eyebrow">СОЗДАНИЕ ПРОГРАММЫ</span>'+
      '<h2>Обучение по материалам MOJO</h2><p class="muted">Загрузи PDF, проверь главы и предложения ИИ, затем опубликуй курс.</p>'+
      btn('Открыть программы →','nav','courses','lime-action')+'</section>'+
    '<div class="manager-tools"><button class="manager-tool" data-action="nav" data-id="team"><strong>Команда →</strong>'+
      '<small>Доступы и подтверждения</small></button>'+
      '<button class="manager-tool" data-action="nav" data-id="assignments"><strong>Результаты →</strong>'+
      '<small>Прогресс и попытки</small></button>'+
      '<button class="manager-tool" data-action="nav" data-id="events"><strong>Мероприятия →</strong>'+
      '<small>Тренинги и запись</small></button>'+
      '<button class="manager-tool" data-action="manager-cases"><strong>Практика →</strong>'+
      '<small>Открытые кейсы с ИИ</small></button></div>'+
    '<h2>Ближайшие мероприятия</h2>'+
    (upcoming.length?upcoming.slice(0,2).map(e=>'<div class="card"><strong>'+esc(e.title)+'</strong>'+
      '<p class="muted">'+esc(new Date(e.starts_at).toLocaleString('ru-RU'))+' · '+esc(e.location)+'</p></div>').join(''):
     '<p class="muted">Опубликованных встреч пока нет.</p>')+
    '<p class="manager-secondary">'+btn('Открыть мой учебный путь','leave-manage','','secondary')+'</p>';
}
const done=a=>a.questions?a.passed:!!a.acknowledged_at;
const dateLabel=s=>new Date(s+'T12:00:00').toLocaleDateString('ru-RU');
function overview(items){const n=items.filter(done).length,p=items.length?Math.round(n/items.length*100):0;return `<div class="card progress-card"><h2>${isManager()?'Назначения выполнены':'Прогресс обучения'}: ${n} из ${items.length}</h2><progress max="100" value="${p}" style="width:100%;accent-color:#25483c"></progress><p class="muted">${p}% · ${items.filter(a=>!done(a)&&new Date(a.deadline+'T23:59:59')<new Date()).length} с истёкшим сроком</p></div>`}
const qualityNotice=c=>(c.quality_issues?.length?'<div class="card" role="note"><strong>Проверить вопросы: '+c.quality_issues.length+'</strong><ul>'+c.quality_issues.map(w=>'<li>№'+w.question+': '+esc(w.message)+'</li>').join('')+'</ul><p class="muted">Замечания автоматические; итоговую проверку проводит менеджер.</p></div>':'');
const status=a=>a.archived?'Архив':a.questions?(a.passed?'Тест сдан':a.attempts?'Нужна пересдача':a.acknowledged_at?'Можно сдавать тест':'Не начато'):(a.acknowledged_at?'Ознакомлен':'Не начато');
async function render(){nav();const root=$('#app');
if(view==='home'||view==='catalog'){await learningPage(view);return}
if(view==='dashboard'){await managerDashboard();return}
if(view==='events'){await eventsPage();return}
if(view==='dishes'){await dishesPage();return}
if(view==='cases'){await casesPage();return}
if(view==='profile'){root.innerHTML=`<h1>${esc(user.name)}</h1><div class="card"><p>${esc(roles[user.role])} · ${esc(user.restaurant)}</p><p>Телефон: ${esc(user.phone||'не указан')}</p><p>Чтобы добавить номер, отправьте боту /phone.</p><a class="button" href="https://t.me/skill_mojo_bot">Открыть бота</a></div>${isManager()?'<div class="card"><h2>Управление Академией</h2><p>Программы, сотрудники и результаты — в одном кабинете.</p>'+btn('Открыть кабинет менеджера','open-manager','','lime-action')+'</div>':''}`;return}
if(view==='assignments'){cache=await api('assignments');const current=cache.filter(a=>!a.archived);
  if(isManager()&&managerMode){
    const groups=new Map();
    for(const a of cache){const k=a.staff_id;if(!groups.has(k))groups.set(k,{name:a.name,items:[]});groups.get(k).items.push(a)}
    const completed=current.filter(done).length;
    root.innerHTML=workspaceHeader('Результаты','Прогресс по сотрудникам и история назначений.')+
      '<div class="manager-stats"><div><strong>'+current.length+'</strong><span>назначений</span></div><div><strong>'+completed+'</strong><span>выполнено</span></div><div><strong>'+groups.size+'</strong><span>сотрудников</span></div></div>'+
      ([...groups.values()].map(g=>'<details class="card manager-list"><summary><strong>'+esc(g.name)+'</strong><span>'+g.items.filter(done).length+' из '+g.items.length+' выполнено</span></summary>'+
        g.items.map(a=>'<div class="manager-assignment"><span class="badge">'+esc(status(a))+'</span><h3>'+esc(a.title)+'</h3><p class="muted">До '+esc(dateLabel(a.deadline))+' · попыток '+a.attempts+'/'+a.max_attempts+(a.best_score!==null?' · '+a.best_score+'%':'')+'</p>'+
        '<p class="muted">Уведомление: '+esc(({sent:'доставлено',pending:'в очереди',failed:'ошибка доставки'})[a.notification]||'нет')+'</p>'+btn('Посмотреть ответы','results',a.id,'secondary')+'</div>').join('')+'</details>').join('')||'<div class="card">Назначений пока нет.</div>');
  }else{
    root.innerHTML='<h1>Мои задания</h1>'+overview(current)+(current.length?current.map(a=>'<article class="card"><span class="badge">'+esc(status(a))+'</span><h2>'+esc(a.title)+'</h2><p class="muted">До '+esc(dateLabel(a.deadline))+'</p>'+btn('Открыть','lesson',a.id,'lime-action')+'</article>').join(''):'<div class="card">Пока нет назначенных материалов.</div>');
  }return}
if(view==='team'){cache=await api('team');const pending=cache.filter(s=>!s.active),active=cache.filter(s=>s.active);
  root.innerHTML=workspaceHeader('Команда','Приглашения и доступ сотрудников.')+
    '<div class="manager-stats"><div><strong>'+active.length+'</strong><span>активных</span></div><div><strong>'+pending.length+'</strong><span>ждут подтверждения</span></div></div>'+
    (pending.length?'<h2>Новые заявки</h2>'+pending.map(s=>'<div class="card manager-list"><strong>'+esc(s.name)+'</strong><p>'+esc(roles[s.role])+' · '+esc(s.restaurant)+'</p><p class="muted">Telegram ID: '+esc(s.id)+' · сверь лично перед одобрением</p>'+btn('Подтвердить доступ','approve-staff',s.id,'lime-action')+'</div>').join(''):'')+
    '<details class="card manager-list"><summary><strong>Пригласить сотрудника</strong><span>Одноразовая ссылка</span></summary><label>Пригласить как<select id="invite-role"><option value="trainee">Стажёр</option><option value="waiter">Официант</option></select></label>'+btn('Создать приглашение','invite')+'<div id="invite-result"></div></details>'+
    '<h2>Сотрудники</h2>'+(active.length?active.map(s=>'<details class="card manager-list"><summary><strong>'+esc(s.name)+'</strong><span>'+esc(roles[s.role])+'</span></summary><p class="muted">'+esc(s.restaurant)+'</p>'+(s.role==='trainee'?btn('Перевести в официанты','promote',s.id,'secondary'):'')+'</details>').join(''):'<div class="card">Пока нет активных сотрудников.</div>');return}
if(view==='courses'){await programsPage();return}}
async function programsPage(){
  cache=await api('courses');
  const active=cache.filter(c=>!c.archived),archive=cache.filter(c=>c.archived);
  function entry(c){
    const primary=c.recipe_changed?btn('Создать новую версию','copy',c.id,'lime-action'):
      c.archived?btn('Создать новую версию','copy',c.id,'secondary'):
      c.published?btn('Назначить сотрудникам','assign',c.id,'lime-action'):
        btn('Редактировать','edit',c.id,'lime-action')+btn('Проверить и опубликовать','publish',c.id,'secondary');
    const extras=(!c.published&&!c.archived&&!c.questions.length?btn('Предложить тесты и кейсы (ИИ)','ai-generate',c.id,'secondary'):'')+
      btn('Предпросмотр','preview',c.id,'secondary')+
      (!c.archived?btn('Собрать главы из карточек','course-map',c.id,'secondary')+btn('Редактор текстовых глав','course-text-editor',c.id,'secondary'):'')+
      (c.archived?'':c.published?btn('Создать новую версию','copy',c.id,'secondary')+btn('Архивировать курс','archive-course',c.id,'secondary'):btn('Архивировать черновик','archive-course',c.id,'secondary'));
    return '<details class="card manager-list manager-course"><summary><span><strong>'+esc(c.title)+'</strong><small>'+c.questions.length+' вопросов'+(c.recipe_changed?' · ⚠ рецептура изменилась':'')+(c.quality_issues?.length?' · ⚠ проверить '+c.quality_issues.length:'')+'</small></span><span class="badge">'+(c.archived?'Архив':c.published?'Опубликовано':'Черновик')+'</span></summary>'+
      '<div class="manager-course-actions">'+(c.recipe_changed?'<p class="muted">Утверждённые карточки изменились после создания теста. Текущую версию нельзя назначать или проходить. Собери новую версию и проверь вопросы.</p>':'')+'<div class="actions">'+primary+'</div><details class="manager-more"><summary>Дополнительные действия</summary><div class="actions">'+extras+'</div></details></div></details>';
  }
  $('#app').innerHTML=workspaceHeader('Программы','Создавай и назначай курсы, проверяй материалы перед публикацией.')+
    '<details class="card manager-create"><summary><strong>+ Создать материал</strong><span>PDF или вручную</span></summary>'+
      '<p class="muted">Загрузи учебный PDF — из него появится редактируемый черновик курса.</p>'+coursePdfPanel()+
      '<div class="actions">'+btn('Скачать шаблон ТТК','dish-template','','secondary')+btn('Загрузить заполненный шаблон','dish-open','','lime-action')+btn('Собрать курс из карточек блюд','dish-course-new','','secondary')+btn('Создать вручную','new','','secondary')+'</div></details>'+
    '<div class="manager-tools"><button data-action="dish-open" class="manager-tool"><strong>Карточки блюд · управление →</strong><small>Фото, составы и PDF станционок</small></button>'+
      '<button data-action="manager-cases" class="manager-tool"><strong>Практические кейсы →</strong><small>Тренировки и разборы ИИ</small></button></div>'+
    '<div class="row manager-section-title"><h2>Материалы</h2><span class="badge">'+active.length+'</span></div>'+
    (active.map(entry).join('')||'<div class="card">Начни с загрузки учебного PDF или создай курс вручную.</div>')+
    '<details class="card archive-list"><summary><strong>Архив</strong><span>'+archive.length+' материалов</span></summary>'+
       (archive.map(entry).join('')||'<p class="muted">Архив пуст.</p>')+'</details>'+
    '<details class="card manager-more"><summary>Для разработчика: импорт JSON</summary>'+bulkImportPanel('courses')+'</details>';
  bindBulkImport('courses');bindCoursePdfImport();
}
function dishCourseForm(){
  $('#app').innerHTML=workspaceHeader('Курс из карточек блюд','Сначала собери курс из утверждённых карточек. Затем ИИ предложит тесты и практические кейсы.')+
    '<form id="dish-course-form" class="card">'+
    '<label>Название курса<input name="title" maxlength="180" required placeholder="Например, Основное меню MOJO · холодный цех"></label>'+
    '<label>Проходной балл, %<input name="pass_score" type="number" min="1" max="100" value="80" required></label>'+
    '<button type="submit" class="lime-action">Выбрать карточки →</button></form>';
  $('#dish-course-form').onsubmit=async e=>{
    e.preventDefault();
    const form=e.target,button=form.querySelector('[type=submit]');
    button.disabled=true;
    try{
      const fields=new FormData(form);
      const course=await api('courses','POST',{
        title:fields.get('title').trim(),kind:'ttk',
        body:'Учебные главы собраны из проверенных карточек блюд MOJO.',
        source:'Утверждённые карточки блюд MOJO',
        questions:[],pass_score:Number(fields.get('pass_score'))
      });
      await editCourseDishMap(course.id);
    }catch(err){error(err);button.disabled=false;}
  };
}
async function publishReviewScreen(c){
  if(!c)throw Error('Курс не найден');
  const mapping=await api('learning/'+c.id+'/dish-map');
  let material='';
  let ready=true;
  if(mapping.dish_ids.length){
    const cards=await api('dishes');
    const byId=new Map(cards.map(x=>[x.id,x]));
    const missing=mapping.dish_ids.filter(id=>!byId.get(id)?.published);
    ready=missing.length===0;
    material='<section class="card"><h2>Проверка карточек: '+mapping.dish_ids.length+'</h2>'+
      (missing.length?'<p class="academy-manager-warning">Некоторые карточки сняты с публикации. Сначала заново утверди рецептуры.</p>':'')+
      mapping.dish_ids.map((id,i)=>{
        const card=byId.get(id);
        if(!card||!card.published)return '<p>Карточка №'+id+' · требует утверждения</p>';
        return '<details class="manager-more"><summary>'+(i+1)+'. '+esc(card.title)+
          ' · '+card.ingredients.length+' компонентов</summary>'+
          '<p><strong>Состав:</strong> '+esc(card.ingredients.join(', '))+'</p>'+
          '<p>'+esc(card.description)+'</p>'+
          '<p class="muted">Источник: '+esc(card.source_name)+(card.source_page?' · стр. '+card.source_page:'')+'</p></details>';
      }).join('')+'</section>';
  }else{
    material='<section class="card"><h2>Учебный материал</h2><div class="body">'+esc(c.body)+'</div>'+
      '<p class="muted">Проверь главы в редакторе перед публикацией.</p></section>';
  }
  const review=c.questions.map((q,i)=>'<details class="card manager-more"><summary>Вопрос '+(i+1)+': '+esc(q.question)+'</summary>'+
    (q.type==='ingredients'?'<p>Проверенный состав: '+esc(q.ingredients.map(x=>x[0]).join(', '))+'</p>':
     '<ol>'+q.options.map((v,j)=>'<li>'+esc(v)+
     ((Array.isArray(q.correct)?q.correct.includes(j):j===q.correct)?' — правильный':'')+'</li>').join('')+'</ol>')+
    '<p>'+esc(q.explanation)+'</p><p class="muted">Источник: '+esc(q.source)+'</p></details>').join('');
  $('#app').innerHTML=workspaceHeader('Проверка перед публикацией','Убедись, что составы, формулировки и правильные ответы соответствуют материалам MOJO.')+
    qualityNotice(c)+material+'<h2>Вопросы: '+c.questions.length+'</h2>'+
    (review||'<div class="card">Тест пока не создан. Сначала получи предложения ИИ и проверь их.</div>')+
    (ready&&c.questions.length?'<section class="card"><p>Практические кейсы публикуются отдельно после проверки их критериев.</p>'+
      btn('Материал и ответы проверены — опубликовать','approve',c.id,'lime-action')+'</section>':
      '<p class="muted">Публикация недоступна, пока не утверждены все карточки и вопросы.</p>')+
    btn('Вернуться к программам','nav','courses','secondary');
}
function qHtml(q,i){return `<fieldset class="question" data-question="${i}"><legend>Вопрос ${i+1}</legend><label>Формат<select name="type">${[['single','Один ответ'],['multiple','Несколько ответов'],['ingredients','Состав по памяти']].map(([v,l])=>`<option value="${v}" ${(q.type||'single')===v?'selected':''}>${l}</option>`).join('')}</select></label><label>Вопрос<input name="question" required value="${esc(q.question)}"></label><label>Варианты выбора — один на строку<textarea name="options">${esc((q.options||[]).join('\n'))}</textarea></label><label>Номера верных вариантов через запятую<input name="correct" value="${esc(q.correct===undefined?'':(Array.isArray(q.correct)?q.correct:[q.correct]).map(n=>n+1).join(', '))}"></label><label>Для состава: ингредиент на строку, допустимые названия через |<textarea name="ingredients">${esc((q.ingredients||[]).map(g=>g.join(' | ')).join('\n'))}</textarea></label><label>Объяснение<textarea name="explanation" required>${esc(q.explanation)}</textarea></label><label>Источник<input name="source" required value="${esc(q.source)}"></label>${btn('Убрать вопрос','remove-q',i,'secondary')}</fieldset>`}
function readDraft(){const f=$('#editor'),data=new FormData(f);draft={...draft,title:data.get('title'),kind:data.get('kind'),body:data.get('body'),source:data.get('source'),pass_score:Number(data.get('pass_score')),questions:[...f.querySelectorAll('[data-question]')].map(q=>{const v=n=>q.querySelector('[name='+n+']').value,type=v('type'),correct=v('correct').split(',').map(x=>Number(x.trim())-1);return {type,question:v('question'),options:v('options').split('\n').map(x=>x.trim()).filter(Boolean),correct:type==='multiple'?correct:correct[0],ingredients:v('ingredients').split('\n').filter(x=>x.trim()).map(x=>x.split('|').map(x=>x.trim()).filter(Boolean)),explanation:v('explanation'),source:v('source')}})}}
function editor(){ $('#app').innerHTML=`<h1>${draft.id?'Редактировать':'Создать'} материал</h1><form id="editor" class="card"><label>Название<input name="title" required maxlength="200" value="${esc(draft.title)}"></label><label>Тип<select name="kind">${[['service','Материал по сервису + тест'],['ttk','Технологическая карта + тест'],['notice','Обязательное ознакомление']].map(([v,l])=>`<option value="${v}" ${draft.kind===v?'selected':''}>${l}</option>`).join('')}</select></label><label>Материал<textarea name="body" class="lesson" required>${esc(draft.body)}</textarea></label><label>Документ-источник и версия<input name="source" required value="${esc(draft.source)}"></label><label>Проходной балл, %<input name="pass_score" type="number" min="1" max="100" value="${draft.pass_score}" required></label><div id="questions">${draft.questions.map(qHtml).join('')}</div><div class="actions">${btn('Добавить вопрос','add-q','','secondary')}<button type="submit">Сохранить черновик</button></div><p class="muted">PDF можно загрузить в «Управлении обучением». Для курса с проверкой знаний добавь вопросы и проверь ответы перед публикацией.</p></form>`;$('#editor').onsubmit=async e=>{e.preventDefault();readDraft();try{await api('courses'+(draft.id?'/'+draft.id:''),draft.id?'PUT':'POST',draft);view='courses';await render()}catch(e){error(e)}};$('#editor').querySelectorAll('[data-action]').forEach(b=>b.type='button')}
async function lesson(id){await studyAssignment(id)}

async function assignForm(id){const team=await api('team');$('#app').innerHTML=`<h1>Назначить обучение</h1><form id="assign" class="card"><label>Срок<input type="date" name="deadline" required></label><label>Число попыток<input name="max_attempts" type="number" min="1" max="20" value="3" required></label><h2>Сотрудники</h2>${team.filter(s=>(['trainee','waiter'].includes(s.role)||s.id===user.id)&&s.active).map(s=>`<label><input type="checkbox" name="staff" value="${s.id}">${esc(s.name)}</label>`).join('')}<p>После назначения бот отправит каждому выбранному сотруднику сообщение в личный чат.</p><button>Назначить и уведомить</button></form>`;$('#assign').onsubmit=async e=>{e.preventDefault();const b=e.target.querySelector('button');b.disabled=true;try{const f=new FormData(e.target);const r=await api('assignments','POST',{course_id:Number(id),staff_ids:f.getAll('staff').map(Number),deadline:f.get('deadline'),max_attempts:Number(f.get('max_attempts'))});view='assignments';await render();if(!r.created.length)alert('Этот курс уже назначен выбранным сотрудникам.')}catch(e){b.disabled=false;error(e)}}}
document.addEventListener('click',async e=>{const b=e.target.closest('[data-action]');if(!b)return;const {action,id}=b.dataset;try{switch(action){case'nav':if(isManager()&&['dashboard','team','courses','assignments'].includes(id))managerMode=true;else if(['home','catalog'].includes(id))managerMode=false;view=id;await render();break;case'open-manager':managerMode=true;view='dashboard';await render();break;case'ai-generate':await generateCourseProposal(Number(id));break;case'dish-course-new':dishCourseForm();break;case'leave-manage':managerMode=false;view='home';await render();break;case'manager-cases':managerMode=true;view='cases';nav();await casesPage();break;case'case-results':await caseResults(Number(id));break;case'case-new':caseEditor();break;case'case-review':caseReview(Number(id));break;case'case-edit':caseEditor(Number(id));break;case'case-open':await caseDetail(Number(id));break;case'case-publish':if(confirm('Материал, источник и критерии проверены менеджером?')){await api('cases/'+id+'/publish','POST',{reviewed:true});await casesPage()}break;case'case-archive':if(confirm('Скрыть старую опубликованную версию от сотрудников? История ответов сохранится.')){await api('cases/'+id+'/archive','POST',{confirmed:true});await casesPage()}break;case'invite':{const r=await api('invites','POST',{role:$('#invite-role').value});$('#invite-result').innerHTML=`<p>Одноразовая ссылка, действует 7 дней:</p><input readonly value="${esc(r.url)}"><p class="muted">Отправьте сотруднику. Он должен открыть ссылку и нажать «Старт». После этого проверь его Telegram ID в разделе «Команда» и подтверди доступ.</p>`;break}case'approve-staff':if(confirm('Ты лично проверил, кому принадлежит этот Telegram ID? После подтверждения сотрудник получит доступ к внутренним материалам.')){await api('team/'+id+'/approve','POST',{});await render()}break;case'promote':if(confirm('Подтвердить перевод сотрудника в официанты после очного допуска?')){await api('team/'+id+'/role','POST',{role:'waiter'});await render()}break;case'preview':previewCourse(cache.find(c=>c.id==id));break;case'new':draft={title:'',body:'',source:'',kind:'service',pass_score:80,questions:[]};editor();break;case'edit':case'copy':draft=structuredClone(cache.find(x=>x.id==id));if(action==='copy')delete draft.id;editor();break;case'add-q':readDraft();draft.questions.push({question:'',options:['',''],correct:0,explanation:'',source:''});editor();break;case'remove-q':readDraft();draft.questions.splice(Number(id),1);editor();break;case'publish':await publishReviewScreen(cache.find(x=>x.id==id));break;case'approve':await api('courses/'+id+'/publish','POST',{reviewed:true});await render();break;case'archive-course':if(confirm('Архивировать этот курс вместе со старым тестом? Сотрудники больше не увидят материал и не смогут сдать ранее назначенный тест. История попыток останется в базе. Для новой программы создай новую версию.')){await api('courses/'+id+'/archive','POST',{});await render()}break;case'assign':await assignForm(id);break;case'lesson':await lesson(id);break;case'ack':await api('assignments/'+id+'/acknowledge','POST',{});await lesson(id);break;case'results':{const r=await api('assignments/'+id+'/results');$('#app').innerHTML='<h1>Ответы сотрудника</h1>'+r.attempts.map(t=>`<div class="card"><h2>${t.score}% · ${t.passed?'Сдано':'Не сдано'}</h2><p>${esc(new Date(t.created_at).toLocaleString('ru-RU'))}</p>${r.questions.map((q,i)=>`<p><b>${esc(q.question)}</b><br>Ответ: ${esc(answerLabel(q,t.answers[i]))}<br>Правильно: ${esc(correctLabel(q))}</p>`).join('')}</div>`).join('');break}}}catch(e){error(e)}});
(async()=>{try{const h=await api('health');if(!h.telegram_configured)throw Error('Подключение пилота ещё не завершено. Администратор настраивает бота.');const tg=window.Telegram?.WebApp;if(!tg?.initData)throw Error('Откройте Академию через личный чат с @skill_mojo_bot. Для первого входа нужна ссылка-приглашение.');tg.ready();tg.expand();const r=await api('login','POST',{initData:tg.initData});token=r.token;user=r.user;managerMode=isManager();view=managerMode?'dashboard':'home';await render();const aid=new URLSearchParams(location.search).get('assignment');if(aid)await lesson(Number(aid))}catch(e){$('#app').innerHTML=`<h1>Академия сервиса</h1><div class="card"><p>${esc(e.message)}</p><a class="button" href="https://t.me/skill_mojo_bot">Открыть бота</a></div>`}})();

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

function caseOutcome(id,feedback,courses=[],answer=''){
  const needsReview=feedback.needs_review===true;
  const course=courses.find(x=>x.id===feedback.recommended_course_id);
  const available=caseCache.filter(x=>x.published&&!x.archived&&x.id!==id);
  const next=available.length?available[0]:null;
  const recommendation=needsReview&&course;
  const primary=recommendation?btn('Изучить «'+esc(course.title)+'» →','study',course.id,'lime-action'):
    needsReview?btn('Открыть библиотеку →','nav','catalog','lime-action'):
    next?btn('Следующий кейс →','case-open',next.id,'lime-action'):
    btn('К списку кейсов →','nav','cases','lime-action');
  return '<div class="case-outcome">'+
    btn('← Все кейсы','nav','cases','secondary')+
    '<section class="card case-outcome-hero"><span class="eyebrow">ОТВЕТ СОХРАНЁН</span>'+
    '<h1>'+(needsReview?'Есть что закрепить':'Кейс разобран')+'</h1>'+
    '<p>'+esc(feedback.summary)+'</p></section>'+
    '<section class="card case-outcome-next"><span class="eyebrow">ТВОЙ СЛЕДУЮЩИЙ ШАГ</span>'+
    '<h2>'+(needsReview?'Повтори тему и попробуй применить её':'Закрепи результат на практике')+'</h2>'+
    (needsReview&&feedback.focus_topic?'<p class="case-focus">Повторить: '+esc(feedback.focus_topic)+'</p>':'')+
    '<p>'+esc(feedback.next_step)+'</p>'+
    (recommendation?'<p class="case-course-name">Учебный материал MOJO: '+esc(course.title)+'</p>':
     needsReview?'<p class="muted">Прямой урок по этой теме не найден. Выбери подходящий материал в библиотеке.</p>':'')+
    primary+
    '<div class="case-outcome-actions">'+btn('Попробовать кейс ещё раз','case-open',id,'secondary')+
    (next&&needsReview?btn('Другой кейс','case-open',next.id,'secondary'):'')+
    '</div></section>'+
    '<details class="card case-outcome-details"><summary>Полный разбор ответа</summary>'+
    (answer?'<h3>Твой ответ</h3><p>'+esc(answer)+'</p>':'')+
    '<h3>Что получилось</h3><p>'+esc(feedback.strengths)+'</p>'+
    '<h3>Что улучшить</h3><p>'+esc(feedback.improvements)+'</p>'+
    '<p class="muted">Рекомендация ИИ — учебная обратная связь, не решение о допуске к смене.</p></details></div>';
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
    voiceInputMarkup()+
    "<p class='muted'>Не указывай имена гостей, телефоны и другие персональные данные. Ответ отправится в Yandex AI Studio для разбора. Не является экзаменом.</p>"+
    "<button type='submit' class='lime-action'>Разобрать с ИИ →</button><p id='case-request-state' class='muted' role='status' aria-live='polite'></p></form>"+
    "<section id='case-feedback'></section>"+
    (history.length?"<h2>Предыдущие разборы</h2>"+previous:"");
  const draftKey='mojo-case:'+user.id+':'+id;
  let localDraft={};
  try{localDraft=JSON.parse(localStorage.getItem(draftKey)||'{}')}catch(_){}
  const saved=await api('cases/'+id+'/draft');
  let retryRequestId=localDraft.request_id||saved.request_id||null,lastAnswer=localDraft.answer||saved.answer||'';
  const answerField=$('#case-answer textarea');
  answerField.value=lastAnswer;
  const remember=()=>{
    if(answerField.value!==lastAnswer){lastAnswer=answerField.value;retryRequestId=crypto.randomUUID()}
    try{localStorage.setItem(draftKey,JSON.stringify({answer:lastAnswer,request_id:retryRequestId}))}catch(_){}
  };
  answerField.addEventListener('input',remember);
  if(lastAnswer)$('#case-request-state').textContent='Твой предыдущий ответ восстановлен. Можно повторить отправку.';
  bindVoiceInput($('#case-answer'));
  $('#case-answer').onsubmit=async e=>{
    e.preventDefault();const button=e.target.querySelector('button'),status=$('#case-request-state');button.disabled=true;
    const answer=e.target.querySelector('textarea').value;
    remember();
    if(!retryRequestId)retryRequestId=crypto.randomUUID();
    status.textContent='ИИ анализирует твой ответ. Не закрывай экран.';
    try{
      const f=await api('cases/'+id+'/practice','POST',{answer,request_id:retryRequestId});
      // The AI result is already saved; an unavailable catalog must not discard it.
      try{localStorage.removeItem(draftKey)}catch(_){}
      retryRequestId=null;lastAnswer='';
      const courses=f.needs_review&&f.recommended_course_id?
        await api('learning').catch(()=>[]):[];
      $('#app').innerHTML=caseOutcome(id,f,courses,answer);
      window.scrollTo(0,0);
    }catch(err){button.disabled=false;status.textContent='Не получилось получить обратную связь. Ответ не пропал — можно повторить.';error(err)}
  };
}


function coursePdfPanel(){
 return '<section class="card academy-manager-tools"><span class="eyebrow">ОБЫЧНЫЙ PDF · БЕЗ JSON</span>'+
 '<h2>Создать курс из PDF</h2>'+
 '<p>Загрузи методичку или сервисбук. Сначала появятся учебные главы, затем ИИ предложит тесты и открытые кейсы. Всё остаётся черновиком до проверки и публикации менеджером.</p>'+
 '<form id="course-pdf-form">'+
 '<label>Название курса<input name="title" required maxlength="180" placeholder="Например, WOW — ценности MOJO"></label>'+
 '<label>Учебный PDF<input name="document" type="file" accept="application/pdf,.pdf" required></label>'+
 '<button type="submit" class="lime-action">Загрузить и создать главы →</button>'+
 '<p role="status" id="course-pdf-status" class="muted">PDF до 20 МБ и 55 страниц. Для фотографий и составов блюд используй редактор карточек.</p>'+
 '</form></section>';
}
async function generateCourseProposal(cid){
  $('#app').innerHTML='<h1>ИИ готовит программу</h1>'+
    '<section class="card"><h2>Материал сохранён</h2>'+
    '<p role="status">По учебным главам создаются черновики вопросов и практических ситуаций. Итог обязательно проверит менеджер.</p>'+
    btn('Вернуться к программам','nav','courses','secondary')+'</section>';
  try{
    const result=await api('learning/'+cid+'/generate','POST',{});
    cache=await api('courses');
    $('#app').innerHTML='<h1>Предложения готовы</h1><section class="card">'+
      '<p class="eyebrow">ЕЩЁ НЕ ОПУБЛИКОВАНО</p>'+
      '<h2>'+result.questions+' вопросов и '+result.cases+' практических кейсов</h2>'+
      '<p>Проверь вопросы, варианты, факты, источники и критерии кейсов. ИИ может ошибаться. Сотрудники ничего не увидят до утверждения.</p>'+
      (result.warnings?.length?'<p class="muted">Автопроверка: '+result.warnings.length+' предупреждений. Исправь их в редакторе.</p>':'')+
      '<div class="actions">'+btn('Проверить тест','edit',cid,'lime-action')+
      btn('Проверить кейсы','manager-cases','','secondary')+
      btn('Назад к программам','nav','courses','secondary')+'</div></section>';
  }catch(err){
    const mapping=await api('learning/'+cid+'/dish-map').catch(()=>({dish_ids:[]}));
    const materialsAction=mapping.dish_ids.length?'course-map':'course-text-editor';
    $('#app').innerHTML='<h1>Главы сохранены</h1><section class="card">'+
      '<h2>ИИ не подготовил предложения</h2>'+
      '<p>'+esc(err.message)+'</p>'+
      '<p class="muted">Материал остался в закрытом черновике. Проверь главы и повтори генерацию позже. Никаких курсов или тестов автоматически не опубликовано.</p>'+
      '<div class="actions">'+btn('Повторить ИИ-генерацию','ai-generate',cid,'lime-action')+
      btn('Проверить материалы',materialsAction,cid,'secondary')+
      btn('К программам','nav','courses','secondary')+'</div></section>';
  }
  window.scrollTo(0,0);
}
function bindCoursePdfImport(){
 const form=$('#course-pdf-form');if(!form)return;
 form.onsubmit=async e=>{
  e.preventDefault();
  const title=form.elements.namedItem('title').value.trim();
  const file=form.elements.namedItem('document').files[0];
  if(!file||!title)return;
  const status=$('#course-pdf-status'),button=form.querySelector('[type=submit]');
  if(file.size>20_000_000||!file.name.toLowerCase().endsWith('.pdf')){
   status.textContent='Выбери PDF размером до 20 МБ.';return;
  }
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),120000);
  button.disabled=true;
  status.textContent='Читаем PDF, создаём главы и сохраняем закрытый черновик…';
  try{
   const query=new URLSearchParams({title,filename:file.name});
   const response=await fetch('/api/learning/import-pdf?'+query,{
    method:'POST',signal:controller.signal,
    headers:{Authorization:'Bearer '+token,'Content-Type':'application/pdf'},
    body:file
   });
   const result=await response.json().catch(()=>({}));
   if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'Не удалось импортировать PDF');
   cache=await api('courses');
   $('#app').innerHTML='<h1>'+(result.duplicate?'Черновик уже существует':'PDF загружен')+'</h1>'+
    '<section class="card"><h2>'+esc(title)+'</h2>'+
    '<p>Глав: '+result.chapters+'. Материал сохранён как черновик — сотрудники его пока не увидят.</p>'+
    '<p>Материал готов к проверке. ИИ предложит тест и кейсы; перед публикацией проверь их на соответствие исходному PDF.</p>'+
    '<div class="actions">'+btn('Проверить и отредактировать главы','course-text-editor',result.id,'lime-action')+
    btn('Предложить тест и кейсы (ИИ)','ai-generate',result.id,'secondary')+
    btn('Вернуться к управлению','nav','courses','secondary')+'</div></section>';
   window.scrollTo(0,0);
   if(!result.duplicate)await generateCourseProposal(result.id);
  }catch(err){status.textContent=err.name==='AbortError'?'Превышено время ожидания. Проверь список черновиков перед повтором.':err.message;}
  finally{clearTimeout(timer);button.disabled=false;}
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
