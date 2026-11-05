# Data map

A diagram of every table in the database, for people who aren't developers. It shows where each
table's data comes from (downloaded from the internet, or uploaded in Excel), how the
tables join up by Catchment ID, and, when you click a table, what it holds and its columns.

**To view it,** log in to the admin page and click **Data map** at the top
(<http://localhost:8000/admin/data-map> on your machine).

## How it stays up to date

The admin page makes the page each time it's opened, from the database's master file,
`backend/catalyst/db/schema.yaml`. It uses each table's `title`, `description` and
`filled_by`, and each column's `description` and `example`. So it always matches the
`schema.yaml` the admin page is running: on your machine the admin page restarts when
`schema.yaml` changes, and on the live server it's the copy built into the image, the same
one `schema apply` used.

The only thing it reads from the database is how many rows each table has. The example row
under each table's columns comes from `schema.yaml` and is invented, not real data. It's
behind the admin login, and also asks search engines not to list it.

**When you add a table filled by an importer,** add it under `filled` in `sections.yaml`
(where it's downloaded from, and the command), or the page can't say where it comes from.

## Files

| File | What it is |
|---|---|
| `build.py` | Gathers the facts about every table and puts them in the page |
| `page.html` | The page: layout, styling and the script that draws the diagram |
| `sections.yaml` | The groups of tables and their explanations; where each downloaded table comes from (`filled`); and links the database can't check, such as the list of catchment IDs in Locations (`links`) |
| `backend/tests/test_datamap.py` | Checks the page has every table and column, and needs a login |

## Removing it

1. Delete this `datamap` folder.
2. Delete `backend/tests/test_datamap.py` (its tests are skipped once the folder has gone,
   so this is only tidying up).

Nothing else needs to change. The admin page drops the **Data map** link and the page when
this folder isn't there, and the `title` and `example` lines in `schema.yaml` are harmless
if left in (or delete them).
