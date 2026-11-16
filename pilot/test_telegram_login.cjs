const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(__dirname+'/pilot.js','utf8');
const bootstrap=source.slice(source.indexOf('function telegramGate('),source.indexOf('\n\nfunction previewCourse'));
async function run({invite='',tg,error}={}){
 const app={innerHTML:''},calls=[];let browser=false;
 const ctx={URLSearchParams,Boolean,Number,encodeURIComponent,window:{Telegram:{WebApp:tg}},location:{search:invite?'?invite='+invite:'',hash:''},$:()=>app,esc:s=>s,isManager:()=>false,render:async()=>{},lesson:async()=>{},browserGate:()=>{browser=true},api:async(...a)=>{calls.push(a);if(error)throw Error(error);return {token:'test',user:{}}},setTimeout,Promise};
 await vm.runInNewContext(bootstrap,ctx);
 return {app,calls,browser};
}
(async()=>{
 const token='A'.repeat(32),tg={initData:'signed',ready(){},expand(){}};
 let r=await run({invite:token,tg});assert.equal(r.calls[0][2].invite,token);assert.equal(r.browser,false);
 r=await run({tg,error:'Заявка ожидает одобрения'});assert.equal(r.browser,false);assert.match(r.app.innerHTML,/ожидает одобрения/);assert.doesNotMatch(r.app.innerHTML,/name="password"/);
 r=await run({invite:token});assert.equal(r.browser,false);assert.match(r.app.innerHTML,/start=AAAA/);
 r=await run();assert.equal(r.browser,true);
 r=await run({tg:{...tg,initDataUnsafe:{start_param:token}}});assert.equal(r.calls[0][2].invite,token);
 console.log('Telegram login: invitation, start parameter, approval error, browser separation OK');
})().catch(e=>{console.error(e);process.exit(1)});
