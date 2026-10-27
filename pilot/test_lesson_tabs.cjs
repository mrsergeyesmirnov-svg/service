const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const listeners=[],panels=Array.from({length:4},(_,i)=>({hidden:i!==0}));
const tabs=panels.map((_,i)=>({dataset:{action:'lesson-tab',id:String(i)},setAttribute(k,v){this[k]=v}}));
const ctx={document:{addEventListener(event,fn){if(event==='click')listeners.push(fn)},querySelectorAll(s){return s==='[role=tabpanel]'?panels:tabs}},window:{},console,error(e){throw e}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('learning.js','utf8'),ctx);
(async()=>{for(const i of [1,2,3,0]){for(const fn of listeners)await fn({target:{closest:()=>tabs[i]}});assert.deepEqual(panels.map(p=>p.hidden),panels.map((_,j)=>j!==i));assert.equal(tabs[i]['aria-selected'],'true');assert.equal(tabs[i].disabled,false)}console.log('All lesson tabs switch through the actual click handler');})().catch(e=>{console.error(e);process.exit(1)});
