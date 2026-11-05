"""Tables filled from an outside service's API (`filled_by: api` in schema.yaml).

One module per source, run from the command line (see ../__main__.py):

- catchments.py       the catchments table, from the EA's Catchment Data Explorer
- classifications.py  the EA's classifications and reasons for not achieving good
                      (ea_classifications, ea_rnags), also from the Catchment Data Explorer
- storm_overflows.py  storm overflow spills, from the EA's yearly storm overflow returns
- river_obstacles.py  weirs, culverts and other obstacles, from River Obstacles

All of them download through ea_api.py.
"""
