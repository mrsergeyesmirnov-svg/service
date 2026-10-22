// The learning screens use server-authenticated identity and PostgreSQL progress.
function questionInput(q,name,value){
 if(q.type==='ingredients')return `<label>Перечисли состав по памяти: один ингредиент на строку<textarea name="${name}" required maxlength="3000" placeholder="Напиши состав…">${esc(value||'')}</textarea></label><p class="muted">Количество ингредиентов и подсказки появятся только после ответа.</p>`;
 const multi=q.type==='multiple';return (multi?'<p class="muted">Отметь все подходящие варианты.</p>':'')+q.options.map((o,i)=>`<label class="option"><input type="${multi?'checkbox':'radio'}" name="${name}" value="${i}" ${multi?'':'required'} ${(multi?(value||[]).includes(i):value===i)?'checked':''}><span>${esc(o)}</span></label>`).join('');
}
function readAnswer(q,f,name){return q.type==='ingredients'?String(f.get(name)||''):q.type==='multiple'?f.getAll(name).map(Number):Number(f.get(name))}
function answerLabel(q,a){return q.type==='ingredients'?String(a??''):Array.isArray(a)?a.map(i=>q.options[i]).join(', '):q.options[a]||'—'}
function correctLabel(q){return q.type==='ingredients'?q.ingredients.map(g=>g[0]).join(', '):answerLabel(q,q.correct)}
function reviewQuestion(q,a,i){const assessment=q.assessment;return `<article class="card"><h3>${i+1}. ${esc(q.question)}</h3><p>Твой ответ: ${esc(answerLabel(q,a))}</p><p>Эталон: ${esc(correctLabel(q))}</p>${assessment?.missing?.length?`<p>Пропущено: ${esc(assessment.missing.join(', '))}</p>`:''}${assessment?.extra?.length?`<p>Лишнее или не распознано: ${esc(assessment.extra.join(', '))}</p><p class="muted">Если название равнозначно ингредиенту, попроси менеджера проверить допустимые названия.</p>`:''}<p>${esc(q.explanation)}</p><p class="muted">Повторить: ${esc(q.source)}</p></article>`}
const directions={menu:'Основное меню',bar:'Бар MOJO',coffee:'Теория кофе',service:'Сервис'};
let learningCourses=[],activeCourse,chapterIndex=0,quizIndex=0,quizAnswers=[],quizRequest='';
function learningDone(c){return c.chapters>0&&c.read===c.chapters&&(!c.questions||c.passed)}
function courseCard(c){return `<button class="course-row" data-action="study" data-id="${c.id}"><span class="course-symbol">${navSvg('courses')}</span><span><strong>${esc(c.title)}</strong><small>${esc(directions[c.category])} · ${c.read} из ${c.chapters} глав${c.structured?' · карточки блюд':''}</small><progress max="${c.chapters||1}" value="${c.read}"></progress><small>${learningDone(c)?'Завершено':c.best_score!==null?'Тест: '+c.best_score+'%':'Изучить материал'}</small></span><span aria-hidden="true">›</span></button>`}
async function learningPage(page){
 const root=$('#app');root.innerHTML='<p role="status">Загружаем обучение…</p>';
 learningCourses=await api('learning');
 if(page==='catalog'){
  root.innerHTML='<h1>Курсы</h1><p>'+btn(isManager()?'Карточки блюд · управление':'Карточки блюд','dish-open')+'</p>'+ (isManager()?`<div class="actions">${btn('Управление материалами','nav','courses','secondary')}${btn('Назначения команды','nav','assignments','secondary')}</div>`:'')+`<div class="filters">${btn('Все','filter','all','active')}${Object.entries(directions).map(([k,v])=>btn(v,'filter',k,'secondary')).join('')}</div><div id="course-list">${learningCourses.map(courseCard).join('')||'<div class="card">Утверждённые курсы появятся здесь после проверки менеджером.</div>'}</div>`;
  return;
 }
 const total=learningCourses.reduce((n,c)=>n+c.chapters,0),read=learningCourses.reduce((n,c)=>n+c.read,0),next=learningCourses.find(c=>!learningDone(c));
 const assignments=(await api('assignments')).filter(a=>a.staff_id===user.id&&!done(a));
 root.innerHTML=`<p class="eyebrow">${esc(roles[user.role])} · ${esc(user.restaurant)}</p><h1>Привет, ${esc(user.name)}</h1><section class="card learning-hero"><span class="eyebrow">Программа адаптации MOJO</span><h2>Мой путь в команду</h2><p>Изучи материал и закрепи знания на практике.</p>${total?`<div class="row"><span>Прочитано глав</span><strong>${read} из ${total}</strong></div><progress max="${total}" value="${read}"></progress>`:`<p>Материалы готовятся к публикации.${isManager()?' Черновики доступны в управлении материалами.':''}</p>`}${next?btn('Продолжить обучение →','study',next.id,'lime-action'):btn('Открыть курсы →','nav','catalog','lime-action')}</section><h2>Направления обучения</h2><div class="direction-grid">${Object.entries(directions).map(([k,v])=>`<button class="card direction" data-action="direction" data-id="${k}">${navSvg('courses')}<strong>${v}</strong><small>${learningCourses.filter(c=>c.category===k).length} курсов</small></button>`).join('')}</div>${assignments.length?`<h2>Обязательное обучение</h2>${assignments.slice(0,3).map(a=>`<article class="card"><h3>${esc(a.title)}</h3><p class="muted">До ${esc(dateLabel(a.deadline))}</p>${btn('Открыть назначение','lesson',a.id)}</article>`).join('')}`:''}${isManager()?`<div class="actions">${btn('Назначения команды','nav','assignments','secondary')}${btn('Управление материалами','nav','courses','secondary')}</div>`:''}`;
}
async function study(id){
 $('#app').innerHTML='<p role="status">Открываем курс…</p>';
 activeCourse=await api('learning/'+id);
 chapterIndex=activeCourse.chapters.findIndex(c=>!activeCourse.read.includes(c.id));
 if(chapterIndex<0)chapterIndex=0;
 showChapter();
}
function studyHeader(sub){return `<div class="lesson-top">${btn('←','nav','catalog','secondary')}<div><strong>${esc(activeCourse.title)}</strong><small>${sub}</small></div></div>`}
function legacyText(text){
 // Display only: original course source remains immutable in PostgreSQL.
 return String(text||'').replace(/^===\s*(.*?)\s*===$/gm,'$1').replace(/[▤▥▦]/g,'•');
}
function chapterBody(p){
 if(p.kind!=='dish')
  return '<p class="muted">Материал исходного курса. Менеджер может заменить его проверенными карточками блюд.</p>'+
   '<div class="body lesson-source">'+esc(legacyText(p.body))+'</div>';
 return (p.has_photo?dishPhoto(p.dish_id,'wide'):'<div class="dish-photo wide"><span>Фотография готовится</span></div>')+
 '<p class="eyebrow">'+esc(p.section)+'</p><h2>Состав блюда</h2>'+
 (p.ingredients?.length?'<ul class="chapter-ingredients">'+p.ingredients.map(x=>'<li>'+esc(x)+'</li>').join('')+'</ul>':
  '<p class="muted">Ингредиенты проверяются менеджером.</p>')+
 '<h2>Особенности и подача</h2><div class="body lesson-source">'+esc(p.description||'Описание блюда готовится.')+'</div>'+
 '<p class="muted">Источник: '+esc(p.source)+(p.source_page?' · стр. '+p.source_page:'')+'</p>'+
 '<section class="lesson-practice"><strong>Проверь себя</strong>'+
 '<p>Сможешь без подсказок назвать основные ингредиенты и объяснить это блюдо гостю за 20–30 секунд?</p>'+
 '<p class="muted">После изучения можно потренировать презентацию. Итоговый тест проверит знания без подсказок.</p></section>'+
 '<form id="dish-practice-form" class="lesson-ai"><h2>Презентуй блюдо гостю</h2>'+
 '<label>Представь, что гость спрашивает про это блюдо. Что ты скажешь?'+
 '<textarea name="answer" required minlength="40" maxlength="1600" rows="5" placeholder="Начни со своих слов, без подсказок…"></textarea></label>'+
 '<p class="muted">Не указывай персональные данные гостей. Ответ отправится в Yandex AI Studio для учебного разбора — это не экзамен и не допуск к смене.</p>'+
 '<button type="submit">Получить разбор ИИ</button><p id="dish-practice-state" role="status"></p>'+
 '<div id="dish-practice-feedback" aria-live="polite"></div></form>';
}
function showChapter(){
 const c=activeCourse;
 if(!c.chapters.length){
  $('#app').innerHTML=studyHeader('Материалы на проверке')+
    '<section class="card"><h1>Уроки временно недоступны</h1>'+
    '<p>Менеджер проверяет или обновляет карточки блюд. Результаты предыдущих тестов сохранены.</p>'+
    btn('К каталогу','nav','catalog','secondary')+'</section>';
  return;
 }
 chapterIndex=Math.min(Math.max(chapterIndex,0),c.chapters.length-1);
 const p=c.chapters[chapterIndex],finished=c.chapters.every(p=>c.read.includes(p.id));
 const read=c.chapters.filter(p=>c.read.includes(p.id)).length;
 $('#app').innerHTML=studyHeader('Глава '+(chapterIndex+1)+' из '+c.chapters.length)+
 '<progress max="'+c.chapters.length+'" value="'+read+'"></progress>'+
 '<article class="card chapter"><span class="badge">'+(c.read.includes(p.id)?'Прочитано':'Учебный материал')+'</span>'+
 '<h1>'+esc(p.title)+'</h1>'+chapterBody(p)+'</article>'+
 '<div class="actions chapter-actions">'+
 (chapterIndex?btn('← Предыдущая','chapter-prev','','secondary'):'')+
 btn(c.read.includes(p.id)?'Следующая глава →':'Прочитано, далее →','chapter-next','', 'lime-action')+'</div>'+
 (p.kind==='dish'?'':'<p class="muted">Источник: '+esc(c.source)+'</p>')+
 (finished&&c.questions.length?'<div class="card"><h2>Готов к проверке знаний?</h2>'+
 '<p>Ты изучил все главы. Теперь закрепи материал тестом.</p>'+
 btn('Пройти тест →','study-quiz')+'</div>':'')+
 '<section class="card"><h2>Мои результаты</h2>'+
 (c.history.length?c.history.map(t=>'<p>'+esc(new Date(t.created_at).toLocaleString('ru-RU'))+
 ' · '+t.score+'% · '+(t.passed?'Сдано':'Повторить материал')+'</p>').join(''):
 '<p class="muted">Тест ещё не пройден.</p>')+'</section>'+
 (isManager()?btn('Результаты команды','study-results',c.id,'secondary'):'');
 if(p.kind==='dish'){showDishPhotos();bindDishPractice(c.id,p.dish_id)}
 window.scrollTo(0,0);
}
function bindDishPractice(courseId,dishId){
 const form=$('#dish-practice-form');if(!form)return;
 form.onsubmit=async e=>{
  e.preventDefault();const button=form.querySelector('[type="submit"]');
  const answer=form.elements.namedItem('answer').value;
  if(answer.trim().length<40){error(Error('Напиши не менее 40 символов'));return}
  const state=$('#dish-practice-state');button.disabled=true;
  state.textContent='ИИ проверяет твой ответ…';
  try{
   const f=await api('learning/'+courseId+'/dish-practice','POST',{
    dish_id:dishId,request_id:crypto.randomUUID(),answer
   });
   $('#dish-practice-feedback').innerHTML='<div class="card result-card">'+
    '<h3>Твой разбор</h3><p>'+esc(f.summary)+'</p>'+
    '<h3>Что получилось</h3><p>'+esc(f.strengths)+'</p>'+
    '<h3>Что улучшить</h3><p>'+esc(f.improvements)+'</p>'+
    '<h3>Следующий шаг</h3><p>'+esc(f.next_step)+'</p>'+
    '<p class="muted">ИИ даёт учебную обратную связь. Допуск к работе подтверждает руководитель.</p></div>';
   state.textContent='Разбор сохранён в твоём профиле.';
  }catch(err){
   state.textContent='Ответ не оценён. Он остался в поле — можно повторить позже.';
   error(err);
  }finally{button.disabled=false}
 };
}
function showStudyQuiz(){
 const c=activeCourse,q=c.questions[quizIndex];
 $('#app').innerHTML=studyHeader(`Вопрос ${quizIndex+1} из ${c.questions.length}`)+`<progress max="${c.questions.length}" value="${quizIndex+1}"></progress><form id="study-quiz"><h1>${esc(q.question)}</h1>${questionInput(q,'answer',quizAnswers[quizIndex])}<div class="actions">${quizIndex?btn('Назад','quiz-prev','','secondary'):''}<button type="submit">${quizIndex===c.questions.length-1?'Узнать результат':'Следующий вопрос →'}</button></div><p id="quiz-state" role="status"></p></form>`;
 if(quizIndex)$('#study-quiz [data-action]').type='button';
 $('#study-quiz').onsubmit=async e=>{
  e.preventDefault();quizAnswers[quizIndex]=readAnswer(q,new FormData(e.target),'answer');
  if(quizIndex<c.questions.length-1){quizIndex++;showStudyQuiz();return}
  const button=e.target.querySelector('[type=submit]');button.disabled=true;$('#quiz-state').textContent='Сохраняем результат…';
  try{const r=await api('learning/'+c.id+'/submit','POST',{request_id:quizRequest,answers:quizAnswers});showStudyResult(r)}catch(err){button.disabled=false;$('#quiz-state').textContent='Ответы остались на экране. Можно повторить отправку.';error(err)}
 };
 window.scrollTo(0,0);
}
function showStudyResult(r){
 $('#app').innerHTML=studyHeader('Результат сохранён')+`<section class="card result-card"><p class="eyebrow">${r.passed?'Тест сдан':'Повтори материал'}</p><h1>${r.score}%</h1><p>Порог: ${activeCourse.pass_score}%. Это учебная проверка; очную аттестацию проводит руководитель.</p>${btn('Вернуться к обучению','study',activeCourse.id)}</section><h2>Разбор ответов</h2>${r.review.map((q,i)=>reviewQuestion(q,q.answer,i)).join('')}${btn('К курсам','nav','catalog','secondary')}`;
 window.scrollTo(0,0);
}
document.addEventListener('click',async e=>{
 const b=e.target.closest('[data-action]');if(!b)return;
 const {action,id}=b.dataset;
 if(!['study','filter','direction','chapter-next','chapter-prev','study-quiz','quiz-prev','study-results','course-map','course-map-add','course-map-remove','course-map-up','course-map-down','course-map-save','course-map-suggest'].includes(action))return;
 b.disabled=true;
 try{
  if(action==='course-map')await editCourseDishMap(Number(id));
  if(action==='course-map-add'){
    const dish=Number(id);
    if(courseMapSelected.length>=80)throw Error('В одном курсе максимум 80 карточек');
    if(!courseMapSelected.includes(dish))courseMapSelected.push(dish);
    renderCourseMap();
  }
  if(action==='course-map-remove'){
    courseMapSelected=courseMapSelected.filter(x=>x!==Number(id));renderCourseMap();
  }
  if(action==='course-map-up'||action==='course-map-down'){
    const idx=courseMapSelected.indexOf(Number(id)),other=idx+(action==='course-map-up'?-1:1);
    if(idx>=0&&other>=0&&other<courseMapSelected.length)
     [courseMapSelected[idx],courseMapSelected[other]]=[courseMapSelected[other],courseMapSelected[idx]];
    renderCourseMap();
  }
  if(action==='course-map-suggest'){
    const r=courseMapSource.match(/(?:с\.|стр\.|страницы?)\s*(\d{1,3})\s*[–—-]\s*(\d{1,3})/i);
    if(r){
      const first=Number(r[1]),last=Number(r[2]);
      const proposed=courseMapAvailable.filter(c=>c.source_page>=first&&c.source_page<=last)
       .sort((a,b)=>a.source_page-b.source_page||a.id-b.id).map(c=>c.id);
      if(proposed.length&&confirm('Добавить '+proposed.length+' карточек по страницам '+first+'–'+last+'? Проверь порядок и каждое блюдо до сохранения.')){
        courseMapSelected=[...new Set([...courseMapSelected,...proposed])].slice(0,80);
        renderCourseMap();
      }
    }
  }
  if(action==='course-map-save')await saveCourseDishMap();
  if(action==='study')await study(Number(id));
  if(action==='direction'){view='catalog';await render();filterCourses(id)}
  if(action==='filter')filterCourses(id);
  if(action==='chapter-prev'){chapterIndex--;showChapter()}
  if(action==='chapter-next'){
   const r=await api('learning/'+activeCourse.id+'/read','POST',{chapter_id:activeCourse.chapters[chapterIndex].id});activeCourse.read=r.read;
   if(chapterIndex<activeCourse.chapters.length-1){chapterIndex++;showChapter()}
   else if(activeCourse.questions.length){quizIndex=0;quizAnswers=[];quizRequest=crypto.randomUUID();showStudyQuiz()}
   else showChapter();
  }
  if(action==='study-quiz'){quizIndex=0;quizAnswers=[];quizRequest=crypto.randomUUID();showStudyQuiz()}
  if(action==='quiz-prev'){const f=new FormData($('#study-quiz'));if(f.has('answer'))quizAnswers[quizIndex]=readAnswer(activeCourse.questions[quizIndex],f,'answer');quizIndex--;showStudyQuiz()}
  if(action==='study-results'){
   const rows=await api('learning/'+id+'/results');$('#app').innerHTML=btn('К курсу','study',id,'secondary')+'<h1>Результаты команды</h1>'+rows.map(r=>`<article class="card"><h2>${esc(r.name)}</h2><p>${r.score}% · ${r.passed?'Сдано':'Повторить'} · ${esc(new Date(r.created_at).toLocaleString('ru-RU'))}</p></article>`).join('')+(rows.length?'':'<p>Попыток пока нет.</p>');
  }
 }catch(err){error(err)}finally{b.disabled=false}
});
function filterCourses(id){$('#course-list').innerHTML=learningCourses.filter(c=>id==='all'||c.category===id).map(courseCard).join('')||'<div class="card">В этом направлении пока нет утверждённых курсов.</div>';document.querySelectorAll('[data-action=filter]').forEach(b=>b.classList.toggle('active',b.dataset.id===id))}


// Managers curate the chapter sequence from reviewed dish cards.
// This does not change a course's questions or previous exam attempts.
let courseMapId=null,courseMapTitle='',courseMapSource='',courseMapSelected=[],courseMapAvailable=[],courseMapSearch='';
async function editCourseDishMap(id){
 if(!isManager())throw Error('Доступ только менеджеру');
 const [mapping,cards]=await Promise.all([api('learning/'+id+'/dish-map'),api('dishes')]);
 courseMapId=id;courseMapTitle=mapping.title;courseMapSource=mapping.source||'';
 courseMapSelected=[...mapping.dish_ids];courseMapAvailable=cards.filter(c=>c.published);
 courseMapSearch='';
 $('#app').innerHTML=btn('← Материалы','nav','courses','secondary')+
 '<h1>Главы курса</h1><p class="muted">'+esc(courseMapTitle)+'</p>'+
 '<div class="card"><p>Выбери опубликованные карточки блюд и установи порядок. Сотрудник будет читать их вместо сырого текста станционок, после чего сможет пройти существующий тест.</p>'+ 
 '<p class="muted">При изменении рецептуры карточка снова станет черновиком и исчезнет из учебного курса до повторной проверки.</p></div>'+
 '<div id="course-map-suggest"></div><h2>Порядок глав</h2><div id="course-map-picked"></div>'+ 
 '<h2>Добавить из каталога</h2><label>Поиск по названию и разделу'+
 '<input type="search" id="course-map-search" placeholder="Например: роллы, песто, салат"></label>'+
 '<div id="course-map-available"></div>'+
 '<div class="map-sticky">'+btn('Сохранить состав курса','course-map-save')+'</div>';
 $('#course-map-search').oninput=e=>{courseMapSearch=e.target.value;renderCourseMap()};
 renderCourseMap();
}
function renderCourseMap(){
 if(courseMapId===null)return;
 const range=courseMapSource.match(/(?:с\.|стр\.|страницы?)\s*(\d{1,3})\s*[–—-]\s*(\d{1,3})/i);
 if(range){
  const first=Number(range[1]),last=Number(range[2]);
  const available=courseMapAvailable.filter(c=>c.source_page>=first&&c.source_page<=last);
  $('#course-map-suggest').innerHTML=available.length?
   '<div class="card"><p>Источник: '+esc(courseMapSource)+'</p>'+
   '<p>На страницах '+first+'–'+last+' найдено '+available.length+' опубликованных карточек.</p>'+
   btn('Подобрать по страницам (проверить вручную)','course-map-suggest','','secondary')+'</div>':'';
 } else $('#course-map-suggest').innerHTML='';
 const byId=new Map(courseMapAvailable.map(c=>[c.id,c]));
 const chosen=courseMapSelected.map((id,index)=>{
  const c=byId.get(id),caption=c?esc(c.title):'Карточка №'+id+' (сейчас не опубликована)';
  return '<div class="map-row"><span><b>'+(index+1)+'. '+caption+'</b>'+
  (c?'<small>'+esc(c.section)+'</small>':'<small>Удали или утверди карточку заново</small>')+'</span>'+
  '<div class="map-buttons">'+(index?btn('↑','course-map-up',id,'secondary'):'')+
  (index<courseMapSelected.length-1?btn('↓','course-map-down',id,'secondary'):'')+
  btn('Убрать','course-map-remove',id,'secondary')+'</div></div>';
 }).join('');
 $('#course-map-picked').innerHTML=chosen||'<div class="card"><p>Пока нет глав. Добавь карточки из каталога ниже.</p></div>';
 const keyword=courseMapSearch.toLocaleLowerCase('ru');
 const options=courseMapAvailable.filter(c=>!courseMapSelected.includes(c.id) &&
  (c.title+' '+c.section).toLocaleLowerCase('ru').includes(keyword)).slice(0,80);
 $('#course-map-available').innerHTML=options.map(c=>
  '<div class="map-row"><span><b>'+esc(c.title)+'</b><small>'+esc(c.section)+'</small></span>'+
  btn('Добавить +','course-map-add',c.id,'secondary')+'</div>').join('')||
  '<p class="muted">Нет подходящих опубликованных блюд. Добавить новые можно в разделе «Карточки блюд».</p>';
}
async function saveCourseDishMap(){
 if(courseMapId===null)return;
 if(!courseMapSelected.length&&!confirm('Удалить все привязки? Тогда снова будет показан исходный текст курса.'))return;
 const r=await api('learning/'+courseMapId+'/dish-map','PUT',{dish_ids:courseMapSelected});
 courseMapId=null;
 view='courses';await render();
}
