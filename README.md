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
  catalyst/importers/api/    tables filled from outside sources (the EA's catchments, classifications, RNAGs,
                             storm overflows; River Obstacles; Ordnance Survey's postcodes)
  catalyst/importers/excel/  tables filled by Excel upload (one shared piece of code for all of them)
  catalyst/admin/            the admin page: a diagram of every table (diagram.py, diagram.yaml);
                             download any table; upload an Excel table, preview, approve; publish
  catalyst/publish/          the publish step: writes each location's dashboard as web pages
  tests/
imports/                     lists of what to import, and copies of every download and upload (see imports/README.md)
published/                   the published dashboards (not in git; see published/README.md)
```

## Running locally

Only Docker is needed.

```bash
docker compose up -d                    # start the database, the admin page and the dashboard preview
docker compose run --rm schema plan     # preview changes needed to match schema.yaml
docker compose run --rm schema apply    # make them (asks first)
docker compose run --rm publish         # write the dashboards' pages (or the admin page's Publish button)
docker compose run --rm test            # run the backend tests
```

The admin page is at <http://localhost:8000/admin> (name `admin`, password `admin`), and the
published dashboards at <http://localhost:8080>.

The admin page is a diagram of every table: where its data comes from and how they join up.
Click a table to see its columns and download it as Excel (any table; map shapes are left
out). On the left, where the data comes from, each import command has a box (with the
source's website and the command that downloads its tables again), and so does each table
filled by Excel upload (**Upload data**, to upload an edited copy). It's made from `schema.yaml` each time it's opened, plus
`backend/catalyst/admin/diagram.yaml` (the sections, and where each downloaded table comes
from, its website and its command: add a new importer's table there).

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
- A change of primary key is made too: the old key is dropped before the other changes and
  the new one added after them. If the rows don't fit the new key (e.g. two with the same
  value), the database refuses it and nothing is changed.
- The tool can't move data between columns (e.g. split a column in two). That needs a
  one-off script.
- Only tables in the `public` schema are managed.

## Filling the tables

Each table is filled in one way, set by `filled_by` in `schema.yaml`:

| `filled_by` | How | Tables so far |
|---|---|---|
| `api` | An importer downloads the data from an outside service (`backend/catalyst/importers/api/`) | Catchments, EA Classifications, EA Reasons for Not Achieving Good, Storm Overflows, River Obstacles, Postcodes |
| `excel` | Someone uploads an Excel file in the admin page (`backend/catalyst/importers/excel/`) | EA Scores, Habitat & Land Use |

### From an API

Import the catchments first: the other importers fetch data for every catchment in the
catchments table.

```bash
docker compose run --rm importer catchments imports/catchments.json   # catchments, from the EA (all 92 North Devon rivers)
docker compose run --rm importer classifications                      # the EA's classifications and RNAGs
docker compose run --rm importer storm-overflows                      # storm overflow spills, from the EA's yearly returns
docker compose run --rm importer river-obstacles                      # weirs, culverts and so on, from River Obstacles
docker compose run --rm importer postcodes                            # the postcodes in each catchment, for the postcode search
```

Each downloads and checks everything first, shows what it will change, and asks before saving
(add `--yes` to skip the question). Running one again is safe: catchments are updated, and the
other tables are replaced. Everything downloaded is kept in `imports/raw/`. See
`imports/README.md`.

### From Excel (the admin page)

1. Log in to the admin page and click the table's **Upload data**, on the left.
2. Download it as an Excel file.
3. Add, change or delete rows. Keep the column names in row 1 as they are.
4. Upload it. Every row is checked, then a preview shows exactly what will be added, changed
   and deleted.
5. Approve it, and the table's rows are replaced with the file's. Or cancel, and nothing
   changes.
6. Click **Publish** (in the Public dashboard box at the top of the admin page) to put
   everything approved on the public dashboard. Until then, the box says how many uploads
   are approved but not published, so several can be approved and then published at once.

Each upload replaces the whole table, so always start from a fresh download. Every uploaded
file is kept (in `imports/raw/<table>/`) and listed under its Upload data: to go back to an
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
publish again, with the **Publish** button at the top of the admin page or the command:

```bash
docker compose run --rm publish     # write every location's pages into published/
```

Both do exactly the same (`backend/catalyst/publish/run.py`), and each records the publish
in the `publishes` table (who and when; the command leaves "who" empty). The admin page uses
it to say how many uploads have been approved since the last publish. Only one publish runs
at a time: a second one waits for the first to finish.

On your machine, see them at <http://localhost:8080>. The pages copy the original dashboard
(`Reference/ReferenceImages`): four views, chosen with the cards across the top of every page.

- **Waterbody Dashboard:** the original's tabs, River Status, EA Data, Land Use Data and Sewerage
  Data, for one waterbody at a time. (Its Overview tab is switched off for now: `SHOW_OVERVIEW` in
  `backend/catalyst/publish/site.py`.)
- **Catchment Dashboard:** the whole location on one map, with its ecological class counts, its
  text, and its farms, properties, storm overflows and habitat added up. Its operational catchments
  (e.g. Torridge) each get a page too, narrowed to their waterbodies.
- **Intervention Management** and **Catchment Insights:** placeholders for now, with their focus
  area buttons.

Each location gets a folder (e.g. `published/north-devon/`) with:

- `index.html`: the front page: River Status before a catchment is chosen (or the Overview, when
  it's switched on);
- `<tab>/<catchment ID>/`: each Waterbody Dashboard tab, for each catchment. Clicking the map picks
  another catchment and stays on the same tab;
- `<tab>/`: each tab before a catchment is chosen;
- `catchment-dashboard/`, and `catchment-dashboard/<operational catchment>/` (e.g. `torridge/`);
- `intervention-management/` and `catchment-insights/`.

Panels whose data has a table are filled in, from the EA's data, the Excel tables (text, risk
levels, interventions, thresholds, farms, livestock, phosphate, sewerage and so on) and the "i"
buttons (from the Datasets table, also uploaded in Excel: one row per table, with its text). A panel is shown empty while its table has no rows for that
catchment. Each new data table needs a place on a page, in
`backend/catalyst/publish/templates/` (calculations such as percentages go in
`backend/catalyst/publish/figures.py`).

Hand-written text (River Status Text, Location Text, the "i" text in Datasets) can have
paragraphs, bullets, bold, links, headings and sections that open and close, using a few
Markdown marks (`**bold**`, `[words](https://…)`, `## heading`, `### section`, `> grey box`).
The full list is at the top of `backend/catalyst/publish/text.py`. In Excel, Alt+Enter starts a
new line in a cell. Web and email addresses become links by themselves.

The styles and scripts are in `backend/catalyst/publish/static/`. The maps use Leaflet (copied
into `static/leaflet/`) over OpenStreetMap's map images, which are the only thing the pages load
from elsewhere.

### Locations

Until the admin page can manage locations, add one with SQL:

```bash
docker compose exec db psql -U catalyst -c "INSERT INTO locations (name, catchment_ids) VALUES ('North Devon', ARRAY['GB108050008080', 'GB108050008100'])"
```

Or give it every river imported from a management catchment (North Devon is `3062`):

```bash
docker compose exec db psql -U catalyst -c "UPDATE locations SET catchment_ids = (SELECT array_agg(id ORDER BY id) FROM catchments WHERE management_catchment_id = 3062 AND waterbody_type = 'River') WHERE name = 'North Devon'"
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
| Database files | A Docker volume (`docker compose down -v` deletes it) | The `db-data/` folder, next to the code |
| Admin page | <http://localhost:8000/admin>, login `admin` / `admin` | Logins from `.env`; only through an SSH tunnel until the web server is added |
| Published dashboards | Previewed at <http://localhost:8080> | Written to `published/`; the web server will serve them once it's added |
| Tests | Yes | No |

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

### Deploying to the shared test VM

For the client demo, the app runs on IGI's shared test VM (20.39.226.55), next to Brownfield
GIS, at <https://rivers.smartbiosphere.com>. **Started 12 November 2026** (step 3 done). The
steps are below.

**How it's set up.** Only one program on the VM can use the web ports (80 and 443), so they
belong to a shared *front door*. That's a Caddy server from the
[front-door](https://github.com/tom-igi/front-door) repo, in `/opt/front-door` on the VM. It
already serves brownfield.igiltd.com, and this app's address is set up there too
(`caddy/sites/rivers.caddy`). The front door gets the address's HTTPS certificate by itself,
during the first visit to it. Visitors can only arrive once the address's DNS record points at
the VM, so the address starts working as soon as the record is added, with nothing to do on the
VM then. It serves:

| Address | What it shows |
|---|---|
| `https://rivers.smartbiosphere.com/` | Goes straight to North Devon (`/north-devon/`). The list of locations is still at `/index.html` |
| `https://rivers.smartbiosphere.com/admin` | The admin page |
| Everything else | The published dashboards, from `published/` |

On the VM, `.env` adds `docker-compose.front-door.yml` to the usual live settings. It:

- adds a small `web` container that serves `published/` to the front door;
- takes away the admin page's port, so it's reached only through the front door (at the
  address above, not an SSH tunnel), and its login cookie is sent over HTTPS only;
- moves the database to port 5433, because Brownfield's has 5432. For DBeaver, tunnel with
  `ssh -L 5435:localhost:5433 <user>@20.39.226.55` instead.

So the web server under "Not set up yet" below isn't needed there. The backups still are.

#### Steps

Before you start:

1. **Everything is pushed to GitHub,** including `docker-compose.front-door.yml`.
2. **DNS:** ask whoever manages smartbiosphere.com's DNS for an A record
   `rivers.smartbiosphere.com` → `20.39.226.55`. It must be a plain A record: not URL
   forwarding, and not proxied if the domain is on Cloudflare. Nothing waits for it until
   step 10, so the other steps can be done first.
3. **Room on the VM** for a second database: check with `free -h` and `df -h /`. (Checked on
   12 November 2026: 2.9 GB of memory available, where the app uses about 0.5 GB, and 19 GB of
   disk free.)

On the VM (run `git` without `sudo`):

4. Get the code, and check the folders the containers write to are theirs:

   ```bash
   sudo mkdir /opt/catchment-catalyst && sudo chown "$USER": /opt/catchment-catalyst
   git clone https://github.com/tom-igi/catchment-catalyst.git /opt/catchment-catalyst
   cd /opt/catchment-catalyst
   id -u
   ```

   The containers write to `published/` and `imports/` as user number 1000. If `id -u` doesn't
   print `1000`, give them those folders: `sudo chown -R 1000:1000 published imports`.

5. Make the settings file and switch it to the front-door settings. Then fill in the
   passwords as in "First-time setup", step 4, above, and check it:

   ```bash
   cp .env.prod.example .env
   sed -i 's|^COMPOSE_FILE=.*|COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml:docker-compose.front-door.yml|' .env
   nano .env
   docker compose config --quiet && echo OK
   ```

6. Start it and create the tables:

   ```bash
   docker compose up -d --build
   docker compose run --build --rm schema apply
   docker ps --format '{{.Names}}\t{{.Ports}}'
   ```

   The database should show `127.0.0.1:5433`. The admin page and `web` should show no ports.

7. Import the EA data and add North Devon, with the commands in OPERATING.md §5 ("Tables filled
   from an outside source" and "Locations"). Add `--build` to each `docker compose run`.

8. Switch the address on in the front door. Brownfield isn't interrupted:

   ```bash
   cd /opt/front-door
   git pull
   docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile
   ```

   The front door doesn't ask for the certificate yet, so its log says nothing about
   `rivers.smartbiosphere.com` until the first visit. Until the DNS record is there, don't
   reach the address any other way (for example with an entry in your computer's hosts file):
   the front door would ask for the certificate, and Let's Encrypt would refuse it.

9. Log in to the admin page, upload the Excel tables, approve them, and click **Publish**.
   Once the DNS record is there, the admin page is at <https://rivers.smartbiosphere.com/admin>.
   Before then, reach it through an SSH tunnel to its container:

   1. On the VM, in `/opt/catchment-catalyst`, find the containers' addresses (they change
      whenever the containers are recreated, so run this again if the tunnel stops working):

      ```bash
      docker inspect -f '{{.Name}}{{range .NetworkSettings.Networks}} {{.IPAddress}}{{end}}' $(docker compose ps -q admin web)
      ```

   2. On your machine, using one address from each line:

      ```bash
      ssh -L 8001:<admin address>:8000 -L 8081:<web address>:8080 <user>@20.39.226.55
      ```

   3. The admin page is at <http://localhost:8001/admin>, and the dashboards are at
      <http://localhost:8081/north-devon/>. Use Chrome or Edge: the login cookie is sent over
      HTTPS only, and they make an exception for `localhost`. If logging in keeps coming back
      to the login page, that's why.

   Until the first publish, the address shows a "not found" error.

10. Once the DNS record is there (on the VM, `getent hosts rivers.smartbiosphere.com` prints
    `20.39.226.55`), check that <https://rivers.smartbiosphere.com> opens on North Devon's
    dashboard. The first visit takes a few seconds longer while the front door gets the
    certificate. In `/opt/front-door`, `docker compose logs caddy` then shows
    `certificate obtained successfully`. If the page shows a certificate or connection error
    instead, the log says why: see the front door's README, "Troubleshooting".

11. Fill in OPERATING.md §2 and §3 (the live commands and address), and set up the nightly
    backups ("Not set up yet", below).

Instead of steps 7 and 9, the database on your machine could be copied across (`pg_dump` here,
`pg_restore` on the VM), to show exactly what's on your machine. This hasn't been tried yet.

**Things to know on the VM:**

- Updating to new code is as in "Updating to the latest code", above. The front door's own
  settings live in the front-door repo, not here.
- **Everything for the app is in `/opt/catchment-catalyst`,** including the database's files,
  in `db-data/` (made by step 6). That folder belongs to the database container's user, so
  look inside it with `sudo`. Copying it while the database is running doesn't make a usable
  backup: use `pg_dump`, as the nightly backups will.
- `docker compose down -v` doesn't delete the database there, because it's in a folder rather
  than a Docker volume. Deleting `db-data/` does.
- A "502 Bad Gateway" at the address means the admin page or `web` container isn't running:
  check with `docker compose ps` in `/opt/catchment-catalyst`.
- The front door's README has the rest: how to undo things, logs, and troubleshooting.

### Not set up yet

These get added to `docker-compose.prod.yml` when the site is ready to go public: the web
server (Caddy), serving `published/` with HTTPS at each location's address, and nightly
database backups to Azure storage. See PLAN.md §5–6.
