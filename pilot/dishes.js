/* MOJO editable dish cards. Existing Telegram session and Academy API. */
let dishCards=[],dishFilter="",dishPageIndex=0,dishImageUrls=new Map();
const dishAdmin=()=>["manager","local"].includes(user?.role);
function dishPhoto(id,cls=""){return '<div class="dish-photo '+cls+'" data-dish-picture="'+id+'"><span>Фото блюда</span></div>'}
async function showDishPhotos(){
 for(const node of document.querySelectorAll("[data-dish-picture]")){
  const id=Number(node.dataset.dishPicture);
  if(!dishCards.find(x=>x.id===id)?.has_photo)continue;
  if(!dishImageUrls.has(id)){
   try{
    const r=await fetch("/api/dishes/"+id+"/photo",{headers:{Authorization:"Bearer "+token}});
    if(!r.ok)continue;
    dishImageUrls.set(id,URL.createObjectURL(await r.blob()));
   }catch(e){continue}
  }
  node.innerHTML='<img alt="Фото блюда" loading="lazy" src="'+dishImageUrls.get(id)+'">';
 }
}
function dishListMarkup(){
 const query=dishFilter.toLocaleLowerCase("ru");
 const found=dishCards.filter(x=>(x.title+" "+x.section+" "+x.ingredients.join(" ")).toLocaleLowerCase("ru").includes(query));
 const items=found.slice(dishPageIndex*24,(dishPageIndex+1)*24);
 return '<p class="dish-summary">'+found.length+' карточек'+(dishAdmin()?' · '+dishCards.filter(x=>!x.published).length+' черновиков':'')+'</p>'+
 '<div class="dish-grid">'+(items.map(c=>'<button class="dish-tile" data-action="dish-detail" data-id="'+c.id+'">'+
    dishPhoto(c.id)+'<strong>'+esc(c.title)+'</strong><small>'+esc(c.section)+' · стр. '+esc(c.source_page||"—")+'</small>'+
    (dishAdmin()?'<span class="dish-badge '+(c.published?"live":"")+'">'+(c.published?"Опубликовано":"Черновик")+'</span>':"")+
    '</button>').join("")||"<p>Карточки не найдены.</p>")+'</div>'+
 '<div class="dish-pages">'+(dishPageIndex?btn("← Назад","dish-prev","","secondary"):"")+
 ((dishPageIndex+1)*24<found.length?btn("Показать ещё →","dish-next","","secondary"):"")+'</div>';
}
async function dishesPage(){
 const root=$("#app");root.innerHTML="<p>Загружаем карточки меню…</p>";
 dishCards=await api("dishes");
 root.innerHTML='<div class="lesson-top">'+btn("← Курсы","nav","catalog","secondary")+
 '<div><h1>Карточки блюд</h1><small>MOJO · каталог, состав и особенности подачи</small></div></div>'+
 (dishAdmin()?'<section class="card dish-import"><h2>Загрузка PDF станционок</h2>'+
 '<p>Фото, составы и описания появятся как <b>черновики</b>. Перед публикацией каждую позицию нужно проверить.</p>'+
 '<form id="dish-import-form"><input type="file" name="pdf" accept="application/pdf,.pdf" required>'+
 '<button type="submit">Загрузить PDF</button></form><p id="dish-import-status" role="status"></p>'+
 btn("Добавить блюдо вручную","dish-create","","secondary")+'</section>':"")+
 '<label>Поиск по названию и ингредиентам<input type="search" id="dish-search" value="'+esc(dishFilter)+'" placeholder="Например: песто, лосось, рамен"></label>'+
 '<div id="dish-list">'+dishListMarkup()+'</div>';
 $("#dish-search").oninput=e=>{dishFilter=e.target.value;dishPageIndex=0;paintDishList()};
 if(dishAdmin())$("#dish-import-form").onsubmit=importDishPdf;
 await showDishPhotos();
}
function paintDishList(){$("#dish-list").innerHTML=dishListMarkup();showDishPhotos()}
async function importDishPdf(e){
 e.preventDefault();
 const file=e.target.querySelector('input[name="pdf"]')?.files?.[0];if(!file)return;
 if(file.size>20_000_000){error(Error("PDF больше 20 МБ"));return}
 if(!confirm('Импортировать «'+file.name+'» как неопубликованные черновики?'))return;
 const b=e.target.querySelector("button"),status=$("#dish-import-status");
 b.disabled=true;status.textContent="Извлекаем названия, фотографии и ингредиенты…";
 const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),160000);
 try{
  const r=await fetch("/api/dishes/import",{method:"POST",headers:{Authorization:"Bearer "+token,"Content-Type":"application/pdf"},body:file,signal:controller.signal});
  const v=await r.json();if(!r.ok)throw Error(v.detail||"Ошибка импорта PDF");
  status.textContent="Добавлено "+v.created+" черновиков, пропущено повторных: "+v.skipped+".";
  dishCards=await api("dishes");dishPageIndex=0;paintDishList();
 }catch(err){status.textContent="Не удалось завершить импорт. "+(err.name==="AbortError"?"Истекло время ожидания. Проверь черновики перед повтором.":err.message)}
 finally{clearTimeout(timeout);b.disabled=false}
}
async function dishDetail(id){
 const c=dishCards.find(x=>x.id===id);if(!c)return;
 $("#app").innerHTML=btn("← Каталог","dish-list","","secondary")+
 '<article class="card dish-detail">'+dishPhoto(c.id,"wide")+
 '<span class="dish-kicker">'+esc(c.section)+' · стр. '+esc(c.source_page||"—")+'</span>'+
 '<h1>'+esc(c.title)+'</h1><h2>Ингредиенты</h2><ul>'+
 (c.ingredients.map(s=>"<li>"+esc(s)+"</li>").join("")||"<li>Не указаны</li>")+
 '</ul><h2>Описание и подача</h2><p class="dish-description">'+esc(c.description||"Описание ещё не подготовлено.")+'</p>'+
 '<p class="muted">Источник: '+esc(c.source_name||"Ручная карточка")+' · страница '+esc(c.source_page||"—")+'</p>'+
 (dishAdmin()?'<div class="dish-controls"><p class="muted">'+(c.warning?"Проверить: "+esc(c.warning):"Проверь по актуальной ТТК перед публикацией.")+'</p>'+
 btn("Редактировать","dish-edit",id,"secondary")+
 (!c.published?btn("Материал проверен — опубликовать","dish-publish",id):"")+
 btn("Удалить карточку","dish-delete",id,"secondary")+'</div>':"")+'</article>';
 await showDishPhotos();
}
async function dishEditor(id){
 const c=id?dishCards.find(x=>x.id===id):{title:"",section:"Основное меню",ingredients:[],description:""};
 if(!c)return;
 $("#app").innerHTML=btn("← Карточки","dish-list","","secondary")+
 '<h1>'+(id?"Редактировать блюдо":"Новое блюдо")+'</h1><form class="card dish-edit-form" id="dish-edit-form">'+
 (id?dishPhoto(id,"wide"):"")+
 '<label>Название<input name="title" maxlength="180" required value="'+esc(c.title)+'"></label>'+
 '<label>Раздел меню<input name="section" maxlength="100" required value="'+esc(c.section)+'"></label>'+
 '<label>Ингредиенты (по одному на строку)<textarea name="ingredients" rows="9">'+esc(c.ingredients.join("\n"))+'</textarea></label>'+
 '<label>Описание, особенности, подача<textarea name="description" rows="7" maxlength="4500">'+esc(c.description)+'</textarea></label>'+
 '<label>'+(id?"Заменить фото":"Добавить фото")+' (JPG, PNG, WebP до 4 МБ)<input type="file" id="dish-photo-file" accept="image/jpeg,image/png,image/webp"></label>'+
 '<p class="muted">После изменения опубликованная карточка станет черновиком до проверки менеджера.</p>'+
 '<button type="submit">Сохранить карточку</button></form>';
 $("#dish-edit-form").onsubmit=async e=>{
  e.preventDefault();const b=e.target.querySelector("button");b.disabled=true;
  const form=new FormData(e.target);
  const data={title:String(form.get("title")),section:String(form.get("section")),
    description:String(form.get("description")),
    ingredients:String(form.get("ingredients")).split("\n").map(x=>x.trim()).filter(Boolean)};
  try{
   const saved=await api("dishes"+(id?"/"+id:""),id?"PUT":"POST",data);
   const target=id||saved.id,photo=$("#dish-photo-file")?.files?.[0];
   if(photo){
    if(photo.size>4_000_000)throw Error("Фотография больше 4 МБ");
    const r=await fetch("/api/dishes/"+target+"/photo",{method:"PUT",headers:{Authorization:"Bearer "+token,"Content-Type":photo.type||"image/jpeg"},body:photo});
    const response=await r.json();if(!r.ok)throw Error(response.detail||"Не удалось загрузить фото");
    if(dishImageUrls.has(target)){URL.revokeObjectURL(dishImageUrls.get(target));dishImageUrls.delete(target)}
   }
   await dishesPage();
  }catch(err){error(err)}finally{b.disabled=false}
 };
 await showDishPhotos();
}
document.addEventListener("click",async e=>{
 const b=e.target.closest("[data-action]");if(!b)return;
 const {action,id}=b.dataset;
 if(!["dish-open","dish-list","dish-next","dish-prev","dish-detail","dish-edit","dish-create","dish-delete","dish-publish"].includes(action))return;
 e.preventDefault();b.disabled=true;
 try{
  if(action==="dish-open"){view="dishes";nav();await dishesPage()}
  if(action==="dish-list")await dishesPage();
  if(action==="dish-next"){dishPageIndex++;paintDishList()}
  if(action==="dish-prev"){dishPageIndex=Math.max(0,dishPageIndex-1);paintDishList()}
  if(action==="dish-detail")await dishDetail(Number(id));
  if(action==="dish-edit")await dishEditor(Number(id));
  if(action==="dish-create")await dishEditor(null);
  if(action==="dish-delete"&&confirm("Убрать блюдо из Академии? Данные сохранятся в архиве.")){await api("dishes/"+id,"DELETE");await dishesPage()}
  if(action==="dish-publish"&&confirm("Вы проверили фотографию, состав и описание по действующей ТТК?")){
   await api("dishes/"+id+"/publish","POST",{reviewed:true});await dishesPage()
  }
 }catch(err){error(err)}finally{b.disabled=false}
});
