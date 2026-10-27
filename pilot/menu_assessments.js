/* Independent section assessments: never call an LLM to grade factual compositions. */
let assessmentState=null,assessmentIndex=0,assessmentAnswers=[],assessmentRequest="",assessmentBusy=false;
async function openAssessmentFlow(){
 if(!activeCourse)throw Error("Сначала открой курс");
 assessmentState=await api("menu-assessments/"+activeCourse.id);
 assessmentIndex=0;
 assessmentAnswers=[];
 assessmentRequest=crypto.randomUUID();
 renderAssessment();
}
function assessmentHeader(){
 return studyHeader("Проверка знаний")+
 '<div class="lesson-stage"><span>1 · Изучение</span><span>2 · Карточки</span>'+
 '<span class="stage-active">3 · Проверка</span><span>4 · Практика</span></div>';
}
function renderAssessment(){
 const st=assessmentState;
 if(!st)return;
 if(!st.all_read){
  $("#app").innerHTML=assessmentHeader()+'<section class="card"><h1>Сначала изучи раздел</h1>'+
  '<p>Пройди все учебные карточки. После этого откроется промежуточный тест.</p>'+
  btn("К материалам","assess-review","","secondary")+'</section>';return;
 }
 if(st.control_passed){
  $("#app").innerHTML=assessmentHeader()+'<section class="card"><h1>Раздел сдан</h1>'+
  '<p>Промежуточная и контрольная проверки сохранены отдельно. Составы можно повторять в любое время.</p>'+
  btn("Повторить учебные карточки","assess-review","","secondary")+
  btn("К программе","nav","catalog","lime-action")+'</section>';return;
 }
 const q=st.questions[assessmentIndex];
 if(!q){
  $("#app").innerHTML=assessmentHeader()+'<section class="card"><h1>Проверка не готова</h1>'+
  '<p>Вопросы ещё не утверждены. Обратись к менеджеру.</p>'+
  btn("К материалам","assess-review","","secondary")+'</section>';return;
 }
 const stage=st.next_stage==="control"?"Контрольная проверка всего раздела":"Промежуточный тест";
 $("#app").innerHTML=assessmentHeader()+
 '<div class="card assessment-instructions"><strong>'+stage+'</strong>'+
 '<p>'+(st.next_stage==="control"?
   "Перечисли состав каждого блюда без подсказок. Можно вернуться к материалам и повторить их.":
   "Проверь знание ингредиентов разных блюд. Вопросы составлены только из утверждённых ТТК.")+'</p></div>'+
 '<p class="muted">Вопрос '+(assessmentIndex+1)+' из '+st.questions.length+'</p>'+
 '<progress max="'+st.questions.length+'" value="'+(assessmentIndex+1)+'"></progress>'+
 '<form id="assessment-form" class="card assessment-question"><h1>'+esc(q.question)+'</h1>'+
 questionInput(q,"answer",assessmentAnswers[assessmentIndex])+
 '<div class="actions">'+(assessmentIndex?btn("← Назад","assess-prev","","secondary"):"")+
 '<button type="submit" class="lime-action">'+(assessmentIndex===st.questions.length-1?"Сохранить результат":"Следующий вопрос →")+'</button></div>'+
 '<p id="assessment-message" role="status"></p></form>'+
 btn("Повторить уроки","assess-review","","secondary");
 if(assessmentIndex)$("#assessment-form [data-action]").type="button";
 $("#assessment-form").onsubmit=async e=>{
  e.preventDefault();if(assessmentBusy)return;
  assessmentAnswers[assessmentIndex]=readAnswer(q,new FormData(e.target),"answer");
  if(assessmentIndex<st.questions.length-1){
   assessmentIndex++;renderAssessment();return;
  }
  assessmentBusy=true;const button=e.target.querySelector("button[type=submit]");
  button.disabled=true;$("#assessment-message").textContent="Сохраняем ответы…";
  try{
   const result=await api("menu-assessments/"+activeCourse.id+"/"+st.next_stage+"/submit",
    "POST",{request_id:assessmentRequest,answers:assessmentAnswers});
   renderAssessmentResult(result);
  }catch(err){
   button.disabled=false;$("#assessment-message").textContent="Ответы остались на экране — повтори отправку.";
   error(err);
  }finally{assessmentBusy=false}
 };
 window.scrollTo(0,0);
}
function renderAssessmentResult(result){
 const stage=result.stage==="control"?"Контрольный тест":"Промежуточный тест";
 $("#app").innerHTML=assessmentHeader()+
 '<section class="card result-card"><h1>'+stage+'</h1>'+
 '<strong class="assessment-score">'+result.score+'%</strong>'+
 '<p>'+(result.passed?"Результат сохранён. Этап сдан.":"Не сдано. Можно повторить учебные карточки и попробовать ещё раз.")+'</p>'+
 '<p class="muted">Проходной балл: '+assessmentState.pass_score+'%. Очную сдачу подтверждает руководитель.</p>'+
 '<div class="actions">'+(result.passed?
 btn("Продолжить →","assess-next","","lime-action"):
 btn("Повторить тест","assess-retry","","lime-action"))+
 btn("Повторить материал","assess-review","","secondary")+'</div></section>'+
 '<details class="card lesson-extra"><summary>Разбор ответов</summary>'+
 (result.review||[]).map((q,i)=>reviewQuestion(q,q.answer,i)).join("")+'</details>';
 window.scrollTo(0,0);
}
document.addEventListener("click",async e=>{
 const b=e.target.closest("[data-action]");if(!b)return;
 const action=b.dataset.action;
 if(!["assessments-open","assess-next","assess-retry","assess-prev","assess-review"].includes(action))return;
 b.disabled=true;
 try{
  if(action==="assessments-open"||action==="assess-next"||action==="assess-retry")await openAssessmentFlow();
  if(action==="assess-prev"){
   const form=document.querySelector("#assessment-form");
   if(form)assessmentAnswers[assessmentIndex]=readAnswer(assessmentState.questions[assessmentIndex],new FormData(form),"answer");
   assessmentIndex=Math.max(0,assessmentIndex-1);renderAssessment();
  }
  if(action==="assess-review")showChapter();
 }catch(err){error(err)}finally{b.disabled=false}
});
