'use strict';
// MOJO menu: Quizlet-style name -> composition and composition -> name.
// All answers are taken from the published, manager-reviewed dish snapshot.
let menuDeck=null, menuQueue=[],menuFlipped=false,menuPending=false;

async function openMenuPractice(repeatAll=false){
 if(!activeCourse)throw Error('Сначала открой курс');
 menuDeck=await api('menu-cards/'+activeCourse.id);
 activeCourse.menu=menuDeck;
 menuQueue=(menuDeck.pairs||[]).filter(p=>repeatAll||menuDeck.ratings[p.id]!=='know');
 menuFlipped=false;
 renderMenuPractice();
}
function renderMenuPractice(){
 const c=activeCourse,all=menuDeck?.pairs||[],ratings=menuDeck?.ratings||{};
 const known=all.filter(p=>ratings[p.id]==='know').length;
 if(!all.length){
  $('#app').innerHTML=studyHeader('Карточки меню')+
    '<section class="card"><h1>Карточки пока не подтверждены</h1>'+
    '<p>Менеджер должен сверить составы с ТТК, проверить вопросы и опубликовать курс. Непроверенные ингредиенты не показываются как правильные ответы.</p>'+
    btn('Вернуться к уроку','menu-return','','secondary')+'</section>';
  return;
 }
 if(!menuQueue.length){
  $('#app').innerHTML=studyHeader('Карточки меню')+
   '<section class="card wine-finished"><span class="eyebrow">ЗАКРЕПЛЕНИЕ</span><h1>Карточки пройдены</h1>'+
   '<p>Отмечено «Знаю»: '+known+' из '+all.length+'. Это повторение по памяти, а не финальная аттестация.</p>'+
   '<div class="actions">'+btn('Повторить все','menu-repeat','','secondary')+
   btn('Перейти к тесту','menu-continue','','lime-action')+'</div></section>'+
   btn('К уроку','menu-return','','secondary');window.scrollTo(0,0);return;
 }
 const pair=menuQueue[0];
 const facts=pair.answer.map(([label,value])=>'<div class="wine-fact"><span>'+esc(label)+'</span><strong>'+esc(value)+'</strong></div>').join('');
 const direction=pair.direction==='forward'?'Название → состав':'Состав → название';
 $('#app').innerHTML=studyHeader('Карточки меню')+
  '<div class="lesson-stage"><span>1 · Изучение</span><span class="stage-active">2 · Карточки</span><span>3 · Тест</span><span>4 · Практика</span></div>'+
  '<div class="row wine-stats"><strong>Знаю: '+known+' / '+all.length+'</strong><span>В работе: '+menuQueue.length+'</span></div>'+
  '<progress max="'+all.length+'" value="'+known+'" aria-label="Изучено карточек '+known+' из '+all.length+'"></progress>'+
  '<div class="wine-caption">'+direction+'</div>'+
  '<button type="button" class="wine-flip-card" data-action="menu-flip" aria-expanded="'+menuFlipped+'">'+
  '<span class="wine-card-hint">'+(menuFlipped?'Ответ':'Вспомни без подсказок')+'</span>'+
  (menuFlipped?facts:'<div class="wine-question">'+esc(pair.prompt)+'</div>')+
  '<span class="wine-card-foot">'+(menuFlipped?'Скрыть ответ':'Показать ответ ↻')+'</span></button>'+
  (menuFlipped?'<p class="muted wine-source">Источник: '+esc(pair.source)+'</p>'+
   '<div class="wine-rating-actions">'+btn('Повторить','menu-rate','repeat','secondary')+
   btn('Трудно','menu-rate','hard','secondary')+btn('Знаю','menu-rate','know','lime-action')+'</div>':
   '<p class="muted wine-instruction">Сначала попробуй ответить, затем переверни карточку и оцени себя.</p>')+
  '<div class="actions wine-leave">'+btn('К уроку','menu-return','','secondary')+
  btn('К тесту','menu-continue','','secondary')+'</div>'+
  '<p role="status" id="menu-status" class="muted"></p>';
 window.scrollTo(0,0);
}
async function rateMenu(rating){
 if(menuPending)return;
 if(!menuFlipped||!menuQueue.length)throw Error('Сначала переверни карточку');
 menuPending=true;const p=menuQueue[0];
 const controls=[...document.querySelectorAll('[data-action^="menu-"]')];
 controls.forEach(x=>x.disabled=true);
 try{
  await api('menu-cards/'+activeCourse.id+'/rating','POST',{id:p.id,rating});
  menuDeck.ratings[p.id]=rating;
  menuQueue.shift();
  if(rating!=='know')menuQueue.push(p);
  menuFlipped=false;renderMenuPractice();
 }finally{menuPending=false;controls.forEach(x=>x.disabled=false)}
}
document.addEventListener('click',async e=>{
 const b=e.target.closest('[data-action]');if(!b)return;
 const {action,id}=b.dataset;
 if(!['menu-practice','menu-repeat','menu-flip','menu-rate','menu-return','menu-continue'].includes(action))return;
 b.disabled=true;
 try{
  if(action==='menu-practice')await openMenuPractice();
  if(action==='menu-repeat')await openMenuPractice(true);
  if(action==='menu-flip'){menuFlipped=!menuFlipped;renderMenuPractice()}
  if(action==='menu-rate')await rateMenu(id);
  if(action==='menu-return')showChapter();
  if(action==='menu-continue')await openAssessmentFlow();
 }catch(err){error(err)}finally{b.disabled=false}
});
