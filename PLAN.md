# Catchment Catalyst – Platform Plan

**Status:** High-level plan, agreed in principle. Hosting changed to a single Azure VM (28 October 2026). Phase 1 (foundations) in progress: database schema tool, first tables, data map page and the development / live Docker setup built. Excel uploads, the admin page's login, and a first basic dashboard (static pages from a publish step) built (29 October 2026).
**Last updated:** 29 October 2026

This document describes how we will rebuild the Catchment Catalyst water quality dashboard (currently North Devon) as a platform that can be reused for any location in the country. It covers the data model, how data gets in, how the system is hosted, and what needs to happen before development starts.

---

## 1. Goals

1. **Recreate the existing dashboard** (Overview, River Status, EA Data, Land Use Data, Sewerage Data). The reference screenshots are in `Reference/ReferenceImages`. The original concept is in `Catchment Catalyst IGI.pptx`.
2. **Make it reusable.** A new location should need only:
   - the list of catchment (waterbody) IDs it covers,
   - any data specific to that location (e.g. FOI responses, hand-written text),
   - a new URL.
3. **Let a non-technical person update the data** every few months through an admin portal, without a developer.
4. **Keep it cheap and low-maintenance.** The data is static between updates and there is no live data feed.

---

## 2. Core principles

| Principle | What it means |
|---|---|
| **Catchment ID is the key to everything** | Every row of data is tied to a catchment ID, which is the official EA WFD waterbody ID (e.g. `GB108050008080`), never to a name. Names drift and clash nationally. Name-keyed source files are converted to IDs on import. |
| **One shared set of tables for all locations** | National data is loaded once. Location-specific data goes into the same tables. A location is just a name and a list of catchment IDs. |
| **Store facts, calculate comparisons** | Anything that depends on which catchments are in a location (rankings such as "68/92", status counts, "% of catchment", densities, "increase needed to reach Good") is calculated per location, not stored. |
| **Years are rows, not columns** | Source files have `2025 / 2022 / 2019` columns. The database stores one row per year so a new year needs no change to the table design. |
| **Two ways to fill a table** | Each table is filled in one way only, set by `filled_by` in the master file. **api:** an importer (a small Python module) downloads it from an outside service, e.g. catchments from the EA. **excel:** a person downloads the table as Excel from the admin page, edits it and uploads it again. The file has exactly the table's columns, so no code is needed per table (§4.4). A source file too fiddly to convert by hand in Excel can still get its own importer. |
| **One source per table** | Each table is filled from a single source: the catchments tables only from the EA, hand-written text only through the admin portal, and so on. Anything entered by hand goes in its own table, linked by catchment ID. A re-import can then replace a table's contents without losing anyone's work. |
| **Keep the raw files** | Every uploaded file is kept as it was, so data can be re-imported if an importer had a bug and there is a record of what was loaded and when. |
| **Nothing goes live without review** | Uploads produce a preview first, and changes only appear on the public site after a **publish** step. |

---

## 3. Data model (conceptual)

### 3.1 Core tables

| Table | Contents | Scope |
|---|---|---|
| **catchments** | Catchment ID (EA waterbody ID), name, type, catchment boundary, river line, management / operational catchment and river basin district (EA names and IDs), hydromorphological designation, area, river length, and the IDs of the waterbodies upstream and downstream (lists; names are looked up in this table). Filled entirely by the catchments importer (§4.3). | National |
| **locations** | Location ID, name and the list of catchment IDs it includes (a catchment can be in more than one location). Whatever saves a location checks every ID is in `catchments`, because the database can't check IDs inside a list. Anything else about a location (intro text, photo, branding, contact email) goes in its own tables, keyed by location ID (§3.2). The web address (e.g. `/north-devon`) will be generated from the name, or added with the publish step. | One per location |
| **datasets** | The list of datasets, one row per data table (the tiles on the admin "Choose a table" screen): name, source organisation, date of data, caveats, national or location-specific. Also drives the "i" info buttons. Holds no data itself. | All |
| **uploads** | Each Excel upload: the table, the file (kept), who uploaded it and when, status (preview / approved / cancelled), and the rows it added, changed and deleted. *(Built.)* | All |

### 3.1.1 Changing the database structure

Every table and column is listed in one master file, `backend/catalyst/db/schema.yaml`, which separates core tables from data tables (one per dataset; each must have a `catchment_id`). A schema tool compares it with the database and makes whatever changes are needed (`plan` to preview, `apply` to make them). It runs in the same way locally and on the live server. Changes that would delete data are refused unless explicitly allowed. See `README.md`.

### 3.2 Data tables (one per thing shown on the dashboard)

Each dataset has its own table, and each row has a catchment ID. Built so far: `ea_scores` and `habitat_land_use`. Data about a whole location (e.g. its intro text) will go in tables keyed by **location ID** instead; the master file's rule will be extended to allow this when the first one is added. Catchment data tables come in three kinds:

- **One row per waterbody:** e.g. number of farms, properties on SWW or private sewerage, risk levels.
- **Many rows per waterbody:** e.g. EA classification items per year, habitat types, livestock types, phosphate sources, SWW discharge sites per year, asset improvement plans.
- **Point data with coordinates:** e.g. river obstacles, SWW outlets. If the source has no waterbody ID, the importer works out which catchment boundary each point falls in.

### 3.3 Hand-written text

"Why is the river failing?", "What is happening now?", the intervention hypothesis and the interventions table are written by hand for each catchment. These will be edited through **forms in the admin portal** (with optional bulk upload), not only through CSV.

### 3.4 Replacing data safely

**Built (Excel uploads):** each upload replaces the table's rows with the file's, matching rows by the table's primary key. The preview shows exactly what will be added, changed and deleted, warns when rows will be deleted, and nothing changes until someone approves it. If the table changes between the preview and the approval (e.g. two people uploading at once), the approval is refused and the up-to-date preview is shown instead.

**Later, when tables hold several locations' data:** only the rows for the **waterbodies covered by the file** will be replaced. For example, a new North Devon FOI file would replace North Devon's rows in that table and leave every other location alone. National datasets replace the whole national set.

---

## 4. Data import process

### 4.1 Importers

Tables filled by Excel upload need no importer (§4.4). Each other dataset has one importer, written by a developer, which:

1. **Checks** that the file has the expected columns (and gives a clear error if the source format has changed).
2. **Converts** the data: filters a large national file down to what we need, reshapes year columns into rows, converts units, turns names into IDs, assigns points to catchments, etc.
3. **Validates** it: unknown waterbody IDs, missing catchments, values of the wrong type, values outside expected ranges.
4. **Produces a preview** for a person to approve.

A new type of source file means writing one new importer, which should only happen a few times a year.

### 4.2 Update flow (as seen by a non-technical admin)

1. Log in to the admin page with their own name and password.
2. Choose the table (e.g. "EA Scores") and download it as an Excel file.
3. Add, change or delete rows in Excel, then upload the file.
4. Review the preview: any problems (with Excel row numbers), and the rows that will be added, changed and deleted.
5. **Approve.** The data goes into the database (it is not yet public).
6. **Publish** the location. The public dashboard updates. *(Built as a command for now: `docker compose run --rm publish`. A button in the admin page later.)*

Steps 1–6 are built (§4.4, §5.1).


### 4.3 Catchments importer (built)

Fills the `catchments` table from the EA's Catchment Data Explorer, for a list of catchment IDs in a JSON file (`imports/catchments.json`). For each catchment it downloads:

- the waterbody's **shapefile** from the API: details (name, type, catchment hierarchy names and IDs, hydromorphological designation), catchment boundary and river line, converted from British National Grid to latitude/longitude;
- the waterbody's **web page**, the only source of its **river length** and **upstream / downstream waterbodies**. If the EA changes the page, the importer stops with a clear error rather than guessing.

The **area** is calculated from the boundary (it matches the EA's figure). Only the IDs of upstream / downstream waterbodies are stored. Some, such as estuaries, aren't imported yet (the importer handles rivers only), so their names can't be looked up until it supports those waterbody types too. The importer checks everything before saving, shows a preview, saves all catchments in one go, and keeps the downloaded files. Running it again updates catchments rather than duplicating them. Only river waterbodies are supported so far. Command: see `imports/README.md`. Later, the admin portal will call the same code.

### 4.4 Excel uploads (built)

Every table marked `filled_by: excel` in the master file appears in the admin page, and they all work the same way, with no code per table (`backend/catalyst/importers/excel/`):

- **The file is an exact copy of the table:** the column names in row 1 (in any order) and one row per row, on the first sheet. The easiest start is the table's own download.
- **Each upload replaces the whole table** (§3.4), so a row deleted from the file is deleted from the table. Corrections and deletions are made the same way, so no separate editing screen is needed.
- **Checks before the preview:** the column names; that every value fits its column (numbers, dates, yes/no, and text that Excel has turned into a date); required values; no row appearing twice (by primary key); and that every catchment ID is in the catchments table. All the problems are listed together, with Excel row numbers.
- **Every uploaded file is kept** and listed on the table's page, so going back to an earlier version means downloading that file and uploading it again.
- **To make another table uploadable,** add `filled_by: excel` to it in the master file. Its columns must be text, whole numbers, numbers, yes/no or dates, and it needs a primary key made of its own columns.
---

## 5. Architecture

The system is packaged as **Docker containers** and, for now, runs on a **single Azure virtual machine (VM)** with Docker Compose. The same containers run on a developer's machine: only the settings change. If the platform grows a lot, the same containers can move to separate Azure services without rewriting anything (§5.5).

```
          ┌──────────────────────── Azure VM (Docker Compose) ─────────────────────────┐
          │                                                                            │
 Public   │  Web server ──────────► Public dashboard + published data bundles          │
 users ──►│  (HTTPS for every        (one bundle per location; never touches the       │
          │   location's address)     database)                                        │
          │       │                                                                    │
 Admins ─►│       └──► Admin portal ──► Admin API ──► Import worker (one importer      │
(name and │                                 │               │       per dataset)       │
password) │                                 ▼               ▼                          │
          │                         PostgreSQL + PostGIS (the database)                │
          └───────────────────────────────────────┬────────────────────────────────────┘
                                                  │ raw uploaded files, nightly backups
                                                  ▼
                                   Azure Blob Storage (outside the VM)
```

### 5.1 Components

| Component | Runs as | Role |
|---|---|---|
| **Web server** | Caddy container | The only part open to the internet. Serves the dashboard and admin portal over HTTPS, with a certificate for each location's address that it gets and renews automatically. Caddy rather than nginx because it does the certificates itself, with a much shorter configuration. *(Not built yet.)* |
| **Public dashboard** | Plain web pages, written by the publish step and served by the web server | A folder per location, with a URL each. The data is written into the pages, so they never touch the database and make no API calls. No JavaScript framework: the only scripts draw the maps (Leaflet, on an OpenStreetMap background) and sort the tables. *(A first, basic version is built: a map page per location, and a page per catchment with its details and a sortable table for every data table.)* |
| **Published data bundles** | Folder on the VM (`published/`) | One folder per location, holding its pages, map outlines and everything else they need, written by the publish step. Can always be rebuilt from the database. |
| **Admin portal** | Files served by the web server (at `/admin` or its own address) | Upload, preview, approve and publish screens, plus forms for the hand-written text. Each person has their own name and password; only hashes of the passwords are stored, in the server's settings. Microsoft accounts (Entra ID) could replace this if many more people need access. *(Built so far: the login and the Excel download, upload, preview and approve screens, served by the admin API's container.)* |
| **Admin API** | Python container | Behind the admin portal. Checks logins and roles, handles uploads and publishing. |
| **Import worker** | Python container (same image) | Runs long imports in the background. *(Not needed yet: Excel uploads are checked straight away.)* |
| **Database** | PostgreSQL 17 + PostGIS container | The single source of truth. Not reachable from the internet. PostGIS handles boundaries and point-in-catchment lookups. |
| **Raw files and backups** | Azure Blob Storage | Original uploaded files and nightly database backups, kept off the VM so they survive if it fails. |

### 5.2 Why this design

- **Simple and cheap.** One machine to run and pay for (around Azure's B2s size: 2 processors, 4 GB memory) plus a little storage. *(Check current Azure pricing.)*
- **Development matches live.** The same Compose setup, the same images and the same database container run on a developer's machine and on the VM.
- **A fast, secure public site.** Public users only read static files. Only web traffic reaches the VM, and the database is never exposed.
- **No lock-in.** Everything is a container configured by settings, so it can move to separate Azure services later (§5.5).

### 5.3 What we look after ourselves

On a VM, some jobs that managed services would do are ours:

| Job | How |
|---|---|
| HTTPS certificates | The web server gets and renews them automatically. |
| Database backups | A nightly backup (`pg_dump`) copied to Blob Storage. Restore it occasionally to check it works. **This must not be skipped:** without it, a failed VM disk means losing the data. |
| Security updates | Ubuntu's automatic security updates. Container images are updated when deploying. |
| Firewall | Azure network rules: only web traffic (ports 80 and 443) open to everyone; SSH only from known IP addresses. |
| Monitoring | Azure alerts by email if the VM stops or its disk is nearly full. |

### 5.4 Setting up the VM

The VM and its network rules are set up once by hand in the Azure portal, following written steps (§6.2 and `README.md`). A setup script (Bicep or Terraform) becomes worthwhile if we add a second VM or move to separate services.

### 5.5 Moving to separate Azure services later

If traffic or the number of locations grows a lot, each container can move to an Azure service:

| Now (on the VM) | Later |
|---|---|
| Web server, dashboard and admin portal files | Azure Static Web Apps |
| Admin API | Azure Container Apps |
| Import worker | Azure Container Apps Jobs |
| Database container | Azure Database for PostgreSQL – Flexible Server, with PostGIS (moved by backup and restore) |
| Blob Storage | Unchanged |

To keep this easy: everything stays in containers, all settings come from environment variables, files go to Blob Storage rather than the VM's disk, and the dashboard only reads published files. (Azure's managed PostgreSQL needs PostGIS added to its allowed extensions list first. The schema tool then installs it, as it already does.)

---

## 6. Environments

| Environment | Where | Purpose |
|---|---|---|
| **Local** | Developer's machine: Docker Compose with `docker-compose.override.yml` | Day-to-day development and testing of the full upload → preview → approve → publish → dashboard flow. |
| **Live** | The Azure VM: Docker Compose with `docker-compose.prod.yml` | The public site and the real admin portal. |
| **Test** *(optional, later)* | A second copy on the same VM, at a test address, with its own database | Trying a change on the server before it goes live, if that's ever needed. |

Local and live use the same Compose setup and images; only settings differ, and the commands are the same in both (see `README.md`, "Development and live settings"). Because they match so closely, a separate Test environment is optional.

### 6.1 Local setup

One `docker compose up` starts (built so far: the database, plus the schema tool and tests on demand):

| Container | Role |
|---|---|
| Postgres + PostGIS | The database |
| Azurite (Microsoft's official emulator) | Stands in for Azure Blob Storage |
| Admin API and import worker | As on the VM |
| Web server | Serves the dashboard and admin portal |

**Known differences locally:** a test login (admin / admin), no HTTPS certificates, and Azurite instead of real Blob Storage.

### 6.2 The live VM

- Ubuntu LTS, around Azure's B2s size (2 processors, 4 GB memory), with enough disk for the database and Docker images. Region: UK South (to be confirmed).
- A fixed public IP address, with each location's domain name pointed at it.
- Network rules: ports 80 and 443 open to everyone; SSH only from known IP addresses. The database port is never opened.
- Automatic security updates switched on.
- Docker installed, the code cloned from GitHub, and the settings in `.env` (template: `.env.prod.example`). Step-by-step: `README.md`, "Live server".

### 6.3 Deploying changes

1. Test locally (`docker compose run --rm test`).
2. Push to GitHub.
3. On the VM: pull the code, rebuild and restart, then check and apply any database changes (`schema plan`, then `schema apply`). The exact commands are in `README.md`.

Later, GitHub can run the tests on every push and do step 3 automatically.

---

## 7. Adding a new location

1. Make sure the national datasets cover the new area. These are already loaded nationally, with boundaries for the whole country.
2. In the admin portal, create the location: its name and catchment IDs. The portal checks each ID is a known catchment.
3. Add its other details (intro text, photo, branding, contact email) in the location tables.
4. Upload any location-specific datasets (e.g. FOI responses) and write or upload the per-catchment text.
5. Publish the location.
6. Point the new address's domain name at the VM and add it to the web server's list of addresses. The web server gets its HTTPS certificate automatically. This can be done manually.

No code changes should be needed unless the new location brings a new kind of source file, which would need a new importer.

---

## 8. What the dashboard shows (from reference screenshots)

This list is the starting point for the dataset inventory in Section 9. To be confirmed when the final screens are agreed.

**On every catchment page:** catchment map coloured by ecological status (click to select), catchment name, catchment ranking (e.g. 68/92), EA ecological classification for 2025 / 2022 / 2019, failing elements, EA RNAGs (reasons for not achieving Good).

| Page | Panels |
|---|---|
| **Overview** | Intro text, photo, count of waterbodies by ecological status, map of the whole location by ecological status, "Using this dashboard" text, contact email |
| **River Status** | Why is the river failing?, What is happening now?, Risk levels (Untreated Sewage, Sewage (Private), Livestock, Runoff, Modification, Invasive Species, Overheating, Running Dry), Intervention hypothesis with confidence level, Interventions table (desired change, lead partner, actions, how we'll know; primary / contingency) |
| **EA Data** | EA scoring table: classification items × years (Latest, 2025, 2022, 2019, 2016) with thresholds (Poor / Moderate / Good / High) and colour coding |
| **Land Use Data** | River information (area, length, upstream / downstream rivers; the current "river system" isn't EA data, so it isn't imported: if still wanted, it would come from a hand-written table), Habitat and land use (type, area, % of catchment, relative coverage), Number of farms, Livestock pressures (number, density, density rating), Phosphate source estimate (2025 / 2030 by source), River obstacles (map and table: EA ID, site name, type, origin), Risk levels |
| **Sewerage Data** | SWW intermittent discharges (hours per year by site, 2021–2025), SWW outlet locations map, Properties on SWW / private sewerage, private sewerage per ha, Continuous discharge text, Source of phosphate (continuous / diffuse), SWW asset improvement plans (site, improvements, completion date, predicted spills), Risk levels |

---

## 9. Before development starts

### 9.1 Collect the raw data

For each dashboard panel, collect the **original raw source file**, as downloaded or received and not pre-processed. This lets the importers be designed around the real conversions. For each one, record:

| Field | Example |
|---|---|
| Dataset name | SWW intermittent discharges |
| Panel(s) it feeds | Sewerage Data → Intermittent discharges table |
| Source | South West Water EDM return / FOI / EA open data / hand-written |
| National or per location | Per location |
| Keyed by | Waterbody ID / name / site name / coordinates |
| How often it changes | Yearly |
| How it is currently converted | Description of the current manual steps, if known |
| Example raw file | Path in `Reference/` |

### 9.2 Confirm the final dashboard screens

Agree the final set of pages and panels (Section 8), including anything to be added, removed or changed from the current version.

### 9.3 Questions to answer

1. **Catchment ranking:** how is "68/92" calculated?
2. **Risk levels:** are they calculated from data (and if so with what rules and thresholds), or assigned by hand?
3. **Rating bands:** how are "Relative coverage" (habitat) and "Density rating" (livestock) decided?
4. **Phosphate source estimates and 2030 values:** where do these come from (a model output, a file)?
5. **Hand-written text:** who writes it, and will they use the admin portal?
6. **Branding per location:** does the Biosphere logo, colours, intro text or contact email change per location?
7. **Admin users:** who can upload, and can someone be limited to managing only their own location? *So far: one or two people, each with their own login, who can upload to every table.*
8. **Which waterbodies count:** the current dashboard includes only the 92 river waterbodies, excluding lakes, reservoirs and some coastal waters. Is this the rule for every location? *(The EA's North Devon management catchment contains exactly these 92 rivers plus 6 lakes.)*
9. **Column mapping screen or importers?** The concept deck (slide 3) shows the admin choosing which column in the file goes into which database column, remembered for next time. Section 4.1 instead has a small importer written for each dataset. A mapping screen handles simple files with no developer; some conversions need code (e.g. livestock's `Cattle_Dairy, Sheep, …` columns becoming rows). A likely answer is both: a mapping screen for simple files, importers for the rest. **Decided (29 October 2026): neither, for now.** An uploaded file must be an exact copy of the table (§4.4), so there's nothing to map, and importers are only written for API sources or files too fiddly to convert in Excel.

### 9.4 Notes from the reference data so far

- **River length:** the current dashboard's figures match neither the EA's (e.g. Langham Lake: dashboard 13.9 km, EA 15.53 km) nor a length calculated from the EA's river line (13.20 km). Decided: use the EA's figure.
- `DO.csv`, `Fish.csv` and `Phosphate.csv` are keyed by **name**, not ID, and include location-specific ranks. These look like derived files and may come from `EA Data.csv`. To be confirmed when the raw data arrives.
- `Fish.csv` and `EA Data.csv` include 6 reservoirs that are not in `waterbody_id_name.csv` (98 vs 92 waterbodies).
- `geojson/` has 93 boundaries for the 92 listed waterbodies. The extra one is `GB30844801` (likely an estuary or coastal water).
- **Boundaries: prefer the EA shapefile over GeoJSON** (example in `WB_GB108050020040_c3-plan_shapefile`). Both get loaded into PostGIS and served to the dashboard as web-ready GeoJSON, so the file format doesn't matter. The shapefile is better because it contains more:
  - (Both formats include the river line as well as the catchment area, so either can be used to draw rivers on the maps.)
  - **Management and operational catchment names and the river basin district** (e.g. `MNCAT_NAME = North Devon`). A new location's waterbody list could be picked by management catchment instead of typed in.
  - **Modified-status designation** (artificial or heavily modified).

  It uses British National Grid coordinates, and the importer converts them to standard latitude/longitude for web maps. Ideally download the **national** WFD Cycle 3 river waterbody catchments dataset in one go rather than per catchment.

---

## 10. Build phases (after data and screens are confirmed)

1. **Foundations:** database design, Docker Compose local setup, waterbody boundaries loaded.
2. **Importers:** one per dataset, with validation and preview, tested against the real raw files.
3. **Publish step:** generate a data bundle per location, including the calculated values (rankings, counts, percentages). *(Started: `backend/catalyst/publish/`. No calculated values yet.)*
4. **Public dashboard:** recreate the five pages, reading from the published bundles. *(Started: a basic map and tables, not yet the real pages.)*
5. **Admin portal:** upload, preview, approve, publish and the text-editing forms.
6. **Live server:** set up the Azure VM (§6.2) with HTTPS, backups and monitoring, then deploy. Migrate North Devon.
7. **Second location:** add a new location end to end to prove that it can be reused.
