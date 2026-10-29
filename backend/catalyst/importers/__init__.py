"""Importers: the code that fills the data tables, in two kinds.

- api/    tables filled from an outside service's API, e.g. catchments from
          the EA's Catchment Data Explorer. One module per source.
- excel/  tables filled by uploading an Excel file in the admin page, e.g. EA
          scores. One shared piece of code for all of them: a new table only
          needs `filled_by: excel` in schema.yaml.

schema.yaml says which kind fills each table (`filled_by: api` or `excel`).
"""
