// Regressions for image loading that previously blocked iPhone scrolling.
const fs=require("node:fs");
const vm=require("node:vm");
const assert=require("node:assert/strict");
const src=fs.readFileSync("dishes.js","utf8");
const html=fs.readFileSync("index.html","utf8");
const css=fs.readFileSync("mobile_polish.css","utf8");
assert.match(html,/mobile_polish\.css\?v=20261027-simple1/);
assert.match(css,/-webkit-overflow-scrolling:touch/);
assert.match(css,/backdrop-filter:none/);
let fetched=0, observer;
const nodes=[1,1,2].map(id=>({
 isConnected:true,
 dataset:{dishPicture:String(id)},
 replaceChildren(img){this.photo=img;},
}));
class Observer{
 constructor(callback,options){this.callback=callback;this.options=options;this.observed=[];observer=this;}
 observe(node){this.observed.push(node)}
 unobserve(node){this.observed=this.observed.filter(x=>x!==node)}
 trigger(node){this.callback([{target:node,isIntersecting:true}])}
}
const ctx={
 console,window:{},URL:{createObjectURL:()=>"blob:photo-"+fetched},
 IntersectionObserver:Observer,
 fetch:async path=>{
  fetched++;
  return {ok:true,blob:async()=>new Uint8Array([1,2,3])};
 },
 token:"test", user:{role:"manager"}, learningCourses:[],
 activeCourse:null,btn:()=>"",esc:String,error:()=>{},
 document:{
  querySelectorAll:()=>nodes.filter(n=>n.dataset.photoReady!=="true"),
  createElement:tag=>({tagName:tag,alt:"",decoding:"",loading:"",src:""}),
  addEventListener:()=>{},
 },
};
vm.createContext(ctx);vm.runInContext(src,ctx,{filename:"dishes.js"});
vm.runInContext("dishCards=[{id:1,has_photo:true},{id:2,has_photo:false}]",ctx);
(async()=>{
 await ctx.showDishPhotos();
 assert.equal(fetched,0,"Opening the catalog must not prefetch photos below the fold");
 assert.equal(observer.observed.length,3);
 observer.trigger(nodes[0]);
 observer.trigger(nodes[1]);
 observer.trigger(nodes[2]);
 await new Promise(r=>setImmediate(r));
 assert.equal(fetched,1,"Multiple views of one photo must share one authenticated request");
 assert.equal(nodes[0].photo.tagName,"img");
 assert.equal(nodes[1].photo.tagName,"img");
 assert.equal(nodes[2].photo,undefined,"Items without photos stay placeholders");
 assert.equal(nodes[0].dataset.photoReady,"true");
 console.log("Mobile lazy photos: OK");
})().catch(err=>{console.error(err);process.exitCode=1});
