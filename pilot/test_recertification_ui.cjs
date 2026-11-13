const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const root={innerHTML:''},listeners=[];
let requests=[];
const ctx={console,FormData,window:{scrollTo(){}},document:{addEventListener(t,fn){listeners.push(fn)}},
 $:()=>root,esc:String,btn:(label,action,id)=>`<button data-action="${action}" data-id="${id}">${label}</button>`,
 reviewQuestion:()=>'<article>review</article>',error(e){throw e},
 api:async(...args)=>{requests.push(args);return requests.length===1?progress:complete}};
const progress={id:'attempt',questions:[{},{}],submitted:false,locked:true,evaluation:{graded:1,state:'grading'}};
const complete={...progress,submitted:true,score:null,passed:null,review:[],pass_score:80,
 evaluation:{graded:2,state:'review',needs_review:true,provisional_score:50,score_upper:100}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('recertification.js','utf8'),ctx);
(async()=>{
 vm.runInContext('recert='+JSON.stringify({...progress,evaluation:{graded:0}}),ctx);
 await ctx.recertCheck();
 assert.equal(requests.length,2);assert.equal(requests[0][3],90000);
 assert.match(root.innerHTML,/Нужна проверка менеджером/);
 assert.match(root.innerHTML,/50–100%/);assert.doesNotMatch(root.innerHTML,/null%|Не сдано/);
 ctx.api=async()=>{throw Error('unavailable')};
 await ctx.recertCheck();assert.match(root.innerHTML,/Ответы сохранены/);assert.match(root.innerHTML,/Продолжить проверку/);
 assert(!vm.runInContext('recertBusy',ctx));
 ctx.recertOutcome({...complete,score:75,passed:false,evaluation:{needs_review:false}});
 assert.match(root.innerHTML,/75%/);assert.match(root.innerHTML,/Не сдано/);
 console.log('Semantic recertification progress, provisional result and retry UI: OK');
})().catch(e=>{console.error(e);process.exitCode=1});
