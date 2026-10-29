"""Tables filled from an outside service's API (`filled_by: api` in schema.yaml).

One module per source, run from the command line (see ../__main__.py):

- catchments.py  the catchments table, from the EA's Catchment Data Explorer
                 (downloads through ea_api.py)
"""
