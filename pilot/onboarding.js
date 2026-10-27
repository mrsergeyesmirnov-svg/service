/* MOJO: two-day induction inside the EXISTING Telegram Mini App.
   Uses shared api(), btn(), questionInput() and the already authenticated user.
   No mentors, no additional navigation tabs, no AI-generated restaurant facts. */
let onboardState = null;
let onboardDiagnostic = null;
let onboardDiagnosticRequest = null;
let onboardBusy = false;
let onboardManagerId = null;

function onboardingHomeCard(s){
 if(!s?.available)return '';
 const stage=s.stage;
 const title=stage==='day1'?'День 1 · Знакомство':stage==='day2'?'День 2 · Проверка знаний':'Адаптация пройдена';
 const sub=stage==='day1'?'Знакомство, небольшие задания и отзыв о первом дне.':
           stage==='day2'?'Самооценка, короткие проверки и темы для повторения.':
           'Основная программа открыта. Учебные материалы остаются доступны.';
 const completed=(s.quests||[]).filter(x=>x.status==='done').length;
 const progress=stage==='day1'?completed+' из '+s.quests.length+' заданий':
                stage==='day2'?s.topics.filter(x=>x.diagnosed).length+' из 3 тем':'День 1 и День 2 завершены';
 return '<section class="card onboard-home">'+
 '<span class="eyebrow">МОЙ ПУТЬ · MOJO</span><h2>'+esc(title)+'</h2>'+
 '<p>'+esc(sub)+'</p><span class="onboard-home-progress">'+esc(progress)+'</span>'+
 btn(stage==='main'?'Посмотреть мой маршрут':'Продолжить адаптацию →','onboard-open','','lime-action')+
 '</section>';
}

const obStatus={
 todo:'Нужно выполнить',pending:'На проверке',done:'Готово',revise:'Нужно доработать'
};
function obStages(stage){
 return '<div class="onboard-stages" aria-label="Этапы адаптации">'+
 ['День 1','День 2','Программа'].map((label,i)=>{
  const done=(i===0&&stage!=='day1')||(i===1&&stage==='main');
  const active=(i===0&&stage==='day1')||(i===1&&stage==='day2')||(i===2&&stage==='main');
  return '<span class="'+(done?'complete':active?'current':'')+'">'+esc(label)+(done?' ✓':'')+'</span>';
 }).join('')+'</div>';
}
function obBack(){
 return '<div class="onboard-back">'+btn('← Мой путь','nav','home','secondary')+'</div>';
}
function obQuestMarkup(q){
 const state=q.status||'todo',color=state==='done'?'done':state==='pending'?'pending':state==='revise'?'revise':'todo';
 const form=(state==='todo'||state==='revise')?
  '<form data-onboard-form="quest" data-key="'+esc(q.key)+'">'+
   '<label>Короткий ответ<textarea name="answer" rows="3" maxlength="1200" required placeholder="'+esc(q.prompt)+'">'+esc(q.answer||'')+'</textarea></label>'+
   '<button type="submit" class="lime-action">'+(q.review?'Передать менеджеру':'Выполнено')+'</button></form>':'';
 return '<details class="card onboard-quest" '+(state==='revise'?'open':'')+'>'+
  '<summary><span class="onboard-quest-icon">'+(state==='done'?'✓':'○')+'</span><span class="onboard-quest-name">'+esc(q.title)+
  '<small class="ob-status '+color+'">'+esc(obStatus[state])+'</small></span><span class="onboard-chevron">›</span></summary>'+
  '<div class="onboard-quest-body"><p>'+esc(q.instruction)+'</p>'+
  (q.review?'<p class="muted">После ответа менеджер подтвердит выполнение лично.</p>':'')+
  (q.review_comment?'<p class="ob-review-comment">Комментарий менеджера: '+esc(q.review_comment)+'</p>':'')+
  (state==='pending'?'<p class="muted">Ответ сохранён. Сообщение о проверке увидишь здесь.</p>':'')+
  (state==='done'&&q.answer?'<p class="muted">Твой ответ: '+esc(q.answer)+'</p>':'')+form+'</div></details>';
}
function obDayOne(s){
 const all=s.quests.every(q=>q.status==='done');
 return '<div class="onboard-title"><span class="eyebrow">ПЕРВЫЙ ДЕНЬ</span>'+
  '<h1>Добро пожаловать в MOJO</h1>'+
  '<p>Сегодня твоя задача — познакомиться с командой и освоиться в ресторане. Это ориентир на первые четыре часа, а не таймер и не экзамен.</p></div>'+
  '<div class="card onboard-welcome"><strong>Как это работает</strong><p>Выполняй небольшие задания в зале, записывай ответы и спрашивай менеджера, если что-то непонятно. Не обслуживай гостей самостоятельно без допуска.</p></div>'+
  '<h2 class="onboard-section-title">Твои задания</h2>'+
  '<div class="onboard-task-list">'+s.quests.map(obQuestMarkup).join('')+'</div>'+
  (all?'<section class="card onboard-feedback"><h2>Как прошёл первый день?</h2>'+
     '<p>Спасибо за выполненные задания. Оставь короткий отзыв — после него откроется второй день.</p>'+
     '<form data-onboard-form="feedback">'+
     '<label>Как прошёл день? <select name="rating" required>'+[1,2,3,4,5].map(n=>'<option value="'+n+'" '+(n===5?'selected':'')+'>'+n+' из 5</option>').join('')+'</select></label>'+
     '<label>Насколько понятны инструкции? <select name="clarity" required>'+[1,2,3,4,5].map(n=>'<option value="'+n+'" '+(n===5?'selected':'')+'>'+n+' из 5</option>').join('')+'</select></label>'+
     '<label>Что можно улучшить? (необязательно)<textarea name="comment" maxlength="1000" rows="3"></textarea></label>'+
     '<button type="submit" class="lime-action">Завершить первый день →</button></form></section>':
     '<p class="onboard-hint">Когда менеджер подтвердит практические задания, здесь появится короткий отзыв о первом дне.</p>');
}
function obSelfAssessment(s){
 return '<section class="card onboard-self"><h2>С чего начнём?</h2>'+
  '<p>Отметь, насколько уверенно ты чувствуешь себя в этих темах. Это не оценка и не освобождение от обязательного обучения.</p>'+
  '<form data-onboard-form="self">'+s.topics.map(topic=>
   '<fieldset class="onboard-level"><legend>'+esc(topic.title)+'</legend>'+
   [['know','Знаю'],['partial','Частично'],['new','Не знаю']].map(([v,title])=>
     '<label><input type="radio" name="'+esc(topic.key)+'" value="'+v+'" '+(topic.level===v?'checked':'')+' required><span>'+title+'</span></label>').join('')+
   '</fieldset>').join('')+
  '<button type="submit" class="lime-action">Сохранить самооценку</button></form></section>';
}
function obDayTwo(s){
 const levels=s.topics.every(t=>!!t.level);
 const all=s.topics.every(t=>t.diagnosed);
 return '<div class="onboard-title"><span class="eyebrow">ВТОРОЙ ДЕНЬ</span><h1>Проверим, что уже знаешь</h1>'+
  '<p>Сначала самооценка, затем короткие проверки по утверждённым материалам. При ошибках подскажем, какую тему повторить.</p></div>'+
  (!levels?obSelfAssessment(s):'<section class="card"><h2>Твои темы</h2><p class="muted">Самооценка сохранена. Чтобы завершить диагностику, ответь на вопросы по каждой теме — даже если отметил «Знаю».</p></section>')+
  (levels?s.topics.map(t=>'<article class="card onboard-topic"><div><strong>'+esc(t.title)+'</strong>'+
   '<p class="muted">Ты отметил: '+esc(({know:'Знаю',partial:'Частично',new:'Не знаю'})[t.level]||'—')+'</p>'+
   (t.diagnosed?'<span class="ob-status '+(t.passed?'done':'revise')+'">Результат '+t.score+'% · '+(t.passed?'хорошо':'есть темы для повторения')+'</span>':
      '<span class="ob-status todo">Ещё не проверено</span>')+'</div>'+
   (t.course_id?btn(t.diagnosed?'Повторить проверку':'Проверить знания','onboard-diagnostic',t.key,'secondary'):
    '<p class="onboard-unmapped">Менеджер ещё не выбрал утверждённый курс для этой темы.</p>')+
   (t.course_id?btn('Изучить материал','onboard-study',t.course_id,'secondary'):'')+
   '</article>').join(''):'')+
  (levels?'<section class="onboard-next"><p>Нужна практика общения с гостем? В разделе «Практика» доступны опубликованные менеджером ситуации.</p>'+
     btn('Открыть практику →','nav','cases','secondary')+'</section>':'')+
  (all?'<section class="card onboard-done"><h2>Диагностика завершена</h2><p>Теперь доступны твои рекомендации и основная программа. Это ещё не допуск к самостоятельной работе.</p>'+btn('Мой маршрут →','onboard-open','','lime-action')+'</section>':'');
}
function obMain(s){
 const suggested=s.recommendations||[];
 return '<section class="card onboard-done"><span class="eyebrow">ДВА ДНЯ ЗАВЕРШЕНЫ</span>'+
  '<h1>Продолжай обучение</h1><p>Знакомство и диагностика сохранены. Разделы программы, которые назначил менеджер, доступны для повторения и после сдачи.</p>'+
  btn('Открыть программу →','nav','catalog','lime-action')+'</section>'+
  (suggested.length?'<h2 class="onboard-section-title">Что стоит повторить</h2>'+
   suggested.map(item=>'<div class="card onboard-topic"><strong>'+esc(item.title)+'</strong><small>Обязательная тема для обучения</small>'+
      btn('Перейти к курсу','onboard-study',item.course_id,'secondary')+'</div>').join(''):
   '<p class="muted">Тематические рекомендации появятся после проверки знаний или назначения курсов.</p>')+
  '<p class="onboard-hint">Окончательное решение о допуске принимает руководитель после очной аттестации.</p>';
}

async function onboardingPage(){
 const root=$('#app');root.innerHTML='<p role="status">Открываем твой маршрут…</p>';
 onboardState=await api('onboarding/me');
 if(!onboardState.available){
  root.innerHTML=obBack()+'<section class="card"><h2>Адаптация</h2><p>Этапы первых двух дней предназначены для новых стажёров. Твои обычные курсы остаются в программе.</p>'+btn('К программе','nav','catalog','secondary')+'</section>';
  return;
 }
 root.innerHTML=obBack()+'<div class="onboard-wrap">'+obStages(onboardState.stage)+
   (onboardState.stage==='day1'?obDayOne(onboardState):
    onboardState.stage==='day2'?obDayTwo(onboardState):obMain(onboardState))+'</div>';
}
function onboardUuid(){
 if(window.crypto?.randomUUID)return window.crypto.randomUUID();
 // Only a client-side retry identifier. Not a security credential.
 return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,c=>{
  const r=Math.floor(Math.random()*16);return (c==='x'?r:(r&3|8)).toString(16);
 });
}
async function onboardingDiagnosticPage(topic){
 const root=$('#app');
 root.innerHTML=obBack()+'<p role="status">Открываем проверку…</p>';
 onboardDiagnostic=await api('onboarding/diagnostics/'+encodeURIComponent(topic));
 onboardDiagnosticRequest=onboardUuid();
 const d=onboardDiagnostic;
 root.innerHTML=obBack()+'<section class="onboard-wrap"><div class="onboard-title"><span class="eyebrow">ДЕНЬ 2 · ДИАГНОСТИКА</span>'+
 '<h1>'+esc(d.title)+'</h1><p>Три коротких вопроса из опубликованного курса. Отвечай по памяти; правильные варианты появятся после отправки.</p></div>'+
 '<form data-onboard-form="diagnostic" data-topic="'+esc(d.topic)+'">'+
 d.questions.map((q,i)=>'<fieldset class="card onboard-question"><legend>'+(i+1)+'. '+esc(q.question)+'</legend>'+
 questionInput(q,'q'+i)+'</fieldset>').join('')+
 '<button type="submit" class="lime-action onboard-finish">Проверить ответы</button></form></section>';
}
function obDiagnosticResult(result){
 onboardDiagnosticRequest=null;
 const missed=(result.explanations||[]).filter(x=>!x.correct);
 $('#app').innerHTML=obBack()+'<section class="onboard-wrap"><div class="card onboard-done">'+
 '<span class="eyebrow">ПРОВЕРКА ЗАВЕРШЕНА</span><h1>'+result.score+'%</h1>'+
 '<p>'+(result.passed?'Хорошая основа.':'Есть темы, которые стоит повторить.')+
 ' Самооценка не заменяет обязательную аттестацию.</p>'+
 (missed.length?'<h2>На что обратить внимание</h2>'+
  missed.map(x=>'<p><strong>'+esc(x.question)+'</strong><br>'+esc(x.explanation)+'<br><small>Источник: '+esc(x.source)+'</small></p>').join(''):'')+
 btn('Вернуться к маршруту','onboard-open','','lime-action')+'</div></section>';
}
async function onboardingTeamPage(){
 const root=$('#app');root.innerHTML='<p role="status">Загружаем адаптацию…</p>';
 const rows=await api('onboarding/team');
 root.innerHTML=workspaceHeader('Адаптация новичков','Первый день · второй день · основная программа')+
 '<div class="actions">'+btn('Темы диагностики','onboard-manager-topics','','secondary')+
 btn('К команде','nav','team','secondary')+'</div>'+
 (rows.length?rows.map(s=>'<article class="card onboard-team-row"><div><strong>'+esc(s.name)+'</strong>'+
 '<p class="muted">'+esc(s.restaurant)+' · '+(s.day2_completed_at?'День 2 завершён':s.day1_completed_at?'Второй день':'Первый день')+
 (s.pending?' · На проверке: '+s.pending:'')+'</p></div>'+
 btn('Открыть','onboard-manager-staff',s.id,'secondary')+'</article>').join(''):
 '<section class="card"><p>Активных стажёров пока нет.</p></section>');
}
async function onboardingTeamDetail(staffId){
 onboardManagerId=Number(staffId);
 const data=await api('onboarding/team/'+onboardManagerId),root=$('#app');
 root.innerHTML=workspaceHeader(data.name,'Сведения доступны только руководителю')+
 '<div class="actions">'+btn('← Все стажёры','nav','onboarding-team','secondary')+'</div>'+
 obStages(data.stage)+
 '<section class="card"><h2>Прогресс</h2><p>День 1: '+(data.day1_complete?'завершён':'в процессе')+
 '. День 2: '+(data.day2_complete?'завершён':'в процессе')+'.</p>'+
 '<form data-onboard-form="deadline"><label>Ориентир окончания первых двух дней'+
 '<input name="target_date" type="date" required value="'+esc(data.target_date||'')+'"></label>'+
 '<button class="secondary" type="submit">Сохранить срок</button></form></section>'+
 '<h2 class="onboard-section-title">Задания первого дня</h2>'+
 data.quests.map(q=>'<article class="card onboard-manager-quest"><strong>'+esc(q.title)+'</strong>'+
 '<span class="ob-status '+esc(q.status)+'">'+esc(obStatus[q.status])+'</span>'+
 (q.answer?'<p>'+esc(q.answer)+'</p>':'')+
 (q.status==='pending'&&q.review?'<form data-onboard-form="review" data-key="'+esc(q.key)+'">'+
 '<label>Комментарий, если нужна доработка<textarea name="comment" maxlength="600" rows="2"></textarea></label>'+
 '<div class="actions"><button name="decision" value="approve" type="submit" class="lime-action">Подтвердить</button>'+
 '<button name="decision" value="revise" type="submit" class="secondary">Вернуть</button></div></form>':'')+
 '</article>').join('')+
 (data.feedback?'<section class="card"><h2>Отзыв первого дня</h2><p>День: '+data.feedback.rating+'/5 · Понятность: '+data.feedback.clarity+'/5</p>'+
 '<p>'+esc(data.feedback.comment||'Без комментария')+'</p></section>':'')+
 '<section class="card"><h2>Диагностика второго дня</h2>'+
 data.topics.map(t=>'<p>'+esc(t.title)+': '+esc(({know:'знаю',partial:'частично',new:'не знаю'})[t.level]||'самооценки нет')+
 (t.diagnosed?' · '+t.score+'%':' · нет проверки')+'</p>').join('')+'</section>';
}
async function onboardingTopicsPage(){
 const data=await api('onboarding/topics'),root=$('#app');
 const known=new Map(data.mapped.map(x=>[x.topic,x.course_id]));
 root.innerHTML=workspaceHeader('Темы диагностики','Для каждой темы выбери опубликованный курс с проверенными вопросами.')+
 btn('← Адаптация','nav','onboarding-team','secondary')+
 (data.courses.length?data.topics.map(t=>
  '<form class="card" data-onboard-form="mapping" data-topic="'+esc(t.key)+'">'+
  '<h2>'+esc(t.title)+'</h2><label>Источник вопросов<select name="course_id" required>'+
  '<option value="">Выбери курс…</option>'+
  data.courses.map(c=>'<option value="'+c.id+'" '+(known.get(t.key)===c.id?'selected':'')+'>'+esc(c.title)+'</option>').join('')+
  '</select></label><label class="ob-check"><input type="checkbox" name="reviewed" required>Я проверил, что вопросы этого курса относятся к указанной теме.</label>'+
  '<button type="submit" class="lime-action">Сохранить тему</button></form>').join(''):
  '<section class="card"><h2>Пока нет подходящих курсов</h2>'+
  '<p>Сначала опубликуй базовый сервисный курс и другие материалы, содержащие хотя бы три утверждённых вопроса. Без источника диагностика не создаётся.</p>'+
  btn('Перейти к программам','nav','courses','secondary')+'</section>');
}
async function onboardingStudy(cid){
 managerMode=false;view='catalog';nav();await study(Number(cid));
}
document.addEventListener('click',async e=>{
 const action=e.target.closest('[data-action]')?.dataset?.action;
 if(!action?.startsWith('onboard-'))return;
 const target=e.target.closest('[data-action]'),id=target.dataset.id;
 if(onboardBusy)return;
 onboardBusy=true;
 try{
  if(action==='onboard-open'){managerMode=false;view='onboarding';nav();await onboardingPage()}
  if(action==='onboard-diagnostic')await onboardingDiagnosticPage(id);
  if(action==='onboard-study')await onboardingStudy(id);
  if(action==='onboard-manager-staff')await onboardingTeamDetail(id);
  if(action==='onboard-manager-topics')await onboardingTopicsPage();
 }catch(err){error(err)}finally{onboardBusy=false}
});
document.addEventListener('submit',async e=>{
 const form=e.target,kind=form.dataset.onboardForm;
 if(!kind)return;
 e.preventDefault();
 if(onboardBusy)return;
 onboardBusy=true;
 const buttons=[...form.querySelectorAll('button[type=submit]')];
 const submitter=e.submitter;
 buttons.forEach(b=>b.disabled=true);
 const field=new FormData(form);
 try{
  if(kind==='quest'){
   await api('onboarding/quests/'+form.dataset.key+'/submit','POST',{answer:field.get('answer')});
   await onboardingPage();
  }
  if(kind==='feedback'){
   await api('onboarding/day1/feedback','POST',{
    rating:Number(field.get('rating')),clarity:Number(field.get('clarity')),comment:field.get('comment')||''
   });
   await onboardingPage();
  }
  if(kind==='self'){
   const levels={service:field.get('service'),menu:field.get('menu'),allergens:field.get('allergens')};
   await api('onboarding/self-assessment','POST',{levels});
   await onboardingPage();
  }
  if(kind==='diagnostic'){
   const answers=onboardDiagnostic.questions.map((q,i)=>readAnswer(q,field,'q'+i));
   const result=await api('onboarding/diagnostics/'+form.dataset.topic+'/submit','POST',{
    course_id:onboardDiagnostic.course_id,request_id:onboardDiagnosticRequest,answers
   });
   obDiagnosticResult(result);
  }
  if(kind==='review'){
   if(!submitter)throw Error('Выбери решение по заданию');
   await api('onboarding/quests/'+form.dataset.key+'/review','POST',{
    staff_id:onboardManagerId,decision:submitter.value,comment:field.get('comment')||''
   });
   await onboardingTeamDetail(onboardManagerId);
  }
  if(kind==='deadline'){
   await api('onboarding/team/'+onboardManagerId,'PATCH',{target_date:field.get('target_date')});
   await onboardingTeamDetail(onboardManagerId);
  }
  if(kind==='mapping'){
   await api('onboarding/topics/'+form.dataset.topic,'PUT',{
    course_id:Number(field.get('course_id')),reviewed:field.has('reviewed')
   });
   await onboardingTopicsPage();
  }
 }catch(err){error(err);buttons.forEach(b=>b.disabled=false)}
 finally{onboardBusy=false}
});
