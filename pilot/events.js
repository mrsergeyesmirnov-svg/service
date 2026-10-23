// Real Academy events, shared API and authenticated identity; no sample events.
let eventCache=[];
const eventDate=value=>new Date(value).toLocaleString('ru-RU',{day:'numeric',month:'long',hour:'2-digit',minute:'2-digit',year:'numeric'});
async function eventsPage(){
  eventCache=await api('events');
  const managerial=isManager();
  let html=managerial?workspaceHeader('Мероприятия','Очные тренинги, лекции и запись сотрудников.'):
    '<span class="eyebrow">АКАДЕМИЯ MOJO</span><h1>Мероприятия</h1><p class="muted">Очные занятия и тренинги команды.</p>';
  if(managerial)html+=btn('+ Создать мероприятие','event-new','','lime-action');
  html+=eventCache.length?eventCache.map(e=>{
    const status=e.cancelled?'Отменено':e.published?'Открыта запись':'Черновик';
    const manage=managerial?'<p class="muted">Записалось: '+e.participants+' · '+status+'</p>'+
      '<div class="actions">'+(!e.published&&!e.cancelled?btn('Опубликовать','event-publish',e.id):'')+
      (!e.published&&!e.cancelled?btn('Изменить','event-edit',e.id,'secondary'):'')+
      (e.participants?btn('Участники','event-participants',e.id,'secondary'):'')+
      (!e.cancelled?btn('Отменить мероприятие','event-cancel',e.id,'secondary'):'')+'</div>':
      (e.registered?btn('Отменить запись','event-leave',e.id,'secondary'):btn('Записаться','event-join',e.id,'lime-action'));
    return '<article class="card event-card"><span class="eyebrow">'+esc(eventDate(e.starts_at))+'</span>'+
      '<h2>'+esc(e.title)+'</h2><p class="muted">'+esc(e.location)+'</p>'+
      (e.description?'<p>'+esc(e.description)+'</p>':'')+manage+'</article>';
  }).join(''):'<div class="card"><h2>Ближайших мероприятий пока нет</h2><p class="muted">Руководитель добавит тренинги и встречи. Здесь появится возможность записаться.</p></div>';
  $('#app').innerHTML=html;
}
function eventForm(item){
  if(!isManager())return;
  const formValue=item?new Date(item.starts_at).toISOString().slice(0,16):'';
  $('#app').innerHTML=workspaceHeader(item?'Редактировать мероприятие':'Новое мероприятие','Мероприятие появится у сотрудников только после публикации.')+
    '<form class="card" id="event-form">'+
    '<label>Название<input name="title" maxlength="180" required value="'+esc(item?.title||'')+'" placeholder="Например, тренинг по сервису"></label>'+
    '<label>Дата и время<input name="starts_at" type="datetime-local" required value="'+formValue+'"></label>'+
    '<label>Место<input name="location" maxlength="180" required value="'+esc(item?.location||'')+'" placeholder="MOJO Россия, учебная зона"></label>'+
    '<label>Описание<textarea name="description" maxlength="2000" placeholder="Тема, формат и подготовка">'+esc(item?.description||'')+'</textarea></label>'+
    '<button type="submit" class="lime-action">Сохранить черновик</button></form>'+
    btn('← Вернуться','event-back','','secondary');
  $('#event-form').onsubmit=async e=>{
    e.preventDefault();
    const form=e.target,button=form.querySelector('[type=submit]');button.disabled=true;
    try{
      const data=new FormData(form),d=new Date(data.get('starts_at'));
      if(Number.isNaN(d.getTime()))throw Error('Проверь дату и время');
      await api(item?'events/'+item.id:'events',item?'PUT':'POST',{
        title:data.get('title'),description:data.get('description'),
        location:data.get('location'),starts_at:d.toISOString()
      });
      await eventsPage();
    }catch(err){error(err);button.disabled=false;}
  };
}
document.addEventListener('click',async e=>{
  const b=e.target.closest('[data-action]');if(!b)return;
  const {action,id}=b.dataset;
  if(!action.startsWith('event-'))return;
  e.preventDefault();
  try{
    if(action==='event-back'){await eventsPage();return}
    if(action==='event-new'){eventForm();return}
    const ev=eventCache.find(x=>x.id===Number(id));
    if(!ev)throw Error('Мероприятие не найдено');
    if(action==='event-edit'){eventForm(ev);return}
    if(action==='event-publish'){
      if(confirm('Опубликовать и открыть запись на мероприятие?'))await api('events/'+id+'/publish','POST',{});
    }
    if(action==='event-cancel'){
      if(confirm('Отменить мероприятие? Записанные сотрудники должны быть дополнительно уведомлены.'))await api('events/'+id+'/cancel','POST',{});
    }
    if(action==='event-join')await api('events/'+id+'/signup','POST',{});
    if(action==='event-leave'){
      if(confirm('Отменить свою запись?'))await api('events/'+id+'/signup','DELETE');
    }
    if(action==='event-participants'){
      const people=await api('events/'+id+'/participants');
      $('#app').innerHTML=workspaceHeader('Участники',ev.title)+
        '<div class="card">'+(people.length?people.map(p=>'<p>'+esc(p.name)+' · '+esc(roles[p.role])+'</p>').join(''):'Записей пока нет.')+'</div>'+
        btn('← К мероприятиям','event-back','','secondary');
      return;
    }
    await eventsPage();
  }catch(err){error(err)}
});
