# Progress

Where the build is up to, the decisions made along the way, and what's next.
For the overall design, see [PLAN.md](PLAN.md). For commands, see [README.md](README.md).

**Last updated:** 13 November 2026

---

## Picking up again

**Just running it?** [OPERATING.md](OPERATING.md) has only the essential commands (written for
Tom to run things himself, 29 October 2026).

```bash
docker compose up -d                      # start the local database, admin page and dashboard preview
docker compose run --rm schema plan       # should say "The database already matches schema.yaml."
docker compose run --rm test              # run the tests (184 passing at the last update)
docker compose run --rm publish           # rebuild the dashboard pages (or the admin page's Publish button)
```

- Admin page: <http://localhost:8000/admin> (name `admin`, password `admin`): a diagram of every
  table; click any table to download it, or an Excel table's **Upload data** (on the left) to upload it,
  and **Publish** (at the top) to put what's approved on the dashboard
- Dashboard: <http://localhost:8080> (open North Devon; every waterbody has real data in every panel once it's published)

The local database is on `localhost:5434` (database, user and password are all `catalyst`),
for DBeaver or pgAdmin.

**Working style:** one step at a time. Each step is suggested and agreed before it's built,
and optional extras are kept self-contained so they're easy to remove.

---

## What's built

| Part | Where | What it does |
|---|---|---|
| **Database master file** | `backend/catalyst/db/schema.yaml` | Lists every table and column. The only place the database structure is defined. |
| **Schema tool** | `backend/catalyst/db/` | `schema plan` previews changes, `schema apply` makes them. All-or-nothing, refuses to delete data unless told to, handles renames and changes of primary key. |
| **Catchments importer** | `backend/catalyst/importers/api/`, `imports/` | Fills the catchments table from the EA's Catchment Data Explorer, for the management catchments (all their rivers) and IDs in `imports/catchments.json`. Preview first, safe to re-run, keeps the downloaded files. |
| **EA, River Obstacles and postcode importers** | `backend/catalyst/importers/api/` | For every imported catchment: the EA's classifications and RNAGs (`importer classifications`), storm overflow spills from the EA's yearly returns (`importer storm-overflows`), obstacles from River Obstacles (`importer river-obstacles`), and the postcodes inside it from Ordnance Survey's Code-Point Open (`importer postcodes`). Each replaces its table, with a preview first, and keeps the downloads. |
| **Excel uploads** | `backend/catalyst/importers/excel/` | For every table marked `filled_by: excel`: download it as Excel, upload an edited copy, see what will be added, changed and deleted, then approve. No code per table. |
| **Admin page** | `backend/catalyst/admin/` | One page behind a login (one name and password per person): a diagram of every table (`diagram.py`, `diagram.yaml`) showing where its data comes from (downloaded or Excel), how the tables join up by Catchment ID, and each table's columns when clicked. Any table can be downloaded as Excel from there; each Excel table has its own **Upload data** box on the left, and the upload's preview is its own page. Made from `schema.yaml` each time it's opened. A **Publish** button at the top rebuilds the dashboards, and says how many uploads have been approved since the last publish. Runs with `docker compose up -d`. |
| **Publish step and dashboard** | `backend/catalyst/publish/`, `published/` | Writes each location's dashboard as plain web pages, laid out like the original (`Reference/ReferenceImages`), with four views chosen by cards across the top of every page. **Waterbody Dashboard:** River Status, EA Data, Land Use Data and Sewerage Data, one waterbody at a time (the Overview tab is built but switched off). **Catchment Dashboard:** the whole location on one big map, with its panels over it, and a page per operational catchment. **Intervention Management:** its five focus areas as on the North Devon Biosphere's pages (Critical Path, Unit Cost of Interventions, Intervention Summary, Interventions Detail with a page per intervention, Community Action). **Catchment Insights:** its eight focus areas' questions, as on the North Devon Biosphere's pages, from a file (`publish/content/north-devon/catchment-insights.yaml`) rather than the database. Every panel now has a table. Previewed at <http://localhost:8080>. |
| **Dev and live setup** | `docker-compose*.yml`, `.env*.example` | The same commands on your machine and on the live server. Only the settings differ. |
| **Tests** | `backend/tests/` | Cover the schema tool, the importers, the Excel uploads, the admin page (and its diagram) and the publish step. |

### Tables so far

| Table | Kind | Holds | Rows |
|---|---|---|---|
| `catchments` | Core | Every EA river waterbody: details, outline, river line, area, length, upstream/downstream IDs. Filled only by the importer. | 92 (every North Devon river) |
| `locations` | Core | ID, name, and the list of catchment IDs | 1 (North Devon, with the 92 catchments) |
| `datasets` | Core, Excel | The text in each "i" button: one row per data table that has one (table name, text) | 7 |
| `uploads` | Core | Every Excel upload: table, file, who, when, status, rows added / changed / deleted | 38 |
| `publishes` | Core | Every publish of the dashboards: when, and who (empty for the publish command) | 5 |
| `ea_classifications` | Data, EA | The EA's status for each classification item and year (2009 to 2022), per catchment | 27,294 |
| `ea_rnags` | Data, EA | The EA's reasons for not achieving good: element, activity, sector | 513 |
| `storm_overflows` | Data, EA | Each storm overflow's spills (hours, count) per year, 2021 to 2025, with its location | 755 (about 150 overflows into 57 catchments) |
| `river_obstacles` | Data, River Obstacles | Weirs, culverts, fords and so on, with their location | 423 (in 80 catchments) |
| `postcodes` | Data, Ordnance Survey | Each postcode whose centre is inside a catchment, for the postcode search | 5,104 (in all 92) |
| `ea_scores` | Data, Excel | The measured values behind the EA's statuses (e.g. Fish (EQR) 0.36), per measure and year (2016, 2019, 2022, 2025): EA Data page | 1,704 (all 92) |
| `ea_thresholds` | Data, Excel | Poor / Moderate / Good / High thresholds per measure: EA Data page | 1,012 (all 92) |
| `habitat_land_use` | Data, Excel | Area of each habitat type, and its relative coverage: Land Use Data, Catchment Dashboard | 459 (all 92) |
| `river_status_text` | Data, Excel | Why is the river failing?, What is happening now?, the intervention hypothesis and its confidence | 92 |
| `risk_levels` | Data, Excel | One column per risk (8), each Very Low … Very High | 92 |
| `catchment_rankings` | Data, Excel | The ranking, e.g. 68 for "68/92" | 92 |
| `farms` | Data, Excel | Number of farms | 91 (no figure for Upper East Lyn River) |
| `livestock` | Data, Excel | Number of each kind of livestock, and its density rating | 459 (all 92) |
| `phosphate_sources` | Data, Excel | Each source's % of the phosphate, per year (2025, 2030), and whether it's Continuous or Diffuse | 1,456 (91: none for Bradwell Stream) |
| `sewerage_properties` | Data, Excel | Properties on public (SWW) and on private sewerage | 92 |
| `sewerage_improvements` | Data, Excel | The water company's planned improvements: site, improvements, completion year, predicted spills | 150 (in 57 waterbodies) |
| `intervention_types` | Data (by location), Excel | Intervention Management: each type of intervention (12), with its line in the summary table and its Interventions Detail (overview, progress, group headings) | 12 |
| `intervention_waterbodies` | Data, Excel | Intervention Management: where each type of intervention is needed, with its size, cost, funding, delivery and lead | 293 (in 83 waterbodies) |
| `intervention_unit_costs` | Data (by location), Excel | Intervention Management: the indicative cost of each type of intervention | 12 |
| `location_text` | Data (by location), Excel | One row per location: the Catchment Dashboard's three texts, the Sewerage Data page's two explanations, the text under each dashboard (with its sections), and Intervention Management's four texts (Critical Path, the Unit Cost purpose, the Summary's introduction, Community Action) | 1 |

`catchments`, the four EA / River Obstacles tables and `postcodes` are filled by importers; the rest of the
data tables by Excel upload.

**Every Excel table now has the real data** (12 November 2026, uploads 21 to 34), from the
original dashboard's files in `Reference/ReferenceData/Waterbody Scorecards` (not in git). The
sample rows (Langham Lake from the screenshots, made-up West Okement) are gone. Each file was
uploaded and approved through the admin page, so it's listed under the table's recent uploads
and kept in `imports/raw/<table>/`. Nothing has been published yet: click **Publish** to put it on
the dashboard. A backup from just before is in `backups/before-scorecard-data-2026-11-12.dump`.

| Table | From (in `Source data/` unless it says Reports) |
|---|---|
| `catchment_rankings`, `farms`, `sewerage_properties` | `Waterbody Lookup/Waterbody Lookup.xls` (Biosphere Ranking, FARMS, SWW Sewerage, Private Sewerage) |
| `risk_levels` | Worked out with the original's own rules (from the `.pbix`): storm overflows from `CSO Spill Data/EDM 2021 to 2025 … Biosphere area.csv` (2025 spill duration), private sewerage per ha from Waterbody Lookup, livestock N + P load from APHA, and Runoff, Modification, Invasive Species, Overheating and Running Dry from `ESME/`. All 92 match the original's export (`Reports/Summary WB data for AI.csv`). |
| `livestock` | `APHA Livestock Data/APHA Livestock Data Feb 2026.xlsx`: five rows per waterbody (a blank is 0, as on the original), density rating by the original's rule |
| `habitat_land_use` | `Habitats/Nat Eng Simplified Habitat.csv` (m² ÷ 10,000), relative coverage by the original's rule |
| `phosphate_sources` | `EA Phosphate data/SAGIS Phosphate source.xlsx`, Source breakdown sheet: 2025 = end of AMP7, 2030 = end of AMP8 |
| `sewerage_improvements` | `SWW Asset Upgrades/National Plan Data - updated.xlsx` (Water UK), North Devon rows whose waterbody is one of the 92 |
| `interventions` | `Improvement Information/Archive/Interventions.xlsx` (240 rows). **Since replaced:** River Status now shows Intervention Waterbodies, and the table was taken out of `schema.yaml` (see Intervention Management) |
| `river_status_text` | `Improvement Information/Improvement Information.xlsx` |
| `ea_scores`, `ea_thresholds` | `Reports/<measure> data.csv`, the original's own exports of its EA Data page (values for 2016, 2019, 2022 and 2025, and thresholds) |
| `location_text` | North Devon's three Catchment Dashboard texts from `Catchment dashboard/Catchment dashboard summaries.xlsx`; the other five columns unchanged |
| `datasets` | The original's "i" button texts, found in the `.pbix` (risk levels, ranking, habitat, livestock, phosphate); Sewerage Improvements' is new wording, from `SWW Asset Upgrades/Source of data.txt`; EA Classifications' unchanged |

The scripts that built and uploaded the files were one-offs, kept outside the project.

---

## Decisions made (and why)

**Database structure**
- **A master file rather than migration scripts.** The structure is easy to read in one place, and git keeps its history.
- **One table per dataset.** Each dataset has different columns, and each Excel file lines up with one table.
- **Every data table must have a `catchment_id`** linked to `catchments`; the schema tool enforces this. Tables keyed by `location_id` will be allowed when the first one is needed.
- **"Catchment" means an EA WFD waterbody,** and "Catchment ID" is its EA ID, matching the concept deck.
- **One source per table.** `catchments` comes only from the EA. Anything entered by hand goes in its own table, linked by ID, so re-imports never overwrite anyone's work.
- **EA Scores has `status` (e.g. Poor) and `value` (e.g. 0.16) as separate columns,** so numbers stay numbers.

**Catchments and the EA data**
- **Catchment details come from the EA's shapefile download.** It holds more than the GeoJSON: catchment names and IDs, and the hydromorphological designation.
- **River length comes from the EA web page,** because the API doesn't provide it. The current dashboard's lengths match neither source (Langham Lake: dashboard 13.9 km, EA 15.53 km).
- **Area is calculated from the outline.** It matches the EA's figures.
- **"River system" was dropped.** It isn't EA data, and if it's still wanted it would come from a hand-written table.
- **Upstream and downstream are stored as lists of IDs on `catchments`.** Names are looked up there. Estuaries aren't imported yet, so a few won't find a name.

**Filling tables: API or Excel**
- **Each table says how it's filled** with `filled_by` in the master file: `api` (an importer, in `importers/api/`) or `excel` (the admin page, using the shared code in `importers/excel/`). Only `excel` tables can be downloaded and uploaded in the admin page, and its diagram shows which is which.
- **An upload is an exact copy of the table.** Same column names (any order), first sheet. No column mapping screen and no code per table, which answers the old "mapping screen or importers?" question for now.
- **Each upload replaces the whole table**, rather than only adding rows. One process covers adding, correcting and deleting, so no editing screen is needed. The workflow is: download, edit, upload.
- **The preview is the safety net.** It lists every row to be added, changed and deleted, and warns about deletions (strongly if it would empty the table). Nothing changes until someone approves.
- **Approval re-checks the preview.** If the table changed in between (e.g. the other person uploaded), approval is refused and the fresh preview is shown. This catches someone uploading from an out-of-date download.
- **Every uploaded file is kept** (`imports/raw/<table>/`) and listed on the table's page. Undo means downloading an earlier file and uploading it again.
- **Rows are matched by the primary key,** which is also the duplicate check: the same catchment, measure and year twice in a file is refused, with the Excel row numbers.
- **The API importers share only a few small pieces** (`importers/api/common.py`, 11 November 2026): `ImportProblem`, `replace_rows` (empty the table, then insert in batches of 5,000) and `run_folder` (`imports/raw/<table>/<date and time>/`). Each source's downloading and reading stays in its own module, because they really are different. No general framework that runs every importer the same way unless many more sources are added.
- **Excel tables can only have text, number, yes/no and date columns,** and need a primary key made of their own columns (no auto-numbered IDs). The schema tool enforces this. `real` and `numeric` are left out because stored values change slightly, so every upload would show them as changed.

**Admin login**
- **One name and password per person, checked by the Python app,** not a shared login. Uploads then record who made them, and one person can be removed without affecting the other.
- **Only password hashes are stored,** in `ADMIN_USERS` in `.env` (made with `docker compose run --rm admin hash-password <name>`). The login cookie is signed with `ADMIN_SECRET_KEY`, lasts 12 hours, and is never sent with requests from other sites.
- **Microsoft accounts (Entra ID) later,** only if many more people need access.

**The dashboard**
- **Plain web pages, not a JavaScript app.** The dashboard only shows data (tables and a simple map), so the publish step writes the data straight into the pages, as the admin page does with its diagram. There are no API calls and no build step. React and TypeScript were considered: they'd only pay off for a much more interactive dashboard.
- **The publish step has two halves:** `collect.py` gathers a location's data and knows nothing about web pages; `site.py` and the templates turn it into pages. A different front end could reuse the first half.
- **The pages copy the original dashboard's five tabs and colours** (29 October 2026). Each tab except the Overview has a page per catchment (`<tab>/<catchment ID>/`) and one before a catchment is chosen (`<tab>/`). Clicking the map stays on the same tab, as in the original.
- **The Overview is switched off for now** (Tom, 29 October 2026; he'll bring it back later). It's still built and tested: `SHOW_OVERVIEW = True` in `site.py` brings it back as the front page. Until then the front page is River Status before a catchment is chosen.
- **A panel is shown empty while its table has no rows for the catchment,** with its headings (and table headings) only. Every panel now has a table (5 November 2026), except the Overview's photo and the logo.
- **Calculations are in `figures.py`:** each catchment's latest ecological status (for the map colours and the Overview counts), the EA scoring grid, failing elements, RNAGs, each habitat's % of the catchment, the storm overflow table, and (5 November 2026) livestock densities, the phosphate split, sewerage per ha and the Catchment Dashboard's totals. Ranking and "Relative Coverage" are typed in until their rules are agreed (PLAN.md §9.3).
- **A new data table no longer appears by itself:** it needs a place on a page. The original layout has no space for a generic table.
- **The "i" buttons show the table's text from Datasets,** with the table's title as the heading, and are greyed out until it has a row. The text is split into paragraphs and lists like the other hand-written text. A web address in it is shown as plain text, not a link.
- **Tables are sortable** by clicking a heading (a small script, `static/sort.js`). Numbers sort as numbers, and empty cells always go last.
- **Choosing another catchment keeps your place** (Tom, 12 November 2026). Clicking a catchment on a Waterbody Dashboard map, a tab, an upstream or downstream river, or a management / operational catchment button on the Catchment Dashboard opens the new page scrolled to where you were, not at the top. Those pages share a layout, so you stay on the same panel. A small script (`static/keep-scroll.js`) does it for links inside anything marked `data-keep-scroll`, and `map.js` asks it to when its map has `data-keep-scroll`. The position is kept in the browser tab's session storage, only for the page being opened and only for 30 seconds. The view cards at the top still open at the top. Without the script, pages open at the top as before.
- **Maps: Leaflet over OpenStreetMap,** with the catchment outlines coloured by ecological status (the colours are in `style.css`) and the rivers drawn on top. The original has no background map or rivers; Tom preferred them (29 October 2026). Leaflet is copied into the project rather than loaded from elsewhere.
- **One self-contained folder per location** (`published/north-devon/`), so each can later be served at its own address. Each folder is built alongside the old one and swapped in, so a half-written dashboard is never served.
- **A location's web address comes from its name** (North Devon → `north-devon`), for now.

**EA data** (29 October 2026)
- **The EA's real classifications replace EA Scores on the dashboard.** They come from the Catchment Data Explorer (`importer classifications`), one download per management catchment, so all 92 rivers take two downloads. They give a status for each item and year but **no values** (e.g. Fish EQR 0.36). Since 5 November 2026 the values come from EA Scores (Excel), shown beside the EA's statuses (see "The new tables").
- **The latest classification year is 2022.** The Catchment Data Explorer doesn't have 2025 yet (the EA publishes it separately on data.gov.uk), so the side panel shows 2022, 2019 and 2016.
- **Where a year was classified in two cycles** (2019 in cycles 2 and 3), the later cycle is used.
- **The EA Data grid shows the items on the original dashboard** (Ecological, Fish, Phosphate and so on, plus Specific pollutants and Chemical), not the EA's 60-odd single chemicals.
- **Failing elements: elements and sub elements below Good** (Moderate, Poor, Bad, etc.) in the catchment's latest year. Chemicals ("Fail") are left out, and so is "Macrophytes and Phytobenthos Combined" when one of its sub elements is failing. This reproduces the original exactly for Langham Lake (Fish, Phosphate, Phytobenthos Sub Element).
- **EA RNAGs: the activities the EA gives in its latest cycle,** leaving out "Not applicable". Also matches the original for Langham Lake.
- **Storm overflows are tied to a catchment by the WFD waterbody ID in the EA's return,** not by location. This reproduces the original's figures exactly for Langham Lake. About a third of South West Water's overflows have no waterbody ID (mostly into estuaries and the sea) and are left out; a few on North Devon streams are among them (e.g. Fremington).
- **Storm overflow hours are rounded with halves up** (1462.5 → 1463), as on the original. Blank or "#N/A" hours mean no figure (e.g. no monitor yet), not zero, and an overflow with no figures at all is left out, as on the original. The map shows where each overflow was in its latest year (some moved slightly).
- **The storm overflow returns are read for every water company,** by their column headings, so other locations work too. The years read start at 2021; the dashboard shows the latest five.
- **River obstacles come from River Obstacles** (the EA and The Rivers Trust), via its public map service, and are tied to the catchment whose outline they're inside. Obstacle 39245 in Langham Lake matches the original.
- **Licences:** the EA data is Open Government Licence; River Obstacles is CC BY-SA 4.0. Both are credited in the dashboard's footer. Offering River Obstacles as a download would bring in CC BY-SA's "share alike" condition.

**The postcode search** (Tom, 13 November 2026: "go ahead with option 1, I dont like nearest catchment, just say it is outside the catchments")
- **The Waterbody Dashboard's map panel has a postcode box:** "Click the map to select a river catchment, or enter a postcode". A postcode opens the catchment it's in, on the same tab and scrolled to the same place, as clicking the map does, and the page then says "EX36 3AA is in Nadrid Water." beside the Go button (below it if there isn't room).
- **The heading is sized to the panel so it fits on one line** (Tom: "preferably so it all fits on one line"), from 1.05rem down to 0.8rem (the footer's size), where it wraps instead. With Windows' Segoe UI it's on one line on screens 1536 px wide and up (12.8 px there, 16 px at 1920 px), and two lines at 1366 px and below. One line there would need about 11 px text.
- **Still static, with no server code and no outside service.** The publish step writes the location's postcodes into `postcodes/<district>.json` (e.g. `EX36.json`: `{"3AA": "<catchment ID>", ...}`), one small file per district (19 files, 168 KB, the biggest 19 KB). `static/postcode.js` fetches only the one it needs. postcodes.io (a free lookup service) was the other option, turned down because each visitor's postcode would go to a third party and the search would depend on it.
- **The postcodes come from Ordnance Survey's Code-Point Open** (free, OS OpenData licence), the centre point of every postcode in Great Britain, via `importer postcodes`. The importer keeps the postcodes whose centre is inside a catchment's outline (checked in PostGIS, like River Obstacles). A postcode that crosses a boundary goes to the catchment its centre is in.
- **A postcode outside every catchment is just "outside the North Devon catchments"**, with no "nearest catchment" (Tom). That's a lot of the towns: only 5,104 of the 10,183 postcodes around the catchments are inside one. Central Barnstaple (all of EX31 1xx) is outside, as are about 70% of EX31 and EX34 (Ilfracombe) and half of EX39 (Bideford), because they're by the estuaries or the sea, which aren't imported. EX19, EX36, EX37 and EX38 are all, or almost all, inside. Importing estuaries and coastal waters (Open questions) would cover more.
- **A misspelt postcode that looks like a real one also says "outside",** since only the postcodes inside are published. One that isn't shaped like a postcode (e.g. "EX36") says "That doesn't look like a full postcode".
- **The page only says which catchment a postcode is in after checking it,** so a link with `?postcode=` on the end can't make it say something untrue.
- **The footer credits Ordnance Survey, Royal Mail and National Statistics,** as Code-Point Open's licence asks, with the year of the publish. The box and the credit only appear while the Postcodes table has rows for the location.
- **Ordnance Survey updates Code-Point Open every three months** (the one imported is October 2026). Re-run `importer postcodes`, then publish.
- **Tried in a real browser** (headless Chromium): a postcode inside, outside, in a district with no file, half a postcode, one in the catchment already shown, a link naming the wrong catchment, the tab and scroll position kept, and a phone-width screen.
- **Not on the test VM yet.** To put it there: pull, `schema apply`, `importer postcodes`, then publish (all with `--build`).

**Choosing a catchment by name** (Tom, 13 November 2026: "a dropdown where all the catchments are listed … alphabetical and grouped and the user just selects")
- **A list of every waterbody, under the postcode box** on the Waterbody Dashboard's map panel ("Or choose from the list"). Choosing one opens it on the same tab, scrolled to the same place, as clicking the map does. On a waterbody's page, the list shows that waterbody.
- **A to Z, or "By area":** a small switch beside the list (below it on narrower screens) puts the waterbodies under their EA operational catchments instead, A to Z within each: Hartland and Clovelly Streams (3), Taw and North Devon Streams (52) and Torridge (37), the same groups as the Catchment Dashboard's buttons. A to Z is the default. The browser remembers the choice (local storage) for the next page. The switch only appears when a location's waterbodies are in more than one operational catchment.
- **The page lists them A to Z, and `static/catchment-list.js` regroups them,** so nothing else is published. No two North Devon waterbodies share a name.

**The four views** (Tom, 5 November 2026)
- **Cards across the top of every page** choose the view: Waterbody Dashboard (the four tabs we
  already had, unchanged in layout), Catchment Dashboard, Intervention Management and Catchment
  Insights, as in the new reference images (`Overview.jpg`, `Catchment Dashboard.jpg`, ...). The
  current one is greyed. The front page is still the Waterbody Dashboard's River Status.
- **The card pictures are stand-ins,** cut from the reference screenshots
  (`publish/static/cards/`), so they're small. Replace them with the real pictures, keeping the
  names.
- **The "EA Inspections" tab** in the newer Waterbody Dashboard in `Overview.jpg` was left out:
  Tom said to keep the Waterbody Dashboard as in 1–5.jpg.
- **The Catchment Dashboard is one big map with its panels laid over it,** as in the image. On a
  phone the panels go below the map. The map fits the catchments into the space beside the panels.
- **Its operational catchment buttons each open a page** (`catchment-dashboard/torridge/`) with
  the map zoomed to them (the rest faded) and every count and total narrowed to their waterbodies.
  A management catchment that is the whole location is the Catchment Dashboard's front page.
  Its waterbodies can't be clicked (Tom, 13 November 2026; they used to open the Waterbody
  Dashboard). Hovering still shows a waterbody's name and status, with no highlight.
- **The Catchment Dashboard's text is one set per location** (`location_text`), and stays the
  same when an operational catchment is chosen, as a Power BI text box would. Text per
  operational catchment would be a small change if it's wanted.
- **Its figures are added up from the waterbodies' rows** (farms, properties, habitat), so
  nothing is stored twice. When only some waterbodies have figures, the total says so, e.g.
  "(2 of 92 waterbodies)". Habitat % is of the area of the waterbodies with habitat figures.
- **"SWW sewage outflows (CSO & STW)" is counted from the storm overflow returns**: the overflows
  into the location's waterbodies in the latest year (152 for North Devon, against 167 on the
  original, because overflows with no waterbody ID are left out; see Open questions).
- **The water company's name comes from the storm overflow data** ("South West Water"), so the
  labels say "Properties on South West Water sewerage" rather than "SWW".
- **Intervention Management and Catchment Insights are placeholders:** the focus-area buttons
  work, each showing its name and "This section is under development." Critical Path used to
  show a starting position (rivers, good, failing) from the EA's classifications; Tom had it
  made the same as the others (6 November 2026). A small script (`static/tabs.js`) switches between sections; without it
  every section is shown.

**The new tables** (Tom, 5 November 2026)
- **A table for every panel,** all filled by Excel upload, so the data can be uploaded as it
  arrives. Each shows on the pages as soon as it has rows.
- **Tables about a whole location have a `location_id` instead of a `catchment_id`** (the rule
  in the master file now allows either, but not both). `location_text` is the first. In its
  Excel file, North Devon is location 1. The admin diagram joins it to Locations.
- **Worked out, not stored:** livestock density (number per 100 ha of the catchment), % of
  catchment, private sewerage per ha, the Continuous / Diffuse split of phosphate (adding up the
  sources by their `discharge` column), and the Catchment Dashboard's totals.
- **Typed in until their rules are agreed:** ranking, risk levels, relative coverage and
  density rating (PLAN.md §9.3). Each could be replaced by a calculation later.
- **Risk levels are one column per risk** (eight), rather than a row per risk, so the Excel file
  is one row per waterbody and the risk names can't be mistyped.
- **Hand-written text is in Excel cells:** Alt+Enter starts a new line, a blank line a new
  paragraph, and lines starting with "- ", "* " or "•" become a list. It's always shown as typed,
  never as HTML.
- **EA Scores now holds the measured values behind the EA's statuses** (e.g. Fish (EQR) 0.36),
  named as on the original's EA Data page; EA Thresholds holds each measure's thresholds, per
  catchment because some depend on the river's type. The EA Data grid places each measure as on
  the original (the list is `MEASURES` in `figures.py`): an item with one measure shows its values
  in its own row (e.g. "Fish (EQR)" instead of "Fish"), coloured by the EA's status; an item with
  several (Invertebrates, pH) keeps its row of statuses with a row for each measure below. Any
  other measure goes at the bottom. Values show at least 2 decimal places, more if given (0.057).
- **The Sewerage page's two explanations** (intermittent and continuous discharges) are the same
  for every waterbody, so they're in Location Text.

**Locations**
- **Just a name and a list of catchment IDs.** Other location details (intro text, photo, branding, contact email) will go in location tables. Whatever saves a location must check the IDs exist, because the database can't check IDs inside a list.

**Hosting**
- **One Azure VM running Docker Compose,** with the option to move to separate Azure services if it grows (PLAN.md §5.5).
- **Caddy for the web server** (when the VM is set up), rather than nginx, because it gets and renews the HTTPS certificates itself. It only does HTTPS and serving files: the login is in the Python app. Until it's added, the live admin page is only reachable through an SSH tunnel.
- **Three Compose files:** shared, dev (loaded automatically) and live (chosen by `COMPOSE_FILE` in the server's `.env`). Passwords on the server have no defaults.
- **The data map is a page in the admin site, behind the login** (Tom, 5 November 2026), rather than a file opened from disk or a page at an unlisted address. The admin page makes it from `schema.yaml` when it's opened, so there's no file to rebuild and it's on the live server with no extra setup.
- **The data map is a flow diagram** (Tom, 5 November 2026), chosen from five designs: where the data comes from → tables → Catchments → dashboards, with a panel of details when a table is clicked. It replaced the original page of text and tables.
- **The data map became the admin page** (Tom, 5 November 2026). Logging in goes straight to the diagram, headed "Your data"; the list of tables and each table's own page are gone. An Excel table's details panel has the download, the upload and its recent uploads (and any upload waiting to be approved, also shown on the table's box). The preview stays a full page, because it can list hundreds of rows; approving or cancelling goes back to the diagram with the table's panel open. An upload's problems are shown in the panel too. Its code moved from `datamap/` into `admin/` (`diagram.py`, `diagram.yaml`, `templates/home.html`), since it's no longer optional. The old addresses (`/admin/data-map`, `/admin/tables/<table>`) redirect to it.
- **Upload on the left, download for every table** (Tom, 5 November 2026). The diagram's key and introduction were removed, and its column headings now say which are tables: "Data tables", "Catchments table", "Locations table". Each Excel table has its own box in the left-hand column ("where the data comes from") with an **Upload data** button, which opens the upload (download, edit, upload, recent uploads, any upload waiting to be approved); approving, cancelling or a problem with the file comes back to it (`/admin#upload-<table>`). Clicking any table, Excel or not, shows its details and a **Download as Excel** button (`/admin#<table>`). Only Excel tables can be uploaded. Map shapes (the catchment outline and river line) are left out of downloads: each is thousands of coordinates, no use in Excel, and the longest North Devon outline (22,555 characters) is already two-thirds of what an Excel cell holds, so bigger catchments elsewhere could go over; lists of IDs become comma-separated text, and times are in UK time.
- **Every table has its own "where the data comes from" box, and a table's panel is only about the table** (Tom, 5 November 2026). Clicking a table shows just its title, its name in the database, its description, **Download as Excel** and its columns; the row count, "one row for each", where it comes from and the Links section were removed. Where its data comes from moved to its box in the left-hand column: one per import command (so EA Classifications and EA RNAGs, both filled by `importer classifications`, share one), and one per other table. The boxes are wide and two lines high, with their button beside "API" (or "Uploaded in Excel"). A downloaded box opens the source's website (`url` in `diagram.yaml`, which must start with https://) and its command (`/admin#from-<table>`, for any of its tables); a housekeeping box opens its note; an Excel table's opens Upload data (`/admin#upload-<table>`). Source names say "EA" rather than "Environment Agency" (only on the admin page: the dashboard's licence credits still say it in full). Catchments stays in the third column, joined by a line to its own box in the top row. Locations has no box on the left: it's the dashboards' list, changed with a database command (see OPERATING.md).
- **A "Transformation" step between where the data comes from and its tables** (Tom, 5 November 2026), as the diagram's second column, so data can one day arrive in another layout (e.g. a file someone was sent, uploaded as it is) and be changed to fit the table. Every Excel upload is **1 to 1 for now** (a dashed box, "No change, for now"): the file must already be in the table's layout. Each downloaded source's box says "Reshaped" and, when clicked, lists in a few steps what its importer does to the downloads (`transformation` under `filled` in `diagram.yaml`). Housekeeping tables have none. Clicking opens `/admin#transform-<table>`. The wide layout now needs a screen at least 960px wide (it was 860px); narrower ones get the stacked layout. Only the page shows the step so far: the Excel upload code has no transformation in it yet. When the first one is needed, it would go just before `read_upload` in `importers/excel/workbook.py`, with its steps written under `filled` in `diagram.yaml`.
- **The text under the dashboards is laid out as on the original** (Tom, 6 November 2026; `UnderWaterbodyDashboard.jpg`, `UnderCatchmentDashboard.jpg`): an introduction (on the Waterbody Dashboard, in a grey box), bullets, "Understanding the dashboard", then grey sections that open and close (+ / −), the first one open. It's Tom's text, in Location Text (upload 17), with formatting marks added; the Waterbody one is about 13,500 characters, well within an Excel cell's 32,767. **Every hand-written text box now uses the same few Markdown marks** (`publish/text.py`, using the `markdown-it-py` library): bullets (`-` or `•`, two spaces in for a bullet inside a bullet), `**bold**`, `[words](https://…)` links, `## heading`, `### section` (opens and closes), `#### small heading` and `> grey box`; web and email addresses become links by themselves. Nothing else in Markdown is switched on, so typed HTML, file paths and underscores show as typed, and a link that would run a script isn't made. The rules are in Location Text's description on the admin page. **The contact email column was dropped,** as the email is now in the text itself (it was the same address); the automatic "If you have any queries…" sentence went with it. The text under the dashboards is in Arial, as on the original and like the cards at the top.
- **Datasets is just a table name and its "i" text, uploaded in Excel** (Tom, 6 November 2026). It had a numbered ID, name, description, source, link, date, caveats, "national" and two timestamps, but nothing could fill it (only a database command), and the name and source repeated `schema.yaml` and `diagram.yaml`. Now it's two columns, keyed by the table's name, with one free-text box for whatever the "i" should say. It moved out of Housekeeping into the Excel tables, with its own Upload data box, and its box says it's behind the "i" buttons on every dashboard page. Only 7 of the 17 data tables have an "i" button (EA Classifications, Catchment Ranking, Risk Levels, Habitat & Land Use, Livestock, Phosphate Sources, Sewerage Improvements); a row for any other table is kept but not shown. Changing its primary key needed the schema tool to learn to change keys (`_primary_key_changes` in `db/sync.py`; before, it only warned, and `apply` would have left the table with no key).
- **Each data table's box lists where it's shown on the dashboards** (Tom, 6 November 2026), so someone looking at a panel (e.g. "Intervention hypothesis") can find the table to update. Each box in the "Data tables" column lists the pages and, as small tags, the panels on them. The same panel name can come from different tables on different pages: "Intervention hypothesis" is River Status Text on the River Status tab, but Location Text on the Catchment Dashboard. The list is `dashboard` in `diagram.yaml`, written page by page in the dashboards' order, so it has to be changed by hand when a panel is added, renamed or moved; a test checks every data table is on it. To make room, the page is wider (up to 1840px, from 1440px) and the Data tables column takes most of the extra. On screens 1600px and wider the panels sit beside the table's name; on narrower ones they go under it, so the page is longer there. The Catchments table (River Information, the map outlines) isn't listed, as it isn't in that column.


**The Publish button** (agreed 10 November, built 11 November 2026)
- **A Publish button at the top of the admin page,** rather than publishing automatically after
  every approval, so several uploads can be approved, checked, then published at once, and
  nothing goes public as soon as it's approved. It runs the same code as
  `docker compose run --rm publish` (`publish/run.py`), which takes about 4 seconds for North
  Devon, so the page simply waits for it ("Publishing…").
- **Every publish is recorded in a `publishes` table** (when, and who), by the button and the
  command alike. The box beside the button uses it: "2 uploads approved since the last
  publish, so not on it yet: Datasets and Location Text", or "Everything approved is on it",
  with when and by whom it was last published. Until the first publish is recorded it says
  "No publish recorded yet", as earlier publishes weren't recorded.
- **Only Excel uploads are counted.** The importers don't record their runs, so after an import,
  publish anyway.
- **Only one publish at a time** (a lock in the database), so two people pressing Publish, or a
  double click, can't write the same folders at once. The second waits, then publishes again.
- **The box is on the left, under "Your data",** so it can still be seen beside an open panel,
  e.g. straight after approving an upload. The approval message now ends "It will be on the
  public dashboard once you publish."
- **The admin container can now write to `published/`** (both Compose setups), as the publish
  container could. On the live server, the admin page needs `docker compose up -d --build`
  and `schema apply` for this.

**Intervention Management** (Tom, 12 November 2026: "recreate the intervention management page the same as it is there")
- **Copied from the North Devon Biosphere's own pages,** <https://www.northdevonbiosphere.org.uk/north-devon-catchment-interventions.html>
  and the 16 pages under it, read in a browser (the text, tables and their formatting) and uploaded through the admin page
  (uploads 35 to 38). It isn't in `Reference/ReferenceData`: only `Interventions table.xlsx` is close, and it's an older
  version of the waterbody lists (different counts, and no funding, delivery or groups). A backup from just before is
  `backups/before-intervention-management-2026-11-12.dump`.
- **Three new tables and four Location Text columns** (`schema.yaml`): Intervention Types (one row per type of
  intervention: its summary line, its Interventions Detail overview and progress, and its group headings), Intervention
  Waterbodies (one row per waterbody and type), Intervention Unit Costs (one row per type), and Location Text's
  `critical_path`, `unit_costs_purpose`, `intervention_summary` and `community_action`.
- **The figures are as the website shows them, not added up,** because the website's own figures don't agree with each other
  (Open questions), and the summary's % available is a judgement. Only the summary's "Total" lines are worked out (`SummaryPart`
  in `figures.py`), from the lines above them, so they're 0.1–0.2 different from the website's (e.g. c.£366.1m available, where
  it says c.£366.2m). The overview's figures are kept as written (e.g. "£120m (£42m already secured in AMP8 & AMP9)").
- **Waterbody costs and funding are numbers** (so the tables sort and could be added up later), shown as £3m or £2.04m from a
  million, and £16,000 below (the website mixes £16k, £300,000 and £1,008k). An empty Funding Available shows nothing, as
  on the website, and 0 shows £0.
- **Each waterbody's name links to its River Status page,** which the website's don't. A note after the name (e.g.
  "– active mine impacts") is its own column. The website's spellings Mussell Brook, Wooleigh Brook and Upper Little River
  Dart River are the EA's Mussel Brook, Woolleigh Brook and Upper Little Dart River.
- **Interventions Detail is one page with a second row of tabs** (the twelve interventions), like the focus areas above it,
  rather than a page each as on the website. `tabs.js` now copes with a set of tabs inside another, and a link to
  `#intervention-9` opens both. A type's button says its `button` text (e.g. "Farming rules enforcement"), or its name.
- **A line of just `---` starts a new box** in the Critical Path text (`boxes` in `publish/text.py`), for its three boxes.
- **The layout copies the website's:** yellow panels with pale boxes for Critical Path, Unit Cost and Interventions Detail,
  white for the Summary and Community Action, its blue table headings, light blue and green summary rows, and Arial
  (the website uses Jost). The "under development" note is gone from this view; Catchment Insights keeps it.
- **River Status's interventions come from the same tables** (Tom, 12 November 2026): the waterbody's rows in Intervention
  Waterbodies, as Intervention, Size of Intervention, Estimated Cost and Lead (the columns the original's v9 used), grouped
  as in the Intervention Summary (Priority interventions, then Secondary interventions) rather than Primary / Contingency,
  which the new data doesn't have per waterbody. Each intervention links to its page in Intervention Management. The old
  Interventions table (desired change, lead partner, actions, how we'll know) is out of `schema.yaml`. Tom dropped it from the local database the same day (`schema apply --allow-data-loss`). Its 240 rows are in
  `backups/before-dropping-old-interventions-2026-11-12.dump` and in its kept upload,
  `imports/raw/interventions/2026-11-12_135154_29.xlsx`.
- **Left out:** the two photos on Community Action (people at Taw and Torridge River Champions events). There's no way to add
  pictures to the dashboard yet, and they show identifiable people (Open questions).

**Catchment Insights** (Tom, 12 November 2026: "I don't think we should store this into the database for now")
- **Copied from the North Devon Biosphere's pages** (<https://www.northdevonbiosphere.org.uk/north-devon-catchment-insights.html>
  and its eight focus areas): each focus area's questions, in groups under headings, shown as rows that open (+ / −). None has
  an answer yet (the first in five areas says "..."), and Intervention Strategy, Funding & Delivery and Other are just "TBC",
  as on their pages. The "under development" note stays at the top, as on theirs.
- **In a file, not the database:** `backend/catalyst/publish/content/north-devon/catchment-insights.yaml`, one folder per
  location (by its web address), so another location doesn't show North Devon's questions; a location with no file shows
  "This section is under development." To add an answer, put `answer:` under its question (the same marks as the other
  text: bullets, **bold**, links), then publish. On the live server that's a code change: commit, pull and
  `docker compose run --build --rm publish`. A focus area named differently from its button, or a question with no
  `question:` line, stops the publish with a message rather than going missing (`catchment_insights` in `site.py`).
- **The layout copies theirs:** a blue box per group (#3387a2) with grey rows in capitals, opening to a pale panel, in Arial.
  The rows are plain `<details>`, so they open without any script.

**Loading the Waterbody Scorecards data** (Tom, 12 November 2026: "keep the structure of the
database the same, so literally just adding the data")
- **No change to `schema.yaml` or the code.** Each table's file was built from the sources and
  uploaded through the admin page like any other upload. Where a source doesn't fit a table
  without new columns, it was left out (listed under Open questions).
- **The original's rules were read from its Power BI file** (`Waterbody Scorecard Dashboard
  v9.pbix`: its calculated columns, measures and Power Query steps), so risk levels, density
  ratings and relative coverage are worked out exactly as the original did, not typed in. That
  answers most of PLAN.md §9.3 for now; the rules live only in the built files, so new data
  needs them applying again (or, later, in the code).
- **EA Scores' status is worked out from the thresholds,** as the original coloured its values
  (e.g. phosphate below Good's threshold is Good). The dashboard still prefers the EA's own
  status where it classifies the item itself (e.g. Fish).
- **Values are rounded:** EQRs, ammonia and phosphate to 3 decimal places, dissolved oxygen,
  temperature and pH to 2, so the page shows 0.363 and 89.69 rather than 0.3626 and 89.68999.
  Statuses were worked out before rounding.
- **Phosphate's Continuous is STW (SWW) + CSOs (SWW),** everything else Diffuse. That
  reproduces the EA's "Point" figure in 81 of 91 waterbodies, including Langham Lake's 61.0 /
  39.0. The other 10 (mostly on the Taw and Mole) differ by up to 30 points, because the EA's
  Point figure includes phosphate from upstream. See Open questions.
- **Works with several overflows** (12 sites, e.g. Okehampton STW) have a row per overflow in
  Sewerage Improvements, named with Water UK's ID, e.g. "OKEHAMPTON STW (SWW0562)", because
  the table allows one row per site name in a waterbody. The 24 North Devon overflows Water UK
  marks "Not part of a river WB catchment" are left out.
- **Left out rather than guessed:** Upper East Lyn River's farm count (blank in the source),
  Burcombe Stream's dairy cattle (APHA gives "Less than 5"), Bradwell Stream's phosphate sources
  (not in SAGIS), and the 12 empty rows in the interventions file (waterbodies already at Good).
- **The "i" text for Risk Levels leaves out "SWW Treated Sewage",** the original's ninth risk,
  which has no tile here.
- **`FARM COUNTS 2026_09_11.xlsx` has farmers' names, addresses, phone numbers and emails.**
  Nothing was taken from it: its per-waterbody counts (Sheet3) are the same as Waterbody
  Lookup's FARMS for all 91, so Waterbody Lookup was used. Its personal details must never go
  into the database or the dashboard.

---

**Hosting the demo (11 November 2026)**
- **The client demo goes on IGI's shared test VM** (20.39.226.55), next to Brownfield GIS, rather than on a VM of its own. The dedicated VM in PLAN.md §6.2 is for when the platform is built properly. **Deployed 12 November 2026, waiting for the DNS record** (see "Deployed to the test VM", below).
- **Address: `rivers.smartbiosphere.com`.** Plain English for the public, where "catchment" and "intervention" are jargon. The other options were `riverrecovery` and `riverhealth`. `riveraction` was avoided because River Action is a well-known campaign group. The separate live sensor dashboard (on Azure App Service) will have its own smartbiosphere.com address.
- **A shared front door owns the web ports.** Only one program on a machine can use ports 80 and 443, so a Caddy server from the [front-door](https://github.com/tom-igi/front-door) repo sends each address to its app and gets the HTTPS certificates. So on that VM, this app doesn't run the web server of its own that PLAN.md §5.1 describes. Instead, `docker-compose.front-door.yml` adds a small `web` container for `published/` and moves the database to port 5433.
- **The address opens North Devon directly** (a redirect from `/` to `/north-devon/`), because smartbiosphere.com is North Devon's. The list of locations is still at `/index.html`.
- **The front door gets the certificate on the first visit** (Tom, 12 November 2026), so the address works as soon as smartbiosphere.com's IT person adds the DNS record, with nothing to do on the VM then. `rivers.caddy` in the front-door repo is switched on with Caddy's *on-demand* certificates (`tls { on_demand }`): Caddy doesn't ask Let's Encrypt when it starts, only during the first visit, and visitors can only arrive once the DNS points at the VM. Without it, Caddy would ask straight away, fail while there's no DNS record, and retry less and less often. Tested locally with Caddy 2.10 (the VM's version): it starts without asking, and a visit makes it ask. Until the DNS record is there, the admin page is reached through an SSH tunnel to its container (README.md, step 9).
- **On the live server, the database's files are in `db-data/`** in the app's folder (Tom, 12 November 2026), rather than a Docker volume, so everything for the app is in `/opt/catchment-catalyst`. `docker-compose.prod.yml` does this, so your machine still uses the volume. On the server, `docker compose down -v` no longer deletes the database. Copying the folder isn't a backup: backups still use `pg_dump`.
- **The test VM has room** (12 November 2026): 2.9 GB of memory available (the app uses about 0.5 GB) and 19 GB of disk free. It has no swap. Don't use its `/mnt` disk: that's Azure's temporary disk, wiped when the VM is deallocated.

**Deployed to the test VM (12 November 2026)**
- **Running in `/opt/catchment-catalyst`,** with the front door's `rivers.caddy` switched on (on demand). **Waiting only for the DNS record** (an A record `rivers` → `20.39.226.55`, asked of smartbiosphere.com's IT person). Then check `getent hosts rivers.smartbiosphere.com` on the VM and open <https://rivers.smartbiosphere.com>: the first visit gets the certificate.
- **The data was copied from Tom's laptop** instead of importing and uploading again (README steps 7 and 9): `pg_dump` here, `pg_restore --no-owner --no-privileges` into the VM's empty database (no `schema apply` first), `imports/raw/` copied with `scp`, then `schema plan` and `publish`. Tested locally first in a throwaway live-style copy: every table's rows matched, `schema plan` said the database matches, and the published pages matched (apart from code changed since the laptop's last publish). The README still describes the import-and-upload route; updating it is offered.
- **The live admin login is `tom`** (made with `hash-password`).
- **Before the DNS record, view it through an SSH tunnel** to the containers (their addresses from `docker inspect … catchment-catalyst-web-1 catchment-catalyst-admin-1`): dashboards at <http://localhost:8081/north-devon/>, admin at <http://localhost:8001/admin>.
- **SSH from WSL to the VM** works since WSL's own key was added to the VM's `~/.ssh/authorized_keys` (Windows already had its own, different key).
- **Still to do:** nightly backups (until then, the only copy of the live data is `backups/catalyst.dump` on the laptop, as of 12 November) and OPERATING.md §2 and §3. **To start again on the VM:** `docker compose down` in the folder first, then `sudo rm -rf /opt/catchment-catalyst` (the database is in `db-data/`, so nothing is left elsewhere apart from Docker images).
- **The dashboards can be embedded** in another site, such as Smart Biosphere's (no `X-Frame-Options`). The admin page can't be.

---

## Open questions

- **Web address for each location:** for now it comes from the name (`north-devon`). North Devon's demo is at `rivers.smartbiosphere.com` (above). For other locations: will each have its own domain, or a path on one shared domain?
- **Managing locations:** add a page to the admin site, or keep using SQL while there are only one or two?
- **Several locations in one table:** when that happens, replace only the rows for the catchments in the file (PLAN.md §3.4), so locations don't have to share one Excel file.
- **Estuaries and coastal waters:** import them too, so every upstream/downstream ID finds a name?
- **When the platform's own VM is set up** (the demo uses the shared test VM, where git access is already set up): is UK South the right region? Does the private repository need a deploy key?
- **EA Data values:** answered (12 November 2026). The original's come from the EA's classification facts (`EA WFD Data/North Devon WB Classification Facts Data.xlsx`, site by site: the mean for biology, the median for physico-chemical). They're in EA Scores now, from the original's exports. An importer could work them out from the facts instead.
- **2025 classifications:** the EA's 2025 file is now in `EA WFD Data/` (`WFD_River_Canal_and_SWT_Water_Bodies_Cycle_4_Classification_2025.xlsx`), and the text under the Waterbody Dashboard already says the map shows 2025. Until it's loaded into EA Classifications, the map, the "EA Ecological Classification" panel, failing elements and the Catchment Dashboard's counts all show 2022. On the EA Data page, the 2025 column has only EA Scores' values: its status rows (Ecological, Invertebrates and so on) are empty. EA Classifications is filled by `importer classifications`, which replaces every row, so 2025 rows added by hand would be lost at the next import. **Decided (Tom, 12 November 2026): don't change the importer; wait for the Catchment Data Explorer.** On 12 November 2026 it still stopped at 2022 (cycle 3). The EA published the 2025 (cycle 4) results separately on its data services platform and plans to update the Catchment Data Explorer in December 2026. Then re-run `importer classifications` (and publish). The 2025 file has the same 92 waterbody IDs as ours.
- **Interventions: which layout?** Answered (12 November 2026): River Status now uses Intervention Management's tables, which have the newer layout (intervention, size, cost, lead).
- **Storm overflows with no waterbody ID:** also tie them to a catchment by location? That would add a few North Devon stream outfalls (e.g. Fremington) the original doesn't show.
- **Catchment Dashboard text per operational catchment?** For now one set per location. The text for Hartland and Clovelly Streams, Taw and North Devon Streams, and Torridge is written (`Catchment dashboard/Catchment dashboard summaries.xlsx`) but has nowhere to go without a new table or columns.
- **The card pictures:** the real images for the four cards (the stand-ins are cut from the screenshots).
- **Intervention Management's figures disagree on the website itself** (loaded as shown; worth fixing at the source):
  Investment in STWs is 40 waterbodies and £120m in the summary, "13 highest priority, 27 secondary" in its overview,
  but its tables list 41 (13 + 21 + 7, £123m); poultry manure is £1.5m in the summary, £1.9m in its overview, and its
  rows add up to £1.85m (and its overview says £0.4m is available, its rows £0); riparian tree planting is 48 waterbodies
  but its table lists 50; fish habitat is 7 in its overview, 8 in the summary and table, and "six" in its progress; private
  sewerage costs £170,000 but has a £180,000 gap, and its progress says 18 waterbodies for 17 rows; dairy/beef's overview
  says £1.5m is available, its rows £0; the summary's bullets say £387.9m and £18.9m, its total row £388.0m and £19.0m.
  Upper River Yeo (Lapford) is AMP9 but finishes 2025-2030 for phosphate. Once they agree, the summary's figures could be
  added up from Intervention Waterbodies instead of typed in.
- **Community Action's photos:** add them (the dashboard would need a place for pictures), or leave them out?
- **Phosphate Continuous / Diffuse:** answered: the original shows the EA's own Point / Diffuse figures (`SAGIS Phosphate source.xlsx`, "Phosphate Point vs Diffuse" sheet), which include phosphate from upstream, so adding up the sources can't always match. Adding up is within 0.5 points for 81 of 91 waterbodies; the other 10 differ by up to 30. To match exactly, the EA's figures need a table (or two columns) of their own.
- **Not loaded, as the tables have nowhere for them:** the EA's inspection figures per operational catchment (`EA Inspections data/`), SWW's phosphate permit limits per works (`SWW Discharge Permits/`), the original's ninth risk ("SWW Treated Sewage", from phosphate and SAGIS), its "Main pressure" per waterbody and its eutrophication risk (`CaSTCo EA Eutrophication Risk/`), the EA's programmes of measures (`EA RNAG POM Data/RNAG POM.xlsx`), Change Needed To Achieve Good / Moderate, and the Standardised Scoring workings behind the ranking. Already in the database from their original sources: the EA's classifications and RNAGs, storm overflow spills, river obstacles and the catchment outlines.
- The remaining questions in PLAN.md §9.3 (branding, admin users). Ranking, risk levels, rating bands and phosphate sources now follow the original's rules (above).

---

## Suggested next steps

1. **Look over the four views at <http://localhost:8080>** (published 13 November 2026, with the real data and the postcode search), then put the postcode search on the test VM (see "The postcode search").
2. **Decide the open questions the data raised:** the interventions layout, the operational catchment texts and the EA's Point / Diffuse figures (Open questions). In December 2026, check the Catchment Data Explorer for the 2025 classifications and re-run `importer classifications`.
3. **Finish the demo on the shared test VM:** deployed 12 November 2026, waiting for the DNS record. Once it's in, check the address, then set up nightly backups and fill in OPERATING.md §2 and §3.
4. **Answers for Catchment Insights,** as they're written (in its content file), and the TBC focus areas' questions; move them into the database if they're to be edited on the admin page.
5. **Move the original's rules into the code** (risk levels, density ratings, relative coverage), so new data needs only its raw figures uploading, if wanted.
6. **Have GitHub run the tests on every push** (offered, not yet agreed).
7. **More from the EA, if wanted:** the Catchment Data Explorer also has `objectives` (target status and date per item), `investigations` and `site-classifications` (monitoring sites) per management catchment.

---

## Things to know

- **The EA sometimes sends an error page instead of a file,** so the importer retries. For an ID it doesn't recognise, it answers "error 500" rather than "not found".
- **If the EA changes its waterbody web page,** the importer stops with a clear error and its page-reading code needs updating (`backend/catalyst/importers/api/catchments.py`). The other importers stop the same way if a download's columns change.
- **Importing all 92 catchments takes a few minutes** (two downloads each, with a pause between). The storm overflow import downloads about 18 MB (one file per year) and takes a minute or two to read.
- **The EA replaces storm overflow files in place when it corrects them,** so re-run `importer storm-overflows` now and then. The downloaded files are kept in `imports/raw/storm_overflows/`.
- **On the live server, always use `--build`** with `docker compose run`. The code is built into the image there, so without it the old version runs.
- **`docker compose down -v` deletes the local database.** Plain `docker compose down` keeps it.
- **After a change to `requirements*.txt`, rebuild:** `docker compose up -d --build` and `docker compose run --build --rm test`. Code changes need no rebuild locally, because the admin page restarts by itself.
- **On the live server, every `docker compose` command needs `ADMIN_USERS` and `ADMIN_SECRET_KEY` in `.env`,** even commands that don't use the admin page. Make the `ADMIN_USERS` entries on your own machine.
- **The admin page's port is 8000, and the dashboard preview's is 8080** (change `ADMIN_PORT` or `WEB_PORT` in `.env` if either is taken).
- **The dashboard doesn't update by itself:** after approving uploads (or running an importer), click **Publish** on the admin page, or run `docker compose run --rm publish`.
- **Browsers keep copies of the dashboard's styles, scripts and map file,** so every link to them ends with `?v=` and a fingerprint of the files (`version()` in `publish/site.py`). It changes whenever one of them does, so a publish is always seen straight away. (Before this, a browser could show an old stylesheet: Ctrl+F5 fixes that.)
- **OpenStreetMap's map images are free for light use only** (their tile usage policy). Fine for now; a busy public site may need a paid map provider, which is a one-line change in `static/map.js`.
