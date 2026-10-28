# Catchment Catalyst

Water quality dashboard platform. See [PLAN.md](PLAN.md) for the overall design.

## Layout

```
docker-compose.yml          local stack: database + tools
backend/                    all Python code, built into one Docker image
  catalyst/db/schema.yaml   ← the database master file: every table and column
  catalyst/db/schema.py     reads and checks schema.yaml
  catalyst/db/sync.py       compares schema.yaml with the database and applies changes
  tests/
```

## Running locally

Only Docker is needed.

```bash
docker compose up -d                    # start the database (PostgreSQL 17 + PostGIS)
docker compose run --rm schema plan     # preview changes needed to match schema.yaml
docker compose run --rm schema apply    # make them (asks before changing anything)
docker compose run --rm test            # run the backend tests
```

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

## Deployment (Azure)

The same `backend` image runs in Azure. Only `DATABASE_URL` changes:

```bash
DATABASE_URL="postgresql+psycopg://<user>:<password>@<server>.postgres.database.azure.com:5432/catalyst?sslmode=require" \
  python -m catalyst.db plan      # or run the image as a Container Apps Job
```

Before the first `apply` on Azure Database for PostgreSQL, PostGIS must be on the server's
allowed extensions list (server parameter `azure.extensions`, add `POSTGIS`). The schema
tool then installs it, the same way it does locally.
