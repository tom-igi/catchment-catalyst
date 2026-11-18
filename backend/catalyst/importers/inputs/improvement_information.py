"""Improvement Information: River Status Text.

The hand-written analysis of each waterbody on the River Status page
(Improvement Information.xlsx), written by the North Devon Biosphere: why the
river is failing, what is happening now, and the intervention hypothesis with
its confidence. Each is a general statement and up to three or four bullets.
The original Power BI dashboard's DAX measures (Why, What and Hypothesis) put
each statement together with its bullets, leaving out empty ones.

Here a statement and its bullets become one text, the bullets as lines starting
with "- ", which the dashboard shows as a list (as it does for any text).
"""

from __future__ import annotations

import re

from catalyst.importers.excel import FileRow

from .common import Input, SourceRow, Step

ID = "WBID"
CONFIDENCE = "Confidence"
CONFIDENCE_RE = re.compile(r"^\(\s*confidence:\s*(.*?)\s*\)$", re.IGNORECASE)  # how it's typed: (confidence: High)
TEXTS = {  # the table's column -> (the statement's column, the bullets' columns), as in the original's measures
    "why_failing": ("Why general statement", ("Why bullet 1", "Why bullet 2", "Why bullet 3")),
    "happening_now": ("What general statement", ("What bullet 1", "What bullet 2", "What bullet 3", "What bullet 4")),
    "intervention_hypothesis": (
        "Intervention Hypothesis", ("Projects bullet 1", "Projects bullet 2", "Projects bullet 3", "Projects bullet 4"),
    ),
}


def _cell(row: SourceRow, heading: str) -> str:
    """A cell's text, trimmed (the original's TRIM()), and without spaces at the end of its lines (Alt+Enter)."""
    value = row.cells.get(heading)
    if value is None:
        return ""
    return "\n".join(line.rstrip() for line in str(value).splitlines()).strip()


def text(row: SourceRow, statement: str, bullets: tuple[str, ...]) -> str | None:
    """The statement, then each bullet that has text as a line starting with "- ". None if there's nothing."""
    lines = [_cell(row, statement)] if _cell(row, statement) else []
    lines += [f"- {_cell(row, bullet)}" for bullet in bullets if _cell(row, bullet)]
    return "\n".join(lines) or None


def confidence(typed: str) -> str | None:
    """The confidence without the "(confidence: …)" it's typed in, which the dashboard adds back."""
    if not typed:
        return None
    match = CONFIDENCE_RE.match(typed)
    return match.group(1) if match else typed


def work_out(rows: list[SourceRow], problems: list[str], notes: list[str]) -> dict[str, list[FileRow]]:
    texts = []
    for row in rows:
        values = {"catchment_id": row.catchment_id}
        for column, (statement, bullets) in TEXTS.items():
            values[column] = text(row, statement, bullets)
        values["hypothesis_confidence"] = confidence(_cell(row, CONFIDENCE))
        texts.append(FileRow(row.line, values))
    return {"river_status_text": texts}


def _bullets(bullets: tuple[str, ...]) -> str:
    """e.g. Why bullets 1 to 3."""
    return f"{bullets[0].rsplit(' ', 1)[0]}s 1 to {len(bullets)}" if len(bullets) > 1 else bullets[0]


IMPROVEMENT_INFORMATION = Input(
    name="improvement_information",
    title="Improvement Information",
    provider="The North Devon Biosphere, who write the analysis of each waterbody",
    file="Improvement Information.xlsx",
    sheet="Improvement Information",
    headings=(ID, CONFIDENCE, *(h for statement, bullets in TEXTS.values() for h in (statement, *bullets))),
    waterbody_heading=ID,
    by_id=True,
    query="Improvement Information",
    match="Relationship Improvement Information[WATER_BODY] to WeightofEvidenceEutroph_Clip[WATER_BODY], which is "
          "joined to Waterbody Lookup by name",
    steps={"river_status_text": (
        Step(
            ("why_failing",), (TEXTS["why_failing"][0], *TEXTS["why_failing"][1]),
            f"\"Why is the river failing?\": the statement, then {_bullets(TEXTS['why_failing'][1])} as a list, leaving "
            "out empty bullets.",
            "DAX measure Improvement Information[Why]",
        ),
        Step(
            ("happening_now",), (TEXTS["happening_now"][0], *TEXTS["happening_now"][1]),
            f"\"What is happening now?\": the statement, then {_bullets(TEXTS['happening_now'][1])} as a list, "
            "leaving out empty bullets.",
            "DAX measure Improvement Information[What]",
        ),
        Step(
            ("intervention_hypothesis",), (TEXTS["intervention_hypothesis"][0], *TEXTS["intervention_hypothesis"][1]),
            f"The hypothesis, then {_bullets(TEXTS['intervention_hypothesis'][1])} as a list, leaving out empty bullets.",
            "DAX measure Improvement Information[Hypothesis]",
        ),
        Step(
            ("hypothesis_confidence",), (CONFIDENCE,),
            "Without the \"(confidence: …)\" it's typed in, e.g. High. The dashboard puts that back after the heading, "
            "as Intervention hypothesis (confidence: High), as the original did.",
            "DAX measure Improvement Information[Hypothesis] (\"Intervention hypothesis \" & Confidence)",
        ),
    )},
    work_out=work_out,
)
