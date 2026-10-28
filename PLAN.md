# Catchment Catalyst – Platform Plan

**Status:** High-level plan, agreed in principle. Phase 1 (foundations) in progress: database schema tool and first core tables built.
**Last updated:** 28 October 2026

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
| **One shared set of tables for all locations** | National data is loaded once. Location-specific data goes into the same tables. A location is just a list of waterbody IDs. |
| **Store facts, calculate comparisons** | Anything that depends on which catchments are in a location (rankings such as "68/92", status counts, "% of catchment", densities, "increase needed to reach Good") is calculated per location, not stored. |
| **Years are rows, not columns** | Source files have `2025 / 2022 / 2019` columns. The database stores one row per year so a new year needs no change to the table design. |
| **Every conversion is code** | Source files are never in the shape we need, but each source's columns stay the same between downloads. So each dataset gets its own **importer** (a small Python module) rather than a general column-mapping screen. |
| **Keep the raw files** | Every uploaded file is kept as it was, so data can be re-imported if an importer had a bug and there is a record of what was loaded and when. |
| **Nothing goes live without review** | Uploads produce a preview first, and changes only appear on the public site after a **publish** step. |

---

## 3. Data model (conceptual)

### 3.1 Core tables

| Table | Contents | Scope |
|---|---|---|
| **catchments** | Catchment ID (EA waterbody ID), name, type (river, lake, estuary…), catchment boundary, river line, management / operational catchment, river basin district, river system, upstream and downstream waterbodies, area, river length | National |
| **locations** | URL name (e.g. `north-devon`), display name, intro text, photo, logo and branding, contact email | One per location |
| **location_catchments** | Which catchments belong to which location (a catchment can be in more than one location) | One per location |
| **datasets** | The list of datasets, one row per data table (the tiles on the admin "Choose a table" screen): name, source organisation, date of data, caveats, national or location-specific. Also drives the "i" info buttons. Holds no data itself. | All |
| **uploads** | Each import run: dataset, raw file, who uploaded it and when, status (preview / approved / rejected), row counts | All |

### 3.1.1 Changing the database structure

Every table and column is listed in one master file, `backend/catalyst/db/schema.yaml`, which separates core tables from data tables (one per dataset; each must have a `catchment_id`). A schema tool compares it with the database and makes whatever changes are needed (`plan` to preview, `apply` to make them). It runs in the same way locally and against Azure. Changes that would delete data are refused unless explicitly allowed. See `README.md`.

### 3.2 Data tables (one per thing shown on the dashboard)

Each dataset has its own table, and each row has a catchment ID (and, once uploads are tracked, the upload it came from). Built so far: `ea_scores` and `habitat_land_use`. There are three kinds:

- **One row per waterbody:** e.g. number of farms, properties on SWW or private sewerage, risk levels.
- **Many rows per waterbody:** e.g. EA classification items per year, habitat types, livestock types, phosphate sources, SWW discharge sites per year, asset improvement plans.
- **Point data with coordinates:** e.g. river obstacles, SWW outlets. If the source has no waterbody ID, the importer works out which catchment boundary each point falls in.

### 3.3 Hand-written text

"Why is the river failing?", "What is happening now?", the intervention hypothesis and the interventions table are written by hand for each catchment. These will be edited through **forms in the admin portal** (with optional bulk upload), not only through CSV.

### 3.4 Replacing data safely

When a dataset is re-uploaded, only that dataset's rows for the **waterbodies covered by the file** are replaced. For example, a new North Devon FOI file replaces North Devon's rows in that table and leaves every other location alone. National datasets replace the whole national set.

---

## 4. Data import process

### 4.1 Importers

Each dataset has one importer, written by a developer, which:

1. **Checks** that the file has the expected columns (and gives a clear error if the source format has changed).
2. **Converts** the data: filters a large national file down to what we need, reshapes year columns into rows, converts units, turns names into IDs, assigns points to catchments, etc.
3. **Validates** it: unknown waterbody IDs, missing catchments, values of the wrong type, values outside expected ranges.
4. **Produces a preview** for a person to approve.

A new type of source file means writing one new importer, which should only happen a few times a year.

### 4.2 Update flow (as seen by a non-technical admin)

1. Log in to the admin portal with an organisation Microsoft account.
2. Choose the dataset (e.g. "SWW intermittent discharges") and upload the file.
3. The import runs in the background, which handles large files.
4. Review the preview: rows read, problems found, catchments missing, big changes since the last upload.
5. **Approve.** The data goes into the database (it is not yet public).
6. **Publish** the location. The public dashboard updates.

---

## 5. Architecture

The system is packaged as **Docker containers**. The same containers run on a developer's machine and in Azure. Only the connection settings change.

```
                         ┌──────────────────────────────┐
  Public users  ───────► │ Public dashboard              │  Azure Static Web Apps
                         │ (one app, a URL per location) │
                         └──────────────┬───────────────┘
                                        │ reads published data files
                                        ▼
                         ┌──────────────────────────────┐
                         │ Blob Storage                  │
                         │  /raw       uploaded files    │
                         │  /published one data bundle   │
                         │             per location      │
                         └──────▲───────────────▲───────┘
                                │               │ publish step writes bundles
  Admins (Entra login) ──►  Admin portal ──► Admin API ──► Import jobs (Python,
                          (Static Web App)  (Container      one importer
                                             Apps)          per dataset)
                                                  │
                                                  ▼
                         ┌──────────────────────────────┐
                         │ Azure Database for PostgreSQL │
                         │ (Flexible Server + PostGIS)   │
                         └──────────────────────────────┘
```

### 5.1 Components

| Component | Azure service | Role |
|---|---|---|
| **Public dashboard** | Azure Static Web Apps | Serves the website. Custom domain and SSL per location. Reads only published data bundles, so it never touches the database. |
| **Published data and raw files** | Azure Blob Storage | `/raw`: original uploaded files. `/published`: one data bundle per location, written by the publish step. |
| **Database** | Azure Database for PostgreSQL – Flexible Server (Burstable B1ms) with PostGIS | The single source of truth. Managed backups and patching. PostGIS handles boundaries and point-in-catchment lookups. |
| **Admin portal** | Azure Static Web Apps (separate app, or `/admin`) | Upload, preview, approve and publish screens, plus forms for the hand-written text. Login with organisation Microsoft accounts (Entra ID). |
| **Admin API** | Azure Container Apps (Docker container) | Python API behind the admin portal. Scales to zero when not in use. |
| **Import jobs** | Azure Container Apps Jobs (Docker container) | Run the importers in the background when a file is uploaded. |

### 5.2 Why this design

- **No VM to maintain.** Patching, backups, SSL and uptime are handled by Azure.
- **A fast, secure public site.** Public users only read static files: there is no public API and no database exposure.
- **Low cost.** Roughly £20–40 a month in total, almost all of it the database. *(Estimate: check current Azure pricing.)*
- **No lock-in.** Everything is a Docker container, so the same Docker Compose setup could run on a single VM as a fallback without rewriting anything.

### 5.3 Infrastructure as code

The Azure setup will be defined in a script (**Bicep** or **Terraform**) rather than set up by hand in the Azure portal. The same script creates the test and live environments, so they stay identical.

---

## 6. Environments

| Environment | Where | Purpose |
|---|---|---|
| **Local** | Developer's machine, Docker Compose | Day-to-day development and testing of the full upload → preview → approve → publish → dashboard flow. |
| **Test** | Azure (small, can be paused) | Check the Azure-only parts: real Entra login, file-upload events, networking, permissions. |
| **Live** | Azure | The public site and the real admin portal. |

### 6.1 Local setup

One `docker compose up` starts:

| Container | Stands in for |
|---|---|
| Postgres + PostGIS | Azure Database for PostgreSQL |
| Azurite (Microsoft's official emulator) | Azure Blob Storage |
| Admin API | Container Apps |
| Import worker | Container Apps Jobs |

The public dashboard and admin portal run in dev mode alongside these. Microsoft's **SWA CLI** emulates Static Web Apps routing and provides a fake login screen for testing admin roles.

**Known differences locally:** real Entra login, the "file uploaded" event that starts imports (locally the API starts the import directly), and Azure networking and permissions. All of these are checked in the Test environment.

---

## 7. Adding a new location

1. Make sure the national datasets cover the new area. These are already loaded nationally, with boundaries for the whole country.
2. In the admin portal, create the location: name, URL name, intro text, branding, contact email.
3. Add its waterbody IDs.
4. Upload any location-specific datasets (e.g. FOI responses) and write or upload the per-catchment text.
5. Publish the location.
6. Point the new URL at the dashboard (a custom domain on Static Web Apps). This can be done manually.

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
| **Land Use Data** | River information (area, length, river system, upstream / downstream rivers), Habitat and land use (type, area, % of catchment, relative coverage), Number of farms, Livestock pressures (number, density, density rating), Phosphate source estimate (2025 / 2030 by source), River obstacles (map and table: EA ID, site name, type, origin), Risk levels |
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
7. **Admin users:** who can upload, and can someone be limited to managing only their own location?
8. **Which waterbodies count:** the current dashboard includes only the 92 river waterbodies, excluding lakes, reservoirs and some coastal waters. Is this the rule for every location?
9. **Column mapping screen or importers?** The concept deck (slide 3) shows the admin choosing which column in the file goes into which database column, remembered for next time. Section 4.1 instead has a small importer written for each dataset. A mapping screen handles simple files with no developer; some conversions need code (e.g. livestock's `Cattle_Dairy, Sheep, …` columns becoming rows). A likely answer is both: a mapping screen for simple files, importers for the rest. To decide before building the import step.

### 9.4 Notes from the reference data so far

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
3. **Publish step:** generate a data bundle per location, including the calculated values (rankings, counts, percentages).
4. **Public dashboard:** recreate the five pages, reading from the published bundles.
5. **Admin portal:** upload, preview, approve, publish and the text-editing forms.
6. **Azure:** infrastructure script, Test environment, then Live. Migrate North Devon.
7. **Second location:** add a new location end to end to prove that it can be reused.
