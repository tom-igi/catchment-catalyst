# Data map

A plain-English web page showing every table in the database: what it holds, what each
column means, and an example row. It's meant for people who aren't developers.

**To view it,** log in to the admin page and click **Data map** at the top
(<http://localhost:8000/admin/data-map> on your machine).

## How it stays up to date

The admin page makes the page from the database's master file,
`backend/catalyst/db/schema.yaml`. It uses each table's `title` and `description`, and each
column's `description` and `example`. So it always matches the `schema.yaml` the admin page
is running: on your machine the admin page restarts when `schema.yaml` changes, and on the
live server it's the copy built into the image, the same one `schema apply` used.

The page only describes the structure: it never reads the database and contains no real
data. It's behind the admin login, and also asks search engines not to list it.

## Files

| File | What it is |
|---|---|
| `build.py` | Turns the master file into the page |
| `page.html` | The page layout and styling |
| `sections.yaml` | The page's sections (Locations, Catchments, …), which tables go in each, and the explanation shown above them |
| `backend/tests/test_datamap.py` | Checks the page lists every table and column, and needs a login |

## Removing it

1. Delete this `datamap` folder.
2. Delete `backend/tests/test_datamap.py` (its tests are skipped once the folder has gone,
   so this is only tidying up).

Nothing else needs to change. The admin page drops the **Data map** link and the page when
this folder isn't there, and the `title` and `example` lines in `schema.yaml` are harmless
if left in (or delete them).
