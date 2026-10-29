# Catchment Catalyst

Water quality dashboard platform. See [PLAN.md](PLAN.md) for the overall design, and
[PROGRESS.md](PROGRESS.md) for where the build is up to.

**Just want to run it?** [OPERATING.md](OPERATING.md) has only the essential commands. This
file has the details.

## Layout

```
docker-compose.yml           the services, shared by every environment
docker-compose.override.yml  development settings (used on your machine automatically)
docker-compose.prod.yml      live server settings
.env.example                 optional settings for your machine
.env.prod.example            template for the live server's settings
backend/                     all Python code, built into one Docker image
  catalyst/db/schema.yaml    ← the database master file: every table and column
  catalyst/db/schema.py      reads and checks schema.yaml
  catalyst/db/sync.py        compares schema.yaml with the database and applies changes
  catalyst/importers/api/    tables filled from an outside service's API (catchments, from the EA)
  catalyst/importers/excel/  tables filled by Excel upload (one shared piece of code for all of them)
  catalyst/admin/            the admin page: log in, download a table, upload it, preview, approve
  catalyst/publish/          the publish step: writes each location's dashboard as web pages
  tests/
imports/                     lists of what to import, and copies of every download and upload (see imports/README.md)
published/                   the published dashboards (not in git; see published/README.md)
datamap/                     optional data map page: every table in plain English (see datamap/README.md)
```

## Running locally

Only Docker is needed.

```bash
docker compose up -d                    # start the database, the admin page and the dashboard preview
docker compose run --rm schema plan     # preview changes needed to match schema.yaml
docker compose run --rm schema apply    # make them (asks first), and rebuild the data map
docker compose run --rm publish         # write the dashboards' pages
docker compose run --rm test            # run the backend tests
```

The admin page is at <http://localhost:8000/admin> (name `admin`, password `admin`), and the
published dashboards at <http://localhost:8080>.

To see the data map, open `datamap/site/index.html` in a browser. From WSL:
`explorer.exe "$(wslpath -w datamap/site/index.html)"`.

To connect a database client (DBeaver, pgAdmin, etc.): host `localhost`, port `5434`,
database / user / password `catalyst`. To change these, copy `.env.example` to `.env`.

`docker compose down` stops everything and keeps the data. `docker compose down -v` also
**deletes** the local database.

## Changing the database structure

1. Edit `backend/catalyst/db/schema.yaml`. The options are explained at the top of the file.
2. `docker compose run --rm schema plan` shows what will change.
3. `docker compose run --rm schema apply` makes the change.

Notes:

- Changes are all-or-nothing. If one fails, nothing is changed.
- Anything that deletes data (dropping a table or column, changing a column's type) is
  refused unless you add `--allow-data-loss`.
- To rename a table or column, add `renamed_from: <old name>` to it. Otherwise a rename is
  treated as "drop the old one, add a new empty one", which the data-loss check stops.
- The tool can't change a table's primary key, or move data between columns (e.g. split a
  column in two). `plan` warns about primary key differences. Moving data needs a one-off
  script.
- Only tables in the `public` schema are managed.

## Filling the tables

Each table is filled in one way, set by `filled_by` in `schema.yaml`:

| `filled_by` | How | Tables so far |
|---|---|---|
| `api` | An importer downloads the data from an outside service (`backend/catalyst/importers/api/`) | Catchments |
| `excel` | Someone uploads an Excel file in the admin page (`backend/catalyst/importers/excel/`) | EA Scores, Habitat & Land Use |

### From an API

So far there is one importer, for catchments from the EA:

```bash
docker compose run --rm importer catchments imports/catchments.json
```

It downloads and checks everything first, shows what it will add or update, and asks before
saving. Running it again updates catchments rather than duplicating them. See
`imports/README.md`.

### From Excel (the admin page)

1. Log in to the admin page and choose the table.
2. Download it as an Excel file.
3. Add, change or delete rows. Keep the column names in row 1 as they are.
4. Upload it. Every row is checked, then a preview shows exactly what will be added, changed
   and deleted.
5. Approve it, and the table's rows are replaced with the file's. Or cancel, and nothing
   changes.

Each upload replaces the whole table, so always start from a fresh download. Every uploaded
file is kept (in `imports/raw/<table>/`) and listed on the table's page: to go back to an
earlier version, download its file and upload it again.

To make another table uploadable, add `filled_by: excel` to it in `schema.yaml` and run
`schema apply`. It then appears in the admin page, with no code to write. (Its columns must
be text, numbers, yes/no or dates, and it needs a primary key: see the top of `schema.yaml`.)

### Admin logins

Each person has their own name and password. Only a hash of each password is kept, in the
`ADMIN_USERS` setting in `.env`. To add someone:

```bash
docker compose run --rm admin hash-password <name>    # asks for their password, prints their entry
```

Put the printed entry in `ADMIN_USERS` in `.env` (separate people with commas), then run
`docker compose up -d` to restart the admin page with it. To remove someone, delete their
entry and run `docker compose up -d` again. Without `ADMIN_USERS`, the local login is
`admin` / `admin`.

## Publishing the dashboard

The public dashboard is plain web pages, written from the database by the publish step.
Visitors never reach the database, so after the data changes (e.g. an upload is approved),
publish again:

```bash
docker compose run --rm publish     # write every location's pages into published/
```

On your machine, see them at <http://localhost:8080>. The pages copy the original dashboard
(`Reference/ReferenceImages`): the same five tabs, Overview, River Status, EA Data, Land Use
Data and Sewerage Data. Each location gets a folder (e.g. `published/north-devon/`) with:

- `index.html`: the Overview, with a map of the catchments coloured by ecological status;
- `<tab>/<catchment ID>/`: each of the other tabs, for each catchment. Clicking the map picks
  another catchment and stays on the same tab;
- `<tab>/`: each tab before a catchment is chosen.

Panels whose data has a table are filled in (the catchment details, EA Scores, Habitat & Land
Use, and the "i" buttons from the `datasets` table). The others are shown empty until their
table is added. Each new data table now needs a place on a page, in
`backend/catalyst/publish/templates/` (calculations such as percentages go in
`backend/catalyst/publish/figures.py`).

The styles and scripts are in `backend/catalyst/publish/static/`. The maps use Leaflet (copied
into `static/leaflet/`) over OpenStreetMap's map images, which are the only thing the pages load
from elsewhere.

### Locations

Until the admin page can manage locations, add one with SQL:

```bash
docker compose exec db psql -U catalyst -c "INSERT INTO locations (name, catchment_ids) VALUES ('North Devon', ARRAY['GB108050008080', 'GB108050008100'])"
```

Its web address comes from its name (North Devon → `north-devon`). Every catchment ID must
already be in the catchments table: if one isn't, the publish stops, says which, and leaves
the published pages as they were.

## Development and live settings

The commands are the same on your machine and on the live server. What differs is which
settings file Docker Compose adds to `docker-compose.yml`:

| | Your machine | Live server |
|---|---|---|
| Settings file | `docker-compose.override.yml` (added automatically) | `docker-compose.prod.yml` (chosen by `COMPOSE_FILE` in the server's `.env`) |
| Passwords | Simple defaults | Must be set in `.env`, or nothing starts |
| Code | Used straight from this folder, so edits need no rebuild | Built into the image |
| Database port | Open on this machine for DBeaver | Only reachable from the server itself |
| Admin page | <http://localhost:8000/admin>, login `admin` / `admin` | Logins from `.env`; only through an SSH tunnel until the web server is added |
| Published dashboards | Previewed at <http://localhost:8080> | Written to `published/`; the web server will serve them once it's added |
| Tests and data map | Yes | No |

The differences are only settings, never code: the same images run in both places.

## Live server (Azure VM)

### First-time setup

1. Create the VM (size and security settings: PLAN.md §6.2).
2. Install Docker, following Docker's instructions for Ubuntu:
   <https://docs.docker.com/engine/install/ubuntu/>.
3. Get the code: `git clone https://github.com/tom-igi/catchment-catalyst.git`, then
   `cd catchment-catalyst`. If the repository is private, give the server a read-only
   *deploy key* in GitHub first.
4. Create the settings file: `cp .env.prod.example .env`, then fill in:
   - the database password (make one with `openssl rand -hex 24`);
   - `ADMIN_USERS`: an entry for each person, made on your own machine with
     `docker compose run --rm admin hash-password <name>`;
   - `ADMIN_SECRET_KEY` (make one with `openssl rand -hex 32`).
5. Start it and create the tables:

   ```bash
   docker compose up -d
   docker compose run --build --rm schema apply
   ```

### Updating to the latest code

```bash
git pull
docker compose up -d --build
docker compose run --build --rm schema plan     # check what will change in the database
docker compose run --build --rm schema apply
```

To import data on the server, use the same command as locally, with `--build`:
`docker compose run --build --rm importer catchments imports/catchments.json`.

`--build` matters here: on the server the code is built into the image, so without it the
schema tool and importers would still be using the old code (and the old `schema.yaml`).

If an update needs a new setting, every `docker compose` command stops and says which one is
missing from `.env`. Add it (see `.env.prod.example`) and run the command again.

### Using the live admin page

Until the web server (with HTTPS) is added, the admin page only accepts connections from the
server itself. To use it from your machine, open an SSH tunnel
(`ssh -L 8001:localhost:8000 <user>@<server>`), then go to <http://localhost:8001/admin>.

### Looking at the live database

The database only accepts connections from the server itself. To use DBeaver from your
machine, open an SSH tunnel (`ssh -L 5435:localhost:5432 <user>@<server>`), then connect to
`localhost`, port `5435`, with the user and password from the server's `.env`.

### Not set up yet

These get added to `docker-compose.prod.yml` when the site is ready to go public: the web
server (Caddy), serving `published/` with HTTPS at each location's address, and nightly
database backups to Azure storage. See PLAN.md §5–6.
