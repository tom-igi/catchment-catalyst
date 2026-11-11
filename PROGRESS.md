# Progress

Where the build is up to, the decisions made along the way, and what's next.
For the overall design, see [PLAN.md](PLAN.md). For commands, see [README.md](README.md).

**Last updated:** 11 November 2026

---

## Picking up again

**Just running it?** [OPERATING.md](OPERATING.md) has only the essential commands (written for
Tom to run things himself, 29 October 2026).

```bash
docker compose up -d                      # start the local database, admin page and dashboard preview
docker compose run --rm schema plan       # should say "The database already matches schema.yaml."
docker compose run --rm test              # run the tests (167 passing at the last update)
docker compose run --rm publish           # rebuild the dashboard pages (or the admin page's Publish button)
```

- Admin page: <http://localhost:8000/admin> (name `admin`, password `admin`): a diagram of every
  table; click any table to download it, or an Excel table's **Upload data** (on the left) to upload it,
  and **Publish** (at the top) to put what's approved on the dashboard
- Dashboard: <http://localhost:8080> (open North Devon; Langham Lake and West Okement have sample data in every panel)

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
| **EA and River Obstacles importers** | `backend/catalyst/importers/api/` | For every imported catchment: the EA's classifications and RNAGs (`importer classifications`), storm overflow spills from the EA's yearly returns (`importer storm-overflows`), and obstacles from River Obstacles (`importer river-obstacles`). Each replaces its table, with a preview first, and keeps the downloads. |
| **Excel uploads** | `backend/catalyst/importers/excel/` | For every table marked `filled_by: excel`: download it as Excel, upload an edited copy, see what will be added, changed and deleted, then approve. No code per table. |
| **Admin page** | `backend/catalyst/admin/` | One page behind a login (one name and password per person): a diagram of every table (`diagram.py`, `diagram.yaml`) showing where its data comes from (downloaded or Excel), how the tables join up by Catchment ID, and each table's columns when clicked. Any table can be downloaded as Excel from there; each Excel table has its own **Upload data** box on the left, and the upload's preview is its own page. Made from `schema.yaml` each time it's opened. A **Publish** button at the top rebuilds the dashboards, and says how many uploads have been approved since the last publish. Runs with `docker compose up -d`. |
| **Publish step and dashboard** | `backend/catalyst/publish/`, `published/` | Writes each location's dashboard as plain web pages, laid out like the original (`Reference/ReferenceImages`), with four views chosen by cards across the top of every page. **Waterbody Dashboard:** River Status, EA Data, Land Use Data and Sewerage Data, one waterbody at a time (the Overview tab is built but switched off). **Catchment Dashboard:** the whole location on one big map, with its panels over it, and a page per operational catchment. **Intervention Management** and **Catchment Insights:** placeholders with their focus-area buttons. Every panel now has a table. Previewed at <http://localhost:8080>. |
| **Dev and live setup** | `docker-compose*.yml`, `.env*.example` | The same commands on your machine and on the live server. Only the settings differ. |
| **Tests** | `backend/tests/` | Cover the schema tool, the importers, the Excel uploads, the admin page (and its diagram) and the publish step. |

### Tables so far

| Table | Kind | Holds | Rows |
|---|---|---|---|
| `catchments` | Core | Every EA river waterbody: details, outline, river line, area, length, upstream/downstream IDs. Filled only by the importer. | 92 (every North Devon river) |
| `locations` | Core | ID, name, and the list of catchment IDs | 1 (North Devon, with the 92 catchments) |
| `datasets` | Core, Excel | The text in each "i" button: one row per data table that has one (table name, text) | 7, **sample** |
| `uploads` | Core | Every Excel upload: table, file, who, when, status, rows added / changed / deleted | 17 |
| `publishes` | Core | Every publish of the dashboards: when, and who (empty for the publish command) | 2 (both test publishes, 11 November 2026) |
| `ea_classifications` | Data, EA | The EA's status for each classification item and year (2009 to 2022), per catchment | 27,294 |
| `ea_rnags` | Data, EA | The EA's reasons for not achieving good: element, activity, sector | 513 |
| `storm_overflows` | Data, EA | Each storm overflow's spills (hours, count) per year, 2021 to 2025, with its location | 755 (about 150 overflows into 57 catchments) |
| `river_obstacles` | Data, River Obstacles | Weirs, culverts, fords and so on, with their location | 423 (in 80 catchments) |
| `ea_scores` | Data, Excel | The measured values behind the EA's statuses (e.g. Fish (EQR) 0.36), per measure and year: EA Data page | 24, **sample** |
| `ea_thresholds` | Data, Excel | Poor / Moderate / Good / High thresholds per measure: EA Data page | 16, **sample** |
| `habitat_land_use` | Data, Excel | Area of each habitat type, and its relative coverage (typed in): Land Use Data, Catchment Dashboard | 19, **sample** |
| `river_status_text` | Data, Excel | Why is the river failing?, What is happening now?, the intervention hypothesis and its confidence | 2, **sample** |
| `interventions` | Data, Excel | The interventions table: priority (Primary / Contingency), desired change, lead partner, actions, how we'll know | 4, **sample** |
| `risk_levels` | Data, Excel | One column per risk (8), each Very Low … Very High (typed in) | 2, **sample** |
| `catchment_rankings` | Data, Excel | The ranking, e.g. 68 for "68/92" (typed in) | 2, **sample** |
| `farms` | Data, Excel | Number of farms | 2, **sample** |
| `livestock` | Data, Excel | Number of each kind of livestock, and its density rating (typed in) | 8, **sample** |
| `phosphate_sources` | Data, Excel | Each source's % of the phosphate, per year (2025, 2030), and whether it's Continuous or Diffuse | 28, **sample** |
| `sewerage_properties` | Data, Excel | Properties on public (SWW) and on private sewerage | 2, **sample** |
| `sewerage_improvements` | Data, Excel | The water company's planned improvements: site, improvements, completion year, predicted spills | 3, **sample** |
| `location_text` | Data (by location), Excel | One row per location: the Catchment Dashboard's three texts, the Sewerage Data page's two explanations, the text under each dashboard (with its sections) | 1, **sample** (the text under the dashboards is real) |

`catchments` and the four EA / River Obstacles tables are filled by importers; the rest of the
data tables by Excel upload.

**Every Excel table's rows in the local database are samples** (uploaded through the admin page
on 5 November 2026, uploads 3 to 15), so every panel has something to show:
- **Langham Lake** (GB108050014460): copied from the reference screenshots (1–5.jpg), so the
  pages can be compared with the originals.
- **West Okement** (GB108050008080): made up. Its text starts "(Made-up text, for testing.)".
- **North Devon's Location Text**: the Catchment Dashboard's "Why is the river system failing?"
  and the Sewerage texts are copied from the screenshots; "What is happening now?" and
  "Intervention hypothesis" are made up (and say so). The text under the two dashboards is
  Tom's real text (upload 17, 6 November 2026).
- **Habitat** for West and East Okement are the made-up rows from 29 October, now with a relative
  coverage. The old made-up EA Scores rows were replaced.
- **Datasets** (upload 16, 6 November 2026): a row for each of the 7 tables with an "i" button.
  EA Classifications' text is real (where the EA's classifications come from); the other six say
  "(Made-up text, for testing.)", so the download already has the table names in it.

Uploading the real data replaces them completely. The script that uploaded them was a one-off,
kept outside the project.

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
  Clicking a waterbody opens it in the Waterbody Dashboard.
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

---

## Open questions

- **Web address for each location:** for now it comes from the name (`north-devon`). Will each location have its own domain, or a path on one shared domain?
- **Managing locations:** add a page to the admin site, or keep using SQL while there are only one or two?
- **Several locations in one table:** when that happens, replace only the rows for the catchments in the file (PLAN.md §3.4), so locations don't have to share one Excel file.
- **Estuaries and coastal waters:** import them too, so every upstream/downstream ID finds a name?
- **When the VM is set up:** is UK South the right region? Does the private repository need a deploy key?
- **EA Data values:** the EA's download has statuses but not the numbers on the original (EQRs, mg/l), so they go in EA Scores (Excel) for now. Where did the original's come from, and could they be downloaded instead?
- **2025 classifications:** wait for the Catchment Data Explorer, or import the EA's separate 2025 download?
- **Storm overflows with no waterbody ID:** also tie them to a catchment by location? That would add a few North Devon stream outfalls (e.g. Fremington) the original doesn't show.
- **Catchment Dashboard text per operational catchment?** For now one set per location.
- **The card pictures:** the real images for the four cards (the stand-ins are cut from the screenshots).
- **Phosphate Continuous / Diffuse:** adding up Langham Lake's sources gives 60.9 / 39.1; the original shows 61.0 / 39.0, so it may come from its own figures. Is a separate table needed, or is adding up right?
- The remaining questions in PLAN.md §9.3 (ranking, risk levels, rating bands, phosphate sources, branding, admin users).

---

## Suggested next steps

1. **Look over the four views** at <http://localhost:8080> (Langham Lake and West Okement have every panel filled) and the new tables in the admin page.
2. **Upload real data** into the new tables as it arrives: download each from the admin page, replace the sample rows, upload, approve, then click **Publish**.
3. **The details of Intervention Management and Catchment Insights,** when Tom is ready.
4. **Agree the rules** for ranking, risk levels, relative coverage and density rating, so they can be worked out rather than typed in.
5. **Have GitHub run the tests on every push** (offered, not yet agreed).
6. **More from the EA, if wanted:** the Catchment Data Explorer also has `objectives` (target status and date per item), `investigations` and `site-classifications` (monitoring sites) per management catchment.

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
