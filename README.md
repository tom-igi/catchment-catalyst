# Catchment Catalyst

Water quality dashboard platform. See [PLAN.md](PLAN.md) for the overall design, and
[PROGRESS.md](PROGRESS.md) for where the build is up to.

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
  catalyst/importers/        fill the database (one importer per kind of data)
  tests/
imports/                     lists of what to import, and copies of every download (see imports/README.md)
datamap/                     optional data map page: every table in plain English (see datamap/README.md)
```

## Running locally

Only Docker is needed.

```bash
docker compose up -d                    # start the database (PostgreSQL 17 + PostGIS)
docker compose run --rm schema plan     # preview changes needed to match schema.yaml
docker compose run --rm schema apply    # make them (asks first), and rebuild the data map
docker compose run --rm test            # run the backend tests
```

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

## Importing data

Each importer fills its own tables. So far there is one, for catchments from the EA:

```bash
docker compose run --rm importer catchments imports/catchments.json
```

It downloads and checks everything first, shows what it will add or update, and asks before
saving. Running it again updates catchments rather than duplicating them. See
`imports/README.md`.

## Development and live settings

The commands are the same on your machine and on the live server. What differs is which
settings file Docker Compose adds to `docker-compose.yml`:

| | Your machine | Live server |
|---|---|---|
| Settings file | `docker-compose.override.yml` (added automatically) | `docker-compose.prod.yml` (chosen by `COMPOSE_FILE` in the server's `.env`) |
| Passwords | Simple defaults | Must be set in `.env`, or nothing starts |
| Code | Used straight from this folder, so edits need no rebuild | Built into the image |
| Database port | Open on this machine for DBeaver | Only reachable from the server itself |
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
4. Create the settings file: `cp .env.prod.example .env`, then fill in the password
   (make one with `openssl rand -hex 24`).
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

### Looking at the live database

The database only accepts connections from the server itself. To use DBeaver from your
machine, open an SSH tunnel (`ssh -L 5435:localhost:5432 <user>@<server>`), then connect to
`localhost`, port `5435`, with the user and password from the server's `.env`.

### Not set up yet

These get added to `docker-compose.prod.yml` when there's a site to serve: the web server
with HTTPS for each location's address, nightly database backups to Azure storage, the admin
API and the import worker. See PLAN.md §5–6.
