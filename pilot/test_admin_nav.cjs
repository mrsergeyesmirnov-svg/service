// Smoke-test the real learner landing and manager separation without a browser.
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const code = fs.readFileSync("learning.js", "utf8");
const mainCode = fs.readFileSync("pilot.js", "utf8");
const html = fs.readFileSync("index.html", "utf8");
const root = { innerHTML: "" };
const course = {
  id: 7, title: "КУХНЯ 02", category: "menu",
  structured: false, chapters: 2, read: 1, questions: 10,
  passed: false, best_score: null,
};
const btn = (label, action, id = "", cls = "") =>
  '<button class="' + cls + '" data-action="' + action + '" data-id="' + id + '">' + label + '</button>';
const ctx = {
  console,
  document: { addEventListener() {},querySelectorAll:()=>[] },
  showDishPhotos:()=>{},
  eventDate:x=>x,
  window: { scrollTo() {} },
  user: { id: 1, role: "manager", restaurant: "MOJO", name: "Manager" },
  roles: { manager: "Менеджер по сервису" },
  $: selector => selector === "#app" ? root : {oninput:null},
  esc: x => String(x ?? ""),
  btn,
  navSvg: () => "<svg></svg>",
  isManager: () => true,
  done: () => false,
  dateLabel: () => "24.10.2026",
  api: async endpoint => {
    if (endpoint === "learning") return [course];
    if (endpoint === "assignments" || endpoint === "events") return [];
    throw Error("Unexpected API call: " + endpoint);
  },
};
vm.createContext(ctx);
vm.runInContext(code, ctx, { filename: "learning.js" });

async function main() {
  await ctx.learningPage("home");
  assert.match(root.innerHTML, /Мой путь в MOJO/);
  assert.match(root.innerHTML, /Продолжить обучение/);
  assert.match(root.innerHTML, /data-action="open-manager"/);
  assert.doesNotMatch(root.innerHTML, /data-action="dish-open"/);
  assert.match(root.innerHTML, /1 из 2 глав/);

  await ctx.learningPage("catalog");
  assert.match(root.innerHTML, /Программа обучения/);
  assert.match(root.innerHTML, /data-action="study"/);
  assert.match(root.innerHTML, /data-action="open-manager"/);
  assert.match(root.innerHTML, /data-action="nav" data-id="cases"/);
  assert.doesNotMatch(root.innerHTML, /data-action="dish-open"/);

  assert.match(mainCode, /\['home','Главная'\],\['catalog','Программа'\],\['cases','Практика'\],\['events','Мероприятия'\],\['profile','Профиль'\]/);
  assert.match(mainCode, /\['dashboard','Обзор'\],\['courses','Программы'\],\['team','Команда'\],\['events','Мероприятия'\],\['profile','Профиль'\]/);
  assert.match(mainCode, /managerMode=isManager\(\);view=managerMode\?'dashboard':'home'/);
  assert.match(mainCode, /data-action="nav" data-id="events"/);
  assert.match(mainCode, /Карточки блюд · управление/);
  assert.match(mainCode, /coursePdfPanel\(\)/);
  assert.match(mainCode, /function dishCourseForm\(\)/);
  assert.match(mainCode, /data-action="dish-course-new"|btn\('Собрать курс из карточек блюд','dish-course-new'/);
  assert.match(mainCode, /async function publishReviewScreen\(c\)/);
  assert.match(code, /await generateCourseProposal\(cid\)/);
  assert.match(code, /reset_quiz:clear/);
  assert.match(mainCode, /Пройти тест заново|Проверить и опубликовать/);
  assert.match(html, /learning\.js\?v=20261027-stages1/);
  assert.match(html, /pilot\.js\?v=20261027-buttons1/);
  assert.match(html, /dishes\.js\?v=20261027-nav1/);
  assert.match(html, /wine_cards\.js\?v=20261026-1/);
  assert.match(html, /menu_assessments\.js\?v=20261027-stages1/);
  assert.match(html, /wine_cards\.css\?v=20261026-1/);
  assert.match(mainCode, /Скачать шаблон ТТК/);
  assert.match(html, /learning\.css\?v=20261023-events1/);
  assert.match(html, /mobile_polish\.css\?v=20261027-buttons1/);
  const polished = fs.readFileSync('mobile_polish.css', 'utf8');
  assert.match(polished, /\.manager-home-primary\s*>\s*button\.lime-action\s*\{/);
  assert.match(polished, /background:#D5ED89/);
  assert.match(polished, /\.manager-tools\s*>\s*button\.manager-tool/);
  assert.match(mainCode, /<strong>Команда<\/strong>/);
  assert.match(mainCode, /<strong>Результаты<\/strong>/);
  assert.match(html, /events\.js\?v=20261023-events1/);
  const calls=[];
  const assignment={id:42,course_id:7,title:'Required',deadline:'2026-10-24',
    questions:[{type:'single',question:'Required question',options:['A','B']}],
    history:[],review:[],max_attempts:2,pass_score:80,finished:false};
  ctx.api=async (path,method,body)=>{
    calls.push({path,method,body});
    if(path==='assignments/42')return assignment;
    if(path==='learning/7')return {id:7,title:'Course',source:'Synthetic',chapters:[{id:'a',title:'Chapter',body:'Text'}],read:[],questions:[],history:[]};
    if(path==='wine-cards/7')return {cards:[],pairs:[],ratings:{}};
    if(path==='assignments/42/submit')return {score:50,passed:false};
    if(path==='learning/7/submit')return {score:100,passed:true,review:[]};
    throw Error('Unexpected '+path);
  };
  await ctx.studyAssignment(42);
  assert.match(root.innerHTML,/Chapter/);
  assert.match(root.innerHTML,/Обязательно/);
  assert.match(root.innerHTML,/осталось попыток: 2/);
  vm.runInContext("quizAnswers=[0];quizRequest='request-test'",ctx);
  await ctx.submitStudyAnswers();
  assert.equal(calls.filter(x=>x.path==='assignments/42/submit').length,1);
  assert.equal(calls.filter(x=>x.path==='learning/7/submit').length,0);
  assignment.finished=true;
  ctx.showStudyQuiz();
  assert.match(root.innerHTML,/Попытки закончились/);
  assert.doesNotMatch(root.innerHTML,/id="study-quiz"/);
  await ctx.study(7);
  assert.doesNotMatch(root.innerHTML,/Обязательно/);
  await ctx.submitStudyAnswers();
  assert.equal(calls.filter(x=>x.path==='learning/7/submit').length,1);
  const navRoot = {innerHTML: "",classList:{toggle(){}},setAttribute(){}};
  const managerRoot = {innerHTML: ""};
  const managerCtx = {
    document:{body:{classList:{toggle(){}}}},
    console,
    user:{id:999,role:"manager",restaurant:"MOJO",name:"Manager"},
    managerMode:true,view:"dashboard",
    $: selector => selector==="#nav"?navRoot:managerRoot,
    esc:x=>String(x??""),btn,navSvg:()=>"<svg></svg>",
    isManager(){return ["manager","local"].includes(this.user.role)},
    done:()=>false,
    api:async path=>{
      if(path==="team")return [{active:true}];
      if(path==="courses")return [{published:true,archived:false}];
      if(path==="assignments" || path==="events")return [];
      throw Error("Unknown manager API "+path);
    }
  };
  managerCtx.isManager=()=>["manager","local"].includes(managerCtx.user.role);
  vm.createContext(managerCtx);
  const navStart=mainCode.indexOf("function nav(){"),navEnd=mainCode.indexOf("const done=",navStart);
  assert(navStart>0&&navEnd>navStart);
  vm.runInContext(mainCode.slice(navStart,navEnd),managerCtx,{filename:"manager-nav"});
  managerCtx.nav();
  assert.match(navRoot.innerHTML,/data-id="dashboard"/);
  assert.match(navRoot.innerHTML,/data-id="events"/);
  assert.match(navRoot.innerHTML,/Обзор/);
  await managerCtx.managerDashboard();
  assert.match(managerRoot.innerHTML,/Обзор Академии/);
  assert.doesNotMatch(managerRoot.innerHTML,/Мой путь в MOJO/);
  managerCtx.user.role="local";
  managerCtx.nav();
  assert.match(navRoot.innerHTML,/data-id="events"/);
  assert.doesNotMatch(navRoot.innerHTML,/data-id="team"/);
  managerCtx.user.role="trainee";
  managerCtx.managerMode=false;
  managerCtx.view="home";
  managerCtx.nav();
  assert.match(navRoot.innerHTML,/data-id="home"/);
  assert.match(navRoot.innerHTML,/data-id="events"/);
  assert.doesNotMatch(navRoot.innerHTML,/data-id="dashboard"/);
  // The practice result must never strand an employee under AI feedback.
  const start=mainCode.indexOf("function caseOutcome(");
  const end=mainCode.indexOf("async function caseDetail(",start);
  assert(start>0&&end>start);
  const outcomeCtx={
    btn,
    esc:x=>String(x??""),
    caseCache:[{id:10,published:true,archived:false},{id:11,published:true,archived:false}],
  };
  vm.createContext(outcomeCtx);
  vm.runInContext(mainCode.slice(start,end),outcomeCtx,{filename:"case-outcome"});
  const feedback={
    summary:"Нужно уточнить состав",strengths:"Не выдумал рецепт",
    improvements:"Уточнить ограничения",next_step:"Повтори правило проверки на кухне",
    focus_topic:"Ограничения питания",needs_review:true,recommended_course_id:7,
  };
  const recommended=outcomeCtx.caseOutcome(10,feedback,[{id:7,title:"Сервис WOW"}],"Проверю состав.");
  assert.match(recommended,/data-action="study" data-id="7"/);
  assert.match(recommended,/Сервис WOW/);
  assert.match(recommended,/data-action="case-open" data-id="10"/);
  assert.match(recommended,/Твой ответ/);
  assert.match(recommended,/Проверю состав/);
  const unknown=outcomeCtx.caseOutcome(10,{...feedback,recommended_course_id:999},[]);
  assert.match(unknown,/data-action="nav" data-id="catalog"/);
  assert.doesNotMatch(unknown,/data-action="study"/);
  const next=outcomeCtx.caseOutcome(10,{...feedback,needs_review:false},[]);
  assert.match(next,/data-action="case-open" data-id="11"/);
  assert.match(next,/Полный разбор ответа/);
  console.log("MOJO learner path, manager workspace and case outcome: OK");
}
main().catch(error => { console.error(error); process.exitCode = 1; });
