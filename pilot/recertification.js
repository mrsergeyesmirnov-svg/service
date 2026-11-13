let recert=null,recertIndex=0,recertBusy=false;
function recertOutcome(result){
 const pending=result.evaluation?.needs_review;
 $('#app').innerHTML='<h1>Результат переаттестации</h1><section class="card">'+
  (pending?'<h2>Нужна проверка менеджером</h2><p>Предварительно: '+result.evaluation.provisional_score+'–'+result.evaluation.score_upper+'%. Спорные компоненты не считаются неправильными. Окончательные балл и статус ещё не утверждены.</p>':'<h2>'+result.score+'%</h2><p>'+(result.passed?'Сдано':'Не сдано')+' · Проходной балл '+result.pass_score+'%.</p>')+
  btn('К программе','nav','catalog','secondary')+btn('Обновить результат','recert-detail',result.id,'secondary')+'</section>'+
  '<details open><summary>Разбор ответов</summary>'+result.review.map((q,i)=>reviewQuestion(q,q.answer,i)).join('')+'</details>';
}
async function recertCheck(){
 if(recertBusy)return;recertBusy=true;
 try{
  while(true){
   $('#app').innerHTML='<h1>Проверяем составы с ИИ</h1><p role="status">Проверено '+(recert.evaluation?.graded||0)+' из '+recert.questions.length+'. Ответы сохранены. Можно вернуться к проверке позже.</p>';
   recert=await api('recertification/'+recert.id+'/submit','POST',{},90000);
   if(recert.submitted){recertOutcome(recert);break}
  }
 }catch(err){
  $('#app').innerHTML='<h1>Ответы сохранены</h1><p>'+esc(err.message)+'</p><p>Оценка не выставлена. Уже полученные разборы сохранятся при повторе.</p>'+btn('Продолжить проверку','recert-continue',recert.id,'lime-action');
 }finally{recertBusy=false}
}
function recertRender(){
 if(recert.locked||recert.submitted){
  $('#app').innerHTML='<h1>Ответы отправлены</h1><p>Ответы сохранены и закрыты для изменений.</p>'+btn('Продолжить / посмотреть проверку','recert-continue',recert.id,'lime-action');return;
 }
 const q=recert.questions[recertIndex];
 $('#app').innerHTML='<h1>Переаттестация по основному меню</h1><p>'+(recert.mode==='practice'?'Для себя':'Для руководства')+' · '+esc(q.section)+' · Вопрос '+(recertIndex+1)+' из '+recert.questions.length+'</p><progress max="'+recert.questions.length+'" value="'+(recertIndex+1)+'"></progress><form id="recert-form" class="card"><h2>'+esc(q.question)+'</h2>'+questionInput(q,'answer',recert.answers[recertIndex])+'<div class="actions">'+(recertIndex?'<button type="button" id="recert-back" class="secondary">← Назад</button>':'')+'<button type="submit">'+(recertIndex===recert.questions.length-1?'Завершить тест':'Сохранить и дальше →')+'</button></div><p role="status" id="recert-status">Ответы сохраняются при переходе между вопросами.</p></form>';
 async function save(direction){
  if(recertBusy)return;recertBusy=true;
  const form=$('#recert-form'),answer=String(new FormData(form).get('answer')||'');
  form.querySelectorAll('button').forEach(b=>b.disabled=true);
  try{
   await api('recertification/'+recert.id+'/answer','POST',{index:recertIndex,answer});
   recert.answers[recertIndex]=answer;
   if(direction===1&&recertIndex===recert.questions.length-1){
    recertBusy=false;await recertCheck();
   }else{recertIndex+=direction;recertRender()}
  }catch(e){error(e);form.querySelectorAll('button').forEach(b=>b.disabled=false)}
  finally{recertBusy=false}
 }
 $('#recert-form').onsubmit=e=>{e.preventDefault();save(1)};
 if($('#recert-back'))$('#recert-back').onclick=()=>save(-1);
 window.scrollTo(0,0);
}
document.addEventListener('click',async e=>{
 const b=e.target.closest('[data-action]');if(!b)return;
 if(b.dataset.action==='recert-continue'){await recertCheck();return}
 if(b.dataset.action==='recert-detail'){
  try{recertOutcome(await api('recertification/'+b.dataset.id))}catch(err){error(err)}return;
 }
 if(b.dataset.action==='recert-manager-review'){
  try{await recertManagerReview(b.dataset.id)}catch(err){error(err)}return;
 }
 if(b.dataset.action==='recert-start'){
  b.disabled=true;
  try{recert=await api('recertification/start','POST',{mode:b.dataset.id||'practice'});recertIndex=Math.max(0,recert.answers.findIndex(a=>!a));recertRender()}catch(err){error(err)}finally{b.disabled=false}
 }
 if(b.dataset.action==='recert-results'){
  b.disabled=true;
  try{const rows=await api('recertification/results');$('#app').innerHTML='<h1>Переаттестация официантов</h1>'+btn('Назад','nav','team','secondary')+(rows.map(r=>'<section class="card"><h2>'+esc(r.name)+'</h2><p>'+esc(r.restaurant)+' · '+esc(new Date(r.created_at).toLocaleString('ru-RU'))+'</p><p>'+(r.needs_review?'Ожидает проверки менеджером':r.score+'% · '+(r.passed?'Сдано':'Не сдано'))+'</p>'+btn(r.needs_review?'Проверить спорные ответы':'Разбор','recert-manager-review',r.id,'secondary')+'</section>').join('')||'<p>Попыток пока нет.</p>')}catch(err){error(err)}finally{b.disabled=false}
 }
});

async function recertManagerReview(id){
 const result=await api('recertification/'+id);
 if(!result.evaluation?.needs_review){recertOutcome(result);return}
 const disputed=result.review.map((q,index)=>({q,index})).filter(x=>x.q.assessment?.needs_review);
 $('#app').innerHTML='<h1>Проверка спорных ответов</h1><p>Засчитывай только компонент, обозначенный в ответе. Для зачёта укажи точную цитату; одну цитату нельзя использовать дважды.</p><form id="recert-review-form">'+disputed.map(({q,index})=>
  reviewQuestion(q,q.answer,index)+(q.assessment.contradictions.length?'<label><input type="checkbox" name="ack-'+index+'" required>Противоречия рассмотрены</label>':'')+
  q.assessment.components.filter(c=>c.status==='uncertain').map(c=>{
   const key=index+'-'+c.id;
   return '<fieldset><legend>'+esc(c.ingredient)+'</legend><label>Решение<select name="status-'+key+'" required><option value="">Выбери решение</option><option value="recognized">Засчитать</option><option value="missing">Не назван</option></select></label><label>Точная цитата ответа (для зачёта)<input name="evidence-'+key+'" value="'+esc(c.evidence)+'"></label><label>Номер появления цитаты, начиная с 0<input name="occurrence-'+key+'" type="number" min="0" value="'+c.occurrence+'"></label><label>Обоснование<textarea name="reason-'+key+'" required maxlength="500"></textarea></label></fieldset>';
  }).join('')).join('')+'<button>Утвердить результат</button><p id="recert-review-status" role="status"></p></form>';
 $('#recert-review-form').onsubmit=async e=>{
  e.preventDefault();const button=e.target.querySelector('button');button.disabled=true;
  try{
   const f=new FormData(e.target),questions=disputed.map(({q,index})=>({index,acknowledged_contradictions:f.has('ack-'+index),components:q.assessment.components.filter(c=>c.status==='uncertain').map(c=>{
    const key=index+'-'+c.id;return {id:c.id,status:f.get('status-'+key),evidence:f.get('evidence-'+key),occurrence:Number(f.get('occurrence-'+key)),reason:f.get('reason-'+key)};
   })}));
   recertOutcome(await api('recertification/'+id+'/review','POST',{questions}));
  }catch(err){$('#recert-review-status').textContent=err.message;button.disabled=false}
 };
}

document.addEventListener('click',async e=>{
 const b=e.target.closest('[data-action="recert-assign-open"]');if(!b)return;
 b.disabled=true;
 try{
  const staff=(await api('team')).filter(s=>s.active&&s.role==='waiter');
  $('#app').innerHTML='<h1>Назначить переаттестацию</h1>'+btn('Назад','nav','team','secondary')+'<p>30 вопросов из всех семи разделов. Сначала сотрудник проверяет себя, затем проходит официально. Повторы не ограничены.</p><form id="recert-assign-form" class="card"><label>Официант<select name="staff_id" required>'+staff.map(s=>'<option value="'+s.id+'">'+esc(s.name)+' · '+esc(s.restaurant)+'</option>').join('')+'</select></label><button '+(!staff.length?'disabled':'')+'>Назначить</button><p id="recert-assigned-status" role="status"></p></form>';
  $('#recert-assign-form').onsubmit=async ev=>{
   ev.preventDefault();const form=ev.target,submit=form.querySelector('button');submit.disabled=true;
   try{await api('recertification/assign','POST',{staff_id:Number(new FormData(form).get('staff_id'))});$('#recert-assigned-status').textContent='Назначено. Сотрудник увидит обязательную переаттестацию на главной и в программе.'}catch(err){error(err)}finally{submit.disabled=false}
  };
 }catch(err){error(err)}finally{b.disabled=false}
});
