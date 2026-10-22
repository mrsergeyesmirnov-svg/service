// Verify the rendered manager navigation without browser dependencies.
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");

const code = fs.readFileSync("learning.js", "utf8");
const mainCode = fs.readFileSync("pilot.js", "utf8");
const html = fs.readFileSync("index.html", "utf8");
const root = { innerHTML: "" };
const legacyCourse = {
  id: 7, title: "КУХНЯ 02", category: "menu",
  structured: false, chapters: 2, read: 0, questions: 10,
  passed: false, best_score: null,
};
const ctx = {
  console,
  document: { addEventListener() {} },
  window: { scrollTo() {} },
  user: { id: 1, role: "manager", restaurant: "MOJO", name: "Manager" },
  roles: { manager: "Менеджер по сервису" },
  $: selector => selector === "#app" ? root : null,
  esc: x => String(x ?? ""),
  btn: (label, action, id = "", cls = "") =>
    '<button class="' + cls + '" data-action="' + action + '" data-id="' + id + '">' + label + '</button>',
  navSvg: () => "<svg></svg>",
  isManager: () => true,
  done: () => false,
  api: async endpoint => {
    if (endpoint === "learning") return [legacyCourse];
    if (endpoint === "assignments") return [];
    throw Error("Unexpected API call: " + endpoint);
  },
};
vm.createContext(ctx);
vm.runInContext(code, ctx, { filename: "learning.js" });

async function main() {
  await ctx.learningPage("catalog");
  assert.match(root.innerHTML, /data-action="dish-open"/);
  assert.match(root.innerHTML, /Открыть редактор карточек/);
  assert.match(root.innerHTML, /старые тесты/);

  await ctx.learningPage("home");
  assert.match(root.innerHTML, /data-action="dish-open"/);

  assert.match(mainCode, /Карточки блюд · управление/);
  assert.match(html, /learning\.js\?v=20261022-2/);
  assert.match(html, /dishes\.js\?v=20261022-2/);

  console.log("Manager card editor visible on Home, Courses and Materials; cache-buster present.");
}
main().catch(error => { console.error(error); process.exitCode = 1; });
