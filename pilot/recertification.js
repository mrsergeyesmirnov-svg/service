let recert=null,recertIndex=0,recertBusy=false;
function recertRender(){
 const q=recert.questions[recertIndex];
 $('#app').innerHTML='<h1>Переаттестация по основному меню</h1><p>'+(recert.mode==='practice'?'Для себя':'Для руководства')+' · '+esc(q.section)+' · Вопрос '+(recertIndex+1)+' из 40</p><progress max="40" value="'+(recertIndex+1)+'"></progress><form id="recert-form" class="card"><h2>'+esc(q.question)+'</h2>'+questionInput(q,'answer',recert.answers[recertIndex])+'<div class="actions">'+(recertIndex?'<button type="button" id="recert-back" class="secondary">← Назад</button>':'')+'<button type="submit">'+(recertIndex===39?'Завершить тест':'Сохранить и дальше →')+'</button></div><p role="status" id="recert-status">Ответы сохраняются при переходе между вопросами.</p></form>';
 async function save(direction){
  if(recertBusy)return;recertBusy=true;
  const form=$('#recert-form'),answer=String(new FormData(form).get('answer')||'');
  form.querySelectorAll('button').forEach(b=>b.disabled=true);
  try{
   await api('recertification/'+recert.id+'/answer','POST',{index:recertIndex,answer});
   recert.answers[recertIndex]=answer;
   if(direction===1&&recertIndex===39){
    const result=await api('recertification/'+recert.id+'/submit','POST',{});
    $('#app').innerHTML='<h1>Результат переаттестации</h1><section class="card"><h2>'+result.score+'%</h2><p>'+(result.passed?'Сдано':'Не сдано')+' · Проходной балл '+result.pass_score+'%. '+(result.mode==='practice'?'Пробный результат виден только тебе.':'Результат доступен руководству.')+'</p>'+btn('К программе','nav','catalog','secondary')+'</section><details><summary>Разбор ответов</summary>'+result.review.map((q,i)=>reviewQuestion(q,q.answer,i)).join('')+'</details>';
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
 if(b.dataset.action==='recert-start'){
  b.disabled=true;
  try{recert=await api('recertification/start','POST',{mode:b.dataset.id||'practice'});recertIndex=Math.max(0,recert.answers.findIndex(a=>!a));recertRender()}catch(err){error(err)}finally{b.disabled=false}
 }
 if(b.dataset.action==='recert-results'){
  b.disabled=true;
  try{const rows=await api('recertification/results');$('#app').innerHTML='<h1>Переаттестация официантов</h1>'+btn('Назад','nav','team','secondary')+(rows.map(r=>'<section class="card"><h2>'+esc(r.name)+'</h2><p>'+esc(r.restaurant)+' · '+esc(new Date(r.created_at).toLocaleString('ru-RU'))+'</p><p>'+(r.submitted_at?r.score+'% · '+(r.passed?'Сдано':'Не сдано'):'В процессе')+'</p></section>').join('')||'<p>Попыток пока нет.</p>')}catch(err){error(err)}finally{b.disabled=false}
 }
});

document.addEventListener('click',async e=>{
 const b=e.target.closest('[data-action="recert-assign-open"]');if(!b)return;
 b.disabled=true;
 try{
  const staff=(await api('team')).filter(s=>s.active&&s.role==='waiter');
  $('#app').innerHTML='<h1>Назначить переаттестацию</h1>'+btn('Назад','nav','team','secondary')+'<p>40 вопросов из всех семи разделов. Сначала сотрудник проверяет себя, затем проходит официально. Повторы не ограничены.</p><form id="recert-assign-form" class="card"><label>Официант<select name="staff_id" required>'+staff.map(s=>'<option value="'+s.id+'">'+esc(s.name)+' · '+esc(s.restaurant)+'</option>').join('')+'</select></label><button '+(!staff.length?'disabled':'')+'>Назначить</button><p id="recert-assigned-status" role="status"></p></form>';
  $('#recert-assign-form').onsubmit=async ev=>{
   ev.preventDefault();const form=ev.target,submit=form.querySelector('button');submit.disabled=true;
   try{await api('recertification/assign','POST',{staff_id:Number(new FormData(form).get('staff_id'))});$('#recert-assigned-status').textContent='Назначено. Сотрудник увидит обязательную переаттестацию на главной и в программе.'}catch(err){error(err)}finally{submit.disabled=false}
  };
 }catch(err){error(err)}finally{b.disabled=false}
});
