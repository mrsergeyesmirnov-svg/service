/* MOJO final: eight manager-selected, approved menu sections. */
const finalSlots=[
 ["rolls","Роллы"],["asia","Азия"],["salads","Салаты"],
 ["appetizers","Закуски"],["soups","Супы"],["hot","Горячее"],
 ["grill","Гриль"],["desserts","Десерты"]
];
let finalStatus=null,finalIndex=0,finalAnswers=[],finalRequest="",finalBusy=false;

async function configureMenuFinal(){
 const [courses,config]=await Promise.all([api("courses"),api("menu-final/config")]);
 const options=courses.filter(c=>c.published&&!c.archived&&c.reviewed_dish_signature&&!c.recipe_changed);
 $("#app").innerHTML='<h1>Итоговый экзамен MOJO</h1>'+
 '<section class="card"><h2>Состав программы</h2><p>Укажи по одному утверждённому курсу для каждого раздела. '+
 'Никаких автоматических догадок по названиям. Экзамен откроется стажёру только после успешного контроля во всех восьми курсах.</p>'+
 '<form id="menu-final-config">'+finalSlots.map(([key,label])=>
 '<label>'+label+'<select name="'+key+'" required>'+
 '<option value="">Выбери утверждённый курс…</option>'+
 options.map(c=>'<option value="'+c.id+'" '+
 (config.slots?.[key]===c.id?'selected':'')+'>'+
 esc(c.title)+' · #'+c.id+'</option>').join("")+'</select></label>').join("")+
 '<label>Проходной балл (%)<input type="number" name="pass_score" min="70" max="100" required value="'+config.pass_score+'"></label>'+
 '<label><input type="checkbox" name="confirmed" required> Я проверил соответствие всех восьми курсов реальной программе MOJO.</label>'+
 '<button type="submit" class="lime-action">Сохранить программу экзамена</button>'+
 '<p role="status" id="final-config-status"></p></form></section>'+
 btn("К программам","nav","courses","secondary");
 $("#menu-final-config").onsubmit=async e=>{
  e.preventDefault();const form=e.target,button=form.querySelector('[type=submit]');
  const fd=new FormData(form),slots={};
  for(const [key] of finalSlots)slots[key]=Number(fd.get(key));
  if(new Set(Object.values(slots)).size!==finalSlots.length){
   $("#final-config-status").textContent="Нужны восемь разных курсов.";return;
  }
  button.disabled=true;
  try{
   const result=await api("menu-final/config","POST",{
    slots,pass_score:Number(fd.get("pass_score")),confirmed:true
   });
   $("#final-config-status").textContent="Готово: связаны "+result.courses+
     " курсов. В финальном экзамене "+result.questions+" вопросов. Стажёры пока видят его только после сдачи восьми контролей.";
  }catch(err){$("#final-config-status").textContent=err.message||String(err)}
  finally{button.disabled=false}
 };
}

async function openMenuFinal(){
 finalStatus=await api("menu-final/status");
 finalAnswers=[];finalIndex=0;finalRequest=crypto.randomUUID();
 renderMenuFinal();
}
function renderMenuFinal(){
 const st=finalStatus;
 const back=btn("К программе","nav","catalog","secondary");
 if(!st.configured){
  $("#app").innerHTML='<h1>Итоговый экзамен</h1><div class="card"><h2>Программа на проверке</h2>'+
  '<p>Менеджер ещё не связал семь разделов меню и десерты в экзамен.</p>'+back+'</div>';return;
 }
 if(st.passed){
  $("#app").innerHTML='<h1>Итоговый экзамен</h1><div class="card"><h2>Экзамен сдан</h2>'+
  '<p>Результат сохранён. Следующий этап — очная сдача меню с шефом. Онлайн-экзамен не является допуском к сменам.</p>'+
  back+'</div>';return;
 }
 if(!st.ready){
  $("#app").innerHTML='<h1>Итоговый экзамен</h1><div class="card"><h2>Пока закрыт</h2>'+
  '<p>Сначала пройди промежуточную и контрольную проверки во всех восьми разделах.</p>'+
  '<p><strong>Осталось сдать:</strong></p><ul>'+
  st.missing.map(name=>'<li>'+esc(name)+'</li>').join("")+'</ul>'+back+'</div>';return;
 }
 const qs=st.questions,q=qs[finalIndex];
 if(!q)return;
 $("#app").innerHTML='<div class="lesson-top">'+back+
 '<div><strong>Итоговый экзамен по меню и десертам</strong><small>50 открытых вопросов</small></div></div>'+
 '<progress max="'+qs.length+'" value="'+(finalIndex+1)+'"></progress>'+
 '<p class="muted">Вопрос '+(finalIndex+1)+' из '+qs.length+'</p>'+
 '<form id="menu-final-form" class="card"><h1>'+esc(q.question)+'</h1>'+
 questionInput(q,"answer",finalAnswers[finalIndex])+
 '<div class="actions">'+(finalIndex?btn("← Назад","menu-final-prev","","secondary"):"")+
 '<button type="submit" class="lime-action">'+
 (finalIndex===qs.length-1?"Сдать экзамен":"Следующий вопрос →")+'</button></div>'+
 '<p id="menu-final-message" role="status"></p></form>';
 if(finalIndex)$("#menu-final-form [data-action]").type="button";
 $("#menu-final-form").onsubmit=async e=>{
  e.preventDefault();if(finalBusy)return;
  finalAnswers[finalIndex]=readAnswer(q,new FormData(e.target),"answer");
  if(finalIndex<qs.length-1){finalIndex++;renderMenuFinal();return}
  const b=e.target.querySelector('[type=submit]');b.disabled=true;finalBusy=true;
  $("#menu-final-message").textContent="Проверяем и сохраняем ответы…";
  try{
   const result=await api("menu-final/submit","POST",{
    request_id:finalRequest,answers:finalAnswers
   });
   showFinalResult(result);
  }catch(err){b.disabled=false;$("#menu-final-message").textContent="Ответы сохранены на экране. Повтори отправку.";error(err)}
  finally{finalBusy=false}
 };
 window.scrollTo(0,0);
}
function showFinalResult(result){
 $("#app").innerHTML='<h1>Результат итогового экзамена</h1>'+
 '<section class="card result-card"><h2>'+result.score+'%</h2>'+
 '<p>'+(result.passed?'Экзамен сдан. Следующий этап — очная проверка с шефом.':
 'Экзамен пока не сдан. Повтори слабые темы и попробуй ещё раз.')+'</p>'+
 '<p class="muted">Проходной балл: '+finalStatus.pass_score+'%. Онлайн-сдача не заменяет очную аттестацию.</p>'+
 btn("К программе","nav","catalog","secondary")+
 (result.passed?'':btn("Повторить экзамен","menu-final-open","","lime-action"))+
 '</section><details class="card lesson-extra"><summary>Разбор вопросов</summary>'+
 (result.review||[]).map((q,i)=>reviewQuestion(q,q.answer,i)).join("")+'</details>';
 window.scrollTo(0,0);
}
document.addEventListener("click",async e=>{
 const b=e.target.closest("[data-action]");if(!b)return;
 const action=b.dataset.action;
 if(!["menu-final-config","menu-final-open","menu-final-prev"].includes(action))return;
 b.disabled=true;
 try{
  if(action==="menu-final-config")await configureMenuFinal();
  if(action==="menu-final-open")await openMenuFinal();
  if(action==="menu-final-prev"){
   const f=document.querySelector("#menu-final-form");
   if(f)finalAnswers[finalIndex]=readAnswer(finalStatus.questions[finalIndex],new FormData(f),"answer");
   finalIndex=Math.max(0,finalIndex-1);renderMenuFinal();
  }
 }catch(err){error(err)}finally{b.disabled=false}
});
