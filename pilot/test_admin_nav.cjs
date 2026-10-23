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
  document: { addEventListener() {} },
  window: { scrollTo() {} },
  user: { id: 1, role: "manager", restaurant: "MOJO", name: "Manager" },
  roles: { manager: "Менеджер по сервису" },
  $: selector => selector === "#app" ? root : null,
  esc: x => String(x ?? ""),
  btn,
  navSvg: () => "<svg></svg>",
  isManager: () => true,
  done: () => false,
  dateLabel: () => "24.10.2026",
  api: async endpoint => {
    if (endpoint === "learning") return [course];
    if (endpoint === "assignments") return [];
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
  assert.match(root.innerHTML, /Учебные материалы/);
  assert.match(root.innerHTML, /data-action="study"/);
  assert.match(root.innerHTML, /data-action="open-manager"/);
  assert.match(root.innerHTML, /data-action="nav" data-id="cases"/);
  assert.doesNotMatch(root.innerHTML, /data-action="dish-open"/);

  assert.match(mainCode, /\['home','Мой путь'\],\['catalog','Курсы'\],\['events','Мероприятия'\],\['profile','Профиль'\]/);
  assert.match(mainCode, /\['dashboard','Обзор'\],\['courses','Программы'\],\['team','Команда'\],\['events','Мероприятия'\],\['profile','Профиль'\]/);
  assert.match(mainCode, /managerMode=isManager\(\);view=managerMode\?'dashboard':'home'/);
  assert.match(mainCode, /data-action="nav" data-id="events"/);
  assert.match(mainCode, /Карточки блюд · управление/);
  assert.match(mainCode, /coursePdfPanel\(\)/);
  assert.match(mainCode, /Пройти тест заново|Проверить и опубликовать/);
  assert.match(html, /learning\.js\?v=20261023-events1/);
  assert.match(html, /pilot\.js\?v=20261023-events1/);
  assert.match(html, /learning\.css\?v=20261023-events1/);
  assert.match(html, /events\.js\?v=20261023-events1/);
  const calls=[];
  const assignment={id:42,course_id:7,title:'Required',deadline:'2026-10-24',
    questions:[{type:'single',question:'Required question',options:['A','B']}],
    history:[],review:[],max_attempts:2,pass_score:80,finished:false};
  ctx.api=async (path,method,body)=>{
    calls.push({path,method,body});
    if(path==='assignments/42')return assignment;
    if(path==='learning/7')return {id:7,title:'Course',source:'Synthetic',chapters:[{id:'a',title:'Chapter',body:'Text'}],read:[],questions:[],history:[]};
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
  console.log("MOJO learner path, manager workspace and cache-busters: OK");
}
main().catch(error => { console.error(error); process.exitCode = 1; });
