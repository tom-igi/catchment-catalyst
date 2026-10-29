# Progress

Where the build is up to, the decisions made along the way, and what's next.
For the overall design, see [PLAN.md](PLAN.md). For commands, see [README.md](README.md).

**Last updated:** 29 October 2026

---

## Picking up again

**Just running it?** [OPERATING.md](OPERATING.md) has only the essential commands (written for
Tom to run things himself, 29 October 2026).

```bash
docker compose up -d                      # start the local database, admin page and dashboard preview
docker compose run --rm schema plan       # should say "The database already matches schema.yaml."
docker compose run --rm test              # run the tests (89 passing at the last update)
docker compose run --rm publish           # rebuild the dashboard pages from the database
explorer.exe "$(wslpath -w datamap/site/index.html)"   # open the data map
```

- Admin page: <http://localhost:8000/admin> (name `admin`, password `admin`)
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
| **Catchments importer** | `backend/catalyst/importers/api/`, `imports/` | Fills the catchments table from the EA's Catchment Data Explorer for the IDs in `imports/catchments.json`. Preview first, safe to re-run, keeps the downloaded files. |
| **Excel uploads** | `backend/catalyst/importers/excel/` | For every table marked `filled_by: excel`: download it as Excel, upload an edited copy, see what will be added, changed and deleted, then approve. No code per table. |
| **Admin page** | `backend/catalyst/admin/` | The web page for the Excel uploads, with a login (one name and password per person). Runs with `docker compose up -d`. |
| **Publish step and dashboard** | `backend/catalyst/publish/`, `published/` | Writes each location's dashboard as plain web pages, laid out like the original (`Reference/ReferenceImages`): Overview, River Status, EA Data, Land Use Data and Sewerage Data. Panels with a table are filled in (catchment details, EA Scores, Habitat & Land Use); the rest are empty until their table exists. Previewed at <http://localhost:8080>. |
| **Data map** | `datamap/` | A plain-English web page of every table, rebuilt on every `schema apply`. Self-contained: deleting the folder removes it (see `datamap/README.md`). |
| **Dev and live setup** | `docker-compose*.yml`, `.env*.example` | The same commands on your machine and on the live server. Only the settings differ. |
| **Tests** | `backend/tests/`, `datamap/test_datamap.py` | Cover the schema tool, the importer, the Excel uploads, the admin page, the publish step and the data map. |

### Tables so far

| Table | Kind | Holds | Rows |
|---|---|---|---|
| `catchments` | Core | Every EA river waterbody: details, outline, river line, area, length, upstream/downstream IDs. Filled only by the importer. | 2 (West Okement, East Okemont River) |
| `locations` | Core | ID, name, and the list of catchment IDs | 1 (North Devon, with the 2 catchments) |
| `datasets` | Core | One row per data table: name, source, caveats (for the "i" buttons) | 0 |
| `uploads` | Core | Every Excel upload: table, file, who, when, status, rows added / changed / deleted | 2 |
| `ea_scores` | Data, Excel upload | EA classification results per catchment, measure and year | 48, **made up** |
| `habitat_land_use` | Data, Excel upload | Area of each habitat type per catchment | 14, **made up** |

`catchments` is filled from the EA's API; `ea_scores` and `habitat_land_use` by Excel upload.

**The EA Scores and Habitat rows in the local database are invented,** to have something to
show on the dashboard. They were uploaded through the admin page on 29 October 2026 (uploads
1 and 2). Uploading the real data replaces them completely.

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
- **The pages copy the original dashboard's five tabs and colours** (29 October 2026). The Overview is the location's page; each other tab has a page per catchment (`<tab>/<catchment ID>/`) and one before a catchment is chosen (`<tab>/`). Clicking the map stays on the same tab, as in the original.
- **Panels with no table yet are shown empty,** with their headings (and table headings) only. That includes the location's text, photo and logo, ranking, failing elements, RNAGs, risk levels, thresholds and everything on Sewerage Data.
- **Nothing is worked out without an agreed rule.** Failing elements, ranking and "Relative Coverage" could be calculated, but the rules aren't agreed (PLAN.md §9.3), so they're empty. What is calculated is in `figures.py`: each catchment's latest ecological status (for the map colours and the Overview counts), the EA scoring grid, and each habitat's % of the catchment.
- **A new data table no longer appears by itself:** it needs a place on a page. The original layout has no space for a generic table.
- **The "i" buttons show the table's row in `datasets`,** and are greyed out until it has one.
- **Tables are sortable** by clicking a heading (a small script, `static/sort.js`). Numbers sort as numbers, and empty cells always go last.
- **Maps: Leaflet with no background map,** as in the original, with the catchment outlines coloured by ecological status (the colours are in `style.css`). Leaflet is copied into the project rather than loaded from elsewhere.
- **One self-contained folder per location** (`published/north-devon/`), so each can later be served at its own address. Each folder is built alongside the old one and swapped in, so a half-written dashboard is never served.
- **A location's web address comes from its name** (North Devon → `north-devon`), for now.

**Locations**
- **Just a name and a list of catchment IDs.** Other location details (intro text, photo, branding, contact email) will go in location tables. Whatever saves a location must check the IDs exist, because the database can't check IDs inside a list.

**Hosting**
- **One Azure VM running Docker Compose,** with the option to move to separate Azure services if it grows (PLAN.md §5.5).
- **Caddy for the web server** (when the VM is set up), rather than nginx, because it gets and renews the HTTPS certificates itself. It only does HTTPS and serving files: the login is in the Python app. Until it's added, the live admin page is only reachable through an SSH tunnel.
- **Three Compose files:** shared, dev (loaded automatically) and live (chosen by `COMPOSE_FILE` in the server's `.env`). Passwords on the server have no defaults.
- **The data map** will be hosted on the VM alongside the dashboard, at an unlisted address. It isn't published anywhere else.

---

## Open questions

- **Web address for each location:** for now it comes from the name (`north-devon`). Will each location have its own domain, or a path on one shared domain?
- **Managing locations:** add a page to the admin site, or keep using SQL while there are only one or two?
- **Several locations in one table:** when that happens, replace only the rows for the catchments in the file (PLAN.md §3.4), so locations don't have to share one Excel file.
- **Estuaries and coastal waters:** import them too, so every upstream/downstream ID finds a name?
- **When the VM is set up:** is UK South the right region? Does the private repository need a deploy key?
- The remaining questions in PLAN.md §9.3 (ranking, risk levels, rating bands, phosphate sources, branding, admin users).

---

## Suggested next steps

1. **Try the admin page with real data.** Download EA Scores or Habitat & Land Use, paste in real rows, upload, approve, then `docker compose run --rm publish`. Only the 2 imported catchments can have rows until step 2 is done.
2. **Import all 92 North Devon rivers,** and add them to the North Devon location. Let `imports/catchments.json` accept a management catchment (North Devon is `3062`) as well as single IDs. The EA provides the whole management catchment as one download.
3. **The next datasets.** Each needs a table in the master file, and filling in its empty panel on the dashboard. Simple ones can be `filled_by: excel` with no code; fiddly raw files (PLAN.md §9.1) may still need an importer.
4. **Have GitHub run the tests on every push** (offered, not yet agreed).

---

## Things to know

- **The EA sometimes sends an error page instead of a file,** so the importer retries. For an ID it doesn't recognise, it answers "error 500" rather than "not found".
- **If the EA changes its waterbody web page,** the importer stops with a clear error and its page-reading code needs updating (`backend/catalyst/importers/api/catchments.py`).
- **On the live server, always use `--build`** with `docker compose run`. The code is built into the image there, so without it the old version runs.
- **`docker compose down -v` deletes the local database.** Plain `docker compose down` keeps it.
- **After a change to `requirements*.txt`, rebuild:** `docker compose up -d --build` and `docker compose run --build --rm test`. Code changes need no rebuild locally, because the admin page restarts by itself.
- **On the live server, every `docker compose` command needs `ADMIN_USERS` and `ADMIN_SECRET_KEY` in `.env`,** even commands that don't use the admin page. Make the `ADMIN_USERS` entries on your own machine.
- **The admin page's port is 8000, and the dashboard preview's is 8080** (change `ADMIN_PORT` or `WEB_PORT` in `.env` if either is taken).
- **The dashboard doesn't update by itself:** after approving an upload, run `docker compose run --rm publish`.
- **The status maps have no background map,** as in the original. The River Obstacles and SWW Outlet maps will need one (e.g. OpenStreetMap, whose map images are free for light use only).
