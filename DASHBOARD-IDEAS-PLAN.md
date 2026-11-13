# Plan: seven new versions of the North Devon dashboard

Written 12 November 2026, agreed with Tom. When Tom says "execute DASHBOARD-IDEAS-PLAN.md" (or
similar), build everything below without stopping to ask, unless something blocks you.

Tom will look at all seven and choose the one he likes best, or mix ideas from several. These are
for choosing a design, not for going live.

---

## 1. The rules (read these first)

- **Don't change anything that already exists.** That means no changes to `backend/`, the
  database, `schema.yaml`, `published/north-devon/`, `.gitignore`, the Docker files or the
  tests. Only read from them. The only things you add are the new folder below (and a short
  note in PROGRESS.md at the end, see section 9).
- **Everything goes in `published/north-devon-ideas/`.** You can see it at
  <http://localhost:8080/north-devon-ideas/> while `docker compose up -d` is running. Publish only
  replaces `published/north-devon/` and `published/index.html` (see `write_location` and
  `write_index` in `backend/catalyst/publish/site.py`), so pressing Publish won't delete this
  folder. Like everything in `published/`, it isn't kept in git, and that's fine.
- **Static pages only.** Each version is plain HTML, CSS and JavaScript files that a web server
  serves as they are, with no server-side code and no build step (no npm, React, bundlers or
  frameworks). JavaScript running in the browser is fine (the current dashboard uses it too).
- **Frozen data.** Each version shows the data as it is on the day you build it. The versions
  won't update when Publish is pressed, and that's agreed.
- **Nothing from the internet, except map tiles.** Use the copy of Leaflet already in
  `published/north-devon/assets/leaflet/`. Draw charts by hand with SVG (no chart libraries).
  Don't use web fonts. Map backgrounds can use the same OpenStreetMap tiles as the current
  dashboard (`https://tile.openstreetmap.org/{z}/{x}/{y}.png`, with its attribution), or no
  background at all.
- **The same information in every version.** Every item in the checklist in section 4 must be
  somewhere in every version. The versions differ in how people find and read it, not in what's
  there. Don't make up any figures or text: everything shown comes from the data export.
- **Each version must be truly different:** a different starting point, a different way of moving
  around, a different look. The old layout (four cards across the top, four tabs, coloured
  panels) shouldn't come back in any of them.
- **Colours and fonts can change completely.** Each version gets its own look (ideas are given in
  section 6). The one exception is the EA status colours. High, Good, Moderate, Poor and Bad must
  keep the same blue, green, yellow, orange and red meaning in every version (shades can be
  adjusted), always with a key.

---

## 2. Make it look like Tom made it, not like AI made it

Tom asked for these not to look AI-made. They should look like a careful person built them by
hand for North Devon. That means:

**Don't:**
- use purple, indigo or blue-violet gradients, gradient text, glowing shadows, frosted glass or
  blur effects
- put everything in identical rounded cards with soft drop shadows, or make rows of three or four
  "stat tiles" (big number, small grey label, icon)
- use emoji, sparkles, or an icon in front of every heading
- make big centred "hero" sections with a headline, a subheading and two buttons
- write marketing copy such as "Unlock insights", "Dive into", "Explore the power of",
  "at a glance", "seamless", "your journey", taglines or exclamation marks
- Use Title Case On Every Heading, or em dashes all over the text
- use pill badges and "chips" everywhere, or tiny pale-grey text
- use the neon-on-black "analytics dashboard" look
- animate for the sake of it (things fading in as you scroll, cards lifting on hover)
- use the same font stack in every version (or default `system-ui` everywhere)

**Do:**
- use the dashboard's own words. The data already has plain headings such as "Why is the river
  failing?" and "What is happening now?". Write headings in sentence case and British English.
- write labels plainly and briefly, as Tom does in PROGRESS.md
- align text to the left, with a clear order of importance and generous text sizes (16px or more
  for body text)
- use ordinary tables where a table is the clearest way to show something
- use thin rules and borders rather than shadows, square or nearly square corners (0 to 4px),
  and a small palette (one or two colours of its own, plus the EA status colours)
- pick fonts that come with Windows and Mac, a different set for each version, always with
  fallbacks. Tom views these on Windows. Good choices are Georgia, Cambria, Constantia,
  Palatino Linotype, Verdana, Tahoma, Trebuchet MS, Segoe UI, Calibri, Candara, Corbel,
  Franklin Gothic Medium, Bahnschrift, Arial Narrow and Consolas.
- make some small, specific choices a person would make: a sensible default river, a "last
  updated" line, the contact email from the about text, the data credits at the bottom
- write the code by hand, readably, with short comments in plain English (like the existing files
  in `backend/catalyst/publish/static/`)

**Keep it clear for the public:**
- explain every abbreviation the first time it appears, or on hover: RNAG (reasons for not
  achieving good status), EQR (ecological quality ratio), RWB (river water body), CSO (combined
  sewer overflow), STW (sewage treatment works), SWW (South West Water), AMP8/AMP9 (the water
  company's 2025–2030 and 2030–2035 investment plans)
- every colour has a key, every number has its unit, and every chart has a heading saying what
  it shows
- show the "i" texts (what each dataset is and where it comes from) wherever that data appears.
  Use a small "About this data" link or a note under the table, not a mystery icon.
- empty data says so plainly (for example "No storm overflows in this waterbody"), rather than
  showing an empty box
- it must work on a laptop (1366 to 1920px wide) and still be usable on a phone (390px wide)

---

## 3. Step 1: export the data (do this yourself, before any version)

Make one data file that every version reads. Use the publish step's own code, **read-only**, so
the figures match what Publish would show:

- `collect.locations(...)` and `collect.collect(conn, schema, row)` from
  `backend/catalyst/publish/collect.py`, then `Figures(location)` from `figures.py`. The templates
  in `backend/catalyst/publish/templates/` show which method gives which panel.
- **Don't call `publish_all`.** It adds a row to the `publishes` table. Open the connection
  with `conn.execute(sa.text("SET TRANSACTION READ ONLY"))` first.
- Run your export script without adding it to the repo, by piping it into the publish container
  (it mounts the code read-only and has the database settings):
  ```bash
  mkdir -p published/north-devon-ideas/shared/data
  docker compose run --rm -T --no-deps --entrypoint python publish - < /path/to/scratch/export.py > published/north-devon-ideas/shared/data/north-devon.json
  ```
  (Keep the script in your scratchpad. Make sure it only prints the JSON to stdout, with logs
  going to stderr. If `--no-deps` causes a problem, drop it: the database is already running.)
- Turn the hand-written text into HTML with `text.formatted()` (and `text.boxes()` for Critical
  Path), so text shows the same as on the dashboard. That covers bullets, bold, links and
  `###` sections that open and close.
- Keep numbers as numbers. Also copy the formatting rules into a shared `shared/format.js`
  (`_number`, `_pounds`, `_about_pounds`, `_hours` in `site.py`, and `measured` in `figures.py`),
  so money shows as "£2.04m" and "c.£387.9m" in the same way everywhere.
- Catchment Insights questions come from
  `backend/catalyst/publish/content/north-devon/catchment-insights.yaml` (use `site.catchment_insights("north-devon")`).
  **Note:** the last publish (15:18 on 12 November) came before this file was filled in, so
  the published Insights page shows no questions yet. Use the YAML file. Most questions don't
  have answers yet: answers of `"..."` are placeholders, so show those questions with "Answer to
  follow".
- Also include **every year** of each waterbody's ecological status from `Figures.ecological`
  (2009 to 2022), not only the three the dashboard shows. Only the Timeline version (7) uses the
  extra years.
- Copy `published/north-devon/catchments.geojson` to `shared/data/catchments.geojson`. It has a
  polygon and a river line for each waterbody, each with `id`, `name`, `layer` and `status`.
- Copy `published/north-devon/assets/leaflet/` to `shared/leaflet/`.

A suggested shape for `north-devon.json` (adjust it if the code suggests something better):

```text
location     id, name, slug, published date ("12 November 2026"), number of rivers (92),
             water company ("South West Water"), status order, classification years shown,
             latest year, credits (the footer text in templates/base.html)
text         every Location Text field as HTML (about_waterbody_dashboard,
             about_catchment_dashboard, why_failing, happening_now, intervention_hypothesis,
             intermittent_discharges, continuous_discharge, critical_path (as a list of
             boxes), unit_costs_purpose, intervention_summary, community_action, and any others)
info         each dataset's "i" text: table, title, HTML
areas        North Devon plus its 3 operational catchments: kind, name, slug, parent,
             waterbody ids, class counts, farms / public / private sewerage totals (with
             "known of" notes), overflow count, habitat totals
waterbodies  one per waterbody, everything in checklist B below: id, name, operational
             catchment, area, river length, upstream/downstream ids, classification (3 years),
             all ecological years, ranking, failing elements, RNAGs, river text (3 texts +
             confidence), all 8 risks, interventions (grouped), scoring (years, rows,
             thresholds), habitat, obstacles (with lat/lon), farms, livestock, phosphate,
             phosphate by Continuous/Diffuse, discharges (sites x years), outlets (lat/lon/name),
             properties, improvements
interventions  summary parts with totals, overall total, the 12 types (all fields, progress
             HTML, waterbody tables by group heading), unit costs
insights     the 8 focus areas in order: title, groups, questions, answer HTML or null
```

**Check the export** against the current pages before building anything. For example:
- North Devon has 92 waterbodies (Good 13, Moderate 63, Poor 15, Bad 1), 4,263 farms (91 of
  92 waterbodies), 54,478 properties on SWW sewerage, 66,604 on private sewerage, and 152
  outflows. The interventions overall total is c.£387.9m, of which c.£368.8m is available.
- Torridge (Source to Dipple Water), `GB108050014390`, ranks 52/92 and has 69 farms. Its risks are
  Untreated Sewage Very Low, Modification Medium, Sewage (Private) Very Low, Invasive Species
  High, Livestock Medium, Overheating Medium, Runoff Medium and Running Dry Very Low.

If the export disagrees, check whether data has been uploaded since the last publish (the
`uploads` and `publishes` tables) before assuming the export is wrong. Don't "fix" the database.

**Before writing sentences about rankings,** check which way they run (is 1 the best?).
Compare the rankings of Good and Poor waterbodies in the export.

---

## 4. The information checklist (every version shows all of this)

**A. North Devon as a whole**
1. Location name, published date, and "92 river waterbodies in the North Devon Catchment"
2. A map of every waterbody, coloured by ecological status, with its key and the river lines
3. Counts by status (High, Good, Moderate, Poor, Bad, Total) for North Devon and for each of the
   3 operational catchments (Hartland and Clovelly Streams, Taw and North Devon Streams, Torridge)
4. Why is the river system failing? What is happening now? Intervention hypothesis
   (location text)
5. For North Devon and each operational catchment: number of farms (with the "91 of 92
   waterbodies" note), properties on SWW sewerage, properties on private sewerage, and SWW
   sewage outflows (CSO and STW)
6. Habitat and land use totals for each of those areas (habitat, area in ha, % of catchment)
7. The about texts: "Understanding the dashboard" (about_waterbody_dashboard, with all its
   sections) and about_catchment_dashboard. These include the contact email.
8. The data credits (footer) and the "i" texts for every dataset

**B. Each of the 92 waterbodies**
1. Name, EA ID, operational catchment
2. Catchment ranking (e.g. 52/92), with its "i" text
3. EA ecological classification for 2022, 2019 and 2016
4. Failing elements, and the EA's RNAGs (reasons for not achieving good)
5. Why is the river failing? What is happening now? Intervention hypothesis (with its confidence)
6. All 8 risk levels (Untreated Sewage, Modification, Sewage (Private), Invasive Species,
   Livestock, Overheating, Runoff, Running Dry), each Very Low to Very High, with the "i" text
7. Interventions needed, grouped as on the River Status page (Priority / Secondary): intervention
   (with its note), size, estimated cost and lead, each linking to that intervention's details
8. EA scoring: every classification item, the latest value and the values for 2025, 2022, 2019
   and 2016, each coloured by status, with the Poor, Moderate, Good and High thresholds
9. River information: area (ha), river length (km), upstream and downstream rivers (as links)
10. Habitat and land use: habitat, area (ha), % of catchment, relative coverage
11. River obstacles: on a map, and as a table (EA ID, site name, obstacle type, origin)
12. Number of farms
13. Livestock: type, number, density per km², density rating
14. Phosphate sources (estimated): % by source for 2025 and 2030, and the same grouped as
    Continuous or Diffuse
15. The "Intermittent Discharges" and "Continuous Discharge" explanations (location text, shown
    with the sewage information)
16. SWW intermittent sewage discharges: hours per year for each site, 2021 to 2025, with totals
    per site and per year, and the outlet locations on a map
17. Properties on SWW sewerage, properties on private sewerage, and private sewerage per ha
18. SWW asset improvement plans: site, improvements, completion date, predicted spills per year

**C. Intervention Management**
1. Critical path to Good Ecological Status (its boxes, in order)
2. Unit cost of interventions: the purpose text, then all 12 (title, intervention, delivery lead,
   typical cost, funding route, cost confidence, notes)
3. Intervention summary: the introduction, then the table in its parts (Priority, Secondary).
   It shows number and name, No. of RWBs, estimated cost, % available, % delivered ("Data to
   follow" where missing) and lead, with each part's total and the overall total ("c.£387.9m, of
   which c.£368.8m available, and … to be found").
4. Interventions detail for all 12: the overview (description, lead delivery organisation, number
   of RWBs, estimated total cost, funding available, funding gap, funding route, ecological
   benefit, confidence in costings), the progress text, and its waterbody tables under their
   group headings (river water body, size, estimated cost, funding available, started delivery,
   finished delivery, lead)
5. Community Action text

**D. Catchment Insights**
1. The 8 focus areas (State of the Catchment, Agriculture, Wastewater, Fish, Intervention Strategy,
   Funding & Delivery, Community Involvement, Other) with their titles, group headings and
   every question, plus answers where they exist ("Answer to follow" where they don't)
2. The note that this section is still being developed

---

## 5. The folder

```text
published/north-devon-ideas/
  index.html             the page for choosing between them (section 7)
  shared/
    data/north-devon.json
    data/catchments.geojson
    leaflet/             copied from published/north-devon/assets/leaflet/
    format.js            number and money formatting, and loading the data (nothing visual)
  1-map/                 each version: index.html plus its own .css and .js files
  2-story/
  3-table/
  4-questions/
  5-network/
  6-cause-and-effect/
  7-timeline/
```

Versions may share only `shared/`. Each has its own stylesheet and scripts, so the designs stay
independent. Use the URL hash (`#GB108050014390`, or a short path in the hash) for the selected
waterbody, so the back button works and a link to a river can be shared.

---

## 6. The seven versions

Each section says what the idea is, how people move around it, where the checklist items go,
and a starting point for the look. Use your own judgement on the details, but keep to the idea
and the rules in sections 1 and 2.

### Version 1: The map is the dashboard (`1-map/`)

**Idea:** the whole screen is the map, and everything starts from a place.

**How it works:**
- A full-screen Leaflet map of North Devon. A small block in the top left holds the name and a
  **"Colour the rivers by"** list:
  - Ecological status 2022 (the default)
  - Catchment ranking
  - Any one of the 8 risks
  - Storm overflow hours (2021 to 2025 total)
  - Number of farms
  - "Rivers needing…" one of the 12 interventions
  
  The key changes to match. Tick boxes show storm overflow outlets and river obstacles as dots.
- Hovering over a waterbody shows its name and the value being shown. Clicking one opens a
  **panel on the right** (a bottom sheet on a phone) with everything about it, in sections that
  open and close. Its summary (status by year, ranking, failing elements, RNAGs) stays at the
  top, followed by:
  - Why is it failing?
  - What's happening now
  - What would fix it (hypothesis, confidence and interventions)
  - Risks
  - EA measurements (the scoring table)
  - Land and farming (river information, habitat, farms, livestock, phosphate)
  - Sewage (the two explanations, the discharges table, properties, improvement plans)
  - Obstacles
  
  When the sewage or obstacles section opens, those points stand out on the main map. "Go
  upstream" and "Go downstream" buttons move to the next waterbody and pan the map there.
- With nothing selected, the panel shows the **area summary**. You choose North Devon or one of
  the 3 operational catchments, the map zooms to it, and the panel shows the counts, the three
  location texts, the totals and the habitat totals.
- Buttons along the bottom open full-height pages over the map:
  - **"Fixing the rivers"**: all of Intervention Management as one page with a list of
    contents. Each intervention has a "Show these rivers on the map" button, which colours the
    map by that intervention and closes the page.
  - **"Questions"**: Catchment Insights
  - **"About this map"**: the about texts, "i" texts and credits

**Look:** like a walker's field map and guide. Warm paper-coloured panels, dark ink text, one river
blue as the accent, 1px dark borders, no shadows. Use Verdana or Tahoma for labels and Trebuchet MS
for headings.

### Version 2: The river's story (`2-story/`)

**Idea:** it reads like a long article in a newspaper or magazine. You scroll down and it explains
things in order, with a map that changes as you read.

**How it works:**
- **The front page** is "The state of North Devon's rivers". The map is pinned to the right on
  a laptop and changes chapter by chapter (use IntersectionObserver). The chapters are:
  1. 92 rivers, and how they're doing (counts, map by status)
  2. Why they're failing (the location text, including its five groups)
  3. What's happening now
  4. The three operational catchments, one short section each: counts, totals and habitat,
     with the map zoomed to each
  5. The fix: intervention hypothesis, critical path, summary table and totals
  6. Each of the 12 interventions as a short sub-chapter: overview, unit cost, progress, and
     the rivers it's needed in (linking to their stories)
  7. Community action
  8. Questions people ask (Insights)
  9. About and credits
  
  A "Read about a river" index sits at the end and in the header: names grouped by
  operational catchment, plus a small map.
- **A river's story** (`river.html#GB…`) starts with a plain headline, for example "Torridge
  (Source to Dipple Water) is at Moderate status". Under it is a short paragraph built from the
  ranking and the status for 2016, 2019 and 2022. Then come the chapters:
  1. Why it's failing (text, failing elements, RNAGs)
  2. What's been measured (each scoring item as a dot on a Poor–Moderate–Good–High scale, with
     the full table under "See the numbers")
  3. What's on the land (river information, habitat as a bar, farms, livestock, phosphate
     sources with 2025 next to 2030)
  4. Sewage (the two explanations, overflow hours per site per year, properties, improvement
     plans)
  5. Obstacles (the map zooms in and the table)
  6. Risks (all 8 as a plain rated list)
  7. What happens next (what's happening now, hypothesis with confidence, interventions linking
     to the front page's sub-chapters)
  
  The pinned map zooms to the river and shows outlets or obstacles in their chapters. The story
  ends with "Upstream: …" and "Downstream: …" links to the next stories.
- On a phone, the map isn't pinned: it appears as a figure at the top of each chapter.

**Look:** printed long-read. Georgia or Cambria body text at about 19px, in a column about 68
characters wide. Plain bold headlines, a single earthy accent (river brown or ochre), simple SVG
charts with direct labels instead of keys where possible, and a pull quote now and then taken
from the real text.

### Version 3: League table and compare (`3-table/`)

**Idea:** for partners and analysts. It starts with all 92 waterbodies side by side in one table,
then you narrow it down, compare and dig in.

**How it works:**
- **Rivers** (the front page) is one big table with 92 rows. The name column and the header stay
  fixed while you scroll. The columns are in groups, and a "Columns" button picks which groups
  show:
  - Name and operational catchment
  - Rank
  - Status 2016, 2019 and 2022 (coloured cells)
  - Failing elements (a count, listed on hover)
  - The 8 risks (coloured cells marked VL, L, M, H or VH, with a key)
  - Farms and top livestock density rating
  - Overflow hours (2021 to 2025 total)
  - Obstacles (count)
  - Area and length
  - Interventions needed (count, and estimated cost in total)
  
  Every column sorts. A filter bar above the table has:
  - operational catchment
  - status
  - "any risk at High or above" (or a chosen risk at a chosen level)
  - failing element
  - intervention needed
  - search by name
  
  A **summary line** above the table always describes the rivers currently shown: the counts by
  status and the totals (farms, properties, outflows) and habitat. Filtered to an operational
  catchment, it shows exactly that catchment's figures (checklist A3, A5 and A6).
- **Compare:** tick 2 to 4 rows, then press "Compare". Every item from checklist B appears as a
  row, with one column per river.
- **Click a name** to open that river's **data sheet** (`river.html#GB…`). It has every section
  from checklist B as tidy, labelled tables, one after another, with a contents list down the
  side. Make it suitable for printing.
- Other pages in the top bar:
  - **Areas**: North Devon and the 3 operational catchments side by side: counts, totals,
    habitat, and the three location texts
  - **Interventions**: a grid of the 12 interventions against the rivers that need them, then
    the summary table, unit costs, every intervention's detail, the critical path and community
    action
  - **Questions**: Insights as a filterable list
  - **Notes**: the about texts, every "i" text as a list of datasets, and the credits
- A "Download this table (CSV)" button for whatever is showing, made in the browser.

**Look:** like a very well-made spreadsheet. Segoe UI or Tahoma, tabular figures, light row
banding, colour only inside cells (EA colours and a five-step risk scale), one dark green
accent for the bars and buttons. Dense but tidy. On a phone it scrolls sideways with the name
column fixed, and Compare takes 2 rivers.

### Version 4: Start with a question (`4-questions/`)

**Idea:** for the public. It opens with plain-English questions. You pick a question, then a river,
and get a plain answer with the data behind it. It's designed for phones first.

**How it works:**
- **The front page** is "What would you like to know?", with questions in two groups:
  - **About a river:**
    - How healthy is my river? (status by year, ranking, failing elements, RNAGs, EA scoring)
    - What's harming it? (why it's failing, risks, phosphate sources, livestock, land use,
      obstacles)
    - How much sewage goes into it? (discharges by site and year, outlet map, properties, the
      two explanations, phosphate as Continuous or Diffuse)
    - What's being done about it? (what's happening now, improvement plans, interventions with
      delivery)
    - What would it take to fix it? (hypothesis with confidence, interventions with size, cost
      and lead)
    - Where is it and what's around it? (map, river information, upstream and downstream,
      habitat)
  - **About North Devon:**
    - How are North Devon's rivers doing? (counts, map, the 3 operational catchments with
      their totals and habitat)
    - Why are they failing?
    - What's happening now?
    - What's the plan and what will it cost? (hypothesis, critical path, summary, unit costs,
      each intervention's detail)
    - What can I do? (community action)
    - More questions (Insights, all 8 areas)
    - How was this put together? (about texts, "i" texts, credits)
- **"Which river?"** comes next for river questions. It has a search box that suggests as you
  type, a list grouped by operational catchment, and a small map to tap. The chosen river is
  remembered (in localStorage, wrapped in try/catch), so the next question goes straight to the
  answer, with a "Change river" link.
- **An answer** starts with one or two plain sentences made from the data, for example "Torridge
  (Source to Dipple Water) is at Moderate status. It ranks 52nd of North Devon's 92 rivers." Then
  comes the supporting detail in simple form, then "See the data behind this" sections with the
  full tables, then "Other questions about this river". Every answer has its own address
  (`#/river/GB…/health`).
- Check that every item in checklist B appears in at least one answer.

**Look:** like a clear public information leaflet from a local council or charity (but not
copying GOV.UK's look or crown). Verdana about 18px, high contrast, one strong colour (deep
green) and a warm yellow highlight, big tap areas, one column at most 680px wide, short
sentences.

### Version 5: River network diagram (`5-network/`)

**Idea:** the rivers drawn as a schematic, like a transport map. Each waterbody is a "station"
coloured by its status, lines follow the rivers down to the sea, and you can see how problems
pass downstream. (Use the idea of a transport diagram, not anyone's branding: no TfL roundel, no
Johnston-style font, no copy of the tube map.)

**How it works:**
- **Building the diagram:** use `upstream_ids` and `downstream_ids` to make each river system a
  tree that ends at the sea. Draw a **coastline line** along the bottom, with each system
  reaching it at its own point, in geographical order (by where its last waterbody is).
  Waterbodies with no links in North Devon are short lines of their own down to the coast. Draw
  the longest path in each tree as its trunk, with tributaries branching off at 45° or 90°.
  - Work the positions out once with a script, then save them in `5-network/layout.json`. That
    way they can be adjusted by hand afterwards until nothing overlaps and the labels can be
    read.
  - If a full transport-style layout gets too fiddly, fall back to a neat tree for each river
    system (sea at the bottom). It's better to be readable than clever.
  - Draw it all as SVG that can be dragged and zoomed, with + and − buttons.
- Lines are coloured by operational catchment. Stations are filled by status, and can instead be
  coloured by ranking, any risk, or "needs intervention…" (the same choices as version 1).
- **Clicking a station** opens a side panel. At the top it shows "Upstream" and "Downstream":
  the stations above and below with their statuses, and a line such as "3 of the 5 waterbodies
  upstream are Moderate or worse". Under that, everything in checklist B, in sections (Status,
  Pressures, Sewage, Land, Fixes). It also has a small Leaflet map of that waterbody with its
  outlets and obstacles.
- **Clicking a line** (or its name in the key) shows that area's summary: counts, totals,
  habitat and the location texts.
- **"Fixes" mode:** choose an intervention, and the stations needing it get a ring with their cost.
  The panel shows that intervention's detail.
- Other pages: "The plan" (all of Intervention Management), "Questions" (Insights), "About", and
  "Rivers A–Z" (a list, also the easiest way in on a phone). A "Show real map" switch puts a
  Leaflet map in place of the diagram.

**Look:** clean transport-diagram style. White background, thick lines, round stations with dark
outlines, Bahnschrift or Segoe UI (fallback Arial). The only colours are the line colours and the
status colours.

### Version 6: Cause and effect (`6-cause-and-effect/`)

**Idea:** organised around the chain from problem to fix: **pressures → what's failing → rivers →
fixes → money**. Clicking anything in the chain shows what it connects to.

**How it works:**
- **The front page** starts with "Why is the river system failing?" (the location text, with
  its five groups). Below it is a diagram of five columns, linked by ribbons, with ribbon width
  showing the number of rivers:
  1. **Pressures:** the 8 risks. A river counts where that risk is High or Very High. A switch
     changes this column to the RNAG sectors.
  2. **What's failing:** the failing elements (Phosphate, Fish, Invertebrates…)
  3. **Rivers:** the 92, grouped by status
  4. **Fixes:** the 12 interventions, linked to the rivers that need them
  5. **Money:** each intervention's estimated cost, available funding and funding still to be
     found, as bars
- **Clicking a node** highlights everything connected to it and fades the rest. Underneath,
  "What this means" lists the facts. For example, clicking Livestock might give "Livestock risk
  is High or Very High in N rivers. Phosphate fails in N of them. They need slurry management
  (N) and soil health work (N), estimated at £…". (That's the shape only: work out the real
  numbers from the data.) Under that is the list of those rivers. Clicking a river opens its
  page.
- **A filter** for North Devon or one of the 3 operational catchments redraws the diagram. A strip
  above it shows that area's counts, totals and habitat.
- **Under the diagram:**
  - "What is happening now?" and "Intervention hypothesis"
  - the critical path (as the explanation of how fixes lead to Good status)
  - the summary table with its totals, under Money
  - each intervention's full detail and unit cost (opened from its node or a list)
  - community action
  - Insights
  - about and credits
- **A river's page** uses the same chain, left to right, for that one river:
  - its pressures (risks, RNAGs, phosphate sources, livestock, land use, sewage discharges,
    obstacles)
  - what's failing (failing elements, and the scoring table against its thresholds)
  - its status (by year, ranking)
  - the fixes (hypothesis with confidence, interventions, what's happening now, the water
    company's improvement plans)
  - the money (each intervention's cost and lead)
  
  Each column has a short summary at the top and the full tables below it, opened when needed.
  River information and the outlets and obstacles map go in a band across the top.
- On a phone, the columns become steps one under the other: pick a pressure, see the rivers, see
  the fixes.

**Look:** technical drawing. Off-white background, fine dark lines, Franklin Gothic Medium or
Arial Narrow for headings, and Consolas for the numbers. Ribbons are grey until something is
selected, then the selection is drawn in near-black, so it never clashes with the EA status
colours.

### Version 7: Timeline (`7-timeline/`)

**Idea:** everything placed in time. What the rivers were like, what they're like now, and
what's planned. It has a clear "Now" line.

**How it works:**
- **The front page** is North Devon on a timeline from 2009 to 2035, in rows sharing one year axis:
  - **Ecological status of all rivers:** a stacked bar for every classification year in the
    data (2009 to 2022), with 2016, 2019 and 2022 marked as the years the dashboard reports
  - **Storm overflow hours:** the total for each year, 2021 to 2025
  - **Phosphate sources:** 2025 next to the 2030 estimate
  - **Water company improvements:** the number of sites for each completion year, with the AMP8
    (2025–2030) and AMP9 (2030–2035) periods shaded
  - **Interventions:** started and finished delivery where known, "Data to follow" where not
  
  A **"Now"** panel holds the present-day items:
  - the three location texts
  - the counts, including each operational catchment (a selector)
  - the totals and habitat
  
  Below it come the critical path (drawn as steps in order along a line), the summary table and
  totals, unit costs, every intervention's detail, community action, Insights, about and
  credits.
- **Choosing a river:** a list of all 92, each with a small strip of its status for every year,
  sortable by name, operational catchment or ranking, next to a small map.
- **A river's page** (`river.html#GB…`) has three parts:
  - **Before:** its status strip for every year (2016, 2019 and 2022 marked), and each scoring
    item as a small line chart from 2016 to 2025 over shaded Poor, Moderate, Good and High bands
    (from its thresholds), with the full scoring table below
  - **Now:** ranking, failing elements, RNAGs, why it's failing, what's happening now, the 8
    risks, river information, habitat, farms, livestock, obstacles (map and table), properties,
    discharges by site for each year 2021 to 2025, the two explanations, and phosphate sources
    for 2025
  - **Next:** phosphate for 2030, improvement plans placed at their completion year with
    predicted spills, the hypothesis with confidence, and interventions with size, cost, lead
    and delivery
  
  Upstream and downstream links go at the bottom.
- On a phone, timelines scroll sideways with the year labels kept in view. "Now" content stacks
  in one column.

**Look:** calm, like an almanac or an annual report. Cool, pale blue-grey paper, Constantia or
Cambria headings, Calibri or Segoe UI text, a strong year axis, and the "Now" line in one
deliberate colour.

---

## 7. The page for choosing (`published/north-devon-ideas/index.html`)

A plain page that Tom opens first. It has a short introduction ("Seven ways of showing the same
North Devon data, all using the data as at <date>"). Then, for each version, it shows:
- a screenshot (see section 8)
- its name and one paragraph on the idea
- who it suits best
- the link

It ends with a note that ideas can be mixed, for example the map from 1 with the questions from 4.
Keep this page simple: it's for choosing, not one of the designs.

---

## 8. How to build and check it

**Order:**
1. Read this file and PROGRESS.md. Check `docker compose ps` (start it with
   `docker compose up -d` if needed).
2. Do Step 1 (section 3) yourself, and check the export.
3. Build the seven versions. They don't depend on each other, so a subagent can build each one
   at the same time. Give each subagent:
   - the path to this file
   - its version number
   - the paths of the data and shared files
   - this instruction: only write inside its own version folder, read sections 1, 2 and 4 in
     full, and don't use the Playwright browser (it's shared, so parallel use clashes)
   
   It may use `node --check file.js` (Node is installed) to check its scripts, and
   `curl http://localhost:8080/north-devon-ideas/<folder>/` to check files are served.
4. Check each version yourself, one at a time, in the Playwright browser:
   - laptop size (1440×900) and phone size (390×844)
   - no console errors
   - try the main flow from start to finish
   - open at least 3 waterbodies, including `GB108050014390`, one with no storm overflows and
     Upper East Lyn River (no farms figure), and compare a few figures with the current
     dashboard
   - go through checklist section 4 and confirm each item can be found
   - look again at section 2: would Tom think this looks hand-made?
   
   Fix what you find, or send it back to that version's subagent.
5. Take a screenshot of each version's first screen for the choosing page. Playwright can only
   save files under `/tmp/.playwright-mcp/` or this repo, so save them straight into
   `published/north-devon-ideas/shots/`. Then build `index.html` (section 7).

**Notes:**
- `published/north-devon/` and the data export must not change during any of this. Check
  `git status` at the end: the only change in git should be the note in PROGRESS.md (section 9),
  because `published/` isn't tracked.
- The intervention detail is large (the current page is about 200KB). Load data once from
  `shared/data/north-devon.json` and build pages in the browser, rather than copying data into
  each version's HTML.

---

## 9. When it's finished

- Add a short section to PROGRESS.md under "What's built" or as a dated note. It should say that
  the seven ideas are in `published/north-devon-ideas/`, frozen to the build date, not in git,
  and not made by the publish step. Once Tom picks one, the next job is changing the publish step
  (`backend/catalyst/publish/`) to produce it.
- Tell Tom the address (<http://localhost:8080/north-devon-ideas/>), give one line on each
  version, and list anything from the checklist that a version shows only in a limited way.
