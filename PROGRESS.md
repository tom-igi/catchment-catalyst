# Progress

Where the build is up to, the decisions made along the way, and what's next.
For the overall design, see [PLAN.md](PLAN.md). For commands, see [README.md](README.md).

**Last updated:** 28 October 2026

---

## Picking up again

```bash
docker compose up -d                      # start the local database
docker compose run --rm schema plan       # should say "The database already matches schema.yaml."
docker compose run --rm test              # run the tests (40 passing at the last update)
explorer.exe "$(wslpath -w datamap/site/index.html)"   # open the data map
```

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
| **Catchments importer** | `backend/catalyst/importers/`, `imports/` | Fills the catchments table from the EA's Catchment Data Explorer for the IDs in `imports/catchments.json`. Preview first, safe to re-run, keeps the downloaded files. |
| **Data map** | `datamap/` | A plain-English web page of every table, rebuilt on every `schema apply`. Self-contained: deleting the folder removes it (see `datamap/README.md`). |
| **Dev and live setup** | `docker-compose*.yml`, `.env*.example` | The same commands on your machine and on the live server. Only the settings differ. |
| **Tests** | `backend/tests/`, `datamap/test_datamap.py` | Cover the schema tool, the importer and the data map. |

### Tables so far

| Table | Kind | Holds | Rows |
|---|---|---|---|
| `catchments` | Core | Every EA river waterbody: details, outline, river line, area, length, upstream/downstream IDs. Filled only by the importer. | 2 (West Okement, East Okemont River) |
| `locations` | Core | ID, name, and the list of catchment IDs | 0 |
| `datasets` | Core | One row per data table: name, source, caveats (for the "i" buttons) | 0 |
| `ea_scores` | Data | EA classification results per catchment, measure and year | 0 |
| `habitat_land_use` | Data | Area of each habitat type per catchment | 0 |

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

**Locations**
- **Just a name and a list of catchment IDs.** Other location details (intro text, photo, branding, contact email) will go in location tables. Whatever saves a location must check the IDs exist, because the database can't check IDs inside a list.

**Hosting**
- **One Azure VM running Docker Compose,** with the option to move to separate Azure services if it grows (PLAN.md §5.5).
- **Three Compose files:** shared, dev (loaded automatically) and live (chosen by `COMPOSE_FILE` in the server's `.env`). Passwords on the server have no defaults.
- **The data map** will be hosted on the VM alongside the dashboard, at an unlisted address. It isn't published anywhere else.

---

## Open questions

- **Web address for each location** (e.g. `/north-devon`): generate it from the name, or add it with the publish step?
- **Column mapping screen or importers** for uploads (PLAN.md §9.3 Q9)? Probably both.
- **Estuaries and coastal waters:** import them too, so every upstream/downstream ID finds a name?
- **When the VM is set up:** is UK South the right region? Does the private repository need a deploy key?
- The remaining questions in PLAN.md §9.3 (ranking, risk levels, rating bands, phosphate sources, branding, admin users).

---

## Suggested next steps

1. **Import all 92 North Devon rivers.** Let `imports/catchments.json` accept a management catchment (North Devon is `3062`) as well as single IDs. The EA provides the whole management catchment as one download.
2. **The next datasets.** Each needs its raw source file (PLAN.md §9.1), then a table in the master file and an importer.
3. **The `uploads` table** (PLAN.md §3.1), to record each import run. Needed before the admin portal.
4. **Have GitHub run the tests on every push** (offered, not yet agreed).

---

## Things to know

- **The EA sometimes sends an error page instead of a file,** so the importer retries. For an ID it doesn't recognise, it answers "error 500" rather than "not found".
- **If the EA changes its waterbody web page,** the importer stops with a clear error and its page-reading code needs updating (`backend/catalyst/importers/catchments.py`).
- **On the live server, always use `--build`** with `docker compose run`. The code is built into the image there, so without it the old version runs.
- **`docker compose down -v` deletes the local database.** Plain `docker compose down` keeps it.
