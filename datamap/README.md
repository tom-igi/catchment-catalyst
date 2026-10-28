# Data map

A plain-English web page showing every table in the database: what it holds, what each
column means, and an example row. It's meant for people who aren't developers.

**To view it,** open `datamap/site/index.html` in a web browser.

## How it stays up to date

The page is built from the database's master file, `backend/catalyst/db/schema.yaml`. It
uses each table's `title` and `description`, and each column's `description` and `example`.

It's rebuilt automatically every time you run

```bash
docker compose run --rm schema apply
```

even when the database itself had nothing to change, so edits to titles, descriptions or
examples show up straight away. The page only describes the structure: it never connects to
the database and contains no real data.

To rebuild the page on its own:

```bash
docker compose run --rm --entrypoint python schema -m datamap
```

## Hosting

It isn't published anywhere yet. The plan is to host it later on the dashboard's Azure
Static Web App at a path that isn't linked from anywhere. The page asks search engines not
to list it, but anyone who has the link can open it.

## Files

| File | What it is |
|---|---|
| `build.py` | Turns the master file into the page |
| `page.html` | The page layout and styling |
| `test_datamap.py` | Checks the page lists every table and column |
| `site/index.html` | The built page (not kept in git) |

## Removing it

1. Delete this `datamap` folder.
2. Delete the lines that mention `data map` in `docker-compose.yml` (two) and `README.md` (one).

Nothing else needs to change. The schema tool skips the rebuild when this folder isn't there,
the tests skip it too, and the `title` and `example` lines in `schema.yaml` are harmless if
left in (or delete them).
