const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const listeners=[],panels=Array.from({length:4},(_,i)=>({hidden:i!==0}));
const tabs=panels.map((_,i)=>({dataset:{action:'lesson-tab',id:String(i)},setAttribute(k,v){this[k]=v}}));
const ctx={document:{addEventListener(event,fn){if(event==='click')listeners.push(fn)},querySelectorAll(s){return s==='[role=tabpanel]'?panels:tabs}},window:{},console,error(e){throw e},esc:x=>String(x??'').replaceAll('<','&lt;').replaceAll('>','&gt;'),dishPhoto:()=>'<div class="dish-photo"></div>'};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('learning.js','utf8'),ctx);
(async()=>{for(const i of [1,2,3,0]){for(const fn of listeners)await fn({target:{closest:()=>tabs[i]}});assert.deepEqual(panels.map(p=>p.hidden),panels.map((_,j)=>j!==i));assert.equal(tabs[i]['aria-selected'],'true');assert.equal(tabs[i].disabled,false)}console.log('All lesson tabs switch through the actual click handler');})().catch(e=>{console.error(e);process.exit(1)});

const markup=ctx.chapterBody({kind:'dish',title:'Ролл с угрём',dish_id:42,
 description:'Ролл без риса',source:'ТТК MOJO',ingredients:['Угорь','Авокадо','Соус унаги'],
 allergens:'',has_photo:true,source_page:21});
assert.match(markup,/aria-selected="true" data-action="lesson-tab" data-id="1"/);
assert.match(markup,/id="lesson-panel-0"[^>]+hidden/);
assert.match(markup,/id="lesson-panel-1"[^>]*><h2>Состав<\/h2>/);
for(const ingredient of ['Угорь','Авокадо','Соус унаги'])assert.match(markup,new RegExp('<li>'+ingredient+'</li>'));
const unfilled=ctx.chapterBody({kind:'dish',title:'Incomplete',ingredients:[],has_photo:false,source:'draft'});
assert.match(unfilled,/Состав пока не заполнен/);
assert.doesNotMatch(unfilled,/<li>Угорь<\/li>/);
console.log('Dish ingredient lesson defaults and missing data: OK');


const review=ctx.reviewQuestion({
 type:'ingredients',question:'Состав ролла',source:'Source PPTX',
 ingredients:[['Лосось'],['Соус юдзу'],['Тобико']],
 explanation:'Проверить состав',
 assessment:{recognized:1,total:3,missing:['Соус юдзу','Тобико'],
    extra:[],incomplete:[{answer:'юдзу',expected:['Соус юдзу']}]}
},'лосось юдзу',0);
assert.match(review,/Распознано: 1 из 3/);
assert.match(review,/Неполные названия/);
assert.match(review,/Соус юдзу/);
assert.match(review,/<details><summary>Сравнить ответ с эталоном/);
assert.match(review,/<details><summary>Источник/);
const input=ctx.questionInput({type:'ingredients'},'answer','лосось рис');
assert.match(input,/через пробел или запятую/);
console.log('Free-form ingredient feedback is concise and explains qualifiers: OK');
