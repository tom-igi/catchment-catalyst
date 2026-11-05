# Progress

Where the build is up to, the decisions made along the way, and what's next.
For the overall design, see [PLAN.md](PLAN.md). For commands, see [README.md](README.md).

**Last updated:** 5 November 2026

---

## Picking up again

**Just running it?** [OPERATING.md](OPERATING.md) has only the essential commands (written for
Tom to run things himself, 29 October 2026).

```bash
docker compose up -d                      # start the local database, admin page and dashboard preview
docker compose run --rm schema plan       # should say "The database already matches schema.yaml."
docker compose run --rm test              # run the tests (127 passing at the last update)
docker compose run --rm publish           # rebuild the dashboard pages from the database
```

- Admin page: <http://localhost:8000/admin> (name `admin`, password `admin`)
- Data map: <http://localhost:8000/admin/data-map> (or **Data map** at the top of the admin page)
- Dashboard: <http://localhost:8080>

The local database is on `localhost:5434` (database, user and password are all `catalyst`),
for DBeaver or pgAdmin.

**Working style:** one step at a time. Each step is suggested and agreed before it's built,
and optional extras are kept self-contained so they're easy to remove.

---

## What's built

| Part | Where | What it does |
|---|---|---|
| **Database master file** | `backend/catalyst/db/schema.yaml` | Lists every table and column. The only place the database structure is defined. |
| **Schema tool** | `backend/catalyst/db/` | `schema plan` previews changes, `schema apply` makes them. All-or-nothing, refuses to delete data unless told to, handles renames. |
| **Catchments importer** | `backend/catalyst/importers/api/`, `imports/` | Fills the catchments table from the EA's Catchment Data Explorer, for the management catchments (all their rivers) and IDs in `imports/catchments.json`. Preview first, safe to re-run, keeps the downloaded files. |
| **EA and River Obstacles importers** | `backend/catalyst/importers/api/` | For every imported catchment: the EA's classifications and RNAGs (`importer classifications`), storm overflow spills from the EA's yearly returns (`importer storm-overflows`), and obstacles from River Obstacles (`importer river-obstacles`). Each replaces its table, with a preview first, and keeps the downloads. |
| **Excel uploads** | `backend/catalyst/importers/excel/` | For every table marked `filled_by: excel`: download it as Excel, upload an edited copy, see what will be added, changed and deleted, then approve. No code per table. |
| **Admin page** | `backend/catalyst/admin/` | The web page for the Excel uploads, with a login (one name and password per person). Runs with `docker compose up -d`. |
| **Publish step and dashboard** | `backend/catalyst/publish/`, `published/` | Writes each location's dashboard as plain web pages, laid out like the original (`Reference/ReferenceImages`): River Status, EA Data, Land Use Data and Sewerage Data (the Overview is built but switched off for now). Panels with a table are filled in (map colours, classifications, failing elements, RNAGs, catchment details, Habitat & Land Use, river obstacles, storm overflow spills); the rest are empty until their table exists. Previewed at <http://localhost:8080>. |
| **Data map** | `backend/catalyst/datamap/` | A diagram of every table, in the admin page at `/admin/data-map` (login needed): where each table's data comes from (downloaded or Excel), how they join up by Catchment ID, and its columns when clicked. Made from `schema.yaml` (and `sections.yaml` in its folder) each time it's opened. Self-contained: deleting the folder removes it (see its `README.md`). |
| **Dev and live setup** | `docker-compose*.yml`, `.env*.example` | The same commands on your machine and on the live server. Only the settings differ. |
| **Tests** | `backend/tests/` | Cover the schema tool, the importers, the Excel uploads, the admin page, the publish step and the data map. |

### Tables so far

| Table | Kind | Holds | Rows |
|---|---|---|---|
| `catchments` | Core | Every EA river waterbody: details, outline, river line, area, length, upstream/downstream IDs. Filled only by the importer. | 92 (every North Devon river) |
| `locations` | Core | ID, name, and the list of catchment IDs | 1 (North Devon, with the 92 catchments) |
| `datasets` | Core | One row per data table: name, source, caveats (for the "i" buttons) | 0 |
| `uploads` | Core | Every Excel upload: table, file, who, when, status, rows added / changed / deleted | 2 |
| `ea_scores` | Data, Excel upload | EA classification results per catchment, measure and year | 48, **made up** |
| `habitat_land_use` | Data, Excel upload | Area of each habitat type per catchment | 14, **made up** |
| `ea_classifications` | Data, EA | The EA's status for each classification item and year (2009 to 2022), per catchment | 27,294 |
| `ea_rnags` | Data, EA | The EA's reasons for not achieving good: element, activity, sector | 513 |
| `storm_overflows` | Data, EA | Each storm overflow's spills (hours, count) per year, 2021 to 2025, with its location | 755 (about 150 overflows into 57 catchments) |
| `river_obstacles` | Data, River Obstacles | Weirs, culverts, fords and so on, with their location | 423 (in 80 catchments) |

`catchments` and the four tables after it are filled by importers; `ea_scores` and
`habitat_land_use` by Excel upload.

**The EA Scores and Habitat rows in the local database are invented,** to have something to
show on the dashboard. They were uploaded through the admin page on 29 October 2026 (uploads
1 and 2), for the first 2 catchments only. Uploading the real data replaces them completely.
**EA Scores is no longer shown on the dashboard:** the EA's real classifications replaced it
(see "EA data" below).

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
- **Each table says how it's filled** with `filled_by` in the master file: `api` (an importer, in `importers/api/`) or `excel` (the admin page, using the shared code in `importers/excel/`). The admin page only lists `excel` tables, and the data map shows which is which.
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
- **Plain web pages, not a JavaScript app.** The dashboard only shows data (tables and a simple map), so the publish step writes the data straight into the pages, as the data map does. There are no API calls and no build step. React and TypeScript were considered: they'd only pay off for a much more interactive dashboard.
- **The publish step has two halves:** `collect.py` gathers a location's data and knows nothing about web pages; `site.py` and the templates turn it into pages. A different front end could reuse the first half.
- **The pages copy the original dashboard's five tabs and colours** (29 October 2026). Each tab except the Overview has a page per catchment (`<tab>/<catchment ID>/`) and one before a catchment is chosen (`<tab>/`). Clicking the map stays on the same tab, as in the original.
- **The Overview is switched off for now** (Tom, 29 October 2026; he'll bring it back later). It's still built and tested: `SHOW_OVERVIEW = True` in `site.py` brings it back as the front page. Until then the front page is River Status before a catchment is chosen.
- **Panels with no table yet are shown empty,** with their headings (and table headings) only. That includes the location's text, photo and logo, ranking, risk levels, thresholds, farms, livestock, phosphate sources, sewerage properties and SWW improvement plans.
- **Calculations are in `figures.py`:** each catchment's latest ecological status (for the map colours and the Overview counts), the EA scoring grid, failing elements, RNAGs, each habitat's % of the catchment, and the storm overflow table. Ranking and "Relative Coverage" are still empty: their rules aren't agreed (PLAN.md §9.3).
- **A new data table no longer appears by itself:** it needs a place on a page. The original layout has no space for a generic table.
- **The "i" buttons show the table's row in `datasets`,** and are greyed out until it has one.
- **Tables are sortable** by clicking a heading (a small script, `static/sort.js`). Numbers sort as numbers, and empty cells always go last.
- **Maps: Leaflet over OpenStreetMap,** with the catchment outlines coloured by ecological status (the colours are in `style.css`) and the rivers drawn on top. The original has no background map or rivers; Tom preferred them (29 October 2026). Leaflet is copied into the project rather than loaded from elsewhere.
- **One self-contained folder per location** (`published/north-devon/`), so each can later be served at its own address. Each folder is built alongside the old one and swapped in, so a half-written dashboard is never served.
- **A location's web address comes from its name** (North Devon → `north-devon`), for now.

**EA data** (29 October 2026)
- **The EA's real classifications replace EA Scores on the dashboard.** They come from the Catchment Data Explorer (`importer classifications`), one download per management catchment, so all 92 rivers take two downloads. They give a status for each item and year but **no values** (e.g. Fish EQR 0.36), so the EA Data grid shows statuses. EA Scores (Excel, invented rows) is still in the admin page but not shown.
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

**Locations**
- **Just a name and a list of catchment IDs.** Other location details (intro text, photo, branding, contact email) will go in location tables. Whatever saves a location must check the IDs exist, because the database can't check IDs inside a list.

**Hosting**
- **One Azure VM running Docker Compose,** with the option to move to separate Azure services if it grows (PLAN.md §5.5).
- **Caddy for the web server** (when the VM is set up), rather than nginx, because it gets and renews the HTTPS certificates itself. It only does HTTPS and serving files: the login is in the Python app. Until it's added, the live admin page is only reachable through an SSH tunnel.
- **Three Compose files:** shared, dev (loaded automatically) and live (chosen by `COMPOSE_FILE` in the server's `.env`). Passwords on the server have no defaults.
- **The data map is a page in the admin site, behind the login** (Tom, 5 November 2026), rather than a file opened from disk or a page at an unlisted address. The admin page makes it from `schema.yaml` when it's opened, so there's no file to rebuild and it's on the live server with no extra setup.
- **The data map is a flow diagram** (Tom, 5 November 2026), chosen from five designs: where the data comes from → tables → Catchments → dashboards, with a panel of details when a table is clicked. It replaced the original page of text and tables. More changes to it are to come.

---

## Open questions

- **Web address for each location:** for now it comes from the name (`north-devon`). Will each location have its own domain, or a path on one shared domain?
- **Managing locations:** add a page to the admin site, or keep using SQL while there are only one or two?
- **Several locations in one table:** when that happens, replace only the rows for the catchments in the file (PLAN.md §3.4), so locations don't have to share one Excel file.
- **Estuaries and coastal waters:** import them too, so every upstream/downstream ID finds a name?
- **When the VM is set up:** is UK South the right region? Does the private repository need a deploy key?
- **EA Data values:** the EA's download has statuses but not the numbers on the original (EQRs, mg/l). Where did the original's come from? If they come as a spreadsheet, EA Scores could become a values-only Excel table shown alongside the EA's statuses.
- **2025 classifications:** wait for the Catchment Data Explorer, or import the EA's separate 2025 download?
- **Storm overflows with no waterbody ID:** also tie them to a catchment by location? That would add a few North Devon stream outfalls (e.g. Fremington) the original doesn't show.
- The remaining questions in PLAN.md §9.3 (ranking, risk levels, rating bands, phosphate sources, branding, admin users).

---

## Suggested next steps

1. **Try the admin page with real data.** Download Habitat & Land Use, paste in real rows for any of the 92 rivers, upload, approve, then `docker compose run --rm publish`.
2. **The next datasets,** for the empty panels. Each needs a table in the master file and filling in its panel. Simple ones can be `filled_by: excel` with no code; fiddly raw files (PLAN.md §9.1) may still need an importer. Not available from the EA: farms and livestock (Defra), land use (e.g. UKCEH Land Cover), phosphate sources, sewerage properties, SWW improvement plans, risk levels and the written text.
3. **Decide what happens to EA Scores** (see Open questions).
4. **Have GitHub run the tests on every push** (offered, not yet agreed).
5. **More from the EA, if wanted:** the Catchment Data Explorer also has `objectives` (target status and date per item), `investigations` and `site-classifications` (monitoring sites) per management catchment. None has a panel on the original.

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
- **The dashboard doesn't update by itself:** after approving an upload, run `docker compose run --rm publish`.
- **OpenStreetMap's map images are free for light use only** (their tile usage policy). Fine for now; a busy public site may need a paid map provider, which is a one-line change in `static/map.js`.
