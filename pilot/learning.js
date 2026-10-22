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
function learningDone(c){return c.read===c.chapters&&(!c.questions||c.passed)}
function courseCard(c){return `<button class="course-row" data-action="study" data-id="${c.id}"><span class="course-symbol">${navSvg('courses')}</span><span><strong>${esc(c.title)}</strong><small>${esc(directions[c.category])} · ${c.read} из ${c.chapters} глав</small><progress max="${c.chapters||1}" value="${c.read}"></progress><small>${learningDone(c)?'Завершено':c.best_score!==null?'Тест: '+c.best_score+'%':'Изучить материал'}</small></span><span aria-hidden="true">›</span></button>`}
async function learningPage(page){
 const root=$('#app');root.innerHTML='<p role="status">Загружаем обучение…</p>';
 learningCourses=await api('learning');
 if(page==='catalog'){
  root.innerHTML='<h1>Курсы</h1>'+ (isManager()?`<div class="actions">${btn('Управление материалами','nav','courses','secondary')}${btn('Назначения команды','nav','assignments','secondary')}</div>`:'')+`<div class="filters">${btn('Все','filter','all','active')}${Object.entries(directions).map(([k,v])=>btn(v,'filter',k,'secondary')).join('')}</div><div id="course-list">${learningCourses.map(courseCard).join('')||'<div class="card">Утверждённые курсы появятся здесь после проверки менеджером.</div>'}</div>`;
  return;
 }
 const total=learningCourses.reduce((n,c)=>n+c.chapters,0),read=learningCourses.reduce((n,c)=>n+c.read,0),next=learningCourses.find(c=>!learningDone(c));
 const assignments=(await api('assignments')).filter(a=>a.staff_id===user.id&&!done(a));
 root.innerHTML=`<p class="eyebrow">${esc(roles[user.role])} · ${esc(user.restaurant)}</p><h1>Привет, ${esc(user.name)}</h1><section class="card learning-hero"><span class="eyebrow">Программа адаптации MOJO</span><h2>Мой путь в команду</h2><p>Изучи материал и закрепи знания на практике.</p><div class="row"><span>Прочитано глав</span><strong>${read} из ${total}</strong></div><progress max="${total||1}" value="${read}"></progress>${next?btn('Продолжить обучение →','study',next.id,'lime-action'):btn('Открыть курсы →','nav','catalog','lime-action')}</section><h2>Направления обучения</h2><div class="direction-grid">${Object.entries(directions).map(([k,v])=>`<button class="card direction" data-action="direction" data-id="${k}">${navSvg('courses')}<strong>${v}</strong><small>${learningCourses.filter(c=>c.category===k).length} курсов</small></button>`).join('')}</div>${assignments.length?`<h2>Обязательное обучение</h2>${assignments.slice(0,3).map(a=>`<article class="card"><h3>${esc(a.title)}</h3><p class="muted">До ${esc(dateLabel(a.deadline))}</p>${btn('Открыть назначение','lesson',a.id)}</article>`).join('')}`:''}${isManager()?`<div class="actions">${btn('Назначения команды','nav','assignments','secondary')}${btn('Управление материалами','nav','courses','secondary')}</div>`:''}`;
}
async function study(id){
 $('#app').innerHTML='<p role="status">Открываем курс…</p>';
 activeCourse=await api('learning/'+id);
 chapterIndex=activeCourse.chapters.findIndex(c=>!activeCourse.read.includes(c.id));
 if(chapterIndex<0)chapterIndex=0;
 showChapter();
}
function studyHeader(sub){return `<div class="lesson-top">${btn('←','nav','catalog','secondary')}<div><strong>${esc(activeCourse.title)}</strong><small>${sub}</small></div></div>`}
function showChapter(){
 const c=activeCourse,p=c.chapters[chapterIndex],all=c.chapters.every(p=>c.read.includes(p.id));
 $('#app').innerHTML=studyHeader(`Глава ${chapterIndex+1} из ${c.chapters.length}`)+`<progress max="${c.chapters.length}" value="${c.read.length}"></progress><article class="card chapter"><span class="badge">${c.read.includes(p.id)?'Прочитано':'Учебный материал'}</span><h1>${esc(p.title)}</h1><div class="body">${esc(p.body)}</div></article><div class="actions">${chapterIndex?btn('← Назад','chapter-prev','','secondary'):''}${btn(c.read.includes(p.id)?'Далее →':'Прочитано, далее →','chapter-next')}</div><p class="muted">Источник: ${esc(c.source)}</p>${all&&c.questions.length?btn('Закрепить знания: тест →','study-quiz'):''}<section class="card"><h2>Мои результаты</h2>${c.history.length?c.history.map(t=>`<p>${esc(new Date(t.created_at).toLocaleString('ru-RU'))} · ${t.score}% · ${t.passed?'Сдано':'Повторить материал'}</p>`).join(''):'<p class="muted">Тест ещё не пройден.</p>'}</section>${isManager()?btn('Результаты команды','study-results',c.id,'secondary'):''}`;
 window.scrollTo(0,0);
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
 if(!['study','filter','direction','chapter-next','chapter-prev','study-quiz','quiz-prev','study-results'].includes(action))return;
 b.disabled=true;
 try{
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
