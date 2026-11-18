"""Source files: reading one as it came, and working out its tables with the original Power BI dashboard's formulas."""

import io
from pathlib import Path

import pytest
import sqlalchemy as sa
from openpyxl import Workbook

from catalyst.db import load_schema
from catalyst.db.sync import apply_changes
from catalyst.importers import inputs
from catalyst.importers.excel import UploadError
from catalyst.importers.inputs import (
    apha_livestock, ea_classification_facts, esme, habitat, improvement_information, read_sheet, read_sheets, waterbody_lookup,
)
from catalyst.importers.inputs.common import banded

SCHEMA = load_schema()
APHA = inputs.INPUTS["apha_livestock"]
LOOKUP = inputs.INPUTS["waterbody_lookup"]
ESME = inputs.INPUTS["esme"]
HABITAT = inputs.INPUTS["habitat"]
IMPROVEMENT = inputs.INPUTS["improvement_information"]
SAGIS = inputs.INPUTS["sagis_phosphate"]
PLANS = inputs.INPUTS["water_company_plans"]
FACTS = inputs.INPUTS["ea_classification_facts"]
# A cut-down Waterbody Lookup.xls (an older Excel file, as the original is): Abbey River and Badgworthy
# Water's rows from the real one, Bray with no farms figure, and a waterbody that isn't one of ours.
LOOKUP_FILE = Path(__file__).with_name("fixtures") / "waterbody-lookup.xls"
ABBEY, BADGWORTHY, BRAY = "GB108050014050", "GB108051020570", "GB108050014470"

# APHA's headings, with its line breaks, and some of the columns the original didn't use.
APHA_HEADINGS = (
    "Catchment \nName", "Catchment\nSqKm", "Cattle Units \nwithin Catchment", 'Total "Beef" Units', "Beef \nPopulation",
    "Beef Density\nPer SqKm", 'Total "Dairy" Units', "Dairy \nPopulation", "Dairy Density\nPer SqKm",
    "Pig Units \nwithin Catchment", "Total Pig Numbers", "Pig Density Per SqKm", "Sheep Units \nwithin Catchment",
    "Total Sheep Numbers", "Sheep Density Per SqKm", "Poultry Units \nwithin Catchment", "Total Poultry Numbers",
    "Poultry \nPer SqKm",
)
# Abbey River's row in APHA Livestock Data Feb 2026.xlsx.
ABBEY_ROW = ("Abbey River", 16.992163206999997, 11, 8, 635, 37.370168369051974, "Less than 5", 1245, 73.26907026688143,
             9, 248, 14.594963394527385, 14, 974, 57.320541718829325, 14, 15422, 907.5948607677473)
# Badgworthy Water's: no dairy cattle, pigs or poultry (blank).
BADGWORTHY_ROW = ("Badgworthy Water", 25.484844403, "Less than 5", "Less than 5", 25, 0.9809751868470138, None, None,
                  None, None, None, None, "Less than 5", 26, 1.0202141943208944, None, None, None)


def workbook(*sheets: tuple[str, list[tuple]]) -> bytes:
    book = Workbook()
    book.remove(book.active)
    for name, rows in sheets:
        sheet = book.create_sheet(name)
        for row in rows:
            sheet.append(list(row))
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def apha_file(*rows, sheet="Appendix 1 EIR2026_00630") -> bytes:
    return workbook(("Notes", [("Sent on request",)]), (sheet, [APHA_HEADINGS, *rows]))


def problems_with(call) -> str:
    with pytest.raises(UploadError) as error:
        call()
    return "\n".join(error.value.problems)


@pytest.fixture
def database(engine):
    apply_changes(engine, SCHEMA)
    with engine.begin() as conn:
        for catchment_id, name in [(ABBEY, "Abbey River"), (BADGWORTHY, "Badgworthy Water"), (BRAY, "Bray (Mole to Hole Water)")]:
            conn.execute(sa.text("INSERT INTO catchments (id, name, waterbody_type) VALUES (:id, :name, 'River')"),
                         {"id": catchment_id, "name": name})
    return engine


def run(database, data, name="APHA Livestock Data Feb 2026.xlsx", source=APHA):
    with database.connect() as conn:
        return source.run(conn, SCHEMA, data, name)


# --- Reading a file as it came ----------------------------------------------------

def test_reads_the_named_sheet_by_its_headings():
    data = workbook(
        ("Notes", [("Catchment Name", "Beef Population"), ("Not this one", 1)]),
        ("Appendix", [("Beef \nPopulation", "Extra", " catchment  NAME "), (635, "x", "Abbey River"), (None, None, None),
                      (25, None, "Badgworthy Water")]),
    )
    rows = read_sheet(data, "file.xlsx", "Appendix", ("Catchment Name", "Beef Population"))
    assert [(r.line, r.cells) for r in rows] == [
        (2, {"Catchment Name": "Abbey River", "Beef Population": 635}),  # case, spaces and line breaks don't matter
        (4, {"Catchment Name": "Badgworthy Water", "Beef Population": 25}),  # empty rows are skipped
    ]


def test_a_renamed_sheet_is_found_by_its_headings():
    data = workbook(("Notes", [("Something else",)]), ("Appendix 2 EIR2026_00999", [("Catchment Name",), ("Abbey River",)]))
    rows = read_sheet(data, "file.xlsx", "Appendix 1 EIR2026_00630", ("Catchment Name",))
    assert [r.cells for r in rows] == [{"Catchment Name": "Abbey River"}]


def test_missing_columns_are_named():
    data = workbook(("Appendix", [("Catchment Name", "Beef Population")]))
    problems = problems_with(lambda: read_sheet(data, "file.xlsx", "Appendix", ("Catchment Name", "Beef Population", "Pigs")))
    assert problems == "Row 1 is missing this column: Pigs. The columns it needs are: Catchment Name, Beef Population, Pigs."
    data = workbook(("One", [("Catchment Name",)]), ("Two", [("Pigs",)]))
    assert "None of the sheets has every column it needs" in problems_with(
        lambda: read_sheet(data, "file.xlsx", None, ("Catchment Name", "Pigs")))


def test_reads_older_excel_workbooks():
    rows = read_sheet(LOOKUP_FILE.read_bytes(), "Waterbody Lookup.xls", "Waterbody Lookup", ("WBID", "FARMS"))
    assert [r.cells for r in rows][:1] == [{"WBID": "GB108050014050", "FARMS": 24.0}]
    assert rows[2].cells == {"WBID": "GB108050014470", "FARMS": None}  # an empty cell
    assert "This isn't an older Excel workbook (.xls)" in problems_with(lambda: read_sheet(b"no", "file.xls", None, ("WBID",)))


def test_reads_excel_workbooks_and_csv_files_only():
    rows = read_sheet("Catchment Name,Pigs\r\nAbbey River,248\r\n".encode("utf-8-sig"), "file.csv", None, ("Catchment Name", "Pigs"))
    assert [r.cells for r in rows] == [{"Catchment Name": "Abbey River", "Pigs": "248"}]
    assert "file.ods isn't a kind of file that can be read here" in problems_with(lambda: read_sheet(b"x", "file.ods", None, ("Pigs",)))
    assert "This isn't an Excel workbook (.xlsx)" in problems_with(lambda: read_sheet(b"not excel", "file.xlsx", None, ("Pigs",)))


# --- APHA's livestock data ---------------------------------------------------------

def test_apha_livestock_works_out_the_originals_figures(database):
    result = run(database, apha_file(ABBEY_ROW, BADGWORTHY_ROW, ("Somewhere Else",) + ABBEY_ROW[1:]))
    livestock = {(r.values["catchment_id"], r.values["livestock"]): r for r in result.tables["livestock"]}
    assert len(livestock) == 10  # five kinds in each of the two catchments
    beef = livestock[ABBEY, "Beef cattle"]
    assert beef.line == 2  # the row in the file it's from
    assert beef.values == {"catchment_id": ABBEY, "livestock": "Beef cattle", "number": 635, "number_note": None,
                           "density": pytest.approx(37.370168369051974), "density_rating": "Medium"}
    ratings = {kind: livestock[ABBEY, kind].values["density_rating"] for kind in ["Dairy cattle", "Pigs", "Sheep", "Poultry"]}
    assert ratings == {"Dairy cattle": "Medium", "Pigs": "Low", "Sheep": "Low", "Poultry": "Low"}  # 73.3, 14.6, 57.3, 907.6
    # Blank: 0, as the original showed.
    assert livestock[BADGWORTHY, "Poultry"].values == {"catchment_id": BADGWORTHY, "livestock": "Poultry", "number": 0,
                                                       "number_note": None, "density": 0.0, "density_rating": "Low"}

    pressure = {r.values["catchment_id"]: r.values for r in result.tables["livestock_pressure"]}
    abbey = pressure[ABBEY]
    beef, dairy, pigs, sheep, poultry = (livestock[ABBEY, kind].values["density"]
                                         for kind in ["Beef cattle", "Dairy cattle", "Pigs", "Sheep", "Poultry"])
    nitrogen = beef * 70 + dairy * 110 + pigs * 20 + sheep * 13 + poultry * 0.6  # the original's Power Query formulas
    phosphate = beef * 13 + dairy * 23 + pigs * 5 + sheep * 3 + poultry * 0.3
    assert (abbey["nitrogen_load"], abbey["phosphate_load"]) == (nitrogen, phosphate)  # to the last digit
    assert abbey["nitrogen_and_phosphate_load"] == nitrogen + phosphate == pytest.approx(14945.35, abs=0.01)
    assert abbey["pressure"] == "Medium"  # above 10,000
    assert pressure[BADGWORTHY]["pressure"] == "Very Low"

    assert result.rows_read == 3
    assert result.notes == [
        "1 row isn't for a catchment in the Catchments table, so it is left out: Somewhere Else.",
        "The file has no row for 1 catchment in the Catchments table: Bray (Mole to Hole Water).",
    ]


def test_apha_keeps_a_range_instead_of_a_number(database):
    row = list(ABBEY_ROW)
    row[APHA_HEADINGS.index("Dairy \nPopulation")] = "Less than 5"
    result = run(database, apha_file(tuple(row)))
    dairy = next(r.values for r in result.tables["livestock"] if r.values["livestock"] == "Dairy cattle")
    assert (dairy["number"], dairy["number_note"], dairy["density"]) == (None, "Less than 5", pytest.approx(73.26907026688143))


@pytest.mark.parametrize("density, rating", [(80, "Medium"), (80.01, "High"), (30, "Low"), (30.5, "Medium")])
def test_density_ratings_are_above_their_bands(density, rating):
    beef = apha_livestock.ANIMALS[0]
    row = inputs.SourceRow(2, {beef.number: 1, beef.density: density}, catchment_id=ABBEY)
    livestock = apha_livestock.work_out([row], [], [])["livestock"]
    assert livestock[0].values["density_rating"] == rating


@pytest.mark.parametrize("load, pressure", [(40000, "High"), (40000.5, "Very High"), (5000, "Very Low"), (5001, "Low")])
def test_livestock_pressure_is_above_its_bands(load, pressure):
    assert banded(load, apha_livestock.PRESSURE, apha_livestock.LOWEST_PRESSURE) == pressure


def test_apha_problems_are_listed(database):
    bad = list(ABBEY_ROW)
    bad[APHA_HEADINGS.index("Pig Density Per SqKm")] = "lots"
    problems = problems_with(lambda: run(database, apha_file(tuple(bad), ABBEY_ROW)))
    assert "Rows 2 and 3 are both for Abbey River. Each can only appear once." in problems
    data = apha_file(tuple(bad))
    assert "Row 2, Pig Density Per SqKm: 'lots' isn't a number." in problems_with(lambda: run(database, data))
    assert "Row 1 is missing" in problems_with(lambda: run(database, workbook(("Sheet", [("Catchment Name", "Pigs")]))))


# --- Waterbody Lookup -------------------------------------------------------------

def test_waterbody_lookup_works_out_the_originals_figures(database):
    result = run(database, LOOKUP_FILE.read_bytes(), "Waterbody Lookup.xls", source=LOOKUP)
    tables = {name: {r.values["catchment_id"]: r.values for r in rows} for name, rows in result.tables.items()}
    assert tables["catchment_rankings"] == {ABBEY: {"catchment_id": ABBEY, "ranking": 44},
                                            BADGWORTHY: {"catchment_id": BADGWORTHY, "ranking": 79},
                                            BRAY: {"catchment_id": BRAY, "ranking": 1}}
    assert {i: row["number_of_farms"] for i, row in tables["farms"].items()} == {ABBEY: 24, BADGWORTHY: 2}  # Bray's is blank
    abbey = tables["sewerage_properties"][ABBEY]
    assert (abbey["public_sewerage_properties"], abbey["private_sewerage_properties"]) == (526, 610)
    assert abbey["private_sewerage_per_ha"] == 610 / (16981213.366974927 / 10_000) == pytest.approx(0.3592, abs=1e-4)
    assert abbey["private_sewerage_rating"] == "High"  # below 1, not below 0.3
    assert tables["sewerage_properties"][BADGWORTHY]["private_sewerage_rating"] == "Very Low"  # 0.014
    assert tables["ecological_classes"][ABBEY] == {"catchment_id": ABBEY, "year": 2025, "ecological_class": "Moderate"}
    assert tables["river_information"][ABBEY] == {
        "catchment_id": ABBEY, "catchment_area_ha": pytest.approx(1698.12, abs=0.01), "river_length_km": pytest.approx(9.6045),
        "river_system": "Coastal", "upstream_rivers": "None", "downstream_rivers": "Sea",
    }
    # Matched by ID: the waterbody that isn't one of ours is left out.
    assert result.notes == ["1 row isn't for a catchment in the Catchments table, so it is left out: GB000000000000."]


@pytest.mark.parametrize("per_ha, rating", [(0.0, "Very Low"), (0.1, "Low"), (0.149, "Low"), (0.15, "Medium"), (0.99, "High"), (1.0, "Very High")])
def test_private_sewerage_rating_is_below_its_bands(per_ha, rating):
    assert waterbody_lookup.private_rating(per_ha) == rating


# --- ESME ---------------------------------------------------------------------------

ESME_HEADINGS = "FID,WB_CAT,MNCAT_NAME,WB_ID,WB_NAME,aa,aa_r1,aa_r2,iv,iv_r17,wf,wf_r24,ws,ws_r27,wq,wq_r10"


def esme_file(*rows: str) -> bytes:
    return ("\r\n".join([ESME_HEADINGS, *rows]) + "\r\n").encode("utf-8-sig")  # as ESME exports it


def test_esme_works_out_five_risk_levels(database):
    data = esme_file(
        f"2715,River,North Devon,{ABBEY},Abbey River,Category,3,x,Category,One species,Category,2,Category,5,Category,Shaded",
        f"2716,River,North Devon,{BADGWORTHY},Badgworthy Water,Category,1,x,Category,No,Category,3,Category,4,Category,No shade",
        "2717,River,Elsewhere,GB000000000000,Not ours,Category,5,x,Category,No,Category,5,Category,5,Category,Shaded",
    )
    result = run(database, data, "ESME_River_water_bodies_Phase_4_-8564305916099105313.csv", source=ESME)
    rows = {r.values["catchment_id"]: r.values for r in result.tables["esme_risk_levels"]}
    assert rows[ABBEY] == {
        "catchment_id": ABBEY,
        "habitat_quality": 3, "modification": "Medium",
        "runoff_and_infiltration": 2, "runoff": "High",
        "abstraction_sustainability": 5, "running_dry": "Very Low",
        "invasive_species_found": "One species", "invasive_species": "High",
        "river_shade": "Shaded", "overheating": "Low",  # the original's formula says "shaded": the case doesn't matter
    }
    assert [rows[BADGWORTHY][k] for k in ["modification", "runoff", "running_dry", "invasive_species", "overheating"]] == \
        ["Very High", "Medium", "Low", "Low", "High"]
    assert result.notes == [
        "1 row isn't for a catchment in the Catchments table, so it is left out: GB000000000000.",
        "The file has no row for 1 catchment in the Catchments table: Bray (Mole to Hole Water).",
    ]


def test_esme_values_the_original_doesnt_know_leave_the_tile_empty(database):
    data = esme_file(f"1,River,North Devon,{ABBEY},Abbey River,Category,6,x,Category,Species present,Category,2,Category,5,Category,")
    result = run(database, data, "esme.csv", source=ESME)
    (row,) = [r.values for r in result.tables["esme_risk_levels"]]
    assert (row["habitat_quality"], row["modification"]) == (6, None)
    assert (row["invasive_species_found"], row["invasive_species"]) == ("Species present", None)
    assert (row["river_shade"], row["overheating"]) == (None, None)  # blank: no note, as there's nothing to know
    assert result.notes[1:] == [  # after the one about the catchments with no row
        "aa_r1 (R1 River Habitat Quality Index) has 6, which the original's formula doesn't know, so the Modification tile is left empty there.",
        "iv_r17 (R17 Invasive non-native species) has Species present, which the original's formula doesn't know, so the "
        "Invasive Species tile is left empty there.",
    ]
    bad = esme_file(f"1,River,North Devon,{ABBEY},Abbey River,Category,high,x,Category,No,Category,2,Category,5,Category,Shaded")
    assert "Row 2, aa_r1: 'high' isn't a score from 1 to 5." in problems_with(lambda: run(database, bad, "esme.csv", source=ESME))


# --- Natural England habitats -------------------------------------------------------

def habitat_file(*rows: tuple) -> bytes:
    lines = ["water_body_name,Simplified_Habitat_Type,FREQUENCY,SUM_SHAPE_Area"] + [",".join(map(str, row)) for row in rows]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8-sig")


def test_habitat_works_out_each_share_and_coverage(database):
    data = habitat_file(
        ("Abbey River", "Farmland", 1, "10824429.229850200936198"),  # Abbey River's rows in the real file
        ("Abbey River", "Not Farmed", 1, "1290257.577390282182023"),
        ("Abbey River", "Urban", 1, "682494.707142735947855"),
        ("Abbey River", "Wetland", 1, "2265831.573840452823788"),
        ("Abbey River", "Woodland", 1, "1918200.0"),
        ("Badgworthy Water", "Woodland", 1, "1000000"), ("Badgworthy Water", "Woodland", 2, "1000000"),  # twice: added up
        ("Badgworthy Water", "Bog", 1, "2000000"),
    )
    result = run(database, data, "Nat Eng Simplified Habitat.csv", source=HABITAT)
    rows = {(r.values["catchment_id"], r.values["habitat"]): r.values for r in result.tables["habitat_land_use"]}
    total = (10824429.229850200936198 + 1290257.577390282182023 + 682494.707142735947855 + 2265831.573840452823788 + 1918200.0) / 10_000
    farmland = rows[ABBEY, "Farmland"]
    assert farmland["area_ha"] == pytest.approx(1082.4429)
    assert farmland["percent_of_catchment"] == pytest.approx(100 * 1082.4429 / total)  # of the habitat areas: 63.7%
    assert farmland["relative_coverage"] == "High"  # 60% or more
    assert sum(r["percent_of_catchment"] for (c, _), r in rows.items() if c == ABBEY) == pytest.approx(100)
    assert rows[ABBEY, "Wetland"]["relative_coverage"] == "Medium"  # 13.3%: 5% or more, under 20%
    assert rows[BADGWORTHY, "Woodland"]["area_ha"] == 200  # added up
    assert (rows[BADGWORTHY, "Bog"]["percent_of_catchment"], rows[BADGWORTHY, "Bog"]["relative_coverage"]) == (50.0, None)
    assert "Bog isn't a habitat the original's formula gives a relative coverage for, so it's left empty." in result.notes


@pytest.mark.parametrize("name, share, level", [
    ("Farmland", 0.60, "High"), ("Farmland", 0.5999, "Medium"), ("Farmland", 0.39, "Low"),
    ("not farmed", 0.08, "Medium"), ("Urban", 0.06, "High"), ("Urban", 0.029, "Low"), ("Woodland", 0.1, "Medium"),
])
def test_relative_coverage_is_at_or_above_its_bands(name, share, level):
    assert habitat.coverage(name, share) == level


# --- Improvement Information --------------------------------------------------------

IMPROVEMENT_HEADINGS = (
    "Catchment", "EA_Area", "WBID", "WATER_BODY", "Why general statement", "Why bullet 1", "Why bullet 2", "Why bullet 3",
    "What general statement", "What bullet 1", "What bullet 2", "What bullet 3", "What bullet 4", "Intervention Hypothesis",
    "Confidence", "Projects bullet 1", "Projects bullet 2", "Projects bullet 3", "Projects bullet 4",
)


def improvement_row(wbid, name, why="", why_bullets=(), what="", what_bullets=(), hypothesis="", confidence=None, projects=()):
    def four(bullets, n):
        return list(bullets) + [None] * (n - len(bullets))
    return ("North Devon", "Devon and Cornwall", wbid, name, why, *four(why_bullets, 3), what, *four(what_bullets, 4),
            hypothesis, confidence, *four(projects, 4))


def test_improvement_information_puts_each_statement_with_its_bullets(database):
    data = workbook(("Improvement Information", [
        IMPROVEMENT_HEADINGS,
        improvement_row(ABBEY, "Abbey River", why="Abbey River is at Moderate. \nThe failing elements are phosphate. ",
                        what="Current activity includes farm visits.", hypothesis="Nutrient enrichment.",
                        confidence="(confidence: High)"),
        improvement_row(BADGWORTHY, "Badgworthy Water", why="Fish are poor.", why_bullets=(" Barriers ", "", "Mine water"),
                        what=None, hypothesis=None, confidence=None, projects=("Fish pass",)),
    ]))
    result = run(database, data, "Improvement Information.xlsx", source=IMPROVEMENT)
    rows = {r.values["catchment_id"]: r.values for r in result.tables["river_status_text"]}
    assert rows[ABBEY] == {
        "catchment_id": ABBEY,
        "why_failing": "Abbey River is at Moderate.\nThe failing elements are phosphate.",  # trimmed, lines and all
        "happening_now": "Current activity includes farm visits.",
        "intervention_hypothesis": "Nutrient enrichment.",
        "hypothesis_confidence": "High",  # the dashboard adds "(confidence: …)" back
    }
    assert rows[BADGWORTHY] == {
        "catchment_id": BADGWORTHY,
        "why_failing": "Fish are poor.\n- Barriers\n- Mine water",  # the empty bullet left out
        "happening_now": None,
        "intervention_hypothesis": "- Fish pass",  # bullets with no statement
        "hypothesis_confidence": None,
    }


@pytest.mark.parametrize("typed, shown", [("(confidence: High)", "High"), ("(Confidence:Med-High )", "Med-High"),
                                           ("Medium", "Medium"), ("", None)])
def test_the_confidence_is_kept_without_its_brackets(typed, shown):
    assert improvement_information.confidence(typed) == shown


# --- SAGIS phosphate (two sheets) -------------------------------------------------

SAGIS_HEADINGS = ("Management catchment", "Waterbody ID", "Waterbody name", "Source", "% contribution at end of AMP7 (2025)",
                  "% contribution at end of AMP8 (2030)", "Change")


def sagis_file(breakdown, split, split_name="Phosphate Point vs Diffuse"):
    return workbook((split_name, [SAGIS_HEADINGS, *split]),  # in the original's order
                    ("Phosphate Source breakdown", [SAGIS_HEADINGS + (None, None), *breakdown]))


def test_sagis_fills_both_tables_from_their_sheets(database):
    data = sagis_file(
        breakdown=[("North Devon", ABBEY, "Abbey River", "STW (SWW)", 35.877, 30.5, -5.377, None, None),
                   ("North Devon", ABBEY, "Abbey River", "Livestock", 44.194, 44.194, 0, None, None),
                   ("North Devon", BADGWORTHY, "Badgworthy Water", "Arable", 0, None, None, None, None)],
        split=[("North Devon", ABBEY, "Abbey River", "Diffuse", 64.008, 64.008, 0),
               ("North Devon", ABBEY, "Abbey River", "Continuous", 35.992, 35.992, 0)],
    )
    result = run(database, data, "SAGIS Phosphate source.xlsx", source=SAGIS)
    sources = {(r.values["catchment_id"], r.values["source"], r.values["year"]): r.values["percent"] for r in result.tables["phosphate_sources"]}
    assert sources == {
        (ABBEY, "STW (SWW)", 2025): 35.877, (ABBEY, "STW (SWW)", 2030): 30.5,
        (ABBEY, "Livestock", 2025): 44.194, (ABBEY, "Livestock", 2030): 44.194,
        (BADGWORTHY, "Arable", 2025): 0,  # 2030 is blank: no row
    }
    split = {(r.values["source"], r.values["year"]): r.values["percent"] for r in result.tables["phosphate_point_diffuse"]}
    assert split == {("Diffuse", 2025): 64.008, ("Diffuse", 2030): 64.008, ("Continuous", 2025): 35.992, ("Continuous", 2030): 35.992}
    assert result.rows_read == 5  # both sheets


def test_sagis_needs_both_sheets_by_name(database):
    data = sagis_file(breakdown=[], split=[], split_name="Point and diffuse")
    assert "The workbook has no sheet called Phosphate Point vs Diffuse. Its sheets are: Point and diffuse, Phosphate Source breakdown." \
        in problems_with(lambda: run(database, data, "sagis.xlsx", source=SAGIS))
    twice = sagis_file(breakdown=[], split=[("North Devon", ABBEY, "Abbey River", "Diffuse", 1, "lots", 0),
                                          ("North Devon", ABBEY, "Abbey River", "diffuse", 2, 2, 0)])
    problems = problems_with(lambda: run(database, twice, "sagis.xlsx", source=SAGIS))
    assert "Phosphate Point vs Diffuse, row 2, % contribution at end of AMP8 (2030): 'lots' isn't a number." in problems
    assert "Phosphate Point vs Diffuse: rows 2 and 3 are both for diffuse in the same waterbody." in problems


def test_several_sheets_are_read_from_one_opening_of_the_file():
    data = workbook(("A", [("WBID", "x"), ("GB1", 1)]), ("B", [("WBID", "y"), ("GB2", 2)]))
    a, b = read_sheets(data, "file.xlsx", [("A", ("WBID", "x")), ("B", ("WBID", "y"))], by_name=True)
    assert [(r.sheet, r.where, r.cells) for r in a + b] == [("A", "A, row 2", {"WBID": "GB1", "x": 1}), ("B", "B, row 2", {"WBID": "GB2", "y": 2})]
    assert "The sheet B's row 1 is missing this column: z." in problems_with(
        lambda: read_sheets(data, "file.xlsx", [("A", ("WBID",)), ("B", ("WBID", "z"))], by_name=True))


# --- Water UK's storm overflow plans ------------------------------------------------

PLAN_HEADINGS = ("Unique ID", "Water company", "EA site name", "Management Catchment", "Water Body", "Spill improvements planned?",
                 "Rainfall Improvement Target Delivery Year", "Improvements List",
                 "Predicted average annual spill frequency following scheme implementation where applicable")


def test_water_company_plans_keep_a_row_per_overflow(database):
    data = workbook(("Water Company Asset Plans", [
        PLAN_HEADINGS,
        ("SWW0562", "South West Water", "OKEHAMPTON STW", "North Devon", "Abbey River", 2035, "Y", "Increased pass forward flow", 6),
        ("SWW0563", "South West Water", "OKEHAMPTON STW", "North Devon", "Abbey River", 2035, "Y", "Storage", 10),
        ("SWW0001", "South West Water", "HIGH BICKINGTON STW", "North Devon", "Abbey River", "Y", 2030, "Storage", None),  # the right way round
        ("SWW0002", "South West Water", "HARTLAND STW", "North Devon", "Not part of a river WB catchment", 2035, "Y", "Storage", 10),
        ("ANH0001", "Anglian Water", "SOMEWHERE STW", "Welland", "Tove (US Greens Norton)", 2040, None, "Storage", 10),
    ]))
    result = run(database, data, "National Plan Data - updated.xlsx", source=PLANS)
    rows = {r.values["site_name"]: r.values for r in result.tables["sewerage_improvements"]}
    assert rows["OKEHAMPTON STW (SWW0562)"] == {"catchment_id": ABBEY, "site_name": "OKEHAMPTON STW (SWW0562)",
                                                "improvements": "Increased pass forward flow", "completion_year": 2035,
                                                "predicted_spills_per_year": 6}
    assert rows["OKEHAMPTON STW (SWW0563)"]["predicted_spills_per_year"] == 10  # its own row, not added to the other
    assert rows["HIGH BICKINGTON STW"]["completion_year"] == 2030  # one overflow: no ID; the year under its own heading
    assert set(rows) == {"OKEHAMPTON STW (SWW0562)", "OKEHAMPTON STW (SWW0563)", "HIGH BICKINGTON STW"}
    assert result.notes[0] == ("2 rows aren't for a catchment in the Catchments table, so they are left out: "
                               "Not part of a river WB catchment, Tove (US Greens Norton).")


# --- The EA's classification facts --------------------------------------------------

FACT_HEADINGS = ("WATERBODY_ID", "WATERBODY_NAME", "CAL_YEAR", "CLASS_ITEM_NAME", "SET_TYPE_NAME", "FACT_NAME", "FACT_CODE", "FACTVALUE")


def fact(wbid, year, item, fact_name, value, code=None, set_type="Site"):
    return (wbid, "", year, item, set_type, fact_name, code, value)


def test_classification_facts_work_out_the_values_and_thresholds(database):
    data = workbook(("WFD Class Boundaries Ref", [("x",)]), ("Classification Data", [
        FACT_HEADINGS,
        fact(ABBEY, 2025, "Fish", "EQR", "0.5054"), fact(ABBEY, 2025, "FISH", "eqr", "0.4556"),  # the case doesn't matter
        fact(ABBEY, 2016, "Fish", "EQR", "n/a"),  # not a number: left out
        fact(ABBEY, 2013, "Fish", "EQR", "0.9"),  # not a year the page shows
        fact(ABBEY, 2022, "Invertebrates", "NTAXA EQR", "0.7", code="NTAXA_EQR"),
        fact(ABBEY, 2022, "Invertebrates", "NTAXA EQR", "0.9", code="NTAXA_EQR"),
        fact(ABBEY, 2022, "Invertebrates", "NTAXA EQR", "0.1", code="NTAXA_EQR", set_type="Water body"),  # not a site's
        fact(ABBEY, 2019, "Phosphate", "Phosphate", "0.0465"),
        *[fact(ABBEY, 2022, "Phosphate", "Phosphate", v) for v in ("0.05", "0.06", "0.07", "0.08")],
        fact(ABBEY, 2019, "Phosphate", "Good/Moderate Boundary - mg/l", "0.04"),  # an earlier year's boundary
        fact(ABBEY, 2022, "Phosphate", "Good/Moderate Boundary - mg/l", "0.047"),
        fact(ABBEY, 2022, "Phosphate", "Good/Moderate Boundary - mg/l", "0.048"),  # two in a year: the largest
        fact(ABBEY, 2022, "Phosphate", "High/Good Boundary - mg/l", "0.03"),
        fact(ABBEY, 2022, "Phosphate", "Moderate/Poor Boundary - mg/l", "0.1"),
        fact(ABBEY, 2022, "Phosphate", "Poor/Bad Boundary - mg/l", "0.5"),
        fact(BADGWORTHY, 2022, "Fish", "EQR", "0.1"),
    ]))
    result = run(database, data, "North Devon WB Classification Facts Data.xlsx", source=FACTS)
    scores = {(r.values["catchment_id"], r.values["measure"], r.values["year"]): (r.values["value"], r.values["status"])
              for r in result.tables["ea_scores"]}
    assert scores == {
        (ABBEY, "Fish (EQR)", 2025): (0.481, "Good"),  # the average, 0.4805, rounded with halves up
        (ABBEY, "Inverts NTAXA (EQR)", 2022): (0.8, "Good"),  # not above High's 0.8
        (ABBEY, "Phosphate (mg/l)", 2019): (0.047, "Good"),  # below Good's 0.048
        (ABBEY, "Phosphate (mg/l)", 2022): (0.065, "Moderate"),  # the median
        (BADGWORTHY, "Fish (EQR)", 2022): (0.1, "Poor"),
    }
    thresholds = {(r.values["catchment_id"], r.values["measure"]): tuple(r.values[k] for k in ("high", "good", "moderate", "poor"))
                  for r in result.tables["ea_thresholds"]}
    assert thresholds[ABBEY, "Phosphate (mg/l)"] == (0.03, 0.048, 0.1, 0.5)  # the latest year's
    assert thresholds[BADGWORTHY, "Fish (EQR)"] == (0.7, 0.4, 0.2, 0.03)  # fixed
    assert thresholds[BADGWORTHY, "Inverts ASPT (EQR)"] == (0.97, 0.86, 0.72, 0.59)  # for every waterbody in the file
    assert (BADGWORTHY, "Phosphate (mg/l)") not in thresholds  # it has no boundaries


@pytest.mark.parametrize("rule, value, status", [
    ("at_or_above", 0.4, "Good"), ("at_or_above", 0.0299, "Bad"),  # higher is better: Fish
    ("above", 0.4, "Moderate"), ("above", 0.03, "Bad"),
    ("above_no_bad", 0.01, "Poor"), ("above_no_bad", 0.21, "Moderate"),
])
def test_a_values_status_follows_the_originals_colours(rule, value, status):
    limits = {"high": 0.7, "good": 0.4, "moderate": 0.2, "poor": 0.03}
    assert ea_classification_facts.RULES[rule](value, limits) == status


@pytest.mark.parametrize("value, status", [(0.01, "High"), (0.04, "Moderate"), (0.3, "Poor"), (0.5, "Bad")])
def test_lower_is_better_for_ammonia_phosphate_temperature_and_ph_upper(value, status):
    limits = {"high": 0.02, "good": 0.04, "moderate": 0.1, "poor": 0.5}
    assert ea_classification_facts.RULES["below"](value, limits) == status


@pytest.mark.parametrize("value, decimals, shown", [(0.4805, 3, 0.481), (0.0465, 3, 0.047), (89.685, 2, 89.69), (0.4804, 3, 0.48)])
def test_values_are_rounded_with_halves_up(value, decimals, shown):
    assert ea_classification_facts.rounded(value, decimals) == shown


def test_inputs_and_schema_yaml_agree():
    assert inputs.check(SCHEMA) == []
    assert set(SCHEMA.input_tables.values()) == set(inputs.INPUTS)  # every input is used
    for source in inputs.INPUTS.values():
        assert source.tables and set(source.tables) <= set(SCHEMA.metadata.tables)


def test_every_column_says_how_its_worked_out():
    for source in inputs.INPUTS.values():
        headings = set(source.headings) | {h for more in source.more_sheets.values() for h in more}
        titles = {SCHEMA.metadata.tables[t].info["title"] for t in source.tables}
        for table in source.tables:
            columns = [c.name for c in SCHEMA.metadata.tables[table].columns]
            steps = source.table_steps(table)
            assert {c for step in steps for c in step.columns} == set(columns), table  # each column, and only those
            for step in steps:
                assert step.text.endswith(".") and step.power_bi, (table, step.columns)
                # Each input is one of the file's columns, a column worked out before, or another of its tables.
                for name in step.inputs:
                    assert name in headings or name in columns or name in titles, (table, step.columns, name)
            assert source.file_columns(table), table
