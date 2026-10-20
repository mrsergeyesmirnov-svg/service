const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const elements=new Map();let click;const storage=new Map();
const element=()=>({innerHTML:'',textContent:'',value:'',open:false,classList:{add(){},remove(){}},showModal(){this.open=true},close(){this.open=false},scrollIntoView(){}});
const ctx={console,URLSearchParams,location:{search:''},setTimeout(){},window:{scrollTo(){}},document:{querySelector(s){if(!elements.has(s))elements.set(s,element());return elements.get(s)},addEventListener(name,fn){if(name==='click')click=fn}},localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},navigator:{}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(__dirname+'/app.js','utf8'),ctx);
const run=s=>vm.runInContext(s,ctx);
const action=async(a,id)=>click({target:{closest:s=>s==='[data-action]'?{dataset:{action:a,id}}:null}});
(async()=>{
assert.equal(run('progress()'),17);
await action('join','1');assert.equal(run('state.joined.length'),1);
await action('join','1');assert.equal(run('state.joined.length'),0);
await action('join','2');assert.equal(run('state.joined.length'),0,'Full event must reject booking');
run("state.role='manager'");await action('promote');assert.equal(run('state.profile.role'),'trainee','Both exams required');
run('state.menuPassed=true;state.tablePassed=true');await action('promote');assert.equal(run('state.profile.role'),'waiter');
run("state.done=['welcome','contact','menu','service']");assert.equal(run('progress()'),100);
assert.equal(run("esc('<script>')"),'&lt;script&gt;');
for(const role of ['trainee','waiter','manager','local'])for(const p of ['home','courses','events','team','library','profile']){run(`state.role='${role}';page='${p}';render()`);assert(elements.get('#app').innerHTML.includes('Академия'));}
await action('confirm-reset');assert.equal(run('progress()'),17);assert.equal(JSON.parse(storage.get('service-academy-demo-v1')).role,'trainee');
console.log('PASS: booking/cancellation/capacity, exam gate, progress, escaping, role views, reset/persistence');
})().catch(e=>{console.error(e);process.exitCode=1});
