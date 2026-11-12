const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('pilot/pilot.js','utf8');
const start=source.indexOf('(async()=>{try{const tg=');
const end=source.indexOf('\n\nfunction previewCourse',start);
assert(start>=0&&end>start);
async function run(initData){
 let ready=0,request;
 const app={innerHTML:''};
 const context={window:{Telegram:{WebApp:{initData,ready(){ready++},expand(){}}}},
 $:()=>app,esc:String,Error,URLSearchParams,location:{search:'?invite='+ 'A'.repeat(32)},
 api:async(path,method,body)=>{request={path,body};throw Error('Заявка ожидает одобрения')},
 isManager:()=>false};
 await vm.runInNewContext(source.slice(start,end),context);
 assert.equal(ready,1,'Telegram must be ready even without initData');
 assert(!app.innerHTML.includes('Подключаемся'));
 if(initData){assert.equal(request.body.invite,'A'.repeat(32));assert(app.innerHTML.includes('Заявка ожидает одобрения'))}
 else assert.equal(request,undefined);
}
(async()=>{await run('');await run('signed-test-data');console.log('Telegram readiness and invitation forwarding: OK')})().catch(e=>{console.error(e);process.exit(1)});
