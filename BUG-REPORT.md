# Bug report: Catchment Catalyst's code

**Reviewed 19 November 2026**, at commit `2ba0836` (Adding screenshots). Everything in `backend/` was read:
the schema tool, the importers (API, Excel and source files), the admin page, the publish step, its
templates and scripts, and the Docker setup. Where a finding is about data, it was checked against the
local database and the files in `imports/raw/` and `Reference/ReferenceData/`. The tests all pass (264).

The technical methods (the Power BI's formulas, the EA's rules) are taken as right. This report is about
whether they're applied correctly, and about the code itself. The Power BI's own errors are in
[POWERBI-BUG-REPORT.md](POWERBI-BUG-REPORT.md); where our code copies one, both reports say so.

**How to use this:** work down the list one at a time. For each, decide (fix, leave, or change the plan),
then change its **Status** in the table and add a line under it saying what was done and when.

| Severity | Meaning |
|---|---|
| **Medium** | Wrong or misleading on the dashboard or admin page now, or a risk on the live server |
| **Low** | Only in unusual cases, or only once something changes (more locations, a new file layout) |
| **Nit** | Tidying: wording, formatting, documentation |

Nothing found is **High** (wrong figures shown widely to the public).

---

## Summary

| # | Severity | What | Status |
|---|---|---|---|
| [C1](#c1) | Medium | Failing Elements lists different items from the Power BI for 4 waterbodies | Fixed |
| [C2](#c2) | Medium | "Everything approved is on it" can be wrong if an approval and a publish overlap | Fixed |
| [C3](#c3) | Medium | No limit on login attempts on the live admin page | Fixed |
| [C4](#c4) | Medium | Spill durations typed as text (e.g. "02:30:00") are read as "no figure" | Fixed |
| [C5](#c5) | Low | Spill durations stored as a date-time are 24 hours too high (none in today's files) | Fixed |
| [C6](#c6) | Low | Water UK's plans are matched by waterbody name across England | Fixed |
| [C7](#c7) | Low | The EA says two waterbodies' phosphate should be Good; the dashboard shows Moderate with no note | Waiting (Biosphere) |
| [C8](#c8) | Low | Macrophytes and Phytobenthos values can never show as Bad (copied from the Power BI) | Fixed |
| [C9](#c9) | Low | Two overflows with the same site name are added together and counted once | Fixed |
| [C10](#c10) | Low | Some mistakes in a source file are skipped quietly instead of being listed | Fixed |
| [C11](#c11) | Low | A river obstacle on two outlines can go to either catchment | Fixed |
| [C12](#c12) | Low | A connection dropped mid-download stops an importer with a Python error | Fixed |
| [C13](#c13) | Nit | Whole numbers have no thousands separator (54478, not 54,478) | Fixed |
| [C14](#c14) | Nit | Small things: date in UTC, numbered lists, formulas in downloads, map tooltip | Fixed |
| [C15](#c15) | Nit | Out-of-date statements in PROGRESS.md and diagram.yaml | Fixed |

---

## Medium

### C1

**Failing Elements lists different items from the Power BI for 4 waterbodies.**

- **Where:** `backend/catalyst/publish/figures.py:115-120` (`BELOW_GOOD`, `FAILING_LEVELS`) and `:315-329`
  (`failing_elements`).
- **What's wrong:** ours lists every EA *element* or *sub element* below Good in the latest year. The Power
  BI's Failing Elements (its `Failing Parameters 2025 precedence over 2022 HTML` measure) lists only ten
  items: Fish, Invertebrates, Macrophytes sub element, Phytobenthos sub element, Ammonia (Phys-Chem),
  Dissolved Oxygen, Phosphate, pH, Specific pollutants and Temperature. "Specific pollutants" is a
  *component* in the EA's data, so ours never lists it, but lists its single chemicals instead; and ours
  counts "Moderate or less" and "Does Not Support Good", which the Power BI's list doesn't include.
- **Evidence** (EA's 2022 results in the local database):

  | Waterbody | Ours lists | The Power BI lists |
  |---|---|---|
  | Venn | Manganese, Zinc | Specific pollutants |
  | Coney Gut | Mitigation Measures Assessment | (not listed) |
  | Taw Estuary | Mitigation Measures Assessment | (not listed) |
  | West Okement | Hydrological Regime | (not listed) |

  Every other waterbody's 2022 list is the same. (The Power BI also uses 2025 where the EA's 2025 file
  has it: that's the known difference, waiting for the EA's December update.) PROGRESS.md says ours
  "reproduces the original exactly", but that was only checked for Langham Lake.
- **Fix:** list only the Power BI's ten items (by the EA's item name, ignoring case), as the plan is to
  follow the Power BI. Or, if ours is preferred, say so in PROGRESS.md and POWERBI-INPUTS-PLAN.md.
  **Decision needed.**

- **Status:** **Fixed, 19 November 2026** (Tom: match the Power BI). `failing_elements` lists only the Power BI's ten items
  (ignoring case), when Moderate, Poor or Bad, and the panel says "None" when there are none, as the Power BI's
  does. Checked on the local data: Venn now lists Specific pollutants; Coney Gut, Taw Estuary and West Okement no
  longer list Mitigation Measures Assessment or Hydrological Regime; Langham Lake is unchanged. PROGRESS.md updated.

### C2

**"Everything approved is on it" can be wrong if an approval and a publish overlap.**

- **Where:** `backend/catalyst/admin/uploads.py:93-98` (`approved_at = now()`),
  `backend/catalyst/publish/run.py:114-127`, `backend/catalyst/admin/app.py:227-238` (the Publish box).
- **What's wrong:** in PostgreSQL, `now()` is when a transaction *started*, not when it finished. An
  approval can take a while (the EA classification facts take about 14 seconds to read and compare). If
  Publish is pressed while an approval is still running, the publish reads the tables before the approval
  is saved, but records a `published_at` later than the approval's `approved_at`. The Publish box then
  counts the upload as published ("Everything approved is on it") when it isn't on the dashboard. A
  publish can also read a source file's tables part-way through being approved (one table before, another
  after), since each query sees whatever's been saved by then.
- **How likely:** low, but it only needs one person with the admin page open in two tabs, or two people.
- **Fix:** make an approval take the same lock as Publish (`pg_advisory_xact_lock(7316001)`, `LOCK` in
  `run.py`) at its start, so the two never overlap. A small change in `approve` in `app.py`.

- **Status:** **Fixed, 19 November 2026.** An approval now takes the publish lock first (`publish.run.lock`), so the two never
  overlap, and both record their time once they have the lock (`clock_timestamp()`, not `now()`). Test:
  `test_an_approval_waits_for_a_publish_and_is_timed_after_it`.

### C3

**No limit on login attempts on the live admin page.**

- **Where:** `backend/catalyst/admin/app.py:116-123` (`log_in`).
- **What's wrong:** the admin page is on the internet behind the front door
  (rivers.smartbiosphere.com/admin, once the DNS record is in). Each wrong password is slowed a little by
  scrypt, but nothing stops someone guessing for days. Passwords of 12 or more characters make it unlikely
  to succeed, but there's no warning or slowing down either.
- **Fix:** after, say, 5 wrong passwords for a name or from one address in 15 minutes, refuse for 15
  minutes (kept in memory in the app: there's one admin container). Or fail2ban on the VM reading the
  front door's log. Worth doing before the address goes live.

- **Status:** **Fixed, 19 November 2026.** After 5 wrong passwords from one address or for one name in 15 minutes, that
  address or name waits until the first is 15 minutes old (even the right password is refused meanwhile), with
  "Too many wrong passwords. Try again in N minutes." Kept in memory (`passwords.Attempts`).
  `docker-compose.front-door.yml` sets `FORWARDED_ALLOW_IPS: "*"` so the address is the visitor's (from Caddy's
  X-Forwarded-For), not the front door's for everyone. Needs `docker compose up -d --build` on the VM.

### C4

**Spill durations typed as text (e.g. "02:30:00") are read as "no figure".**

- **Where:** `backend/catalyst/importers/api/storm_overflows.py:163-179` (`hours`).
- **What's wrong:** from 2024 the EA's returns give durations as hh:mm:ss. Most are proper Excel times,
  which `hours()` reads; but some companies typed them as text, and `hours()` only reads text that's a
  plain number. `hours("02:30:00")` and `hours("123:45:00")` both give None ("no figure").
- **Evidence:** the 2025 return has 1,450 such text cells, all in Anglian Water's sheet (e.g.
  "00:15:00"). South West Water's are all proper times, so **North Devon is not affected today**. Another
  location (or South West Water changing how it fills the form) would lose those overflows' hours, and
  with them the Untreated Sewage tile.
- **Fix:** in `hours()`, read text of the form `H:MM:SS` (any number of hours) as hours, as the Power BI's
  `Annual Spill Duration (seconds)` column does. Add a test.

- **Status:** **Fixed, 19 November 2026.** `hours()` reads text of the form H:MM:SS (any number of hours), as the Power BI's
  column does. Tests added. North Devon's figures don't change (South West Water's are proper times).

---

## Low

### C5

**Spill durations stored as a date-time are 24 hours too high (none in today's files).**

- **Where:** `backend/catalyst/importers/api/storm_overflows.py:172-173`.
- **What's wrong:** a duration of more than a day, in a cell formatted as a date and time rather than as
  `[h]:mm:ss`, comes from openpyxl as a date in 1900. Excel counts 1900 as a leap year by mistake, so
  openpyxl adds a day to dates before 1 March 1900, and subtracting 30 December 1899 then gives 24 hours
  too many for any duration between 1 and 60 days.
- **Evidence:** `hours(from_excel(1.5))` gives 60 hours; it should be 36. Today's returns have no such
  cells (they're times, durations or numbers), so nothing is wrong yet.
- **Fix:** use openpyxl's `to_excel(value) * 24` for a date-time, which undoes the same adjustment.

- **Status:** **Fixed, 19 November 2026.** A date-time is turned back with openpyxl's `to_excel(value) * 24`. The test that
  expected 54 hours for 1 January 1900 06:00 (Excel's 1.25 days) now expects 30.

### C6

**Water UK's plans are matched by waterbody name across England.**

- **Where:** `backend/catalyst/importers/inputs/water_company_plans.py:265-275` (matched by `Water Body`,
  by name), using `inputs/common.py:311-352`.
- **What's wrong:** the national file has 14,187 overflows. Waterbody names aren't unique in England, so a
  waterbody elsewhere with the same name as one of ours would have its overflows added to ours. The Power
  BI matches by name the same way.
- **Evidence:** checked: all 150 rows matched today are in North Devon's management catchment, so
  **nothing is wrong now**. It matters once the catchments table has more than one area.
- **Fix:** also check the row's `Management Catchment` (or `River Basin District`) against the catchment's.

- **Status:** **Fixed, 19 November 2026.** Source files can name a management catchment column (`area_heading`); Water UK's
  plans use its Management Catchment, so a row only matches a waterbody of that name in the same management
  catchment (or one whose management catchment isn't known). Rows left out this way are listed in the preview.

### C7

**The EA says two waterbodies' phosphate should be Good; the dashboard shows Moderate with no note.**

- **Where:** data, shown by the EA Data page (`ea_scores`, `figures.scoring`).
- **What's wrong:** the Power BI's Scorecard shows a message for Lower River Lew (Torridge) and Upper River
  Mere: "The EA has confirmed that Phosphate should be at Good status. We will update this table ASAP"
  (its `EAScoringMessage` measure). Ours shows Lower River Lew's 2025 phosphate, 0.065 mg/l, as Moderate
  (Good is below 0.040), with no note. The same measure has notes for Venn, Coney Gut and Taw Estuary.
- **Status of the decision:** already an open point in POWERBI-INPUTS-PLAN.md ("The Power BI's message for
  five waterbodies"). Listed here so it isn't forgotten: it's the one place the dashboard shows a figure
  its own source says is wrong.
- **Fix:** ask the North Devon Biosphere whether the EA has corrected it. If not, either add a short note
  (e.g. a column in River Status Text) or leave it.

- **Status:** **Waiting, 19 November 2026** (Tom: leave it and ask the Biosphere). No code change. Ask the North Devon
  Biosphere whether the EA has corrected Lower River Lew's and Upper River Mere's phosphate.

### C8

**Macrophytes and Phytobenthos values can never show as Bad (copied from the Power BI).**

- **Where:** `backend/catalyst/importers/inputs/ea_classification_facts.py:49` (`above_no_bad`) and `:96-101`.
- **What's wrong:** this copies the Power BI's colour rule, which colours everything at or below the
  Moderate threshold orange (Poor), so a value below the Poor/Bad threshold (0.2) is Poor rather than Bad.
  The other EQRs (Fish, invertebrates) do have Bad. See POWERBI-BUG-REPORT.md, P11.
- **Evidence:** no Macrophytes or Phytobenthos value in the database is 0.2 or below, so **nothing is
  shown wrongly today**.
- **Fix:** decide whether to keep matching the Power BI. If not, use the `above` rule for these two.

- **Status:** **Fixed, 19 November 2026** (Tom: allow Bad). Macrophytes and Phytobenthos use the `above` rule, so a value at
  or below 0.2 is Bad; `above_no_bad` is gone. Nothing in today's data changes. POWERBI-INPUTS-PLAN.md updated.

### C9

**Two overflows with the same site name are added together and counted once.**

- **Where:** `backend/catalyst/publish/figures.py:383-389` (`discharges`) and `:565-571` (`overflow_count`).
- **What's wrong:** the Sewerage Data page's table has a row per *site name*, and the Catchment Dashboard
  counts site names. Two different overflows with the same name in the same year are added into one row,
  and counted as one.
- **Evidence:** WEST STREET SPS_PSCSOEO_SOUTH MOLTON (2021 and 2022) and MIDDLE MARWOOD STW_SSO_MARWOOD
  (2021 to 2024) each have two overflows with the same name. 2025 (the year the count uses) has none, so
  the count is right today; the table's earlier years add the two together. The Power BI does the same
  (its table groups by site name).
- **Fix:** if wanted, show each separately, named with its `unique_id` or permit reference where a name
  repeats (as Sewerage Improvements does with Water UK's ID), and count by `unique_id`.

- **Status:** **Fixed, 19 November 2026** (Tom: show each separately). The return's IDs can't link years (none before 2023, a
  new format in 2024), so outlets are told apart by their grid reference: where one name has outlets in different
  places in a year, each has its own row, e.g. MIDDLE MARWOOD STW_SSO_MARWOOD (SS 5331 3739) and (SS 5332 3739), and
  counts once (`figures.overflows`). WEST STREET SPS_PSCSOEO_SOUTH MOLTON's two rows in 2021 and 2022 have the same
  name, place, permit and activity, so can't be told apart and are still added together (in 2021 they're identical,
  34.98 hours and 24 spills each, so may be one overflow listed twice: worth asking the EA). The 2025 count is
  unchanged (152).

### C10

**Some mistakes in a source file are skipped quietly instead of being listed.**

- **Where:**
  - `backend/catalyst/importers/inputs/waterbody_lookup.py:201-209` and `inputs/common.py:393-406`
    (`count`): text in Biosphere Ranking, FARMS, SWW Sewerage or Private Sewerage (e.g. "N/A" or "6 8")
    gives no value, with no note, so the waterbody silently has no ranking or farm count.
  - `waterbody_lookup.py:223-225`: `ecological_class` isn't checked. A typo such as "moderate" or
    "Moderat" would colour the map grey, and appear as its own row in the Catchment Dashboard's counts
    (`figures.py:548-557` compares exactly).
  - `inputs/ea_classification_facts.py:143`: a CAL_YEAR that isn't a number stops the upload with an
    error page (500) rather than a listed problem.
- **Evidence:** none of today's files has these mistakes.
- **Fix:** list each in the preview's problems (or notes), as the other inputs do.

- **Status:** **Fixed, 19 November 2026.** Text in Biosphere Ranking, FARMS, SWW Sewerage or Private Sewerage is left
  empty with a note in the preview (e.g. "Row 5, FARMS: 'N/A' isn't a number, so it's left empty."); an
  ecological class that isn't High, Good, Moderate, Poor or Bad (any case) is a problem, and " moderate " is stored
  as Moderate; a CAL_YEAR that isn't a year is a problem, not an error page.

### C11

**A river obstacle on two outlines can go to either catchment.**

- **Where:** `backend/catalyst/importers/api/river_obstacles.py:87-89` (`place`).
- **What's wrong:** an obstacle inside two outlines (where they overlap slightly) goes to whichever the
  database returns last, which can change from one import to the next. The postcodes importer handles the
  same case by taking the first catchment by ID. Also, a point exactly on an outline is in neither
  (`ST_Contains`), so it's left out.
- **Fix:** order by catchment ID and keep the first, as `postcodes.place` does; consider `ST_Intersects`.

- **Status:** **Fixed, 19 November 2026.** Ordered by catchment ID, keeping the first, as postcodes do, and `ST_Intersects`, so
  a point exactly on an outline is kept.

### C12

**A connection dropped mid-download stops an importer with a Python error.**

- **Where:** `backend/catalyst/importers/api/ea_api.py:130-141` and `importers/api/postcodes.py:159-168`.
- **What's wrong:** the retries catch HTTP errors, timeouts and unreachable servers, but not a connection
  dropped part-way through a download (`ConnectionResetError`, `http.client.IncompleteRead`). Those stop
  the importer with a Python traceback instead of retrying, or saying "Nothing has been imported: …".
  Nothing is saved, so no harm is done, but the message is unhelpful.
- **Fix:** also catch `OSError` and `http.client.HTTPException` in the retry loop.

- **Status:** **Fixed, 19 November 2026.** Both retry loops also catch `OSError` and `http.client.HTTPException`, and say "the
  download from the EA stopped part-way" (or Ordnance Survey). Tests added.

---

## Nits

### C13

**Whole numbers have no thousands separator (54478, not 54,478).**

- **Where:** `backend/catalyst/publish/site.py:263-269` (`_number` without decimals uses `repr`), shown by
  `templates/catchment-dashboard.html:79-82`, `templates/sewerage.html:60-61` and `templates/land-use.html:84`.
- **Evidence:** the published Catchment Dashboard shows "Number of Farms: 4263", "Properties on South West
  Water sewerage: 54478" and "Properties on private sewerage: 66604". The Power BI shows these as `#,##0`
  (54,478), and our own decimals already have separators.
- **Fix:** format whole numbers with `{:,}`.

- **Status:** **Fixed, 19 November 2026.** Whole numbers are written with `{:,}` (54,478). Shows on the dashboard after the
  next publish.

### C14

**Small things.**

- **The publish date is in UTC** (`site.py:109` and `:308-310` use the container's date). Between midnight
  and 1 am in summer, "Published 19 November 2026" says the day before.
- **A line starting with a number and a full stop becomes a numbered list** (`text.py:171-173`: the
  `list` rule covers numbered lists too, which the documented marks don't mention). No text in the
  database has such a line today, but one starting "2030. The plan…" would be turned into a list starting
  at 2030.
- **A downloaded table's text that starts with "=" is written as a formula** (`importers/excel/workbook.py:101-102`).
  Re-uploaded, it would come back empty; opened in Excel, it would run as a formula. No such text today.
- **The big map's tooltips treat a catchment's name as HTML** (`publish/static/map.js:49`), while the small
  maps use plain text (`points.js:139-143`). The names come from the EA, so it's only a tidiness point.
- **The publish command always notes `north-devon-ideas`** as "isn't a current location's folder"
  (`publish/__main__.py:73-76`). Harmless, but it'll be printed on every publish until the ideas are moved.

- **Status:** **Fixed, 19 November 2026.** All five: the publish date (and the footer's year) is the UK's; a line starting
  with a number and a full stop or bracket isn't a numbered list; a downloaded cell starting with "=" is written as
  text (with Excel's quote prefix); the big map's tooltips are plain text; the publish command only mentions a
  folder it wrote (one with `catchments.geojson`), so `north-devon-ideas` isn't mentioned.

### C15

**Out-of-date statements in PROGRESS.md and diagram.yaml.**

These predate the source files (18 November) and could mislead a later session:

- `PROGRESS.md:45`: the Source files row lists only APHA, the Waterbody Lookup and ESME ("the plan lists
  the rest"); all eight are built.
- `PROGRESS.md:158-159`: "`filled_by` ... `api` ... or `excel`" and "An upload is an exact copy of the
  table" (source files are neither).
- `PROGRESS.md:179`: figures.py works out "livestock densities, the phosphate split, sewerage per ha", and
  "Ranking and Relative Coverage are typed in". All now come from the source files.
- `PROGRESS.md:259-265`: "Worked out, not stored: livestock density (number per 100 ha of the
  catchment), % of catchment, private sewerage per ha, the Continuous / Diffuse split"; "Typed in until
  their rules are agreed: ranking, risk levels, relative coverage and density rating"; "Risk levels are one
  column per risk (eight)" (the Risk Levels table has gone).
- `PROGRESS.md:242-244`: "152 for North Devon, against 167 on the original, because overflows with no
  waterbody ID are left out". The Power BI actually counts every site name in five years of returns
  (POWERBI-BUG-REPORT.md, P6); its 2025 count would be 150.
- `backend/catalyst/admin/diagram.yaml:31-35` and `:151-153`: Uploads is "a record of every Excel file
  uploaded here"; it now records source files too.

- **Status:** **Fixed, 19 November 2026.** The PROGRESS.md statements listed and `diagram.yaml`'s Uploads text are updated.

---

## Checked and found right

So it's clear what was covered, these were checked closely and found to be right:

- **The schema tool** (`db/`): reading `schema.yaml`, the checks on data and Excel tables, renames, changes
  of primary key, all-or-nothing apply, and refusing to lose data without `--allow-data-loss`.
- **Excel uploads** (`importers/excel/`): reading by headings, type checks, duplicate keys, missing links,
  the comparison, the fingerprint that stops an out-of-date approval, and replacing rows in one transaction.
- **The eight source files against the Power BI's formulas**, line by line:
  - APHA: blanks as 0, the density bands (all "above"), the nitrogen and phosphate weights, added up in
    the Power BI's order, and the pressure bands
  - Waterbody Lookup: area ÷ 10,000, length ÷ 1,000, private sewerage per ha and its bands (all "below")
  - ESME: the five mappings (scores 5 to 1, and the text ignoring case)
  - Habitat: m² ÷ 10,000, share of the waterbody's habitat total, and its bands ("at or above")
  - Improvement Information, SAGIS, and Water UK's swapped headings
  - EA classification facts: which facts each measure averages or takes the median of, the latest year's
    boundaries, the fixed biology thresholds, halves rounded up, and each colour rule's direction
- **Untreated Sewage:** 1,440, 720, 240 and 120 hours are exactly the Power BI's 5,184,000, 2,592,000,
  864,000 and 432,000 seconds, all "above".
- **The grid reference conversion** (letters to eastings and northings), and the postcode importer and search.
- **The admin login:** scrypt hashes, the same time for an unknown name, a signed cookie that's never sent
  from other sites (which also stops forged form posts), and logging out anyone removed from `ADMIN_USERS`.
- **Safety of shown text:** every page escapes what was typed; the Markdown marks can't make a script link;
  the admin page's diagram puts everything in as plain text.
- **Publishing:** collected before anything is written, the new folder swapped in, one at a time (the lock),
  and the `?v=` fingerprints.
- **The Docker setup:** live passwords have no defaults, ports are local only, HTTPS-only cookies behind the
  front door, and logs are capped.
