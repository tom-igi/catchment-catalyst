// Takes the numbered screenshots of the dashboards shown at /admin/screenshots.
//
// Each screenshot is a dashboard page with a number on each part of it, the number of the table
// its data comes from: the same number as on that table's box on the admin page. It reads the
// numbers from the admin page (so from diagram.yaml), opens each page of the published dashboard
// in a headless browser, puts the numbers on it and saves it here, with screenshots.json, which
// lists what each number is on each screenshot.
//
// Run it on your own machine, with the dashboards published and the admin page running
// (docker compose up -d): see README.md in this folder.
//
//     node backend/catalyst/admin/screenshots/take.mjs
//
// Settings, from the environment (each has a default that suits `docker compose up -d`):
//     CHROME            the browser: Chromium, Chrome or Playwright's chrome-headless-shell
//     DASHBOARD_URL     the published location's address (http://localhost:8080/north-devon/)
//     ADMIN_URL         the admin page's address (http://localhost:8000)
//     ADMIN_NAME, ADMIN_PASSWORD     a login for it (admin, admin)
//     WATERBODY         the waterbody shown on the Waterbody Dashboard (GB108050014340, Lower Little
//                       River Dart: it has something in every panel)
//
// When a panel is added, moved or renamed on the dashboard, change SHOTS below and take them
// again. It stops if something it's to number isn't on the page, and warns if a table the
// admin page lists on a page isn't numbered on its screenshot.

import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CHROME = process.env.CHROME ||
  path.join(os.homedir(), ".cache/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-linux64/chrome-headless-shell");
const DASHBOARD = (process.env.DASHBOARD_URL || "http://localhost:8080/north-devon/").replace(/\/?$/, "/");
const ADMIN = (process.env.ADMIN_URL || "http://localhost:8000").replace(/\/$/, "");
const LOGIN = { name: process.env.ADMIN_NAME || "admin", password: process.env.ADMIN_PASSWORD || "admin" };
const WATERBODY = process.env.WATERBODY || "GB108050014340";
const WIDTH = 1600;  // wide enough for the EA Data page's whole table
const SCALE = 1.35;  // pixels per CSS pixel, so the text is sharp when zoomed in
const QUALITY = 84;  // WebP quality
const MAX_HEIGHT = 1250;  // CSS pixels: longer pages are cut off, with a fade (or the shot's `maxHeight`)

// ---------------------------------------------------------------------------------------------
//  What's numbered on each screenshot
// ---------------------------------------------------------------------------------------------
//
// Each part: `sel`, a CSS selector (every element it matches is one part, unless `each`, which
// numbers each separately), optionally only those containing `text`; `what`, what it is, for the
// list under the screenshot; and `tables`, where its data comes from (table names, as in
// schema.yaml). `at` places the numbers: on its top left corner (the default), "tr" (top right),
// "left" (just left of it), "before" (left of its first line), or {x, y} (a point on it, as a
// fraction of its width and height: {x: 1, y: 1} is its bottom right corner). `outline: false` for
// small things, which only get the number; `small` for smaller numbers.
//
// `diagram` is the pages (and "page: panel"s) in diagram.yaml's `dashboard` list that the
// screenshot shows, to check every table listed there is numbered on it.

const INFO_BUTTONS = { sel: "button.info", each: true, at: { x: 1, y: 0 }, outline: false, small: true,
  what: 'The text in each "i" button', tables: ["datasets"] };
const TEXT_UNDER = { sel: "section.about", what: "The text under the dashboard", tables: ["location_text"] };

// The column down the left of every Waterbody Dashboard tab.
const LEFT_COLUMN = [
  { sel: "#map", at: { x: .5, y: .06 }, outline: false, what: "Map: each waterbody's outline and river", tables: ["catchments"] },
  { sel: "#map", at: { x: .5, y: .06 }, outline: false, what: "Map colours: each waterbody's 2025 ecological class", tables: ["waterbody_figures"] },
  { sel: "#map", at: { x: .5, y: .06 }, outline: false, what: "Map colours, for a waterbody with no 2025 class", tables: ["ea_classifications"] },
  { sel: "form.postcode", at: "tr", what: "The postcode search", tables: ["postcodes"] },
  { sel: ".catchment-list", at: { x: .93, y: .5 }, what: "The list of waterbodies (names, and the areas they're listed by)", tables: ["catchments"] },
  { sel: ".catchment-list", at: { x: .93, y: .5 }, what: "Which waterbodies are on this dashboard", tables: ["locations"] },
  { sel: ".ranking", at: { x: .96, y: 1 }, what: "Catchment Ranking", tables: ["waterbody_figures"] },
  { sel: ".classification .years li:first-child", what: "EA Ecological Classification: 2025", tables: ["waterbody_figures"] },
  { sel: ".classification .years li:not(:first-child)", what: "EA Ecological Classification: the years before 2025", tables: ["ea_classifications"] },
  { sel: ".side .pair .panel:first-child", at: "tr", what: "Failing Elements", tables: ["ea_classifications"] },
  { sel: ".side .pair .panel:last-child", at: "tr", what: "EA RNAGs", tables: ["ea_rnags"] },
  { sel: "h1.title-bar", at: { x: .03, y: .5 }, outline: false, what: "The waterbody's name", tables: ["catchments"] },
];

const riskTile = (name, table) =>
  ({ sel: ".risks li", text: name, outline: false, small: true, what: `Risk Levels: ${name}`, tables: [table] });
const ESME_TILES = ["Modification", "Invasive Species", "Overheating", "Runoff", "Running Dry"].map(n => riskTile(n, "esme_risk_levels"));

const waterbody = page => `${page}/${WATERBODY}/`;
const focusArea = id => `document.getElementById(${JSON.stringify("tab-" + id)}).click()`;

const SHOTS = [
  {
    file: "1-river-status", title: "Waterbody Dashboard: River Status", url: waterbody("river-status"),
    diagram: ["Every Waterbody tab", "River Status", "Every dashboard page"], from: ".dashboard", to: "section.about",
    parts: [
      ...LEFT_COLUMN,
      { sel: ".why", what: "Why is the river failing?", tables: ["river_status_text"] },
      { sel: ".now", what: "What is happening now?", tables: ["river_status_text"] },
      { sel: ".hypothesis", what: "Intervention hypothesis, and its confidence", tables: ["river_status_text"] },
      riskTile("Untreated Sewage", "sewage_overflow_pressure"),
      riskTile("Sewage (Private)", "waterbody_figures"),
      riskTile("Livestock", "livestock_pressure"),
      ...ESME_TILES,
      { sel: ".interventions", at: { x: .3, y: 0 }, what: "Interventions: each intervention's name, and the group it's in", tables: ["intervention_types"] },
      { sel: ".interventions", at: { x: .3, y: 0 }, what: "Interventions: which this waterbody needs, with their size, cost and lead", tables: ["intervention_waterbodies"] },
      INFO_BUTTONS, TEXT_UNDER,
    ],
  },
  {
    file: "2-ea-data", title: "Waterbody Dashboard: EA Data", url: waterbody("ea-data"),
    diagram: ["Every Waterbody tab", "EA Data", "Every dashboard page"], from: ".dashboard", to: "section.about",
    parts: [
      ...LEFT_COLUMN,
      { sel: [".scoring thead tr:first-child th.group:not(:last-child)", ".scoring thead tr:last-child th:not(.first-threshold):not(.first-threshold ~ th)",
               ".scoring tbody td:not(.first-threshold):not(.first-threshold ~ td)"].join(", "),
        at: { x: .3, y: 0 }, what: "Environment Agency Scoring: the statuses (e.g. Moderate, High) and their colours", tables: ["ea_classifications"] },
      { sel: [".scoring thead tr:first-child th.group:not(:last-child)", ".scoring thead tr:last-child th:not(.first-threshold):not(.first-threshold ~ th)",
               ".scoring tbody td:not(.first-threshold):not(.first-threshold ~ td)"].join(", "),
        at: { x: .3, y: 0 }, what: "Environment Agency Scoring: the measured values (e.g. 0.744)", tables: ["ea_scores"] },
      { sel: ".scoring tbody tr:first-child td:nth-of-type(2)", small: true, at: { x: .5, y: 1.35 },
        what: "Environment Agency Scoring: Ecological in 2025", tables: ["waterbody_figures"] },
      { sel: ".scoring thead th.group:last-child, .scoring .first-threshold, .scoring .first-threshold ~ *",
        what: "Environment Agency Scoring: the thresholds", tables: ["ea_thresholds"] },
      INFO_BUTTONS, TEXT_UNDER,
    ],
  },
  {
    file: "3-land-use-data", title: "Waterbody Dashboard: Land Use Data", url: waterbody("land-use"),
    diagram: ["Every Waterbody tab", "Land Use Data", "Every dashboard page"], from: ".dashboard", to: "section.about",
    parts: [
      ...LEFT_COLUMN,
      { sel: ".river-info", what: "River Information: area, length, river system, upstream and downstream rivers", tables: ["waterbody_figures"] },
      { sel: ".river-info tbody tr:first-child td", at: "left", outline: false, small: true, what: "River Information: Catchment ID", tables: ["catchments"] },
      { sel: ".habitat", what: "Habitat and Land Usage", tables: ["habitat_land_use"] },
      ...ESME_TILES,
      riskTile("Livestock", "livestock_pressure"),
      { sel: ".obstacles", what: "River Obstacles (the map and the table)", tables: ["river_obstacles"] },
      { sel: ".farms", what: "Number of Farms", tables: ["waterbody_figures"] },
      { sel: ".livestock", what: "Livestock Pressures", tables: ["livestock"] },
      { sel: ".phosphate", what: "Phosphate source (estimated)", tables: ["phosphate_sources"] },
      INFO_BUTTONS, TEXT_UNDER,
    ],
  },
  {
    file: "4-sewerage-data", title: "Waterbody Dashboard: Sewerage Data", url: waterbody("sewerage"),
    diagram: ["Every Waterbody tab", "Sewerage Data", "Every dashboard page"], from: ".dashboard", to: "section.about",
    parts: [
      ...LEFT_COLUMN,
      { sel: ".intermittent", what: "Intermittent Discharges (the explanation)", tables: ["location_text"] },
      { sel: ".discharges", what: "Intermittent Sewage Discharges (hrs per year)", tables: ["storm_overflows"] },
      { sel: ".outlets", what: "Outlet Locations", tables: ["storm_overflows"] },
      { sel: ".properties", what: "Properties on public and private sewerage", tables: ["waterbody_figures"] },
      { sel: ".continuous", what: "Continuous Discharge (the explanation)", tables: ["location_text"] },
      { sel: ".phosphate", what: "Source of Phosphate", tables: ["phosphate_point_diffuse"] },
      riskTile("Untreated Sewage", "sewage_overflow_pressure"),
      riskTile("Sewage (Private)", "waterbody_figures"),
      { sel: ".plans", what: "Asset Improvement Plans", tables: ["sewerage_improvements"] },
      INFO_BUTTONS, TEXT_UNDER,
    ],
  },
  {
    file: "5-catchment-dashboard", title: "Catchment Dashboard", url: "catchment-dashboard/",
    note: "Each operational catchment's page (the buttons on the left) is the same, for its waterbodies only.",
    diagram: ["Catchment Dashboard", "Every dashboard page"], from: ".dashboard", to: "section.about",
    parts: [
      { sel: "#map", at: { x: .4, y: .3 }, outline: false, what: "Map: each waterbody's outline and river", tables: ["catchments"] },
      { sel: "#map", at: { x: .4, y: .3 }, outline: false, what: "Map colours: each waterbody's 2025 ecological class", tables: ["waterbody_figures"] },
      { sel: "#map", at: { x: .4, y: .3 }, outline: false, what: "Map colours, for a waterbody with no 2025 class", tables: ["ea_classifications"] },
      { sel: ".cd-areas", at: "tr", what: "The management and operational catchments (each waterbody's, from the EA)", tables: ["catchments"] },
      { sel: ".cd-counts", at: "tr", what: "Ecological Class 2025 counts", tables: ["waterbody_figures"] },
      { sel: ".cd-counts", at: "tr", what: "Ecological Class counts, for a waterbody with no 2025 class", tables: ["ea_classifications"] },
      { sel: ".cd-story", what: "Why is the river system failing?, What is happening now? and Intervention hypothesis (a button each)", tables: ["location_text"] },
      { sel: ".cd-figures .pill", text: "Farms", at: "left", what: "Number of Farms (added up)", tables: ["waterbody_figures"] },
      { sel: ".cd-figures .pill", text: "Properties", at: "left", what: "Properties on public and private sewerage (added up)", tables: ["waterbody_figures"] },
      { sel: ".cd-figures .pill", text: "outflows", at: "left", what: "Sewage outflows (CSO & STW): how many", tables: ["storm_overflows"] },
      { sel: ".cd-habitat", what: "Habitat and Land Usage (added up)", tables: ["habitat_land_use"] },
      INFO_BUTTONS, TEXT_UNDER,
    ],
  },
  {
    file: "6-critical-path", title: "Intervention Management: Critical Path", url: "intervention-management/",
    diagram: ["Intervention Management: Critical Path"], from: ".focus", to: "#critical-path", setup: focusArea("critical-path"),
    parts: [{ sel: "#critical-path", what: "Critical Path", tables: ["location_text"] }],
  },
  {
    file: "7-unit-cost", title: "Intervention Management: Unit Cost of Interventions", url: "intervention-management/",
    diagram: ["Intervention Management: Unit Cost of Interventions"], from: ".focus", to: "#unit-cost-of-interventions", setup: focusArea("unit-cost-of-interventions"),
    parts: [
      { sel: "#unit-cost-of-interventions > .focus-body:not(.unit-cost)", what: "Unit Cost of Interventions: the Purpose", tables: ["location_text"] },
      { sel: "#unit-cost-of-interventions > .unit-cost", what: "Unit Cost of Interventions: each intervention's costs", tables: ["intervention_unit_costs"] },
    ],
  },
  {
    file: "8-intervention-summary", title: "Intervention Management: Intervention Summary", url: "intervention-management/",
    diagram: ["Intervention Management: Intervention Summary"], from: ".focus", to: "#intervention-summary", setup: focusArea("intervention-summary"),
    parts: [
      { sel: "#intervention-summary > :not(h2):not(.scroll-x)", at: "before", what: "Intervention Summary: the text above the table", tables: ["location_text"] },
      { sel: "#intervention-summary .summary-table", at: "before", what: "Intervention Summary: the table (a row for each intervention)", tables: ["intervention_types"] },
    ],
  },
  {
    file: "9-interventions-detail", title: "Intervention Management: Interventions Detail", url: "intervention-management/",
    note: "Intervention 8 is shown: each of the others has the same layout.", maxHeight: 1700,
    diagram: ["Intervention Management: Interventions Detail"], from: ".focus", to: "#interventions-detail", setup: focusArea("interventions-detail") + "; " + focusArea("intervention-8"),
    parts: [
      { sel: ".detail-buttons", at: "tr", what: "Interventions Detail: the buttons (each intervention's short name)", tables: ["intervention_types"] },
      { sel: "#intervention-8 > :not(.group):not(.group ~ *)", at: "before",  // everything above the first heading over the waterbodies
        what: "Interventions Detail: each intervention's title, overview and progress", tables: ["intervention_types"] },
      { sel: "#intervention-8 > h4.group", each: true, at: "before", outline: false, small: true,
        what: "Interventions Detail: the headings over the waterbodies", tables: ["intervention_types"] },
      { sel: "#intervention-8 .intervention-table", each: true, at: "before", what: "Interventions Detail: the waterbodies that need it, with size, cost, funding, delivery and lead", tables: ["intervention_waterbodies"] },
    ],
  },
  {
    file: "10-community-action", title: "Intervention Management: Community Action", url: "intervention-management/",
    diagram: ["Intervention Management: Community Action"], from: ".focus", to: "#community-action", setup: focusArea("community-action"),
    parts: [{ sel: "#community-action", what: "Community Action", tables: ["location_text"] }],
  },
  {
    file: "11-catchment-insights", title: "Catchment Insights", url: "catchment-insights/",
    note: "Not from the database: its questions and answers are written in the code, in " +
          "backend/catalyst/publish/content/north-devon/catchment-insights.yaml.",
    diagram: [], from: ".focus", to: ".focus-panel:not([hidden])",
    parts: [], label: { sel: ".focus-panel:not([hidden]) > h2", text: "Not in the database" },
  },
];

// ---------------------------------------------------------------------------------------------
//  Taking them
// ---------------------------------------------------------------------------------------------

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function adminModel() {
  // Log in to the admin page and read its model: every table, with its number.
  const login = await fetch(`${ADMIN}/admin/login`, {
    method: "POST", redirect: "manual", body: new URLSearchParams({ name: LOGIN.name, password: LOGIN.password }),
  });
  const cookie = (login.headers.get("set-cookie") || "").split(";")[0];
  if (login.status !== 303 || !cookie) throw new Error(`Couldn't log in to ${ADMIN}/admin as ${LOGIN.name} (set ADMIN_NAME and ADMIN_PASSWORD)`);
  const page = await (await fetch(`${ADMIN}/admin`, { headers: { cookie } })).text();
  const found = page.match(/<script id="model" type="application\/json">([\s\S]*?)<\/script>/);
  if (!found) throw new Error(`${ADMIN}/admin doesn't have the diagram's model`);
  return JSON.parse(found[1]);
}

async function browser() {
  if (!fs.existsSync(CHROME)) throw new Error(`No browser at ${CHROME}: set CHROME to Chromium or Chrome`);
  const port = 9400 + Math.floor(Math.random() * 400);
  const chrome = spawn(CHROME, [`--remote-debugging-port=${port}`, "--headless=new", "--no-sandbox", "--hide-scrollbars",
    "--force-color-profile=srgb", `--window-size=${WIDTH},1000`, "about:blank"], { stdio: "ignore" });
  let target;
  for (let i = 0; i < 100 && !target; i++) {
    try { target = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(t => t.type === "page"); } catch { /* not up yet */ }
    if (!target) await sleep(150);
  }
  if (!target) { chrome.kill(); throw new Error("The browser didn't start"); }
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  let id = 0;
  const waiting = new Map();
  ws.onmessage = message => {
    const data = JSON.parse(message.data);
    if (data.id && waiting.has(data.id)) { waiting.get(data.id)(data); waiting.delete(data.id); }
  };
  const send = (method, params = {}) => new Promise(resolve => { const n = ++id; waiting.set(n, resolve); ws.send(JSON.stringify({ id: n, method, params })); });
  const run = async expression => {
    const reply = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (reply.error || reply.result.exceptionDetails) throw new Error(JSON.stringify(reply.error || reply.result.exceptionDetails));
    return reply.result.result.value;
  };
  await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: WIDTH, height: 1000, deviceScaleFactor: SCALE, mobile: false });
  return { send, run, close: () => { ws.close(); chrome.kill(); } };
}

async function load(b, url) {  // url null: wait for the page that's open
  if (url) await b.send("Page.navigate", { url });
  for (let i = 0; i < 100; i++) {  // the page, its fonts and the map's pictures
    await sleep(150);
    const ready = await b.run(`document.readyState === "complete" &&
      [...document.querySelectorAll("img.leaflet-tile")].every(img => img.classList.contains("leaflet-tile-loaded"))`).catch(() => false);
    if (ready) break;
  }
  await b.run("document.fonts.ready.then(() => true)");
  await sleep(600);  // the maps' last moves
}

// Runs in the page: puts the numbers on it, and says what it couldn't find.
function annotate(parts, label, colour) {
  const css = `
    #shot-numbers { position: absolute; left: 0; top: 0; z-index: 2147483647; pointer-events: none; }
    #shot-numbers .shot-box { position: absolute; border: 3px dashed ${colour}; border-radius: 9px;
      box-shadow: 0 0 0 1.5px rgba(255,255,255,.85), inset 0 0 0 1.5px rgba(255,255,255,.85); }
    #shot-numbers .shot-tags { position: absolute; display: flex; gap: 5px; margin: 0; padding: 0; }
    #shot-numbers .shot-n { display: grid; place-items: center; min-width: 30px; height: 30px; padding: 0 7px; border-radius: 15px;
      background: ${colour}; color: #fff; font: 800 16px/1 "Segoe UI", Arial, sans-serif; font-variant-numeric: tabular-nums;
      box-shadow: 0 0 0 2.5px #fff, 0 2px 7px rgba(0,0,0,.5); }
    #shot-numbers .shot-small .shot-n { min-width: 25px; height: 25px; padding: 0 6px; border-radius: 13px; font-size: 13.5px;
      box-shadow: 0 0 0 2px #fff, 0 1px 5px rgba(0,0,0,.5); }
    #shot-numbers .shot-label { padding: 10px 18px; height: auto; border-radius: 22px; font-size: 22px; white-space: nowrap; }`;
  const layer = document.createElement("div");
  layer.id = "shot-numbers";
  const style = document.createElement("style");
  style.textContent = css;
  const boxes = document.createElement("div");  // the outlines, under all the numbers
  layer.append(style, boxes);
  document.body.appendChild(layer);

  const rectOf = elements => {
    const rs = elements.map(e => e.getBoundingClientRect());
    return {
      left: Math.min(...rs.map(r => r.left)) + scrollX, top: Math.min(...rs.map(r => r.top)) + scrollY,
      right: Math.max(...rs.map(r => r.right)) + scrollX, bottom: Math.max(...rs.map(r => r.bottom)) + scrollY,
    };
  };
  const shown = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== "hidden"; };
  const rows = new Map();  // where numbers have been put -> their row, so a part's numbers go side by side
  const missing = [];

  function tagsAt(r, at, small) {
    const key = [r.left, r.top, r.right, r.bottom].map(Math.round).join() + JSON.stringify(at);
    if (rows.has(key)) return rows.get(key);
    const row = document.createElement("div");
    row.className = "shot-tags" + (small ? " shot-small" : "");
    const w = r.right - r.left, h = r.bottom - r.top;
    // Centred on the point: its corner, or a point inside it; or just left of it.
    let x, y, shift = "translate(-50%, -50%)";
    if (at === "left") { x = r.left - 6; y = r.top + h / 2; shift = "translate(-100%, -50%)"; }
    else if (at === "before") { x = r.left - 10; y = r.top + 16; shift = "translate(-100%, -50%)"; }
    else if (at === "tr") { x = r.right; y = r.top; }
    else if (at && typeof at === "object") { x = r.left + w * at.x; y = r.top + h * at.y; }
    else { x = r.left; y = r.top; }
    Object.assign(row.style, { left: x + "px", top: y + "px", transform: shift });
    layer.appendChild(row);
    rows.set(key, row);
    return row;
  }

  for (const part of parts) {
    let found = [...document.querySelectorAll(part.sel)].filter(shown);
    if (part.text) found = found.filter(e => e.textContent.includes(part.text));
    if (!found.length) { missing.push(part.sel + (part.text ? ` containing "${part.text}"` : "")); continue; }
    for (const group of part.each ? found.map(e => [e]) : [found]) {
      const r = rectOf(group);
      if (part.outline !== false) {
        const key = "box" + [r.left, r.top, r.right, r.bottom].map(Math.round).join();
        if (!rows.has(key)) {
          const box = document.createElement("div");
          box.className = "shot-box";
          Object.assign(box.style, { left: r.left + "px", top: r.top + "px", width: (r.right - r.left) + "px", height: (r.bottom - r.top) + "px" });
          boxes.appendChild(box);
          rows.set(key, box);
        }
      }
      const row = tagsAt(r, part.at, part.small);
      for (const number of part.numbers) {
        if ([...row.children].some(n => n.textContent === String(number))) continue;
        const n = document.createElement("span");
        n.className = "shot-n";
        n.textContent = number;
        row.appendChild(n);
      }
    }
  }
  // Move numbers that would cover each other apart, sideways, and keep them all inside the picture.
  const tagRows = [...layer.querySelectorAll(".shot-tags")];
  const nudge = (row, by) => { row.style.left = (parseFloat(row.style.left) + by) + "px"; };
  for (let pass = 0; pass < 3; pass++) {
    tagRows.forEach((row, i) => {
      for (const other of tagRows.slice(0, i)) {
        const a = row.getBoundingClientRect(), b = other.getBoundingClientRect();
        if (a.right + 4 <= b.left || b.right + 4 <= a.left || a.bottom + 2 <= b.top || b.bottom + 2 <= a.top) continue;
        nudge(row, (a.left + a.right) / 2 >= (b.left + b.right) / 2 ? b.right + 4 - a.left : b.left - 4 - a.right);
      }
    });
  }
  for (const row of tagRows) {
    const r = row.getBoundingClientRect();
    nudge(row, r.left < 4 ? 4 - r.left : r.right > innerWidth - 4 ? innerWidth - 4 - r.right : 0);
  }
  if (label) {
    const target = document.querySelector(label.sel);
    if (!target) missing.push(label.sel);
    else {
      const row = tagsAt(rectOf([target]), { x: .7, y: .5 }, false);
      const n = document.createElement("span");
      n.className = "shot-n shot-label";
      n.textContent = label.text;
      row.appendChild(n);
    }
  }
  return missing;
}

async function take(b, shot, numbers) {
  await b.send("Emulation.setDeviceMetricsOverride", { width: WIDTH, height: 1000, deviceScaleFactor: SCALE, mobile: false });
  await load(b, DASHBOARD + shot.url);
  if (shot.setup) { await b.run(shot.setup); await sleep(400); }
  // The window as tall as the page, so it's laid out as it will be in the screenshot before it's numbered.
  for (let i = 0, height = 0; i < 4; i++) {
    const now = await b.run("document.documentElement.scrollHeight");
    if (now === height) break;
    height = now;
    await b.send("Emulation.setDeviceMetricsOverride", { width: WIDTH, height, deviceScaleFactor: SCALE, mobile: false });
    await b.run("scrollTo(0, 0)");
    await sleep(500);
  }
  await load(b, null);
  const parts = shot.parts.map(p => ({ ...p, numbers: p.tables.map(t => numbers.get(t)) }));
  const missing = await b.run(`(${annotate})(${JSON.stringify(parts)}, ${JSON.stringify(shot.label || null)}, "#c2006b")`);
  if (missing.length) throw new Error(`${shot.title}: couldn't find ${missing.join("; ")}`);

  // From the top of `from` to the bottom of `to`; or, for the text under the dashboard, a little of it.
  const box = await b.run(`(() => {
    const from = document.querySelector(${JSON.stringify(shot.from)}).getBoundingClientRect();
    const to = document.querySelector(${JSON.stringify(shot.to)}).getBoundingClientRect();
    const under = ${JSON.stringify(shot.to)} === "section.about";
    return { top: from.top + scrollY - (under ? 0 : 12), bottom: under ? to.top + scrollY + 150 : to.bottom + scrollY + 14 };
  })()`);
  const top = Math.max(0, Math.floor(box.top));
  let height = Math.ceil(box.bottom) - top;
  const most = shot.maxHeight || MAX_HEIGHT;
  if (height > most || shot.to === "section.about") {  // fade out where it's cut off
    height = Math.min(height, most);
    await b.run(`(() => { const f = document.createElement("div");
      Object.assign(f.style, { position: "absolute", left: 0, width: "100%", top: ${top + height - 70} + "px", height: "70px",
        background: "linear-gradient(rgba(255,255,255,0), #fff)", zIndex: 2147483646, pointerEvents: "none" });
      document.body.appendChild(f); })()`);
  }
  const reply = await b.send("Page.captureScreenshot", {
    format: "webp", quality: QUALITY,
    clip: { x: 0, y: top, width: WIDTH, height, scale: 1 },
  });
  if (!reply.result) throw new Error(`${shot.title}: the screenshot failed: ${JSON.stringify(reply.error)}`);
  const file = shot.file + ".webp";
  fs.writeFileSync(path.join(HERE, file), Buffer.from(reply.result.data, "base64"));

  const byTable = new Map();
  for (const p of shot.parts) for (const t of p.tables) {
    if (!byTable.has(t)) byTable.set(t, []);
    if (!byTable.get(t).includes(p.what)) byTable.get(t).push(p.what);
  }
  return {
    file, title: shot.title, url: shot.url, note: shot.note || null,
    width: Math.round(WIDTH * SCALE), height: Math.round(height * SCALE),
    numbers: [...byTable].map(([table, what]) => ({ number: numbers.get(table), table, what })).sort((a, b) => a.number - b.number),
  };
}

const model = await adminModel();
const numbers = new Map(model.tables.filter(t => Number.isInteger(t.number)).map(t => [t.name, t.number]));
const unnumbered = [...new Set(SHOTS.flatMap(s => s.parts.flatMap(p => p.tables)))].filter(t => !numbers.has(t));
if (unnumbered.length) throw new Error(`No number for ${unnumbered.join(", ")}: give each one in diagram.yaml's \`numbers\``);

const b = await browser();
const shots = [];
try {
  for (const shot of SHOTS) {
    shots.push(await take(b, shot, numbers));
    // The tables the admin page says are on this page, but which aren't numbered on it.
    const numbered = new Set(shot.parts.flatMap(p => p.tables));
    const shows = place => shot.diagram.some(e => e === place.page || place.panels.some(panel => e === `${place.page}: ${panel}`));
    const listed = model.tables.filter(t => (t.dashboard || []).some(shows)).map(t => t.name);
    const left = [...new Set(listed)].filter(t => !numbered.has(t));
    console.log(`${shot.file}.webp` + (left.length ? `  (not numbered, but diagram.yaml lists it on this page: ${left.join(", ")})` : ""));
  }
} finally {
  b.close();
}
const waterbodyName = model.tables && (await fetch(DASHBOARD + waterbody("river-status")).then(r => r.text()))
  .match(/<h1 class="title-bar">([^<]*)<\/h1>/)?.[1];
const taken = new Date().toISOString().slice(0, 10);
fs.writeFileSync(path.join(HERE, "screenshots.json"), JSON.stringify({
  taken, dashboard: DASHBOARD, waterbody: { id: WATERBODY, name: waterbodyName || null }, shots,
}, null, 2) + "\n");
console.log(`Saved ${shots.length} screenshots and screenshots.json in ${HERE}`);
