'use strict';
// Wine recall is intentionally separate from examinations and AI grading.
let wineQueue=[],wineFlipped=false,wineData=null,wineEditorId=null,wineEditorTitle='',wineDraft=[],wineReadOnly=false;

async function openWinePractice(repeatAll=false){
 if(!activeCourse)throw Error('Сначала открой учебный курс');
 wineData=await api('wine-cards/'+activeCourse.id);
 activeCourse.wine=wineData;
 wineQueue=wineData.pairs.filter(p=>repeatAll||wineData.ratings[p.id]!=='know');
 wineFlipped=false;
 renderWinePractice();
}

function renderWinePractice(){
 const c=activeCourse,all=wineData?.pairs||[],ratings=wineData?.ratings||{};
 const known=all.filter(p=>ratings[p.id]==='know').length;
 if(!all.length){
  $('#app').innerHTML=studyHeader('Карточки вина')+
   '<section class="card"><h1>Карточки пока не добавлены</h1>'+
   '<p>Менеджер ещё не подготовил проверенную винную карту для этого курса.</p>'+
   btn('Вернуться к курсу','wine-return','','secondary')+'</section>';return;
 }
 if(!wineQueue.length){
  $('#app').innerHTML=studyHeader('Карточки вина')+
   '<section class="card wine-finished"><span class="eyebrow">ПОВТОРЕНИЕ</span><h1>Карточки пройдены</h1>'+
   '<p>Отмечено «Знаю»: '+known+' из '+all.length+'. Это тренировка памяти, не экзамен и не допуск к смене.</p>'+
   '<div class="actions">'+btn('Повторить все','wine-repeat','','secondary')+
   btn('Перейти к тесту','wine-continue','','lime-action')+'</div></section>'+
   btn('К курсу','wine-return','','secondary');window.scrollTo(0,0);return;
 }
 const p=wineQueue[0];
 const details=wineFlipped?p.answer.map(([key,val])=>'<div class="wine-fact"><span>'+esc(key)+'</span><strong>'+esc(val)+'</strong></div>').join(''):
  '<div class="wine-question">'+esc(p.prompt)+'</div>';
 const direction=p.direction==='forward'?'Название → сорт, страна, регион':'Сорт, страна, регион → название';
 $('#app').innerHTML=studyHeader('Карточки вина')+
  '<div class="lesson-stage"><span>1 · Изучение</span><span class="stage-active">2 · Карточки</span><span>3 · Тест</span><span>4 · Практика</span></div>'+
  '<div class="row wine-stats"><strong>Знаю: '+known+' / '+all.length+'</strong><span>В работе: '+wineQueue.length+'</span></div>'+
  '<progress max="'+all.length+'" value="'+known+'" aria-label="Изучено карточек '+known+' из '+all.length+'"></progress>'+
  '<div class="wine-caption">'+esc(direction)+'</div>'+
  '<button type="button" class="wine-flip-card" data-action="wine-flip" aria-expanded="'+wineFlipped+'">'+
   '<span class="wine-card-hint">'+(wineFlipped?'Ответ':'Попробуй вспомнить ответ')+'</span>'+
   details+
   '<span class="wine-card-foot">'+(wineFlipped?'Нажми, чтобы скрыть ответ':'Показать ответ ↻')+'</span></button>'+
  (wineFlipped?'<p class="muted wine-source">Источник: '+esc(p.source)+'</p>'+
   '<div class="wine-rating-actions">'+btn('Повторить','wine-rate','repeat','secondary')+
   btn('Трудно','wine-rate','hard','secondary')+
   btn('Знаю','wine-rate','know','lime-action')+'</div>':
   '<p class="muted wine-instruction">Сначала ответь по памяти, затем переверни карточку и оцени себя.</p>')+
  '<div class="actions wine-leave">'+btn('К уроку','wine-return','','secondary')+
  btn('К тесту','wine-continue','','secondary')+'</div>'+
  '<p role="status" id="wine-status" class="muted"></p>';
 window.scrollTo(0,0);
}

async function rateWine(rating){
 if(!wineFlipped||!wineQueue.length)throw Error('Сначала открой ответ на карточке');
 const p=wineQueue[0];
 await api('wine-cards/'+activeCourse.id+'/rating','POST',{id:p.id,rating});
 wineData.ratings[p.id]=rating;
 wineQueue.shift();
 if(rating!=='know')wineQueue.push(p);
 wineFlipped=false;renderWinePractice();
}

async function openWineEditor(cid){
 if(!isManager())throw Error('Доступно только менеджеру');
 const data=await api('wine-cards/'+cid);
 wineEditorId=cid;wineEditorTitle=data.title;wineReadOnly=data.published;
 wineDraft=data.cards.map(c=>({...c}));
 renderWineEditor();
}

function collectWineDraft(){
 const form=$('#wine-editor-form');if(!form)return;
 wineDraft=[...form.querySelectorAll('[data-wine-index]')].map(row=>{
  const card={};
  for(const key of ['name','grape','country','region','source'])
   card[key]=row.querySelector('[name='+key+']').value.trim();
  return card;
 });
}

function renderWineEditor(){
 const disabled=wineReadOnly?' disabled':'';
 $('#app').innerHTML=btn('← К программам','nav','courses','secondary')+
  '<h1>Карточки вина</h1><p class="muted">'+esc(wineEditorTitle)+'</p>'+
  '<div class="card"><p>Каждая позиция: название, сорт, страна, регион и источник. После сохранения система создаёт карточки в обе стороны.</p>'+
  '<p class="muted">Если несколько вин имеют одинаковые сорт, страну и регион, обратная карточка покажет все подходящие названия. Система ничего не придумывает.</p>'+
  (wineReadOnly?'<p><strong>Опубликованная версия закрыта для изменений.</strong> Для обновления винной карты создай новый курс и заново утверди карточки.</p>':'<p><strong>Перед сохранением сверь каждую позицию с действующей винной картой MOJO.</strong></p>')+'</div>'+
  '<form id="wine-editor-form">'+wineDraft.map((card,i)=>
   '<section class="card wine-editor-row" data-wine-index="'+i+'">'+
   '<div class="row"><strong>Вино '+(i+1)+'</strong>'+
   (!wineReadOnly?btn('Удалить','wine-remove',i,'secondary'):'')+'</div>'+
   '<label>Название в карте<input name="name" maxlength="180" required'+disabled+' value="'+esc(card.name)+'" placeholder="Точное название из винной карты"></label>'+
   '<label>Сорт (или ассамбляж)<input name="grape" maxlength="140" required'+disabled+' value="'+esc(card.grape)+'"></label>'+
   '<div class="wine-form-grid"><label>Страна<input name="country" maxlength="100" required'+disabled+' value="'+esc(card.country)+'"></label>'+
   '<label>Регион<input name="region" maxlength="140" required'+disabled+' value="'+esc(card.region)+'"></label></div>'+
   '<label>Источник / редакция винной карты<input name="source" maxlength="260" required'+disabled+' value="'+esc(card.source)+'" placeholder="Документ и дата редакции"></label>'+
   '</section>').join('')+'</form>'+
   (!wineReadOnly?'<div class="actions">'+btn('Добавить вино','wine-add','','secondary')+
   btn('Сверено с источником — сохранить','wine-save','','lime-action')+'</div>':'')+
   btn('К программам','nav','courses','secondary')+
   '<p class="muted">До 80 позиций на курс. История экзаменов не изменяется.</p>';
 $('#wine-editor-form').querySelectorAll('button').forEach(b=>b.type='button');
}

async function saveWineEditor(){
 collectWineDraft();
 if(wineDraft.some(c=>Object.values(c).some(v=>!v)))throw Error('Заполни все пять полей каждой винной позиции');
 if(!wineDraft.length&&!confirm('Удалить все карточки из этого черновика?'))return;
 await api('wine-cards/'+wineEditorId,'PUT',{cards:wineDraft,reviewed:true});
 wineEditorId=null;view='courses';await render();
}

// Keep this module independent of older ingredient quizzes and manager handlers.
document.addEventListener('click',async e=>{
 const b=e.target.closest('[data-action]');if(!b)return;
 const {action,id}=b.dataset;
 if(!['wine-practice','wine-flip','wine-rate','wine-repeat','wine-return','wine-continue',
       'wine-editor','wine-add','wine-remove','wine-save'].includes(action))return;
 b.disabled=true;
 try{
  if(action==='wine-practice')await openWinePractice();
  if(action==='wine-repeat')await openWinePractice(true);
  if(action==='wine-flip'){wineFlipped=!wineFlipped;renderWinePractice()}
  if(action==='wine-rate')await rateWine(id);
  if(action==='wine-return')showChapter();
  if(action==='wine-continue'){
   if(activeCourse.questions.length&&!activeCourse.history.some(t=>t.passed)){
    quizIndex=0;quizAnswers=[];quizRequest=crypto.randomUUID();showStudyQuiz();
   }else showStudyComplete();
  }
  if(action==='wine-editor')await openWineEditor(Number(id));
  if(action==='wine-add'){
   collectWineDraft();
   if(wineDraft.length>=80)throw Error('Не больше 80 винных позиций в одном курсе');
   wineDraft.push({name:'',grape:'',country:'',region:'',source:wineDraft.at(-1)?.source||''});
   renderWineEditor();
  }
  if(action==='wine-remove'){
   collectWineDraft();wineDraft.splice(Number(id),1);renderWineEditor();
  }
  if(action==='wine-save')await saveWineEditor();
 }catch(err){error(err)}finally{b.disabled=false}
});
