// Build step for the project page. Run from the site root after editing
// data.js, index.html, styles.css, or app.js:
//
//   node tools/build.mjs
//
// It pre-renders the leaderboard tables into index.html so the page reads
// without JavaScript, stamps the leaderboard date from the last commit that
// touched data.js, and refreshes the cache-busting hashes on the asset URLs.
// The row markup mirrors renderLeaderboard() in app.js.
import { readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import vm from "node:vm";

const root = new URL("..", import.meta.url).pathname;
const read = (p) => readFileSync(root + p, "utf8");
const sandbox = { window: {} };
vm.runInNewContext(read("data.js"), sandbox);
const data = sandbox.window.BVB_DATA;

const esc = (v) =>
  String(v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const score = (n, d = 1) => (Number.isFinite(n) ? n.toFixed(d) : "n/a");
const money = (n) => Number.isFinite(n) ? `$${score(n, 3)}` : "n/a";
const logos = {
  OpenAI: "openai.svg",
  Meta: "meta.png",
  Anthropic: "claude-color.svg",
  Google: "gemini-color.svg",
  xAI: "grok.svg",
  "Zhipu AI": "glm.png",
  Alibaba: "qwen-color.svg",
  "Moonshot AI": "kimi.png",
  MiniMax: "minimax-color.svg",
  ByteDance: "seed.png",
  DeepSeek: "deepseek-color.svg",
  NVIDIA: "nvidia-color.svg",
  Elorian: "elorian.svg",
};
const mono = new Set(["openai.svg", "grok.svg", "glm.png", "kimi.png", "elorian.svg"]);
const tasks = [
  "object_counting",
  "object_abs_distance",
  "object_size_estimation",
  "room_size_estimation",
  "object_rel_distance",
  "object_rel_direction",
  "route_planning",
  "obj_appearance_order",
];
const modelCell = (r) => {
  const logo = logos[r.vendor];
  const img = logo
    ? `<img class="model-logo${mono.has(logo) ? " mono" : ""}" src="assets/model-logos/${logo}" width="20" height="20" alt="" aria-hidden="true" />`
    : "";
  return `<span class="model-identity" title="${esc(r.vendor)}">${img}<span><span class="model-name">${esc(
    r.name,
  )}</span> <span class="effort-text">${esc(r.effort)}</span>${
    r.openWeight ? ' <span class="tag-text">open-weight</span>' : ""
  }</span></span>`;
};
const ranked = [...data].sort((a, b) => b.overall - a.overall || a.rank - b.rank);
const cell = (key, text) => `<td class="num${key === "overall" ? " sorted" : ""}">${text}</td>`;
const rows = ranked
  .map(
    (r, i) =>
      `<tr><td class="num rank${i < 3 ? " top" : ""}">${i + 1}</td><td class="model-cell">${modelCell(r)}</td>${cell(
        "overall",
        score(r.overall, 2),
      )}${cell("dualVqa", score(r.dualVqa))}${cell("latentSim", score(r.latentSim))}${cell(
        "costUsd",
        money(r.costUsd),
      )}</tr>`,
  )
  .join("\n");
const taskRows = ranked
  .map(
    (r) =>
      `<tr><td class="model-cell">${modelCell(r)}</td><td class="num group-start">${score(
        r.layout,
      )}</td><td class="num">${score(r.motion)}</td>${tasks
        .map(
          (k, i) =>
            `<td class="num${i === 0 ? " group-start" : ""}" style="background:color-mix(in srgb, var(--dv) ${(
              r.tasks[k] * 0.16
            ).toFixed(1)}%, transparent)">${score(r.tasks[k])}</td>`,
        )
        .join("")}</tr>`,
  )
  .join("\n");

let html = read("index.html");
html = html.replace(/<tbody id="leaderboard-body">[\s\S]*?<\/tbody>/, `<tbody id="leaderboard-body">\n${rows}\n</tbody>`);
html = html.replace(/<tbody id="task-body">[\s\S]*?<\/tbody>/, `<tbody id="task-body">\n${taskRows}\n</tbody>`);

// Text that follows the data. The same sentences are written by writeFacts()
// in app.js, and these copies serve readers without JavaScript.
const providers = new Set(data.map((r) => r.vendor)).size;
const gaps = data.map((r) => r.latentSim - r.dualVqa);
const lsAbove = gaps.filter((g) => g > 0).length;
const bestDv = Math.max(...data.map((r) => r.dualVqa));
const overview = `The leaderboard covers ${data.length} configurations from ${providers} providers on all 288 test videos. It is updated as new models are evaluated.`;
const lede =
  (lsAbove === data.length
    ? `Latent Similarity is higher than Dual VQA for every configuration on the leaderboard, by ${score(
        Math.min(...gaps),
      )} to ${score(Math.max(...gaps))} points.`
    : `Latent Similarity is higher than Dual VQA for ${lsAbove} of the ${data.length} configurations on the leaderboard.`) +
  ` The highest Dual VQA is ${score(bestDv)}, so every configuration loses at least ${score(
    100 - bestDv,
  )}% of the source-correct answers in its reconstructions.`;
html = html.replace(/(<p id="overview-count">)[\s\S]*?(<\/p>)/, `$1\n            ${overview}\n          $2`);
html = html.replace(/(<p id="results-lede">)[\s\S]*?(<\/p>)/, `$1\n            ${lede}\n          $2`);

// Leaderboard date from the last commit that changed data.js.
try {
  const day = execFileSync("git", ["log", "-1", "--format=%cs", "--", "data.js"], { cwd: root })
    .toString()
    .trim();
  if (day) {
    const label = new Date(`${day}T12:00:00Z`).toLocaleDateString("en-US", {
      month: "long",
      day: "numeric",
      year: "numeric",
      timeZone: "UTC",
    });
    html = html.replace(
      /(<span class="updated" id="updated-stamp">)[^<]*(<\/span>)/,
      `$1Leaderboard updated ${label}$2`,
    );
  }
} catch {
  // Not a git checkout. Keep the existing date.
}

// Content hashes so browsers fetch changed files.
for (const file of ["styles.css", "data.js", "gallery.js", "app.js"]) {
  const hash = createHash("sha256").update(read(file)).digest("hex").slice(0, 12);
  const name = file.replace(".", "\\.");
  html = html.replace(new RegExp(`(${name}\\?v=)[^"]+`), `$1${hash}`);
}

writeFileSync(root + "index.html", html);
console.log(`Built index.html with ${ranked.length} configurations.`);
