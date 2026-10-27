// Acceptance regression: a trainee is NOT finished until the section control exam passes.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const root={innerHTML:''};
const btn=(label,action,id='',cls='')=>
  '<button data-action="'+action+'" data-id="'+id+'" class="'+cls+'">'+label+'</button>';
const context={
  document:{addEventListener(){},querySelectorAll(){return []}},
  window:{scrollTo(){}},console,btn,
  $:selector=>selector==='#app'?root:null,
  esc:value=>String(value??''),
  dishPhoto:()=>'<img>',
  navSvg:()=>'<svg></svg>',
  dateLabel:()=>'',error:err=>{throw err}
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('learning.js','utf8'),context);
function summary(partial){
 return {id:7,title:'MOJO роллы',category:'menu',chapters:8,read:8,
         questions:0,passed:false,staged_menu:true,control_passed:false,
         ...partial};
}
assert.equal(context.learningDone(summary()),false,'Reading all chapters does not pass menu exams');
assert.match(context.courseCard(summary()),/Остались проверки знаний/);
assert.doesNotMatch(context.courseCard(summary()),/Завершён/);
assert.equal(context.learningDone(summary({control_passed:true})),true);
assert.match(context.courseCard(summary({control_passed:true})),/Завершён/);
assert.equal(context.learningDone(summary({read:7,control_passed:true})),false);
assert.equal(context.learningDone(summary({staged_menu:false,questions:1,passed:false})),false);
assert.equal(context.learningDone(summary({staged_menu:false,questions:1,passed:true})),true);
vm.runInContext("activeCourse={id:7,title:'MOJO роллы',chapters:[{id:'a',kind:'dish'}],read:['a'],questions:[],history:[],staged_menu:true,control_passed:false,wine:{pairs:[]},menu:{pairs:[]}}",context);
context.showStudyComplete();
assert.match(root.innerHTML,/Материалы изучены/);
assert.match(root.innerHTML,/data-action="assessments-open"/);
assert.doesNotMatch(root.innerHTML,/ГОТОВО/);
vm.runInContext("activeCourse.control_passed=true",context);
context.showStudyComplete();
assert.match(root.innerHTML,/Промежуточный и контрольный тесты сданы/);
console.log('Trainee completion gate: reading is not an exam pass — OK');
