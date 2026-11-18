"""Importers: the code that fills the data tables, in three kinds.

- api/     tables filled from an outside service's API, e.g. catchments from
           the EA's Catchment Data Explorer. One module per source.
- inputs/  tables worked out from a source file uploaded as it came, in the
           admin page, with the original Power BI dashboard's formulas, e.g.
           Livestock and Livestock Pressure from APHA's livestock data. One
           module per file; one file can fill several tables.
- excel/   tables filled by uploading an Excel file in the table's own layout
           (1 to 1), in the admin page, e.g. Location Text. One shared piece
           of code for all of them: a new table only needs `filled_by: excel`
           in schema.yaml. Source files use its comparing and replacing too.

schema.yaml says which kind fills each table (`filled_by: api`, `input` or `excel`).
"""
