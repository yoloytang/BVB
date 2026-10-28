(() => {
  "use strict";
  const data = window.BVB_DATA;
  const gallery = window.BVB_GALLERY;
  if (!Array.isArray(data) || !data.length || !Array.isArray(gallery)) return;
  const $ = (id) => document.getElementById(id);
  const svgNS = "http://www.w3.org/2000/svg";
  const escape = (value) =>
    String(value).replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  const score = (n, digits = 1) =>
    Number.isFinite(n) ? n.toFixed(digits) : "n/a";
  const money = (n) => Number.isFinite(n) ? `$${score(n, 3)}` : "n/a";
  const costRows = data.filter((r) => Number.isFinite(r.costUsd) && r.costUsd > 0);

  // Theme. The page follows the system setting until the reader picks one.
  const root = document.documentElement;
  const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
  const theme = () => root.dataset.theme || (darkQuery.matches ? "dark" : "light");
  const palette = () => {
    const s = getComputedStyle(root);
    const v = (name) => s.getPropertyValue(name).trim();
    return {
      ink: v("--ink"),
      muted: v("--graphite"),
      grid: v("--grid"),
      axis: v("--axis"),
      page: v("--page"),
      overall: v("--overall"),
      dv: v("--dv"),
    };
  };
  // One color per vendor, used by both charts.
  // One brand color per vendor, used by both charts.
  const vendorPalettes = {
    light: {
      OpenAI: "#2b2b2b",
      Anthropic: "#e68160",
      Google: "#1eb25f",
      xAI: "#9d90ff",
      Meta: "#007fff",
      Alibaba: "#ff7700",
      "Zhipu AI": "#2d43ad",
      "Moonshot AI": "#687287",
      MiniMax: "#ff4265",
      ByteDance: "#00c6e4",
      DeepSeek: "#4d6bfe",
      NVIDIA: "#74B71B",
      Elorian: "#30D75D",
    },
    dark: {
      OpenAI: "#e5e5e1",
      Anthropic: "#ea9474",
      Google: "#32c570",
      xAI: "#b0a6ff",
      Meta: "#449dff",
      Alibaba: "#ff8d28",
      "Zhipu AI": "#768cff",
      "Moonshot AI": "#a2acc2",
      MiniMax: "#ff627f",
      ByteDance: "#13d2ec",
      DeepSeek: "#8096ff",
      NVIDIA: "#96D443",
      Elorian: "#30D75D",
    },
  };



  const vendorColor = (vendor) => vendorPalettes[theme()][vendor] || "#8a8a86";
  const vendorOrder = Object.keys(vendorPalettes.light).sort((a, b) => a.localeCompare(b));
  const modelLogos = {
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
  // Dark single-color marks, which need a light version on the dark page.
  const monoLogos = {
    "openai.svg": "openai-light.svg",
    "grok.svg": "grok-light.svg",
    "elorian.svg": "elorian-light.svg",
    "glm.png": "glm-light.png",
    "kimi.png": "kimi-light.png",
  };
  const logoSrc = (r, forTheme = "light") => {
    let icon = modelLogos[r.vendor];
    if (!icon) return "";
    if (forTheme === "dark" && monoLogos[icon]) icon = monoLogos[icon];
    return `assets/model-logos/${icon}`;
  };
  const isMono = (r) => Boolean(monoLogos[modelLogos[r.vendor]]);
  const axisNames = {
    overall: "Overall",
    dualVqa: "Dual VQA",
    latentSim: "Latent Similarity",
    costUsd: "Cost per scene",
  };
  const lowerIsBetter = new Set(["costUsd"]);
  const effortOrder = ["none", "low", "medium", "high", "xhigh", "max"];
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
  const configName = (r) => `${r.name} with reasoning effort ${r.effort}`;
  const modelCell = (r) => {
    const src = logoSrc(r);
    return `<span class="model-identity" title="${escape(r.vendor)}">${
      src
        ? `<img class="model-logo${isMono(r) ? " mono" : ""}" src="${escape(src)}" width="20" height="20" alt="" aria-hidden="true" />`
        : ""
    }<span><span class="model-name">${escape(r.name)}</span> <span class="effort-text">${escape(
      r.effort,
    )}</span>${r.openWeight ? ' <span class="tag-text">open-weight</span>' : ""}</span></span>`;
  };
  const legendHtml = (vendors) =>
    vendorOrder
      .filter((v) => vendors.has(v))
      .map(
        (v) =>
          `<span><i class="swatch" style="background:${vendorColor(v)}"></i>${escape(v)}</span>`,
      )
      .join("");
  const onResize = (el, fn) => {
    let lastWidth = el.clientWidth,
      queued = 0;
    const run = () => {
      queued = 0;
      if (el.clientWidth !== lastWidth) {
        lastWidth = el.clientWidth;
        fn();
      }
    };
    if ("ResizeObserver" in window)
      new ResizeObserver(() => {
        if (!queued) queued = requestAnimationFrame(run);
      }).observe(el);
    else window.addEventListener("resize", () => requestAnimationFrame(run));
  };

  // ---------------------------------------------------------------------
  // Floating tip, shared by metric definitions and chart marks
  const tip = $("tip");
  const header = document.querySelector(".site-header");
  let tipOwner = null,
    tipAnchor = null,
    tipPinned = false,
    tipAbove = false,
    tipHideTimer = 0;
  function placeTip(rect) {
    const margin = 12;
    const floor = header.getBoundingClientRect().bottom + 6;
    const tw = tip.offsetWidth,
      th = tip.offsetHeight;
    let left = rect.left + rect.width / 2 - tw / 2;
    left = Math.max(margin, Math.min(left, window.innerWidth - tw - margin));
    let top = tipAbove ? rect.top - th - 8 : rect.bottom + 8;
    if (tipAbove && top < floor) top = rect.bottom + 8;
    if (!tipAbove && top + th > window.innerHeight - margin) top = rect.top - th - 8;
    tip.style.left = `${Math.round(left)}px`;
    tip.style.top = `${Math.round(Math.max(floor, top))}px`;
  }
  function showTip(owner, html, { pinned = false, dataTip = false, anchor = null } = {}) {
    clearTimeout(tipHideTimer);
    if (tipOwner && tipOwner !== owner) {
      tipOwner.setAttribute?.("aria-expanded", "false");
      tipOwner.removeAttribute?.("aria-describedby");
    }
    tipOwner = owner;
    tipAnchor = anchor || owner;
    tipPinned = pinned;
    tipAbove = dataTip;
    tip.innerHTML = html;
    tip.classList.toggle("tip-data", dataTip);
    tip.hidden = false;
    if (!dataTip) {
      owner.setAttribute("aria-expanded", "true");
      owner.setAttribute("aria-describedby", "tip");
    }
    placeTip(tipAnchor.getBoundingClientRect());
  }
  function hideTip(force = false) {
    if (tipPinned && !force) return;
    tip.hidden = true;
    if (tipOwner?.classList?.contains("tip-button")) {
      tipOwner.setAttribute("aria-expanded", "false");
      tipOwner.removeAttribute("aria-describedby");
    }
    tipOwner = null;
    tipAnchor = null;
    tipPinned = false;
  }
  // Keep the tip next to its owner while the page or a table scrolls, and
  // close it once the owner leaves the view.
  function followTip() {
    if (tip.hidden || !tipAnchor) return;
    const r = tipAnchor.getBoundingClientRect();
    const box = tipAnchor.closest?.(".table-scroll, .bars-scroll")?.getBoundingClientRect();
    const out =
      r.bottom < header.getBoundingClientRect().bottom ||
      r.top > window.innerHeight ||
      (box && (r.right < box.left || r.left > box.right));
    if (out) hideTip(true);
    else placeTip(r);
  }
  document.addEventListener("scroll", followTip, { capture: true, passive: true });
  window.addEventListener("resize", followTip);
  const metricTipHtml = (key) => $(`tip-${key}`)?.innerHTML || "";
  function bindMetricTips(root = document) {
    root.querySelectorAll(".tip-button").forEach((b) => {
      if (b.dataset.bound) return;
      b.dataset.bound = "1";
      b.setAttribute("aria-controls", "tip");
      b.setAttribute("aria-expanded", "false");
      b.addEventListener("click", (e) => {
        e.stopPropagation();
        if (tipOwner === b && tipPinned) hideTip(true);
        else showTip(b, metricTipHtml(b.dataset.tip), { pinned: true });
      });
      b.addEventListener("pointerenter", (e) => {
        if (e.pointerType === "mouse" && !tipPinned)
          showTip(b, metricTipHtml(b.dataset.tip));
      });
      b.addEventListener("pointerleave", (e) => {
        if (e.pointerType === "mouse")
          tipHideTimer = setTimeout(() => hideTip(), 120);
      });
      b.addEventListener("focus", () => {
        if (!tipPinned || tipOwner !== b) showTip(b, metricTipHtml(b.dataset.tip));
      });
      b.addEventListener("blur", (e) => {
        if (tipOwner === b && (!tipPinned || e.relatedTarget)) hideTip(true);
      });
    });
  }
  tip.addEventListener("pointerenter", () => clearTimeout(tipHideTimer));
  tip.addEventListener("pointerleave", () => {
    if (!tipPinned) hideTip();
  });
  document.addEventListener("pointerdown", (e) => {
    if (tipPinned && !tip.contains(e.target) && !tipOwner?.contains(e.target)) hideTip(true);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !tip.hidden) hideTip(true);
  });
  bindMetricTips();

  const dataTipHtml = (r, highlight) =>
    `<p class="tip-title">${escape(r.name)} <span class="effort-text">${escape(
      r.effort,
    )}</span></p><dl>${["overall", "dualVqa", "latentSim"]
      .map(
        (k) =>
          `<dt>${axisNames[k]}</dt><dd${k === highlight ? ' style="color:var(--ink)"' : ""}>${score(
            r[k],
            k === "overall" ? 2 : 1,
          )}</dd>`,
      )
      .join("")}<dt>Cost per scene</dt><dd>${money(r.costUsd)}</dd></dl>`;

  // ---------------------------------------------------------------------
  // Facts derived from the data, so the prose follows the leaderboard.
  function writeFacts() {
    const providerCount = new Set(data.map((r) => r.vendor)).size;
    const lsAbove = data.filter((r) => r.latentSim > r.dualVqa).length;
    $("overview-count").textContent = `The leaderboard covers ${data.length} configurations from ${providerCount} providers on all 288 test videos. It is updated as new models are evaluated.`;
    const gaps = data.map((r) => r.latentSim - r.dualVqa);
    const bestDv = Math.max(...data.map((r) => r.dualVqa));
    $("results-lede").textContent =
      lsAbove === data.length
        ? `Latent Similarity is higher than Dual VQA for every configuration on the leaderboard, by ${score(
            Math.min(...gaps),
          )} to ${score(Math.max(...gaps))} points. The highest Dual VQA is ${score(
            bestDv,
          )}, so every configuration loses at least ${score(
            100 - bestDv,
          )}% of the source-correct answers in its reconstructions.`
        : `Latent Similarity is higher than Dual VQA for ${lsAbove} of the ${data.length} configurations on the leaderboard. The highest Dual VQA is ${score(
            bestDv,
          )}, so every configuration loses at least ${score(
            100 - bestDv,
          )}% of the source-correct answers in its reconstructions.`;
  }
  writeFacts();

  // ---------------------------------------------------------------------
  // Column chart of scores or reconstruction cost by model
  let barsAxis = "overall",
    barsView = "best",
    costScale = "log";
  function barRows() {
    let rows = data;
    if (barsView === "best") {
      // Compare the cost of each model's best-performing configuration.
      const selectionAxis = barsAxis === "costUsd" ? "overall" : barsAxis;
      const best = new Map();
      for (const r of data) {
        const k = `${r.family}|${r.harness}`;
        const b = best.get(k);
        if (!b || r[selectionAxis] > b[selectionAxis]) best.set(k, r);
      }
      rows = [...best.values()];
    }
    if (barsAxis === "costUsd") rows = rows.filter((r) => Number.isFinite(r.costUsd) && r.costUsd > 0);
    return [...rows].sort((a, b) => b[barsAxis] - a[barsAxis] || a.rank - b.rank);
  }
  // Match multicolor marks using their local logo colors. Each gradient spans
  // the bar itself, so the same brand treatment survives metric/range changes.
  const barGradients = {
    Google: { id: "gemini", colors: ["#3186FF", "#F94543", "#FABC12", "#08B962"] },
    Alibaba: { id: "qwen", colors: ["#6336E7", "#6F69F7"], horizontal: true },
    Meta: { id: "meta", colors: ["#0064E0", "#0081FB"] },
    MiniMax: { id: "minimax", colors: ["#E2167E", "#FE603C"], horizontal: true },
    ByteDance: { id: "seed", colors: ["#A060F0", "#1030F0", "#30E0B0"] },
    DeepSeek: { id: "deepseek-water", colors: ["#69D5FF", "#2B9FF4", "#4D6BFE"] },
  };
  const xaiBarColor = () => theme() === "dark" ? "#c3c7cf" : "#49515e";
  function barPaint(vendor) {
    const gradient = barGradients[vendor];
    if (gradient)
      return { body: `url(#bars-${gradient.id})`, cap: gradient.colors[0] };
    if (vendor === "xAI")
      return { body: "url(#bars-xai)", cap: xaiBarColor() };
    const color = vendor === "Anthropic" && theme() === "light"
      ? "#D97757"
      : vendorColor(vendor);
    return { body: color, cap: color };
  }
  function barPaintDefs() {
    const gradients = Object.values(barGradients).map(({ id, colors, horizontal }) =>
      `<linearGradient id="bars-${id}" x1="0%" y1="0%" x2="${horizontal ? 100 : 0}%" y2="${horizontal ? 0 : 100}%">` +
      colors.map((color, i) => `<stop offset="${100 * i / (colors.length - 1)}%" stop-color="${color}"/>`).join("") +
      `</linearGradient>`,
    ).join("");
    // A quiet diagonal texture distinguishes the monochrome xAI mark from GPT.
    return `<defs>${gradients}<pattern id="bars-xai" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">` +
      `<rect width="7" height="7" fill="${xaiBarColor()}"/><rect width="1" height="7" fill="${palette().page}" fill-opacity="0.24"/>` +
      `</pattern></defs>`;
  }
  function deepseekWaterBar(cx, top, base, width, whaleSize) {
    const h = base - top;
    const nozzle = base + 7 + whaleSize / 4;
    const blue = theme() === "dark" ? "#91DFFF" : "#269FE8";
    // A narrow jet rises from the whale's back and opens into a fountain.
    // Its highest droplet is exactly at the score, never above the data value.
    return `<g class="deepseek-water" transform="translate(${cx},0) scale(${width / 24},1)" aria-hidden="true">` +
      `<path class="bar-body" fill="url(#bars-deepseek-water)" d="M-3.5,${nozzle} C-3.6,${base - h * .38} -5.5,${top + h * .28} -8,${top + 11} Q-10,${top + 5} -12,${top + 9} C-12,${top + 1} -5,${top + 2} 0,${top + 7} C5,${top + 2} 12,${top + 1} 12,${top + 9} Q10,${top + 5} 8,${top + 11} C4,${top + h * .28} -.2,${base - h * .38} -.5,${nozzle} Z"/>` +
      `<path d="M-2,${nozzle - 1} C-2,${base - h * .4} -1.5,${top + h * .25} 0,${top + 13}" fill="none" stroke="#ffffff" stroke-opacity=".55" stroke-width="1"/>` +
      `<path class="bar-cap" d="M-12,${top + 9} C-12,${top + 1} -5,${top + 2} 0,${top + 7} C5,${top + 2} 12,${top + 1} 12,${top + 9}" fill="none" stroke="${blue}" stroke-width="1.5" stroke-linecap="round"/>` +
      `<path d="M0,${top} C-3,${top + 3} -2,${top + 5} 0,${top + 5} C2,${top + 5} 3,${top + 3} 0,${top} Z" fill="${blue}"/>` +
      `<ellipse cx="-14" cy="${top + 14}" rx="1.2" ry="2" fill="${blue}" transform="rotate(28,-14,${top + 14})"/>` +
      `<ellipse cx="14" cy="${top + 13}" rx="1.2" ry="2" fill="${blue}" transform="rotate(-28,14,${top + 13})"/>` +
      `</g>`;
  }
  function renderBars() {
    const C = palette();
    const isCost = barsAxis === "costUsd";
    const isLog = isCost && costScale === "log";
    const rows = barRows();
    const n = rows.length;
    const L = 36,
      R = 4,
      T = isCost ? 52 : 22,
      plotH = 300;
    // Rotated labels hang to the left of their bar, so reserve room for
    // the first few before the plot starts.
    const labelWidth = (r) => (r.name.length + r.effort.length + 1) * 6.6 * 0.72 + 6;
    // Fit more models in view without shrinking labels or removing scrolling.
    const pitch = 36;
    const padLeft = Math.max(
      0,
      ...rows.slice(0, 6).map((r, i) => labelWidth(r) - (L + pitch * i + pitch / 2)),
    );
    const W = Math.round(padLeft + L + R + pitch * n);
    const labelH = Math.ceil(36 + Math.max(...rows.map(labelWidth)) + 8);
    const H = T + plotH + labelH;
    const barW = Math.min(24, Math.round(pitch * 0.67));
    // The axis starts at the multiple of ten below the lowest score, so
    // differences between models stay visible. A break mark shows the cut.
    const max = Math.max(...rows.map((r) => r[barsAxis]));
    const min = Math.min(...rows.map((r) => r[barsAxis]));
    const costStep = max <= 1 ? 0.2 : 0.5;
    const yMax = isCost
      ? Math.max(costStep, Math.ceil(max * 1.08 / costStep) * costStep)
      : Math.ceil((max + 3) / 5) * 5;
    const yMin = isLog ? 10 ** Math.floor(Math.log10(min))
      : isCost ? 0 : Math.max(0, Math.floor((min - 3) / 10) * 10);
    const yStep = isCost ? costStep : yMax - yMin <= 40 ? 5 : 10;
    const scaleValue = isLog ? Math.log10 : (v) => v;
    const y = (v) => T + plotH - ((scaleValue(v) - scaleValue(yMin)) / (scaleValue(yMax) - scaleValue(yMin))) * plotH;
    const ticks = [];
    if (isLog) {
      for (let e = Math.floor(Math.log10(yMin)); e <= Math.ceil(Math.log10(yMax)); e++)
        for (const m of [1, 2, 5]) {
          const v = m * 10 ** e;
          if (v >= yMin && v <= yMax) ticks.push(v);
        }
    } else {
      for (let t = yMin; t <= yMax; t += yStep) ticks.push(t);
    }
    const base = T + plotH;
    const X0 = padLeft + L;
    const valueSize = isCost || pitch < 34 ? 10.5 : 12;
    const svg = [];
    const drawBar = (path, col) => `<path class="bar-body" d="${path}" fill="${col}"/>`;
    svg.push(
      `<svg xmlns="${svgNS}" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="group" aria-label="${escape(
        `${axisNames[barsAxis]}${isCost ? ` in US dollars, ${isLog ? "logarithmic" : "linear"} scale` : ""} by ${barsView === "best" ? "model" : "configuration"}, ${n} bars, sorted from highest to lowest. The axis starts at ${yMin}. Use the arrow keys to move between bars.`,
      )}">`,
    );
    svg.push(barPaintDefs());
    for (const t of ticks) {
      svg.push(
        `<line x1="${X0}" x2="${W - R}" y1="${y(t)}" y2="${y(t)}" stroke="${
          t === yMin ? C.axis : C.grid
        }" stroke-width="1"/><text x="${X0 - (!isCost && yMin > 0 && t === yMin ? 24 : 12)}" y="${y(t) + 4}" text-anchor="end" font-size="12" fill="${C.muted}">${isCost ? `$${t.toFixed(2)}` : t}</text>`,
      );
    }
    if (yMin > 0 && !isCost)
      svg.push(
        `<line x1="${X0 - 18}" x2="${X0}" y1="${base}" y2="${base}" stroke="${C.axis}"/><path d="M${X0 - 16},${base + 4} l3,-8 l3,8 l3,-8" fill="none" stroke="${C.muted}" stroke-width="1.2" style="paint-order:stroke" aria-hidden="true"/>`,
      );
    rows.forEach((r, i) => {
      const cx = X0 + pitch * i + pitch / 2;
      const v = r[barsAxis];
      const top = y(v);
      const h = base - top;
      const x0 = cx - barW / 2;
      const path = `M${x0},${base}V${top}H${x0 + barW}V${base}Z`;
      const src = logoSrc(r, theme());
      const paint = barPaint(r.vendor);
      const isWhale = r.vendor === "DeepSeek";
      const iconSize = isWhale ? 20 : 16;
      const label = `${configName(r)}. ${axisNames[barsAxis]} ${isCost ? money(v) : score(v, barsAxis === "overall" ? 2 : 1)}.`;
      svg.push(
        `<g class="bar-col" data-run="${escape(r.run)}" tabindex="${i === 0 ? 0 : -1}" role="img" aria-label="${escape(label)}">` +
          `<rect class="hit" x="${cx - pitch / 2}" y="${T - 18}" width="${pitch}" height="${plotH + 18 + 34}" rx="3"/>` +
          (isWhale && h >= 24
            ? deepseekWaterBar(cx, top, base, barW, iconSize)
            : drawBar(path, paint.body) +
              `<rect class="bar-cap" x="${x0}" y="${top}" width="${barW}" height="${Math.min(2, h)}" fill="${paint.cap}" aria-hidden="true"/>`) +
          `<text x="${cx}" y="${top - 6}" text-anchor="${isCost ? "start" : "middle"}"${isCost ? ` transform="rotate(-45 ${cx} ${top - 6})"` : ""} font-size="${valueSize}" font-weight="600" fill="${C.ink}">${isCost ? money(v) : score(v, 1)}</text>` +
          (src
            ? `<image href="${escape(src)}" x="${cx - iconSize / 2}" y="${base + (isWhale ? 7 : 9)}" width="${iconSize}" height="${iconSize}" aria-hidden="true"/>`
            : "") +
          `<text transform="translate(${cx + 4},${base + 36}) rotate(-45)" text-anchor="end" font-size="12.5" fill="${C.ink}">${escape(
            r.name,
          )}<tspan fill="${C.muted}"> ${escape(r.effort)}</tspan></text>` +
          `</g>`,
      );
    });
    svg.push("</svg>");
    $("bar-chart").innerHTML = svg.join("");
    syncBarsScroll();
    $("cost-scale-control").hidden = !isCost;
    $("bars-view").querySelector('option[value="best"]').textContent = isCost
      ? "Best Overall configuration per model"
      : "Best configuration per model";
    $("bars-sub").textContent = isCost
      ? `Mean reconstruction cost per scene (USD), ${barsView === "best" ? "using each model’s best Overall configuration" : `all ${n} configurations`}.`
      : `${axisNames[barsAxis]} score of ${
      barsView === "best"
        ? `the configuration with the highest ${axisNames[barsAxis]} for each model`
        : `all ${n} configurations`
    } on all 288 test scenes. Higher is better.`;
    document
      .querySelectorAll("[data-bars-axis]")
      .forEach((b) =>
        b.setAttribute("aria-pressed", String(b.dataset.barsAxis === barsAxis)),
      );
    const cols = [...$("bar-chart").querySelectorAll(".bar-col")];
    const byRun = new Map(data.map((r) => [r.run, r]));
    const show = (g, pinned = false) =>
      showTip(g, dataTipHtml(byRun.get(g.dataset.run), barsAxis), {
        dataTip: true,
        pinned,
        anchor: g.querySelector("path"),
      });
    cols.forEach((g, i) => {
      g.addEventListener("pointerenter", () => show(g));
      g.addEventListener("pointerleave", () => hideTip(true));
      g.addEventListener("click", (e) => {
        e.stopPropagation();
        show(g, true);
      });
      g.addEventListener("focus", () => show(g));
      g.addEventListener("blur", () => hideTip(true));
      g.addEventListener("keydown", (e) => {
        const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
        let next = null;
        if (step) next = cols[Math.max(0, Math.min(cols.length - 1, i + step))];
        if (e.key === "Home") next = cols[0];
        if (e.key === "End") next = cols[cols.length - 1];
        if (!next) return;
        e.preventDefault();
        g.setAttribute("tabindex", "-1");
        next.setAttribute("tabindex", "0");
        next.focus();
        next.scrollIntoView?.({ block: "nearest", inline: "nearest" });
      });
    });
  }
  document.querySelectorAll("[data-bars-axis]").forEach((b) =>
    b.addEventListener("click", () => {
      barsAxis = b.dataset.barsAxis;
      renderBars();
    }),
  );
  $("bars-view").addEventListener("change", () => {
    barsView = $("bars-view").value;
    renderBars();
  });
  $("cost-scale").addEventListener("change", () => {
    costScale = $("cost-scale").value;
    renderBars();
  });
  function syncBarsScroll() {
    const box = document.querySelector(".bars-scroll");
    const max = Math.max(0, box.scrollWidth - box.clientWidth);
    const position = $("bars-position");
    position.max = String(max);
    position.value = String(box.scrollLeft);
    position.disabled = max === 0;
    $("bars-prev").disabled = box.scrollLeft <= 1;
    $("bars-next").disabled = box.scrollLeft >= max - 1;
  }
  const barsScroll = document.querySelector(".bars-scroll");
  barsScroll.addEventListener("scroll", syncBarsScroll, { passive: true });
  $("bars-position").addEventListener("input", (e) => {
    barsScroll.scrollLeft = Number(e.target.value);
    syncBarsScroll();
  });
  for (const [id, direction] of [["bars-prev", -1], ["bars-next", 1]]) {
    $(id).addEventListener("click", () => {
      barsScroll.scrollBy({
        left: direction * barsScroll.clientWidth * 0.75,
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
      });
    });
  }
  renderBars();
  onResize(document.querySelector(".bars-scroll"), renderBars);

  const board = $("board");
  document.querySelectorAll(".view-switch [data-view]").forEach((b) =>
    b.addEventListener("click", () => {
      const view = b.dataset.view;
      board.dataset.view = view;
      document
        .querySelectorAll(".view-switch [data-view]")
        .forEach((o) => o.setAttribute("aria-pressed", String(o.dataset.view === view)));
      hideTip(true);
      if (view === "chart") renderBars();
    }),
  );

  // ---------------------------------------------------------------------
  // Leaderboard
  const COLLAPSED_ROWS = 15;
  let sortKey = "overall",
    bestFirst = true,
    expanded = false;
  function renderLeaderboard() {
    const search = $("model-search")
      .value.trim()
      .toLowerCase()
      .replace(/[-\s]+/g, " ");
    const availability = $("model-type").value;
    const reasoning = $("effort-filter").value;
    const lower = lowerIsBetter.has(sortKey);
    // Rank always counts from the best value of the sorted column.
    const available = data.filter((r) => Number.isFinite(r[sortKey]));
    const unavailable = data.filter((r) => !Number.isFinite(r[sortKey]));
    const merit = [...available].sort(
      (a, b) =>
        (lower ? a[sortKey] - b[sortKey] : b[sortKey] - a[sortKey]) ||
        a.rank - b.rank,
    );
    const ranking = new Map(merit.map((r, i) => [r.run, i + 1]));
    const ordered = [...(bestFirst ? merit : [...merit].reverse()), ...unavailable];
    const shown = ordered.filter((r) => {
      const haystack = `${r.name} ${r.vendor} ${r.effort} ${r.harness}`
        .toLowerCase()
        .replace(/[-\s]+/g, " ");
      return (
        (!search || haystack.includes(search)) &&
        (availability === "all" || (availability === "open") === r.openWeight) &&
        (reasoning === "all" || reasoning === r.effort)
      );
    });
    const filtered = Boolean(search) || availability !== "all" || reasoning !== "all";
    const visible = expanded || filtered ? shown : shown.slice(0, COLLAPSED_ROWS);
    const cell = (r, key, text) =>
      `<td class="num${sortKey === key ? " sorted" : ""}">${text}</td>`;
    $("leaderboard-body").innerHTML = visible
      .map((r) => {
        const rank = ranking.get(r.run) ?? "—";
        return `<tr><td class="num rank${rank <= 3 ? " top" : ""}">${rank}</td><td class="model-cell">${modelCell(
          r,
        )}</td>${cell(r, "overall", score(r.overall, 2))}${cell(
          r,
          "dualVqa",
          score(r.dualVqa),
        )}${cell(r, "latentSim", score(r.latentSim))}${cell(
          r,
          "costUsd",
          money(r.costUsd),
        )}</tr>`;
      })
      .join("");
    $("task-body").innerHTML = shown
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
      .join("");
    const toggle = $("toggle-rows");
    toggle.hidden = filtered || shown.length <= COLLAPSED_ROWS;
    toggle.textContent = expanded
      ? `Show the first ${COLLAPSED_ROWS} only`
      : `Show all ${shown.length} configurations`;
    toggle.setAttribute("aria-expanded", String(expanded));
    $("result-count").textContent =
      visible.length === data.length
        ? `${data.length} configurations`
        : `${visible.length} of ${data.length} configurations`;
    $("empty-state").hidden = shown.length > 0;
    document.querySelectorAll("#results-table th[data-column]").forEach((th) => {
      th.removeAttribute("aria-sort");
      if (th.dataset.column === sortKey) {
        const ascending = lower === bestFirst;
        th.setAttribute("aria-sort", ascending ? "ascending" : "descending");
      }
    });
  }
  document.querySelectorAll("[data-column-sort]").forEach((b) =>
    b.addEventListener("click", () => {
      const key = b.dataset.columnSort;
      if (sortKey === key) bestFirst = !bestFirst;
      else {
        sortKey = key;
        bestFirst = true;
      }
      renderLeaderboard();
    }),
  );
  $("model-search").addEventListener("input", renderLeaderboard);
  $("model-type").addEventListener("change", renderLeaderboard);
  $("effort-filter").addEventListener("change", renderLeaderboard);
  $("toggle-rows").addEventListener("click", () => {
    expanded = !expanded;
    renderLeaderboard();
    if (!expanded) $("toggle-rows").scrollIntoView({ block: "nearest" });
  });
  $("reset-filters").addEventListener("click", () => {
    $("model-search").value = "";
    $("model-type").value = "all";
    $("effort-filter").value = "all";
    renderLeaderboard();
    $("model-search").focus();
  });
  renderLeaderboard();

  // ---------------------------------------------------------------------
  // Score and cost
  let chartAxis = "overall";
  let selectedRun = null;
  let chartX = null,
    chartY = null;
  // Label the two ends of the frontier for the shown score, the cheapest
  // configuration and the highest scoring one.
  let landmarkRuns = [],
    landmarkNames = {};
  const pointRadius = () => 5.5;
  function drawSelection(r) {
    const C = palette();
    const ladder = $("family-ladder"),
      ring = $("selection-ring");
    if (!ladder || !ring || !chartX) return;
    const rungs = costRows
      .filter((d) => d.family === r.family && d.harness === r.harness)
      .sort((a, b) => effortOrder.indexOf(a.effort) - effortOrder.indexOf(b.effort));
    ladder.innerHTML =
      rungs.length > 1
        ? `<polyline points="${rungs
            .map((d) => `${chartX(d.costUsd).toFixed(1)},${chartY(d[chartAxis]).toFixed(1)}`)
            .join(" ")}" fill="none" stroke="${C.ink}" stroke-width="1.5" stroke-opacity=".6" stroke-linejoin="round"/>`
        : "";
    const cx = chartX(r.costUsd),
      cy = chartY(r[chartAxis]);
    ring.innerHTML = `<circle cx="${cx}" cy="${cy}" r="${pointRadius(r) + 4.5}" fill="none" stroke="${C.ink}" stroke-width="2"/>`;
  }
  function showPoint(run) {
    const r = data.find((row) => row.run === run);
    if (!r) {
      $("point-detail").innerHTML = "";
      return;
    }
    selectedRun = run;
    $("point-detail").innerHTML = `<h4>${escape(r.name)} <span class="effort-text">${escape(
      r.effort,
    )}</span></h4><dl><div><dt>Overall</dt><dd>${score(r.overall, 2)}</dd></div><div><dt>Dual VQA</dt><dd>${score(
      r.dualVqa,
    )}</dd></div><div><dt>Latent Similarity</dt><dd>${score(
      r.latentSim,
    )}</dd></div><div><dt>Cost per scene</dt><dd>${money(r.costUsd)}</dd></div></dl>`;
    document.querySelectorAll(".plot-point").forEach((p) => {
      const on = p.dataset.run === run;
      p.setAttribute("aria-pressed", String(on));
      p.setAttribute("tabindex", on ? "0" : "-1");
    });
    drawSelection(r);
  }
  function placeLabels(svgPoints, W, L, R, T, bottom, small = false) {
    const C = palette();
    // Greedy placement that avoids points and earlier labels.
    const boxes = [];
    const hitsPoint = (b) =>
      svgPoints.some(
        (p) =>
          p.x + p.r + 2 > b.x0 &&
          p.x - p.r - 2 < b.x1 &&
          p.y + p.r + 2 > b.y0 &&
          p.y - p.r - 2 < b.y1,
      );
    const overlaps = (b) =>
      boxes.some((o) => o.x0 < b.x1 && o.x1 > b.x0 && o.y0 < b.y1 && o.y1 > b.y0);
    const out = [];
    for (const run of landmarkRuns) {
      const p = svgPoints.find((q) => q.run === run);
      if (!p) continue;
      const [name, effortLabel] = landmarkNames[run];
      const w = (small ? name.length : name.length + effortLabel.length + 1) * 7.1,
        h = 15;
      const candidates = [
        [-12, -12, "end"],
        [12, -12, "start"],
        [-12, 18, "end"],
        [12, 18, "start"],
        [0, -20, "middle"],
        [0, 28, "middle"],
        [-14, -32, "end"],
        [14, -32, "start"],
        [-14, 40, "end"],
        [14, 40, "start"],
        [-10, 4, "end"],
        [10, 4, "start"],
      ];
      for (const [dx, dy, anchor] of candidates) {
        const tx = p.x + dx,
          ty = p.y + dy;
        const x0 = anchor === "end" ? tx - w : anchor === "middle" ? tx - w / 2 : tx;
        const b = { x0, x1: x0 + w, y0: ty - h + 3, y1: ty + 3 };
        if (b.x0 < L || b.x1 > W - R || b.y0 < T - 4 || b.y1 > bottom) continue;
        if (hitsPoint(b) || overlaps(b)) continue;
        boxes.push(b);
        const far = Math.abs(dy) > 24;
        out.push(
          (far
            ? `<line x1="${p.x}" y1="${p.y + (dy < 0 ? -p.r - 1 : p.r + 1)}" x2="${
                anchor === "middle" ? tx : tx + (anchor === "end" ? 2 : -2)
              }" y2="${dy < 0 ? ty + 3 : ty - h + 3}" stroke="${C.ink}" stroke-opacity=".45" stroke-width="1"/>`
            : "") +
            `<text x="${tx}" y="${ty}" text-anchor="${anchor}" fill="${C.ink}" font-size="13" font-weight="600" paint-order="stroke" stroke="${C.page}" stroke-width="4" stroke-linejoin="round" pointer-events="none">${escape(
              name,
            )}${small ? "" : `<tspan fill="${C.muted}" font-weight="500"> ${escape(effortLabel)}</tspan>`}</text>`,
        );
        break;
      }
    }
    return out.join("");
  }
  function renderCostChart() {
    const C = palette();
    const box = $("cost-chart");
    const W = Math.max(300, Math.round(box.clientWidth || 700));
    const small = W < 560;
    const H = Math.round(Math.max(300, Math.min(470, W * 0.6)));
    const L = 44,
      R = 14,
      T = 22,
      B = 48;
    const lo = 0.01,
      hi = 3;
    const x = (v) =>
      L + ((Math.log10(v) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo))) * (W - L - R);
    const values = costRows.map((r) => r[chartAxis]);
    const yMin = Math.floor((Math.min(...values) - 1) / 5) * 5;
    const yMax = Math.ceil((Math.max(...values) + 1) / 5) * 5;
    const yStep = small && yMax - yMin > 20 ? 10 : 5;
    const y = (v) => T + ((yMax - v) / (yMax - yMin)) * (H - T - B);
    chartX = x;
    chartY = y;
    const s = [];
    s.push(
      `<svg xmlns="${svgNS}" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="group" aria-labelledby="cost-title cost-description"><title id="cost-title">${
        axisNames[chartAxis]
      } against mean cost per scene</title><desc id="cost-description">${
        costRows.length
      } configurations. Logarithmic cost axis from 1 cent to 3 dollars. Score axis from ${yMin} to ${yMax}. Select a point with a click, Enter, or Space. Arrow keys move between points.</desc>`,
    );
    for (let t = yMin; t <= yMax; t += yStep)
      s.push(
        `<line x1="${L}" y1="${y(t)}" x2="${W - R}" y2="${y(t)}" stroke="${C.grid}"/><text x="${
          L - 10
        }" y="${y(t) + 4}" text-anchor="end" fill="${C.muted}" font-size="12">${t}</text>`,
      );
    for (const t of small ? [0.01, 0.1, 0.5, 3] : [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 3])
      s.push(
        `<line x1="${x(t)}" y1="${H - B}" x2="${x(t)}" y2="${H - B + 5}" stroke="${C.axis}"/><text x="${x(
          t,
        )}" y="${H - B + 21}" text-anchor="middle" fill="${C.muted}" font-size="12">$${
          t < 1 ? t.toFixed(2) : t
        }</text>`,
      );
    s.push(
      `<line x1="${L}" y1="${H - B}" x2="${W - R}" y2="${H - B}" stroke="${C.axis}"/><text x="${L}" y="${
        T - 8
      }" fill="${C.ink}" font-size="12.5" font-weight="600">${axisNames[chartAxis]}</text><text x="${
        (L + W - R) / 2
      }" y="${H - 8}" fill="${C.muted}" font-size="12.5" text-anchor="middle">Mean cost per scene in US dollars, log scale</text>`,
    );
    const byCost = [...costRows].sort((a, b) => a.costUsd - b.costUsd || b[chartAxis] - a[chartAxis]);
    let best = -Infinity;
    const frontier = [];
    for (const r of byCost)
      if (r[chartAxis] > best) {
        frontier.push(r);
        best = r[chartAxis];
      }
    let path = `M${x(frontier[0].costUsd)},${y(frontier[0][chartAxis])}`;
    for (const r of frontier.slice(1)) path += `H${x(r.costUsd)}V${y(r[chartAxis])}`;
    path += `H${W - R}`;
    const ends = [frontier[0], frontier[frontier.length - 1]].filter(
      (r, i, all) => all.findIndex((o) => o.run === r.run) === i,
    );
    landmarkRuns = ends.map((r) => r.run);
    landmarkNames = Object.fromEntries(ends.map((r) => [r.run, [r.name, r.effort]]));
    s.push(
      `<path d="${path}" fill="none" stroke="${C.overall}" stroke-width="2" stroke-opacity=".85"/><g id="family-ladder" pointer-events="none"></g>`,
    );
    const pts = [];
    for (const r of [...costRows].reverse()) {
      const cx = x(r.costUsd),
        cy = y(r[chartAxis]),
        rad = pointRadius(r);
      pts.push({ run: r.run, x: cx, y: cy, r: rad });
      const label = `${configName(r)}. ${axisNames[chartAxis]} ${score(
        r[chartAxis],
        chartAxis === "overall" ? 2 : 1,
      )}. ${money(r.costUsd)} per scene.`;
      s.push(
        `<g class="plot-point" data-run="${escape(r.run)}" tabindex="-1" role="button" aria-pressed="false" aria-label="${escape(
          label,
        )}"><circle cx="${cx.toFixed(2)}" cy="${cy.toFixed(2)}" r="${Math.max(12, rad + 6)}" fill="transparent"/><circle cx="${cx.toFixed(
          2,
        )}" cy="${cy.toFixed(2)}" r="${rad}" fill="${vendorColor(r.vendor)}" stroke="${C.page}" stroke-width="1.5"/><title>${escape(
          label,
        )}</title></g>`,
      );
    }
    s.push(`<g id="selection-ring" pointer-events="none"></g>`);
    s.push(placeLabels(pts, W, L, R, T, H - B, small));
    s.push("</svg>");
    box.innerHTML = s.join("");
    const points = [...box.querySelectorAll(".plot-point")];
    const orderBy = (key) =>
      [...costRows].sort((a, b) => a[key] - b[key] || a.costUsd - b.costUsd).map((r) => r.run);
    points.forEach((p) => {
      p.addEventListener("click", (e) => {
        e.stopPropagation();
        showPoint(p.dataset.run);
      });
      p.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          showPoint(p.dataset.run);
          return;
        }
        const horizontal = e.key === "ArrowLeft" || e.key === "ArrowRight";
        const vertical = e.key === "ArrowUp" || e.key === "ArrowDown";
        if (!horizontal && !vertical && e.key !== "Home" && e.key !== "End") return;
        e.preventDefault();
        const order = orderBy(vertical ? chartAxis : "costUsd");
        let i = order.indexOf(p.dataset.run);
        if (e.key === "ArrowRight" || e.key === "ArrowUp") i++;
        if (e.key === "ArrowLeft" || e.key === "ArrowDown") i--;
        if (e.key === "Home") i = 0;
        if (e.key === "End") i = order.length - 1;
        i = Math.max(0, Math.min(order.length - 1, i));
        showPoint(order[i]);
        box.querySelector(`.plot-point[data-run="${CSS.escape(order[i])}"]`)?.focus();
      });
    });
    document
      .querySelectorAll("[data-chart-axis]")
      .forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.chartAxis === chartAxis)));
    if (selectedRun) showPoint(selectedRun);
    else {
      // Keyboard entry point before anything is selected.
      const first = orderBy("costUsd")[0];
      box.querySelector(`.plot-point[data-run="${CSS.escape(first)}"]`)?.setAttribute("tabindex", "0");
    }
  }
  $("chart-legend").innerHTML = legendHtml(new Set(costRows.map((r) => r.vendor)));
  document.querySelectorAll("[data-chart-axis]").forEach((b) =>
    b.addEventListener("click", () => {
      chartAxis = b.dataset.chartAxis;
      renderCostChart();
    }),
  );
  renderCostChart();
  onResize($("cost-chart"), renderCostChart);

  const themeButton = $("theme-toggle");
  const syncThemeColor = () => {
    const color = getComputedStyle(root).getPropertyValue("--page").trim();
    document.querySelectorAll('meta[name="theme-color"]').forEach((m) => m.setAttribute("content", color));
  };
  function applyTheme() {
    const dark = theme() === "dark";
    syncThemeColor();
    themeButton.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
    renderBars();
    renderCostChart();
    $("chart-legend").innerHTML = legendHtml(new Set(costRows.map((r) => r.vendor)));
  }
  themeButton.addEventListener("click", () => {
    const next = theme() === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    try {
      localStorage.setItem("bvb-theme", next);
    } catch (e) {}
    applyTheme();
  });
  darkQuery.addEventListener?.("change", () => {
    if (!root.dataset.theme) applyTheme();
  });
  themeButton.setAttribute("aria-label", theme() === "dark" ? "Switch to light mode" : "Switch to dark mode");
  if (root.dataset.theme) syncThemeColor();


  // ---------------------------------------------------------------------
  // Comparison viewer. One clock drives both videos, including seek,
  // model changes, and looping.
  const source = $("source-video"),
    render = $("render-video"),
    videos = [source, render];
  const PREVIEW_SECONDS = 30,
    PREVIEW_FRAMES = 720;
  const sceneNames = {};
  document.querySelectorAll("[data-scene]").forEach((b) => {
    sceneNames[b.dataset.scene] = b.firstChild.textContent.trim().toLowerCase();
  });
  let currentScene = gallery[0],
    currentModel = "astra",
    fraction = 0,
    playing = false,
    busy = false,
    userPaused = false,
    raf = 0,
    version = 0,
    operation = 0;
  const pendingLoads = new WeakMap();
  const playButton = $("play-comparison");
  const toolbar = $("playback-toolbar");
  const icons = {
    play: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5 3v10l8-5z" fill="currentColor"/></svg>',
    pause:
      '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 3h2.5v10H4.5zM9 3h2.5v10H9z" fill="currentColor"/></svg>',
  };
  videos.forEach((v) => {
    v.controls = false;
    v.loop = true;
    v.muted = true;
  });
  function setBusy(value) {
    busy = value;
    toolbar.setAttribute("aria-busy", String(value));
    playButton.setAttribute("aria-disabled", String(value));
  }
  function setButton() {
    playButton.innerHTML = playing ? icons.pause : icons.play;
    playButton.setAttribute("aria-label", playing ? "Pause both videos" : "Play both videos");
  }
  function updateTimeline(value) {
    fraction = Math.max(0, Math.min(1, value));
    const input = $("comparison-time");
    const seconds = (fraction * PREVIEW_SECONDS).toFixed(1);
    input.value = String(Math.round(fraction * PREVIEW_FRAMES));
    input.setAttribute("aria-valuetext", `${seconds} of ${PREVIEW_SECONDS} seconds`);
    $("time-output").textContent = `${seconds} / ${PREVIEW_SECONDS} s`;
    $("ruler").style.setProperty("--at-num", fraction.toFixed(4));
  }
  function pause() {
    operation++;
    playing = false;
    videos.forEach((v) => v.pause());
    cancelAnimationFrame(raf);
    setBusy(false);
    setButton();
  }
  function frame() {
    if (!playing) return;
    if (!source.seeking && !render.seeking && source.duration > 0 && render.duration > 0) {
      const f = source.currentTime / source.duration;
      if (Math.abs(render.currentTime - f * render.duration) > 0.14)
        render.currentTime = Math.min(f * render.duration, render.duration - 0.02);
      updateTimeline(f);
    }
    raf = requestAnimationFrame(frame);
  }
  function updateGalleryInfo() {
    const m = currentScene.models[currentModel];
    const scene = sceneNames[currentScene.id] || currentScene.title.toLowerCase();
    $("source-label").textContent = `${currentScene.dataset} ${currentScene.id}`;
    source.setAttribute("aria-label", `Source video, ${scene} scene`);
    render.setAttribute("aria-label", `${m.name} reconstruction, ${scene} scene`);
    $("example-scores").innerHTML = `Dual VQA <b>${score(m.dualVqa ?? NaN)}</b><span class="sep"></span>Latent Similarity <b>${score(m.latentSim)}</b>`;
    $("media-note").textContent = `Both previews are time-scaled to 30 seconds, so one point on the timeline shows the same relative moment in each video. Scores are for this scene and model.${
      m.dualVqa === null
        ? " Dual VQA is undefined for this scene because the judge answered no question correctly on the source video."
        : ""
    }`;
    document
      .querySelectorAll("[data-scene]")
      .forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.scene === currentScene.id)));
  }
  function changeExample() {
    const resume = playing && !userPaused;
    version++;
    pause();
    updateTimeline(0);
    $("media-error").hidden = true;
    toolbar.hidden = false;
    videos.forEach((v, i) => {
      const stem = `assets/media/${currentScene.id}-${i === 0 ? "source" : currentModel}`;
      v.controls = false;
      v.poster = `${stem}.jpg`;
      v.src = `${stem}.mp4`;
      v.preload = "metadata";
      v.load();
    });
    updateGalleryInfo();
    if (resume) synchronize(0, true);
  }
  function ready(video, token) {
    if (token !== version) return Promise.reject(new Error("changed"));
    if (video.readyState >= 1 && Number.isFinite(video.duration) && video.duration > 0)
      return Promise.resolve();
    const pending = pendingLoads.get(video);
    if (pending?.token === token) return pending.promise;
    const promise = new Promise((resolve, reject) => {
      const done = () => {
        cleanup();
        token === version ? resolve() : reject(new Error("changed"));
      };
      const failed = () => {
        cleanup();
        reject(new Error("media"));
      };
      const cleanup = () => {
        clearTimeout(timeout);
        video.removeEventListener("loadedmetadata", done);
        video.removeEventListener("error", failed);
        if (pendingLoads.get(video)?.token === token) pendingLoads.delete(video);
      };
      const timeout = setTimeout(failed, 15000);
      video.addEventListener("loadedmetadata", done, { once: true });
      video.addEventListener("error", failed, { once: true });
      video.preload = "auto";
      video.load();
    });
    pendingLoads.set(video, { token, promise });
    return promise;
  }
  function seekVideo(video, position, token, request) {
    const time = Math.max(0, Math.min(position * video.duration, video.duration - 0.03));
    return new Promise((resolve, reject) => {
      const done = () => {
        if (
          token === version &&
          request === operation &&
          (video.seeking || video.readyState < 2 || Math.abs(video.currentTime - time) > 0.1)
        )
          return;
        cleanup();
        resolve();
      };
      const failed = () => {
        cleanup();
        reject(new Error("media"));
      };
      const cleanup = () => {
        clearTimeout(timeout);
        video.removeEventListener("seeked", done);
        video.removeEventListener("loadeddata", done);
        video.removeEventListener("error", failed);
      };
      const timeout = setTimeout(failed, 15000);
      video.addEventListener("seeked", done);
      video.addEventListener("loadeddata", done);
      video.addEventListener("error", failed, { once: true });
      try {
        video.currentTime = time;
        done();
      } catch (e) {
        cleanup();
        reject(e);
      }
    });
  }
  async function synchronize(position, shouldPlay) {
    const token = version,
      request = ++operation;
    const current = () => token === version && request === operation;
    playing = shouldPlay;
    videos.forEach((v) => v.pause());
    cancelAnimationFrame(raf);
    updateTimeline(position);
    setButton();
    setBusy(true);
    try {
      await Promise.all(videos.map((v) => ready(v, token)));
      if (!current()) return;
      await Promise.all(videos.map((v) => seekVideo(v, position, token, request)));
      if (!current()) return;
      if (playing) await Promise.all(videos.map((v) => v.play()));
      if (!current()) return;
      $("media-error").hidden = true;
    } catch (e) {
      if (current()) {
        pause();
        $("media-error").textContent =
          "A video did not load, so the two videos cannot play together. Use the controls on each video, or reload the page.";
        $("media-error").hidden = false;
        toolbar.hidden = true;
        videos.forEach((v) => (v.controls = true));
      }
    } finally {
      if (current()) {
        setBusy(false);
        setButton();
        if (playing) raf = requestAnimationFrame(frame);
      }
    }
  }
  playButton.addEventListener("click", () => {
    if (busy) return;
    if (playing) {
      userPaused = true;
      pause();
    } else {
      userPaused = false;
      synchronize(fraction, true);
    }
  });
  $("comparison-time").addEventListener("input", () => {
    synchronize(Number($("comparison-time").value) / PREVIEW_FRAMES, playing);
  });
  // Pointer scrubbing, so a tap or drag anywhere on the ruler seeks.
  const ruler = $("ruler");
  let dragging = false,
    dragQueued = 0,
    dragFraction = 0,
    resumeAfterDrag = false;
  const rulerFraction = (e) => {
    const rect = ruler.getBoundingClientRect();
    return Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
  };
  ruler.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    dragging = true;
    resumeAfterDrag = playing;
    ruler.setPointerCapture(e.pointerId);
    dragFraction = rulerFraction(e);
    synchronize(dragFraction, false);
    e.preventDefault();
  });
  ruler.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    dragFraction = rulerFraction(e);
    updateTimeline(dragFraction);
    if (!dragQueued)
      dragQueued = requestAnimationFrame(() => {
        dragQueued = 0;
        synchronize(dragFraction, false);
      });
  });
  const endDrag = () => {
    if (!dragging) return;
    dragging = false;
    cancelAnimationFrame(dragQueued);
    dragQueued = 0;
    synchronize(dragFraction, resumeAfterDrag);
    $("comparison-time").focus({ preventScroll: true });
  };
  ruler.addEventListener("pointerup", endDrag);
  ruler.addEventListener("pointercancel", endDrag);
  document.querySelectorAll("[data-scene]").forEach((b) =>
    b.addEventListener("click", () => {
      currentScene = gallery.find((s) => s.id === b.dataset.scene);
      changeExample();
    }),
  );
  $("example-model").addEventListener("change", () => {
    currentModel = $("example-model").value;
    changeExample();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) pause();
  });
  // Autoplay once when the viewer is in view on a wide screen, unless the
  // reader prefers reduced motion, saves data, or has paused it.
  const canAutoplay = () =>
    window.matchMedia("(min-width: 721px)").matches &&
    !window.matchMedia("(prefers-reduced-motion: reduce)").matches &&
    !navigator.connection?.saveData;
  if ("IntersectionObserver" in window)
    new IntersectionObserver(
      (entries) => {
        const entry = entries[entries.length - 1];
        if (!entry.isIntersecting) {
          if (playing) pause();
        } else if (entry.intersectionRatio >= 0.5 && !playing && !busy && !userPaused && canAutoplay()) {
          synchronize(fraction, true);
        }
      },
      { threshold: [0, 0.5] },
    ).observe($("examples"));
  setButton();
  updateTimeline(0);
  updateGalleryInfo();

  // ---------------------------------------------------------------------
  // Citation
  $("copy-citation").addEventListener("click", async () => {
    const button = $("copy-citation"),
      status = $("copy-status");
    const text = $("citation-text").textContent;
    status.textContent = "";
    try {
      if (!navigator.clipboard || !window.isSecureContext) throw new Error("clipboard");
      await navigator.clipboard.writeText(text);
      button.textContent = "Copied";
      setTimeout(() => (status.textContent = "BibTeX copied to the clipboard."), 50);
    } catch (e) {
      const range = document.createRange();
      range.selectNodeContents($("citation-text"));
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      button.textContent = "Selected";
      setTimeout(
        () => (status.textContent = "BibTeX selected. Press Command C or Control C to copy it."),
        50,
      );
    }
    setTimeout(() => (button.textContent = "Copy BibTeX"), 2500);
  });
})();
