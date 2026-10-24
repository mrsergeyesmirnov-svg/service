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
let learningCourses=[],activeCourse,activeAssignment=null,chapterIndex=0,quizIndex=0,quizAnswers=[],quizRequest='';
function learningDone(c){return c.chapters>0&&c.read===c.chapters&&(!c.questions||c.passed)}
function courseCard(c){
 const progress=c.chapters?Math.round(100*c.read/c.chapters):0;
 const label=learningDone(c)?'Завершено':c.read?'В процессе':'Не начато';
 return '<button class="course-row" data-action="study" data-id="'+c.id+'">'+
  '<span class="course-symbol">'+navSvg('courses')+'</span><span><strong>'+esc(c.title)+'</strong>'+
  '<small>'+esc(directions[c.category]||'Обучение')+' · '+c.chapters+' глав</small>'+
  '<progress max="100" value="'+progress+'" aria-label="Изучено '+progress+'%"></progress>'+
  '<small>'+label+(c.best_score!==null?' · результат '+c.best_score+'%':'')+'</small></span><span aria-hidden="true">›</span></button>';
}
async function learningPage(page){
 const root=$('#app');root.innerHTML='<p role="status">Загружаем обучение…</p>';
 learningCourses=await api('learning');
 if(page==='catalog'){
  root.innerHTML='<span class="eyebrow">МОЯ БИБЛИОТЕКА</span><h1>Учебные материалы</h1>'+
   '<p class="muted learner-intro">Выбирай тему и учись в своём темпе. Все результаты сохраняются.</p>'+
   '<div class="filters" aria-label="Направления обучения">'+btn('Все','filter','all','active')+
   Object.entries(directions).map(([k,v])=>btn(v,'filter',k,'secondary')).join('')+'</div>'+
   '<div id="course-list">'+(learningCourses.map(courseCard).join('')||'<div class="card">Утверждённые курсы появятся после проверки менеджером.</div>')+'</div>'+
   '<div class="card practice-entry"><span class="eyebrow">ПРАКТИКА</span><h2>Тренировка ситуаций</h2>'+
   '<p class="muted">Попробуй ответить гостю своими словами и получи обратную связь.</p>'+
   btn('Открыть практику →','nav','cases','secondary')+'</div>'+
   (isManager()?'<div class="manager-entry">'+btn('Управление Академией','open-manager','','secondary')+'</div>':'');
  return;
 }
 const myAssignments=(await api('assignments')).filter(a=>a.staff_id===user.id&&!a.archived);
 const pending=myAssignments.filter(a=>!done(a)).sort((a,b)=>a.deadline.localeCompare(b.deadline));
 const complete=learningCourses.filter(learningDone).length,total=learningCourses.length;
 const nextCourse=learningCourses.find(c=>!learningDone(c));
 const urgent=pending[0],next=urgent||nextCourse;
 const caption=urgent?'Обязательное обучение · до '+dateLabel(urgent.deadline):
  nextCourse?esc(directions[nextCourse.category]||'Обучение')+' · '+nextCourse.read+' из '+nextCourse.chapters+' глав':'';
 const progress=total?Math.round(100*complete/total):0;
 const upcoming=[
  ...pending.slice(urgent?1:0,3).map(a=>({id:a.id,title:a.title,kind:'assignment',sub:'До '+dateLabel(a.deadline)})),
  ...learningCourses.filter(c=>!learningDone(c)&&(urgent||!nextCourse||c.id!==nextCourse.id)).slice(0,2).map(c=>({id:c.id,title:c.title,kind:'course',sub:directions[c.category]||'Учебный материал'}))
 ].slice(0,3);
 root.innerHTML='<div class="learner-topline"><span class="eyebrow">'+esc(roles[user.role])+' · '+esc(user.restaurant)+'</span>'+
  (isManager()?btn('Управление →','open-manager','','secondary'):'')+'</div>'+
  '<h1>Привет, '+esc(user.name)+'</h1>'+
  '<section class="card journey-progress" aria-label="Прогресс учебной программы">'+
   '<div class="row"><strong>Мой путь в MOJO</strong><span>'+complete+' из '+total+' курсов</span></div>'+
   '<progress max="100" value="'+progress+'" aria-label="Завершено '+progress+'% курсов"></progress>'+
   '<p class="muted">'+(total?'Продвигайся по программе в своём темпе.':'Программа появится после публикации материалов.')+'</p></section>'+
  (next?'<section class="card journey-next"><span class="eyebrow">СЕЙЧАС В ПРОГРАММЕ</span>'+
   '<h2>'+esc(next.title)+'</h2><p>'+caption+'</p>'+
   '<div class="journey-steps"><span>1 · Материал</span><span>2 · Тест</span><span>3 · Практика</span></div>'+
   btn('Продолжить обучение →',urgent?'lesson':'study',next.id,'lime-action')+'</section>':
   '<section class="card journey-next"><span class="eyebrow">МОЙ ПУТЬ</span><h2>'+(total?'Все курсы пройдены!':'Начни с библиотеки')+'</h2>'+
   '<p class="muted">'+(total?'Можешь повторить уроки или потренироваться на кейсах.':'Как только менеджер опубликует курс, он появится здесь.')+'</p>'+
   btn('Открыть библиотеку →','nav','catalog','lime-action')+'</section>')+
  (upcoming.length?'<div class="row journey-section-title"><h2>Дальше по программе</h2></div>'+
   upcoming.map((c,i)=>'<button class="journey-mini" data-action="'+(c.kind==='assignment'?'lesson':'study')+'" data-id="'+c.id+'"><span class="journey-num">'+(i+1)+'</span><span><strong>'+esc(c.title)+'</strong><small>'+esc(c.sub)+'</small></span><span aria-hidden="true">›</span></button>').join(''):'')+
  '<div class="journey-bottom">'+btn('Вся библиотека →','nav','catalog','secondary')+'</div>';
}
async function study(id){
 activeAssignment=null;
 $('#app').innerHTML='<p role="status">Открываем курс…</p>';
 activeCourse=await api('learning/'+id);
 chapterIndex=activeCourse.chapters.findIndex(c=>!activeCourse.read.includes(c.id));
 if(chapterIndex<0)chapterIndex=Math.max(0,activeCourse.chapters.length-1);
 if(activeCourse.chapters.length&&activeCourse.chapters.every(c=>activeCourse.read.includes(c.id))&&
  (!activeCourse.questions.length||activeCourse.history.some(t=>t.passed)))showStudyComplete();
 else showChapter();
}
async function studyAssignment(id){
 $('#app').innerHTML='<p role="status">Открываем назначенный курс…</p>';
 const assignment=await api('assignments/'+id);
 const course=await api('learning/'+assignment.course_id);
 activeAssignment=assignment;
 activeCourse={...course,questions:assignment.questions,history:assignment.history,pass_score:assignment.pass_score};
 chapterIndex=activeCourse.chapters.findIndex(c=>!activeCourse.read.includes(c.id));
 if(chapterIndex<0)chapterIndex=Math.max(0,activeCourse.chapters.length-1);
 showChapter();
}
async function submitStudyAnswers(){
 if(!activeAssignment)return api('learning/'+activeCourse.id+'/submit','POST',{request_id:quizRequest,answers:quizAnswers});
 const id=activeAssignment.id;
 const result=await api('assignments/'+id+'/submit','POST',{request_id:quizRequest,answers:quizAnswers});
 activeAssignment=await api('assignments/'+id);
 return {...result,review:activeAssignment.review.map((q,i)=>({...q,answer:quizAnswers[i]}))};
}
function studyHeader(sub){return `<div class="lesson-top">${btn('← Мой путь','nav','home','secondary')}<div><strong>${esc(activeCourse.title)}</strong><small>${sub}</small>${activeAssignment?`<small>Обязательно · до ${esc(dateLabel(activeAssignment.deadline))} · осталось попыток: ${Math.max(0,activeAssignment.max_attempts-activeAssignment.history.length)}</small>`:''}</div></div>`}
function legacyText(text){
 // Display only: original course source remains immutable in PostgreSQL.
 return String(text||'').replace(/^===\s*(.*?)\s*===$/gm,'$1').replace(/[▤▥▦]/g,'•');
}
function chapterBody(p){
 if(p.kind==='text')return '<div class="body lesson-source">'+esc(p.body)+'</div>'+ (p.source?'<p class="muted">Источник: '+esc(p.source)+'</p>':'');
 if(p.kind!=='dish')
  return '<p class="muted">Материал исходного курса. Менеджер может заменить его проверенными карточками блюд.</p>'+
   '<div class="body lesson-source">'+esc(legacyText(p.body))+'</div>';
 return (p.has_photo?dishPhoto(p.dish_id,'wide'):'<div class="dish-photo wide"><span>Фотография готовится</span></div>')+
 '<p class="eyebrow">'+esc(p.section)+'</p><h2>Состав блюда</h2>'+
 (p.ingredients?.length?'<ul class="chapter-ingredients">'+p.ingredients.map(x=>'<li>'+esc(x)+'</li>').join('')+'</ul>':
  '<p class="muted">Ингредиенты проверяются менеджером.</p>')+
 '<h2>Особенности и подача</h2><div class="body lesson-source">'+esc(p.description||'Описание блюда готовится.')+'</div>'+
 (p.allergens?'<h2>Аллергены и ограничения</h2><p>'+esc(p.allergens)+'</p>':'<p class="muted">Данные об аллергенах уточняются по ТТК; не обещай гостю отсутствие аллергенов.</p>')+
 '<p class="muted">Источник: '+esc(p.source)+(p.source_page?' · стр. '+p.source_page:'')+'</p>'+
 '<p class="muted">После изучения глав сначала пройди тест. Затем можно презентовать блюдо гостю голосом или текстом и получить разбор ИИ.</p>';

}
function showStudyComplete(){
 const c=activeCourse,passed=c.history.some(t=>t.passed);
 $('#app').innerHTML=studyHeader('Обучение завершено')+
  '<section class="card journey-next"><span class="eyebrow">ГОТОВО</span><h1>Отличная работа!</h1>'+
  '<p>'+(passed?'Тест сдан, результаты сохранены.':'Все главы прочитаны.')+'</p>'+
  (c.chapters.some(x=>x.kind==='dish')?btn('Практика с ИИ →','study-practice','','lime-action'):btn('Практика ситуаций →','nav','cases','lime-action'))+
  btn('Повторить материал','chapter-review','','secondary')+'</section>'+
  btn('К моему пути','nav','home','secondary');
 window.scrollTo(0,0);
}
function showChapter(){
 const c=activeCourse;
 if(!c.chapters.length){
  $('#app').innerHTML=studyHeader('Материалы на проверке')+
   '<section class="card"><h1>Уроки временно недоступны</h1>'+
   '<p>Менеджер проверяет материалы. История предыдущих тестов сохранена.</p>'+
   btn('К библиотеке','nav','catalog','secondary')+'</section>';
  return;
 }
 chapterIndex=Math.min(Math.max(chapterIndex,0),c.chapters.length-1);
 const p=c.chapters[chapterIndex],read=c.chapters.filter(p=>c.read.includes(p.id)).length;
 const last=chapterIndex===c.chapters.length-1,passed=c.history.some(t=>t.passed);
 const nextLabel=last?(c.questions.length&&!passed?'Перейти к тесту →':c.chapters.some(x=>x.kind==='dish')?'К практике →':'Завершить урок →'):(c.read.includes(p.id)?'Следующая глава →':'Прочитано, далее →');
 $('#app').innerHTML=studyHeader('Глава '+(chapterIndex+1)+' из '+c.chapters.length)+
  '<div class="lesson-stage"><span class="stage-active">1 · Изучение</span><span>2 · Тест</span><span>3 · Практика</span></div>'+
  '<div class="row lesson-progress"><strong>Глава '+(chapterIndex+1)+' / '+c.chapters.length+'</strong><span>'+read+' прочитано</span></div>'+
  '<progress max="'+c.chapters.length+'" value="'+read+'"></progress>'+
  '<article class="card chapter"><span class="badge">'+(c.read.includes(p.id)?'Прочитано':'Урок')+'</span>'+
  '<h1>'+esc(p.title)+'</h1>'+chapterBody(p)+'</article>'+
  '<div class="actions chapter-actions">'+(chapterIndex?btn('← Назад','chapter-prev','','secondary'):'')+
  btn(nextLabel,'chapter-next','','lime-action')+'</div>'+
  (last?'<details class="card lesson-extra"><summary>История обучения и тесты</summary>'+
   (c.history.length?c.history.map(t=>'<p>'+esc(new Date(t.created_at).toLocaleString('ru-RU'))+
    ' · '+t.score+'% · '+(t.passed?'Сдано':'Повторить материал')+'</p>').join(''):'<p>Тест ещё не пройден.</p>')+
   (c.questions.length?btn('Пройти тест заново','study-quiz','','secondary'):'')+
   (isManager()?btn('Результаты команды','study-results',c.id,'secondary'):'')+'</details>':'');
 if(p.kind==='dish')showDishPhotos();
 window.scrollTo(0,0);
}
function showPostTestPractice(dishId){
 const c=activeCourse, cards=c.chapters.filter(x=>x.kind==='dish');
 if(!cards.length){showChapter();return}
 const selected=cards.find(x=>x.dish_id===dishId)||cards[0];
 const options=cards.map(x=>'<option value="'+x.dish_id+'"'+(x.dish_id===selected.dish_id?' selected':'')+'>'+esc(x.title)+'</option>').join('');
 $('#app').innerHTML=studyHeader('Практика · после теста')+
 '<div class="lesson-stage"><span>1 · Изучение</span><span>2 · Тест</span><span class="stage-active">3 · Практика</span></div><section class="card lesson-ai"><p class="eyebrow">Ситуационная тренировка</p>'+
 '<h1>Презентуй блюдо гостю</h1>'+
 '<p class="muted">Представь, что гость спрашивает об одном из блюд MOJO. Ты уже изучил материал и прошёл тест. Сейчас попробуй объяснить его своими словами, как за столом.</p>'+
 '<label>Выбери блюдо для презентации<select id="practice-dish-select">'+options+'</select></label>'+
 '<form id="dish-practice-form"><label>Что скажешь гостю?'+
 '<textarea name="answer" required minlength="40" maxlength="1600" rows="5" placeholder="Начни со своих слов…"></textarea></label>'+
 voiceInputMarkup()+
 '<p class="muted">Не указывай персональные данные гостей. ИИ проверяет содержание по утверждённой карточке и даёт рекомендации. Допуск к смене подтверждает руководитель.</p>'+
 '<button class="lime-action" type="submit">Получить разбор ИИ →</button>'+
 '<p id="dish-practice-state" role="status"></p>'+
 '<div id="dish-practice-feedback" aria-live="polite"></div></form></section>'+
 btn('Вернуться к курсу','study',c.id,'secondary');
 $('#practice-dish-select').onchange=e=>{
    const draft=$('#dish-practice-form [name=answer]').value.trim();
    if(draft&&!confirm('При смене блюда несохранённый ответ очистится. Продолжить?')){
      e.target.value=String(selected.dish_id);return;
    }
    showPostTestPractice(Number(e.target.value));
  };
 bindDishPractice(c.id,selected.dish_id);
 bindVoiceInput($('#dish-practice-form'));
 window.scrollTo(0,0);
}
function bindDishPractice(courseId,dishId){
 const form=$('#dish-practice-form');if(!form)return;
 let practiceRequestId=null,previousText='';
 form.onsubmit=async e=>{
  e.preventDefault();const button=form.querySelector('[type="submit"]');
  const answer=form.elements.namedItem('answer').value;
  if(answer.trim().length<40){error(Error('Напиши не менее 40 символов'));return}
  if(answer!==previousText){practiceRequestId=crypto.randomUUID();previousText=answer}
  const state=$('#dish-practice-state');button.disabled=true;
  state.textContent='ИИ проверяет твой ответ…';
  try{
   const f=await api('learning/'+courseId+'/dish-practice','POST',{
    dish_id:dishId,request_id:practiceRequestId,answer
   });
   $('#dish-practice-feedback').innerHTML='<div class="card result-card">'+
    '<h3>Твой разбор</h3><p>'+esc(f.summary)+'</p>'+
    '<h3>Что получилось</h3><p>'+esc(f.strengths)+'</p>'+
    '<h3>Что улучшить</h3><p>'+esc(f.improvements)+'</p>'+
    '<h3>Следующий шаг</h3><p>'+esc(f.next_step)+'</p>'+
    '<p class="muted">ИИ даёт учебную обратную связь. Допуск к работе подтверждает руководитель.</p></div>';
   state.textContent='Разбор сохранён в твоём профиле.';
   practiceRequestId=null;previousText='';
  }catch(err){
   state.textContent='Ответ не оценён. Он остался в поле — можно повторить позже.';
   error(err);
  }finally{button.disabled=false}
 };
}
function showStudyQuiz(){
 if(activeAssignment&&activeAssignment.finished){
  $('#app').innerHTML=studyHeader('Обязательное обучение')+'<section class="card"><h1>'+
   (activeAssignment.history.some(t=>t.passed)?'Тест уже сдан':'Попытки закончились')+'</h1><p>'+
   (activeAssignment.history.some(t=>t.passed)?'Результат сохранён. Можно повторить материал или перейти к практике.':'Обратись к менеджеру. Материал и разбор остаются доступны.')+'</p>'+
   btn('Повторить материал','chapter-review','','secondary')+btn('Практика','nav','cases','lime-action')+'</section>'+
   activeAssignment.review.map((q,i)=>reviewQuestion(q,undefined,i)).join('');
  return;
 }
 const c=activeCourse,q=c.questions[quizIndex];
 $('#app').innerHTML=studyHeader(`Вопрос ${quizIndex+1} из ${c.questions.length}`)+`<div class="lesson-stage"><span>1 · Изучение</span><span class="stage-active">2 · Тест</span><span>3 · Практика</span></div><progress max="${c.questions.length}" value="${quizIndex+1}"></progress><form id="study-quiz"><h1>${esc(q.question)}</h1>${questionInput(q,'answer',quizAnswers[quizIndex])}<div class="actions">${quizIndex?btn('Назад','quiz-prev','','secondary'):''}<button type="submit">${quizIndex===c.questions.length-1?'Узнать результат':'Следующий вопрос →'}</button></div><p id="quiz-state" role="status"></p></form>`;
 if(quizIndex)$('#study-quiz [data-action]').type='button';
 $('#study-quiz').onsubmit=async e=>{
  e.preventDefault();quizAnswers[quizIndex]=readAnswer(q,new FormData(e.target),'answer');
  if(quizIndex<c.questions.length-1){quizIndex++;showStudyQuiz();return}
  const button=e.target.querySelector('[type=submit]');button.disabled=true;$('#quiz-state').textContent='Сохраняем результат…';
  try{const r=await submitStudyAnswers();showStudyResult(r)}catch(err){button.disabled=false;$('#quiz-state').textContent='Ответы остались на экране. Можно повторить отправку.';error(err)}
 };
 window.scrollTo(0,0);
}
function showStudyResult(r){
 activeCourse.history.unshift({score:r.score,passed:r.passed,created_at:new Date().toISOString()});
 $('#app').innerHTML=studyHeader('Результат сохранён')+
  '<section class="card result-card"><p class="eyebrow">'+(r.passed?'Тест сдан':'Есть что повторить')+'</p>'+
  '<h1>'+r.score+'%</h1><p>Проходной балл: '+activeCourse.pass_score+'%. Очный допуск подтверждает руководитель.</p>'+
  (activeCourse.chapters.some(x=>x.kind==='dish')?
   btn('Практика с ИИ →','study-practice','','lime-action'):
   btn('Практика ситуаций →','nav','cases','lime-action'))+
  (!r.passed?btn('Повторить главы','chapter-review','','secondary'):'')+'</section>'+
  '<details '+(!r.passed?'open ':'')+'class="card lesson-extra"><summary>Разбор '+r.review.length+' ответов</summary>'+
  (r.review.length?r.review.map((q,i)=>reviewQuestion(q,q.answer,i)).join(''):'<p>Разбор откроется после сдачи теста или завершения разрешённых попыток. Пока повтори материал перед следующей попыткой.</p>')+'</details>'+
  btn('К моему пути','nav','home','secondary');
 window.scrollTo(0,0);
}
document.addEventListener('click',async e=>{
 const b=e.target.closest('[data-action]');if(!b)return;
 const {action,id}=b.dataset;
 if(!['study','study-practice','filter','direction','chapter-next','chapter-prev','chapter-review','study-quiz','quiz-prev','study-results','course-map','course-map-add','course-map-remove','course-map-up','course-map-down','course-map-save','course-map-suggest','course-text-editor','text-chapter-add','text-chapter-remove','text-chapter-up','text-chapter-down','text-chapter-save'].includes(action))return;
 b.disabled=true;
 try{
  if(action==='course-text-editor')await editTextChapters(Number(id));
  if(action==='text-chapter-add'){readTextChapterDraft();textChaptersDraft.push({title:'',body:'',source:''});renderTextChapterEditor()}
  if(action==='text-chapter-remove'){readTextChapterDraft();textChaptersDraft.splice(Number(id),1);renderTextChapterEditor()}
  if(action==='text-chapter-up'||action==='text-chapter-down'){
    readTextChapterDraft();const k=Number(id),other=k+(action==='text-chapter-up'?-1:1);
    if(k>=0&&other>=0&&other<textChaptersDraft.length)[textChaptersDraft[k],textChaptersDraft[other]]=[textChaptersDraft[other],textChaptersDraft[k]];
    renderTextChapterEditor();
  }
  if(action==='text-chapter-save')await saveTextChapters();
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
  if(action==='study-practice')showPostTestPractice(Number(id)||undefined);
  if(action==='direction'){view='catalog';await render();filterCourses(id)}
  if(action==='filter')filterCourses(id);
  if(action==='chapter-prev'){chapterIndex--;showChapter()}
   if(action==='chapter-review'){chapterIndex=0;showChapter()}
  if(action==='chapter-next'){
   const r=await api('learning/'+activeCourse.id+'/read','POST',{chapter_id:activeCourse.chapters[chapterIndex].id});activeCourse.read=r.read;
   if(activeAssignment&&activeCourse.chapters.every(ch=>activeCourse.read.includes(ch.id))&&!activeAssignment.acknowledged_at){
    await api('assignments/'+activeAssignment.id+'/acknowledge','POST',{});activeAssignment.acknowledged_at=true;
   }
   if(chapterIndex<activeCourse.chapters.length-1){chapterIndex++;showChapter()}
   else if(activeCourse.history.some(t=>t.passed)||!activeCourse.questions.length)showStudyComplete();
   else {quizIndex=0;quizAnswers=[];quizRequest=crypto.randomUUID();showStudyQuiz()}
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
let courseMapId=null,courseMapTitle='',courseMapSource='',courseMapSelected=[],courseMapOriginal=[],courseMapHasQuestions=false,courseMapPublished=false,courseMapAvailable=[],courseMapSearch='';
async function editCourseDishMap(id){
 if(!isManager())throw Error('Доступ только менеджеру');
 const [mapping,cards]=await Promise.all([api('learning/'+id+'/dish-map'),api('dishes')]);
 courseMapId=id;courseMapTitle=mapping.title;courseMapSource=mapping.source||'';
 courseMapSelected=[...mapping.dish_ids];courseMapOriginal=[...mapping.dish_ids];courseMapHasQuestions=mapping.questions_count>0;courseMapPublished=mapping.published;courseMapAvailable=cards.filter(c=>c.published);
 courseMapSearch='';
 $('#app').innerHTML=btn('← Материалы','nav','courses','secondary')+
 '<h1>Главы курса</h1><p class="muted">'+esc(courseMapTitle)+'</p>'+
 '<div class="card"><p>Выбери утверждённые карточки и установи порядок. После сохранения ИИ предложит проверяемые вопросы и открытые кейсы; менеджер сможет исправить их перед публикацией.</p>'+ 
 '<p class="muted">Для одного пакета ИИ — до 16 карточек. При изменении рецептуры потребуется заново проверить вопросы и опубликовать новую версию курса.</p></div>'+
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
 const changed=JSON.stringify(courseMapOriginal)!==JSON.stringify(courseMapSelected);
 const clear=changed&&courseMapHasQuestions&&!courseMapPublished;
 if(clear&&!confirm('Состав курса изменён. Сбросить черновик теста и заново получить предложения ИИ? История попыток не удаляется.'))return;
 const cid=courseMapId;
 const r=await api('learning/'+cid+'/dish-map','PUT',{dish_ids:courseMapSelected,reset_quiz:clear});
 courseMapId=null;
 if(r.generation_ready&&r.dish_ids.length<=16){await generateCourseProposal(cid);return}
 if(r.generation_ready){
  $('#app').innerHTML='<h1>Главы курса сохранены</h1><section class="card">'+
   '<h2>Слишком много карточек для одной генерации</h2>'+
   '<p>Разбей материал на курсы до 16 карточек, чтобы ИИ проверил каждый источник, а не пропустил часть меню.</p>'+
   btn('Изменить главы','course-map',cid,'lime-action')+
   btn('К программам','nav','courses','secondary')+'</section>';
  return;
 }
 view='courses';await render();
}


// Text chapters for coffee, service and other courses without recipe cards.
let textChapterCourse=null,textChapterTitle='',textChapterSource='',textChaptersDraft=[];
async function editTextChapters(cid){
 if(!isManager())throw Error('Доступ только руководителю');
 const data=await api('learning/'+cid+'/text-chapters');
 textChapterCourse=cid;textChapterTitle=data.title;textChapterSource=data.source;
 textChaptersDraft=data.chapters.map(x=>({...x}));
 renderTextChapterEditor();
}
function readTextChapterDraft(){
 const editor=$('#text-chapters-form');if(!editor)return;
 const fields=[...editor.querySelectorAll('[data-chapter-index]')];
 textChaptersDraft=fields.map(node=>({
  title:node.querySelector('[name=title]').value,
  body:node.querySelector('[name=body]').value,
  source:node.querySelector('[name=source]').value
 }));
}
function renderTextChapterEditor(){
 $('#app').innerHTML=btn('← Материалы','nav','courses','secondary')+
 '<h1>Редактор учебных глав</h1><p class="muted">'+esc(textChapterTitle)+'</p>'+
 '<div class="card"><p>Введи короткие учебные главы вместо сырого текста PDF. Сохраняются отдельные уроки, а тест и предыдущие результаты курса не меняются.</p>'+
 '<p class="muted">Если в курсе привязаны карточки блюд, сначала отвяжи их в редакторе карточек — два формата нельзя включить одновременно.</p></div>'+
 '<form id="text-chapters-form">'+textChaptersDraft.map((ch,i)=>
  '<article class="card text-chapter-editor" data-chapter-index="'+i+'">'+
  '<div class="row"><strong>Глава '+(i+1)+'</strong>'+
  '<div class="map-buttons">'+(i?btn('↑','text-chapter-up',i,'secondary'):'')+
  (i<textChaptersDraft.length-1?btn('↓','text-chapter-down',i,'secondary'):'')+
  btn('Удалить','text-chapter-remove',i,'secondary')+'</div></div>'+
  '<label>Заголовок<input maxlength="180" required name="title" value="'+esc(ch.title)+'"></label>'+
  '<label>Учебный текст<textarea name="body" required maxlength="6000" rows="8">'+esc(ch.body)+'</textarea></label>'+
  '<label>Источник (необязательно)<input name="source" maxlength="500" value="'+esc(ch.source||textChapterSource)+'"></label>'+
  '</article>').join('')+'</form>'+
 '<div class="actions">'+btn('Добавить главу +','text-chapter-add','','secondary')+
 btn('Сохранить главы','text-chapter-save')+'</div>'+
 '<p class="muted">До 60 глав по 6000 символов. Редактирование меняет идентификатор главы и потребует повторного ознакомления, но результаты тестов сохраняются.</p>';
 $('#text-chapters-form').querySelectorAll('button').forEach(b=>b.type='button');
}
async function saveTextChapters(){
 readTextChapterDraft();
 if(!textChaptersDraft.length&&!confirm('Удалить все созданные главы? Вернётся старый исходный текст курса.'))return;
 if(textChaptersDraft.some(x=>!x.title.trim()||!x.body.trim()))throw Error('Заполни заголовок и текст каждой главы');
 await api('learning/'+textChapterCourse+'/text-chapters','PUT',{chapters:textChaptersDraft});
 textChapterCourse=null;view='courses';await render();
}
