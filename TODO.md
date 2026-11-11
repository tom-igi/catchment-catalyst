# To do

Agreed changes waiting to be built. Tom will say when to start each one.

## Share the repeated code in the API importers

**Agreed:** 10 November 2026

**The problem:** the API importers (`backend/catalyst/importers/api/`) repeat a few small
pieces, and the copies have already drifted (only `classifications.py` inserts in batches of
5,000).

**The plan:** a small shared module (e.g. `api/common.py`) with:

- `replace_rows(conn, table, rows)`: delete every row, then insert the new ones in batches.
  Replaces the `save()` bodies in `classifications.py`, `storm_overflows.py` and
  `river_obstacles.py` (storm overflows keeps its extra latitude/longitude step).
- `run_folder(raw_dir, table)`: makes `raw/<table>/<date and time>/`, used by every
  `save_raw_files()`.
- `ImportProblem` moved here from `catchments.py`.

Keep each source's own fetch and read code separate: they really are different. No general
framework that runs every importer the same way unless many more sources are added.
The command flow in `importers/__main__.py` stays as it is.

The tests in `backend/tests/` should still pass unchanged.
