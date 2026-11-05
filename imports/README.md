# Imports

Lists of what to import, plus a copy of everything the importers download and every Excel
file uploaded in the admin page.

| File | What it is |
|---|---|
| `catchments.json` | Which catchments to import from the EA's Catchment Data Explorer: whole management catchments (all their rivers) and/or single catchment IDs |
| `raw/` | Every file downloaded, in a folder per import run, and every Excel file uploaded, in a folder per table (not kept in git) |

`catchments.json` looks like this (either list can be left out):

```json
{
  "description": "North Devon: every river waterbody in the EA's North Devon management catchment (3062).",
  "management_catchments": [3062],
  "catchments": ["GB108050008080"]
}
```

A management catchment means all its river waterbodies. Lakes and other waterbodies can't be
imported yet, so they're left out. To import the catchments:

```bash
docker compose run --rm importer catchments imports/catchments.json
```

It downloads everything first and checks it, shows what it will add or update, and asks
before saving anything. Running it again is safe: catchments already in the database are
updated rather than duplicated.

Then the data for those catchments, from the EA and River Obstacles:

```bash
docker compose run --rm importer classifications    # ea_classifications and ea_rnags
docker compose run --rm importer storm-overflows    # storm_overflows
docker compose run --rm importer river-obstacles    # river_obstacles
```

Each replaces its tables' rows, and keeps what it downloaded in `raw/<table>/<date and time>/`.

Later, the admin portal will do the same job through a web page.
