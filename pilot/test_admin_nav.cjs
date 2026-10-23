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

  assert.match(mainCode, /\['home','Мой путь'\],\['catalog','Библиотека'\],\['profile','Профиль'\]/);
  assert.match(mainCode, /\['team','Команда'\],\['courses','Программы'\],\['assignments','Результаты'\]/);
  assert.match(mainCode, /Карточки блюд · управление/);
  assert.match(mainCode, /coursePdfPanel\(\)/);
  assert.match(mainCode, /Пройти тест заново|Проверить и опубликовать/);
  assert.match(html, /learning\.js\?v=20261023-ux1/);
  assert.match(html, /pilot\.js\?v=20261023-ux1/);
  assert.match(html, /learning\.css\?v=20261023-ux1/);
  console.log("MOJO learner path, manager workspace and cache-busters: OK");
}
main().catch(error => { console.error(error); process.exitCode = 1; });
