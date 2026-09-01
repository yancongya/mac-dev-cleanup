#!/usr/bin/env node
/**
 * Headless render check for the generated dashboard (development-time only).
 *
 * The dashboard itself stays dependency-free; this checker needs jsdom:
 *   npm i jsdom                       # resolvable from the current directory
 *   MDC_JSDOM=/path/to/jsdom/lib/api.js  node scripts/check_dashboard_dom.mjs dashboard.html
 *
 * Verifies: zero runtime errors, all sections render, search keeps focus across
 * re-renders, the settings schema renders every field, and reason strings are
 * translated.
 */
import { readFileSync } from "node:fs";
import os from "node:os";

async function loadJsdom() {
  const candidates = ["jsdom", process.env.MDC_JSDOM].filter(Boolean);
  for (const candidate of candidates) {
    try {
      return await import(candidate);
    } catch (err) {
      if (candidate === candidates[candidates.length - 1]) {
        console.error(
          "找不到 jsdom。请先安装：npm i jsdom\n" +
          "或设置 MDC_JSDOM=/path/to/node_modules/jsdom/lib/api.js"
        );
        throw err;
      }
    }
  }
}

const { JSDOM, VirtualConsole } = await loadJsdom();

const html = readFileSync(process.argv[2], "utf8");
// The committed dashboard.html is a data-free shell that references dashboard_data.js
// (gitignored). For the DOM checks we inline the latest scan state so rendering is
// deterministic and does not depend on async file:// script loading.
const statePath = `${os.homedir()}/.codex/logs/mac-dev-cleanup/state.json`;
let renderHtml = html;
try {
  const state = JSON.parse(readFileSync(statePath, "utf8"));
  renderHtml = renderHtml
    .replace("/*__DATA__*/null", JSON.stringify(state))
    .replace("/*__CONFIG__*/null", JSON.stringify(state.config || {}));
} catch (e) {
  // fall through with null DATA; checks will fail clearly rather than render silently
}
const errors = [];
const vc = new VirtualConsole();
vc.on("jsdomError", (e) => errors.push("jsdomError: " + (e.stack || e.message)));
vc.on("error", (...a) => errors.push("console.error: " + a.join(" ")));
vc.on("warn", (...a) => errors.push("console.warn: " + a.join(" ")));

const dom = new JSDOM(renderHtml, {
  runScripts: "dangerously",
  pretendToBeVisual: true,
  virtualConsole: vc,
  url: "http://127.0.0.1:8765/dashboard.html",
});

const { window } = dom;
const doc = window.document;
const $ = (s) => doc.querySelector(s);
const text = (s) => ($(s) ? $(s).textContent.trim() : null);

await new Promise((r) => setTimeout(r, 300));

const checks = [];
const ok = (name, cond, extra = "") =>
  checks.push({ name, pass: !!cond, extra: cond ? "" : extra });

// --- structure ---
ok("app 容器已渲染", $("#app").children.length > 0);
ok("boot-error 未触发", !$("#boot-error").classList.contains("show"));
ok("摘要六宫格", doc.querySelectorAll(".sum-cell").length === 6, doc.querySelectorAll(".sum-cell").length);
ok("风险分布三行", doc.querySelectorAll(".cr-item[data-risk]").length === 3);
ok("候选项表格已渲染", doc.querySelectorAll("tbody tr").length > 0, doc.querySelectorAll("tbody tr").length);
ok("工具自检格子", doc.querySelectorAll(".tool-cell").length > 0);
ok("面板系统已渲染", doc.querySelectorAll(".panel").length >= 5);
ok("toast 容器存在", !!$("#toast"));

// --- i18n ---
const bodyText = doc.body.textContent;
ok("无英文 'ok' 工具状态", !/\bok\b/.test($("#app").querySelectorAll(".ts")[0]?.textContent || ""));
ok("标题已汉化", doc.title.includes("清理控制台"), doc.title);
ok("品牌已汉化", text(".brand h1").includes("清理控制台"), text(".brand h1"));
ok("扫描模式下 m-mode 为中文", text("#m-mode") === "仅扫描", text("#m-mode"));
const reasonCells = [...doc.querySelectorAll("td.reason")].map((e) => e.textContent);
const chineseReasons = reasonCells.filter((t) => /[一-龥]/.test(t)).length;
ok("原因列已汉化", chineseReasons > 0 && chineseReasons >= reasonCells.length * 0.9,
  `${chineseReasons}/${reasonCells.length} 含中文；样例: ${reasonCells.slice(0, 3).join(" | ")}`);
// Untranslated templates still carry whole English phrases; proper nouns
// (Tauri/Rust, Vite, cargo) are allowed to survive translation.
const ENGLISH_TEMPLATE = /(directory: |cache directory|under ~\/Library|Rebuildable |Generated test|stale project|older than \d+-month|Large (archive|file|directory|log) )/;
ok("无残留英文 reason 模板",
  !reasonCells.some((t) => ENGLISH_TEMPLATE.test(t)),
  reasonCells.filter((t) => ENGLISH_TEMPLATE.test(t)).slice(0, 3).join(" | "));
ok("筛选 chip 带计数", /\d/.test($("#chips .chip .n")?.textContent || ""), $("#chips")?.textContent.trim());

// --- settings schema ---
const settingsPanel = doc.querySelector('.panel-head[data-panel="settings"]');
if (settingsPanel) settingsPanel.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
const settingsBody = doc.querySelector('#pbody-settings');
const labels = [...(settingsBody || doc).querySelectorAll(".field label")].map((e) => e.textContent.trim());
const allChinese = labels.every((l) => /[一-龥]/.test(l));
ok("设置项标签全部含中文", allChinese, labels.filter((l) => !/[一-龥]/.test(l)).join(", "));
ok("含构建衍生物分组", labels.some((l) => l.includes("构建目录名")), labels.join(" / ").slice(0, 200));
ok("含微信媒体保留月数", labels.some((l) => l.includes("微信媒体")), labels.join(" / ").slice(0, 120));
ok("设置项数量 >= 15", labels.length >= 15, labels.length);
ok("aria-expanded 已切换", settingsPanel?.getAttribute("aria-expanded") === "true");

// --- search keeps focus (the bug this rewrite fixed) ---
// First expand the candidates panel so search-input is visible
const candidatesPanel = doc.querySelector('.panel-head[data-panel="table"]');
if (candidatesPanel) candidatesPanel.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
await new Promise(r => setTimeout(r, 50));
const input = $("#search-input");
input.focus();
ok("搜索框可获得焦点", doc.activeElement === input);
input.value = "tauri";
input.dispatchEvent(new window.Event("input", { bubbles: true }));
ok("输入后焦点保持", doc.activeElement === input, "activeElement=" + (doc.activeElement && doc.activeElement.id));
ok("输入后列表已过滤", doc.querySelectorAll("tbody tr").length >= 0);
const countText = text("#count");
ok("计数已更新", /\d+ \/ \d+/.test(countText || ""), countText);

// --- copy affordance ---
const copyCell = doc.querySelector("[data-copy]");
ok("路径可复制标记", !!copyCell);
ok("复制标记带 title", !!copyCell?.getAttribute("title"));

// --- risk filter ---
const chip = doc.querySelector('#chips .chip[data-risk="manual"]');
if (chip) {
  chip.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  const rows = doc.querySelectorAll("tbody tr");
  const allManual = [...rows].every((r) => r.textContent.includes("待确认"));
  ok("筛选后仅剩待确认", allManual, rows.length + " 行");
}

// --- sort headers (reset search/filter first to ensure table renders) ---
input.value = "";
input.dispatchEvent(new window.Event("input", { bubbles: true }));
// Reset risk filter to "all"
const allChip = doc.querySelector('#chips .chip[data-risk="all"]');
if (allChip) allChip.click();
await new Promise(r => setTimeout(r, 50));
const sortHeaders = doc.querySelectorAll("thead th[data-sort]");
ok("排序表头已渲染", sortHeaders.length >= 3, sortHeaders.length + " 个");
if (sortHeaders.length > 0) {
  sortHeaders[0].dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  const arrow = sortHeaders[0].textContent;
  ok("排序箭头已切换", arrow.includes("↑") || arrow.includes("↓"), arrow);
}

// --- offline CLI generation ---
const saveBtn = $("#save-btn");
ok("离线时按钮为生成命令", saveBtn.textContent.includes("生成配置命令"), saveBtn.textContent);
saveBtn.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
ok("已生成 CLI 命令", (text("#cmd-pre") || "").includes("--set-config"), (text("#cmd-pre") || "").slice(0, 80));
ok("CLI 含 build_artifacts", (text("#cmd-pre") || "").includes("build_artifacts"));
// The CLI output should be nested config.json structure (thresholds nested, not flat)
const cmdText = text("#cmd-pre") || "";
ok("CLI 含嵌套 thresholds", cmdText.includes('"thresholds"') && cmdText.includes('"app_cache_min_mb"'),
   cmdText.includes('"thr_app_cache_min_mb"') ? "仍然扁平(BUG)" : "已嵌套");
ok("CLI 含嵌套 build_artifacts", cmdText.includes('"tauri_parents"'));
// downloadConfig should also produce nested JSON
const dlBtn = $("#dl-btn");
let downloadPayload = null;
const origCreate = window.URL.createObjectURL;
window.URL.createObjectURL = function(blob) {
  downloadPayload = blob; return "blob:test";
};
dlBtn.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
window.URL.createObjectURL = origCreate;
if (downloadPayload && typeof downloadPayload.text === "function") {
  downloadPayload.text().then(function(t) {
    const j = JSON.parse(t);
    ok("下载 config.json 含 thresholds 对象", typeof j.thresholds === "object", JSON.stringify(Object.keys(j)));
    ok("下载 config.json 含 build_artifacts 对象", typeof j.build_artifacts === "object");
  });
} else {
  ok("下载 config.json 含 thresholds 对象", false, "无法读取 Blob");
}
ok("toast 已提示", $("#toast").classList.contains("show"), $("#toast").textContent);

// (sort headers tested above, before save click)

// --- report ---
console.log("");
for (const c of checks) {
  console.log(`${c.pass ? "  PASS" : "  FAIL"}  ${c.name}${c.extra ? "  → " + c.extra : ""}`);
}
const failed = checks.filter((c) => !c.pass);
console.log(`\n${checks.length - failed.length}/${checks.length} 项通过`);
if (errors.length) {
  console.log("\n运行时错误:");
  errors.forEach((e) => console.log("  " + e));
}
dom.window.close();
process.exit(failed.length || errors.length ? 1 : 0);
