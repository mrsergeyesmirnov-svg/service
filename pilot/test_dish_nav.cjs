// Smoke-test dish review navigation without a browser.
const fs=require("node:fs");
const vm=require("node:vm");
const assert=require("node:assert/strict");
const source=fs.readFileSync("dishes.js","utf8");
const root={innerHTML:""},form={dataset:{},addEventListener(){}};
let clickHandler,confirmYes=false;
const buttons=(label,action,id,cls)=>'<button data-action="'+action+'" data-id="'+id+'">'+label+'</button>';
const ctx={
 console,
 document:{
   addEventListener:(name,callback)=>{if(name==="click")clickHandler=callback},
   querySelectorAll:()=>[],
   querySelector:sel=>sel==="#dish-edit-form"?form:null
 },
 user:{role:"manager"},
 $:sel=>sel==="#app"?root:sel==="#dish-edit-form"?form:null,
 esc:value=>String(value??""),
 btn:buttons,
 FormData:class {get(name){return {title:"Рамен обновлённый",section:"Супы",ingredients:"Лапша",description:"",allergens:""}[name]}},
 api:async(path,method,data)=>{
   if(path==="dishes")return cards;
   const id=Number(path.split("/")[1]),card=cards.find(c=>c.id===id);
   if(method==="PUT"){Object.assign(card,data,{published:false});return {id}}
   if(path.endsWith("/publish")){card.published=true;return {ok:true}}
   throw Error("Unexpected API: "+path);
 },
 error:err=>{throw err},confirm:()=>confirmYes,
 learningCourses:[],activeCourse:null,token:"test"
};
vm.createContext(ctx);
vm.runInContext(source,ctx,{filename:"dishes.js"});
const cards=[
 {id:1,title:"Уха",section:"Супы",ingredients:["Рыба"],description:"",source_page:1,allergens:""},
 {id:2,title:"Рамен",section:"Супы",ingredients:["Лапша"],description:"",source_page:2,allergens:""},
 {id:3,title:"Борщ",section:"Супы",ingredients:["Свёкла"],description:"",source_page:3,allergens:""},
 {id:4,title:"Ролл",section:"Роллы",ingredients:["Рис"],description:"",source_page:4,allergens:""}
];
vm.runInContext("dishCards="+JSON.stringify(cards)+';dishFilter="Супы";',ctx);
async function click(action,id){
 const button={dataset:{action,id:String(id)},disabled:false};
 await clickHandler({target:{closest:()=>button},preventDefault(){}});
}
(async()=>{
 await ctx.dishDetail(2);
 assert.match(root.innerHTML,/2 из 3/);
 assert.match(root.innerHTML,/data-action="dish-adjacent" data-id="1"/);
 assert.match(root.innerHTML,/data-action="dish-adjacent" data-id="3"/);
 assert.doesNotMatch(root.innerHTML,/data-id="4"/);
 await click("dish-adjacent",3);
 assert.match(root.innerHTML,/Борщ/);
 assert.match(root.innerHTML,/3 из 3/);
 assert.doesNotMatch(root.innerHTML,/Следующая →/);
 await ctx.dishEditor(2);
 assert.match(root.innerHTML,/Редактировать блюдо/);
 assert.match(root.innerHTML,/Описание, особенности, подача \(необязательно\)/);
 assert.match(root.innerHTML,/data-action="dish-adjacent-edit" data-id="1"/);
 form.dataset.dirty="true";
 await click("dish-adjacent-edit",1);
 assert.match(root.innerHTML,/value="Рамен"/);
 confirmYes=true;
 await click("dish-adjacent-edit",1);
 assert.match(root.innerHTML,/value="Уха"/);
 await ctx.dishEditor(2);
 form.dataset.dirty="true";
 const saveButton={disabled:false};
 form.querySelector=()=>saveButton;
 await form.onsubmit({preventDefault(){},target:form});
 assert.match(root.innerHTML,/Редактировать блюдо/);
 assert.match(root.innerHTML,/value="Рамен обновлённый"/);
 assert.match(root.innerHTML,/Карточка сохранена/);
 assert.match(root.innerHTML,/data-action="dish-adjacent-edit" data-id="3"/);
 assert.equal(form.dataset.dirty,"false");
 await click("dish-publish",2);
 assert.equal(cards[1].published,true);
 assert.match(root.innerHTML,/Карточка опубликована/);
 assert.match(root.innerHTML,/Редактировать блюдо/);
 await click("dish-adjacent-edit",3);
 assert.match(root.innerHTML,/value="Борщ"/);
 assert.doesNotMatch(root.innerHTML,/Следующая →/);
 console.log("Dish save, publish and sequential editing: OK");
})().catch(e=>{console.error(e);process.exitCode=1});
