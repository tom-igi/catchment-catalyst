"""Tables worked out from a source file (`filled_by: input` in schema.yaml).

The original Power BI dashboard read each dataset from a file, such as APHA's
livestock data, and worked its figures out with Power Query steps and DAX
formulas. Each module here is one of those files (an "input"): the sheet and
columns it reads, the original's formulas, and the tables they fill. Its steps
say what's worked out in words, with where each is in the Power BI file, for
the admin page's Transformation column.

What's worked out here is anything that turns the one file into each
waterbody's figures (unit changes, densities, ratings, pressures), so the
preview shows the figures themselves changing. Anything that needs more than
one table, or a whole location, is worked out when the dashboards are
published (catalyst.publish.figures; README.md, "Where the figures are worked
out").

1. Someone uploads the file as it came, in the admin page.
2. Its input reads it and works out the rows of each of its tables (Input.run).
3. Each table is compared with its new rows, as an Excel upload is
   (catalyst.importers.excel), and every change is previewed.
4. Once approved, every table it fills is changed at once.
5. If a formula changes later, "Work it out again" (on its upload in the admin
   page) runs its last approved file through the formulas as they are now, as
   a new upload of the same file, previewed and approved in the same way.

To add one: write its module (apha_livestock.py is an example), list it in
INPUTS below, and mark its tables in schema.yaml with `filled_by: input` and
`input: <its name>`.
"""

from catalyst.db import Schema

from .apha_livestock import APHA_LIVESTOCK
from .common import Example, Input, Result, SourceRow, Step, figure, read_sheet, read_sheets
from .ea_classification_facts import EA_CLASSIFICATION_FACTS
from .esme import ESME
from .habitat import HABITAT_FILE
from .improvement_information import IMPROVEMENT_INFORMATION
from .sagis_phosphate import SAGIS_PHOSPHATE
from .water_company_plans import WATER_COMPANY_PLANS
from .waterbody_lookup import WATERBODY_LOOKUP

INPUTS: dict[str, Input] = {
    i.name: i for i in (
        WATERBODY_LOOKUP, APHA_LIVESTOCK, ESME, HABITAT_FILE, IMPROVEMENT_INFORMATION, SAGIS_PHOSPHATE, WATER_COMPANY_PLANS,
        EA_CLASSIFICATION_FACTS,
    )
}

__all__ = ["INPUTS", "Example", "Input", "Result", "SourceRow", "Step", "check", "figure", "read_sheet", "read_sheets"]


def check(schema: Schema) -> list[str]:
    """Mistakes between schema.yaml and the inputs: each table names an input that fills it, and the other way round.

    An input none of whose tables are in schema.yaml isn't used, so it's left alone.
    """
    problems = []
    marked = schema.input_tables
    for table, name in marked.items():
        if name not in INPUTS:
            problems.append(f"schema.yaml: {table} is filled by the input {name}, which isn't in catalyst/importers/inputs/")
        elif table not in INPUTS[name].tables:
            problems.append(f"schema.yaml: {table} is filled by the input {name}, which doesn't fill it")
    for name, source in INPUTS.items():
        if name not in marked.values():
            continue
        if name in schema.metadata.tables:
            problems.append(f"The input {name} has the same name as a table. Give it another.")
        for table in source.tables:
            if table not in schema.metadata.tables:
                problems.append(f"The input {name} fills {table}, which isn't in schema.yaml")
            elif marked.get(table) != name:
                problems.append(f"The input {name} fills {table}, but schema.yaml doesn't say `filled_by: input` and `input: {name}` for it")
    return problems
