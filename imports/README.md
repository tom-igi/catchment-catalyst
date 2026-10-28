# Imports

Lists of what to import, plus a copy of everything the importers download.

| File | What it is |
|---|---|
| `catchments.json` | Which catchments to import from the EA's Catchment Data Explorer |
| `raw/` | Every file downloaded, in a folder per import run (not kept in git) |

To import the catchments listed in `catchments.json`:

```bash
docker compose run --rm importer catchments imports/catchments.json
```

It downloads everything first and checks it, shows what it will add or update, and asks
before saving anything. Running it again is safe: catchments already in the database are
updated rather than duplicated.

Later, the admin portal will do the same job through a web page.
