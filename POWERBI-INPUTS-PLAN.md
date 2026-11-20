# Source files: the admin page as the Power BI dashboard has it

**Agreed with Tom, 18 November 2026. All nine steps were built that day.** What's left is under "Open
points" at the end.

Tom asked for the admin page to follow the original Power BI dashboard
(`Reference/ReferenceData/Waterbody Scorecards/Waterbody Scorecard Dashboard v9.pbix`):

- **On the left**, the files the Power BI read (mostly in `Source data/`), uploaded as they came
- **The transformation** is the Power BI's own Power Query steps and DAX formulas
- **The tables** stay much as they are, with more, narrower tables where a file's formulas need them

His answers (18 November 2026):

1. **Keep the importers.** Tables downloaded from the original source (catchments, EA classifications and
   RNAGs, storm overflows, river obstacles, postcodes) stay as they are, rather than uploading the Power BI's
   downloaded copies of the same data.
2. **Only files that feed today's dashboard.** Files the Power BI read for panels we don't have are left out
   (see the end).
3. **Each file fills only its own tables.** Risk Levels is split by the file each risk comes from, and put
   back together when the dashboard is published. Uploading one file can never change another file's data.
4. **Match the Power BI's ecological status,** worked out with its own rules (including Coney Gut, Taw Estuary
   and Venn always Moderate), not the EA's official status.

Fixed numbers (bands, multipliers) live in each file's code and are shown on the admin page in words made
from the same numbers.

---

## How it works (built in step 1)

- `backend/catalyst/importers/inputs/`: one module per source file (`apha_livestock.py` is the example).
  Each says the sheet and column headings it reads, how it matches rows to catchments, its formulas, and
  its steps in words, each with where it is in the Power BI file ("In Power BI: …").
- `schema.yaml`: the tables it fills say `filled_by: input` and `input: <its name>`.
- The admin page: each source file is a purple box on the left ("Source file", **Upload file**), and its
  tables are on the right. Its upload panel says which sheet and columns it needs.
- **One transformation per table** (Tom, 18 November 2026: "1 transformation per table and make it clear the
  inputs and the function"): each table has its own box in the Transformation column ("Power BI's formulas,
  6 columns in, 5 steps"). Its panel shows the **inputs** (the file, sheet and columns it reads), the
  **function** (a step for each of the table's columns: which columns it fills, from which inputs, how, and
  where that is in the Power BI file), and the **table**. Each input's steps (`Step(columns, inputs, text,
  power_bi)`) must cover every column of its tables (a test checks). The importers' tables show what they
  download (`input`, `inputs` in `diagram.yaml`) and their steps; Excel tables, 1 to 1.
- An upload is previewed table by table, then approved all at once. `uploads.uploaded_to` is the source
  file's name, and `uploads.changes` keeps each table's counts.
- The file is read by its headings (any order; case, spaces and line breaks don't matter), from the named
  sheet, or the first sheet with the headings if it's been renamed. Rows are matched to catchments by
  waterbody name; anything else is left out and listed in the preview.
- Reads `.xlsx`, `.xls` (with `xlrd`, added in step 2) and `.csv`. Rows are matched by waterbody name, or by
  the EA's waterbody ID where the file has one (`by_id`).

---

## The steps

| # | Source file (`Source data/…`) | Power BI query | Tables | Status |
|---|---|---|---|---|
| 1 | `APHA Livestock Data/APHA Livestock Data Feb 2026.xlsx` | APHA Livestock Data | `livestock`, new `livestock_pressure` (the Livestock tile) | **Built 18 Nov 2026** |
| 2 | `Waterbody Lookup/Waterbody Lookup.xls` | Waterbody Lookup | `catchment_rankings`, `farms`, `sewerage_properties` (+ private sewerage per ha and its rating: the Sewage (Private) tile), new `ecological_classes` (2025), new `river_information` | **Built 18 Nov 2026**; the five merged into one, `waterbody_figures`, 20 Nov 2026 |
| 3 | `ESME/ESME_River_water_bodies_Phase_4_….csv` | ESME_River_water_bodies_Phase_4_-8564305916099105313 | new `esme_risk_levels` (Runoff, Modification, Invasive Species, Overheating, Running Dry tiles) | **Built 18 Nov 2026** |
| 4 | (storm overflows importer, kept) | EDM 2021 to 2025 … Biosphere area | new `sewage_overflow_pressure` (the Untreated Sewage tile); `risk_levels` gone | **Built 18 Nov 2026** |
| 5 | `Habitats/Nat Eng Simplified Habitat.csv` | Nat Eng Simplified Habitat | `habitat_land_use` (+ `percent_of_catchment`) | **Built 18 Nov 2026** |
| 6 | `Improvement Information/Improvement Information.xlsx` | Improvement Information | `river_status_text` | Built 18 Nov 2026, **undone 20 Nov 2026** (an Excel table again) |
| 7 | `EA Phosphate data/SAGIS Phosphate source.xlsx` | Phosphate Source breakdown, Phosphate Point vs Diffuse | `phosphate_sources`, new `phosphate_point_diffuse` | **Built 18 Nov 2026** |
| 8 | `SWW Asset Upgrades/National Plan Data - updated.xlsx` | Water Company Asset Plans | `sewerage_improvements` | **Built 18 Nov 2026** |
| 9 | `EA WFD Data/North Devon WB Classification Facts Data.xlsx` | EA Classification Data | `ea_scores`, `ea_thresholds` | **Built 18 Nov 2026** |

### 1. APHA livestock (built)

- Blank densities are 0 (Power Query step Custom1). Numbers as APHA gives them, 0 where blank; a range
  such as "Less than 5" is kept in `number_note` (only Burcombe Stream's dairy cattle).
- Density: APHA's own per km² figure (before, it was worked out from our catchment area).
- Density rating (DAX columns): beef High > 80, Medium > 30; dairy 100 / 40; pigs 100 / 30; sheep 300 / 100;
  poultry 5,000 / 1,000; otherwise Low.
- Nitrogen load = beef density × 70 + dairy × 110 + pigs × 20 + sheep × 13 + poultry × 0.6; phosphate
  load = × 13, 23, 5, 3, 0.3; pressure from their total: Very High > 40,000, High > 20,000, Medium > 10,000,
  Low > 5,000, otherwise Very Low.
- Checked against the data before: all 92 waterbodies had the same numbers, ratings and Livestock risk.

### 2. Waterbody Lookup (built)

**Since 20 November 2026** the tables named below (`catchment_rankings`, `farms`, `sewerage_properties`,
`ecological_classes` and `river_information`) are one table, `waterbody_figures`, with a row per waterbody
(a blank figure, e.g. Upper East Lyn River's farms, is left empty rather than the row left out). The rest
of this step is as it was built.

- Ranking: `Biosphere Ranking` as typed (worked out outside the Power BI, in `EA Standardised Scoring/`).
- Farms: `FARMS` (blank for Upper East Lyn River, so no row, as before). Properties: `SWW Sewerage`,
  `Private Sewerage`.
- Private sewerage per ha = Private Sewerage ÷ (Shape_Area ÷ 10,000) (the lookup's own area, Power Query
  and DAX column); rating: Very Low < 0.1, Low < 0.15, Medium < 0.3, High < 1.0, otherwise Very High. Within
  0.003 of the old figure (worked out from our catchment area).
- Matched by `WBID`.
- **Ecological class (Tom, 18 November 2026: "Maybe we better use the 2025 data"):** `ecological_class` is
  the EA's 2025 class, the same as the EA's own 2025 file for all 92. It goes in `ecological_classes` (year
  2025) and, as on the Power BI, colours the maps, gives 2025 in the EA Ecological Classification box (2019
  and 2022 still from the EA's classifications) and the Catchment Dashboard's class counts. 7 of the 92
  differ from 2022. Failing elements still come from the EA's latest year with element results (2022).
  When the EA's Catchment Data Explorer has 2025 (planned December 2026), `ecological_classes` still wins
  for 2025.
- Checked against the data before: rankings, farms, properties and the Sewage (Private) rating were the same
  for all 92.
- **River Information (added 18 November 2026, after step 4):** the Land Use Data page's River Information
  box now shows the lookup's catchment area, river length, river system (back again) and upstream and
  downstream rivers, as on the Power BI, in `river_information`. The rivers are typed as names: each that's
  one of the location's catchments links to its page; the rest show as typed. Six names don't match because
  of their spelling in the lookup ("Middle River Okemont", "Lower River Okemont", "West Okemont", "Wooleigh
  Brook", "Upper Little Dart", "Taw (Little Dart to River Mole)"): correcting them in the lookup makes them
  links. A catchment with no row shows the EA's figures, as before.

### 3. ESME (built)

- Matched by `WB_ID`. Runoff `wf_r24`, Modification `aa_r1`, Running Dry `ws_r27`: 5 Very Low, 4 Low,
  3 Medium, 2 High, 1 Very High. Invasive Species `iv_r17`: No → Low, One species → High. Overheating
  `wq_r10`: no shade → High, medium shade → Medium, shaded → Low.
- The file says "Shaded", "Medium shade" and "No shade": DAX ignores case, so this does too.
- `esme_risk_levels` keeps ESME's value beside each level (e.g. habitat quality 3, Modification Medium).
  A value the original's formulas don't know leaves the tile empty, as the original did, and the preview
  says so.
- Checked against the data before: all five levels were the same for all 92. `risk_levels` now has only
  Untreated Sewage (step 4).

### 4. Untreated Sewage (built)

- Power BI: each waterbody's total 2025 spill duration: Very High > 1,440 hours (5,184,000 s), High > 720,
  Medium > 240, Low > 120, otherwise Very Low. A waterbody with no overflows is 0 hours, Very Low.
- The storm overflows importer is kept (answer 1), so `importer storm-overflows` works this out into
  `sewage_overflow_pressure`, replaced with Storm Overflows. It uses the latest year of the returns (2025 now),
  where the Power BI named 2025.
- Checked against the Power BI's file: the same hours for 90 of 92. The Power BI matched overflows by
  waterbody **name**, and the water company typed two of them differently ("MOLE", "TIDAL TORRIDGE") with
  the right waterbody ID, so it missed Alswear No 1 STW (Mole (Bray to Yeo), 67 hours) and Frithelstock Stone
  STW (Langtree Lake, 8 hours). The importer matches by ID, so it has them. Only one level changes: Mole (Bray
  to Yeo) is Medium (281 hours) where the Power BI said Low (214).
- `risk_levels` has gone. Its "i" text stays in Datasets under `risk_levels`, which the publish step now
  treats as the Risk Levels panel's name (`INFO_PANELS` in `publish/collect.py`).

### 5. Habitat (built)

- Area (ha) = SUM_SHAPE_Area ÷ 10,000. % of catchment = area ÷ the waterbody's total habitat area (not
  our catchment area), stored as `percent_of_catchment`. Relative coverage: Farmland High ≥ 60%, Medium ≥ 40%;
  Not Farmed 40 / 8; Urban 6 / 3; Wetland 20 / 5; Woodland 20 / 10; otherwise Low. Matched by
  `water_body_name`, with a row per habitat (`one_row_each=False`).
- The Catchment Dashboard's shares are each habitat's area over all the chosen catchments' habitat areas, as
  the Power BI's Catchment Summaries page did.
- Checked against the data before: every relative coverage the same for all 459 rows. Areas now keep every
  decimal (they were rounded to 2), and the % of catchment moves by at most 0.1 of a point.

### 6. Improvement Information (built, then undone)

**Undone 20 November 2026** (Tom): the North Devon Biosphere writes it, so it isn't a source file. River Status
Text is an Excel table again, uploaded 1 to 1 (PROGRESS.md). What follows is how it was read until then.


- Why = "Why general statement" and bullets 1–3; What = "What general statement" and bullets 1–4;
  hypothesis = "Intervention Hypothesis" and "Projects bullet" 1–4; confidence. Blank bullets left out (as
  the DAX measures do). Matched by `WBID`.
- Each statement and its bullets become one text, the bullets as "- " lines, which the dashboard shows as a
  list. Spaces at the ends of lines are trimmed (invisible on the page).
- Confidence is typed "(confidence: High)"; the table keeps "High", and the dashboard's heading puts it back
  as "Intervention hypothesis (confidence: High)", as the Power BI showed it.
- Checked against the data before: identical for all 92 (no file has any bullets yet), so uploading it
  says there's nothing to change.

### 7. SAGIS phosphate (built)

- Breakdown sheet: each source's % at the end of AMP7 (2025) and AMP8 (2030), into `phosphate_sources` (a row
  per year, as before; its `discharge` column, our own Continuous / Diffuse label for each source, has gone).
- Point vs Diffuse sheet: the EA's own Continuous / Diffuse figures, into `phosphate_point_diffuse`, for the
  Sewerage Data page's Source of Phosphate (adding up the sources only matched for 81 of 91). Matched by
  `Waterbody ID`.
- The first input with two sheets: they have the same columns, so each is read by its exact name
  (`more_sheets`), and a renamed sheet is reported rather than guessed.
- Checked against the data before: the same 1,456 source percentages (401 differ in the last of 16 digits,
  lost by the earlier load). Continuous changes by over 0.5 points in 10 waterbodies, most for Mole (Source to
  Burcombe Stream), 43.0% → 73.5%, and Bradiford Water, 0.5% → 25.1%. Bradwell Stream isn't in SAGIS.

### 8. Water company asset plans (built)

- National file (14,187 rows, read in about 2 seconds): rows whose `Water Body` is one of our catchments, by
  name as the Power BI did (all 150 are in North Devon; 24 more there say "Not part of a river WB catchment").
  Site, improvements list, year, predicted spills.
- **The file's headings are swapped:** "Spill improvements planned?" holds the year and "Rainfall Improvement
  Target Delivery Year" holds Y or blank. The Power BI showed the first, as the year; so does this, and it uses
  the other if a later file puts a year there.
- **One difference, on purpose:** the Power BI's table added up rows with the same site and improvements list,
  so two overflows at one works showed as one row with their predicted spills and years added together (e.g.
  4070). Here each overflow keeps its row, named with Water UK's ID where a site has several (12 sites), as the
  data was before.
- Checked against the data before: identical (150 rows), so uploading it says there's nothing to change.

### 9. EA classification facts (built)

- From the "Classification Data" sheet (96,402 rows; about 14 seconds to read, so each preview and approval
  takes that long). Matched by `WATERBODY_ID`.
- Values for 2016, 2019, 2022 and 2025 (the years the Power BI's EA Data page shows): biology EQRs are the
  average of the year's facts (Fish, Inverts NTAXA and ASPT site facts, Macrophytes and Phytobenthos
  MEAN_EQR_SITE), physico-chemistry the median (ammonia, DO, phosphate, temperature, pH lower and upper).
  Rounded as shown (3 decimal places, 2 for DO, temperature and pH) with halves up, as Power BI shows them.
- Thresholds: fixed for biology (e.g. Fish 0.7, 0.4, 0.2, 0.03); for physico-chemistry, the latest year's
  High/Good … Poor/Bad Boundary facts.
- Each value's status from its thresholds, by the Power BI's colour rules (EAColour…): Fish "at or above";
  the invertebrate EQRs, DO and pH Lower "above"; macrophytes and phytobenthos "above", never Bad; ammonia,
  phosphate, temperature and pH Upper "below" (lower is better). **Changed 19 November 2026** (BUG-REPORT.md,
  C8): macrophytes and phytobenthos are now plain "above", so they can be Bad, as the other EQRs can. No value
  in today's data is low enough for this to change anything.
- Checked against the data before (from the Power BI's own exports): the same 1,704 values, 1,012 thresholds
  and every status, except 10 values 0.001 apart, all exact halves the earlier load rounded down (e.g. East
  Okemont River's 2025 Fish EQR, 0.4805: 0.481 now, as Power BI shows 0.0465 as 0.047).
- The EA Data grid's Ecological row now has 2025 from Ecological Classes (the Waterbody Lookup), as the Power
  BI's grid did (its [ClassECO2025]).
- **The grid's status rows stay the EA's own** (EA Classifications), as the Power BI's are for Ecological,
  Biological, Physico-chemical, pH and Hydromorphological in 2016–2022. The Power BI works out a few rows
  itself instead, and those weren't copied: Invertebrates (the worst site's class; its 2022 really shows 2019's,
  so 10 waterbodies differ from the EA's 2022), Macrophytes and Phytobenthos Combined (from the values, with
  fixed bands), and 2025's rows (from the facts, falling back to 2022 where 2025 is missing; Invertebrates 2025
  from the EA's 2025 file). 2025's status rows wait for the EA's December update, like Failing Elements.
- **Answer 4 (Coney Gut, Taw Estuary and Venn always Moderate):** that rule is only in Power BI measures for
  pages we don't have (POMs, Achieving Good), and as a message on its Scorecard (`EAScoringMessage`, five
  waterbodies, e.g. "This is a heavily modified river and the classification is elevated to Moderate"). The grid
  itself uses the EA's statuses. Not added (an open point).

## Open points (18 November 2026)

- **How a single-measure row is coloured on the EA Data grid** (e.g. Fish (EQR) 0.36): ours by the EA's own
  status for the item (as decided on 5 November 2026), the Power BI v9 by the value against its thresholds.
- **The Power BI's message for five waterbodies** on its Scorecard (above): add it to the EA Data page?
- **2025 status rows and Failing Elements:** wait for the EA's December 2026 update, then re-run
  `importer classifications` and publish.
- **Deploying:** none of this is on the test VM yet (see PROGRESS.md, Suggested next steps).

## Other differences found and fixed (18 November 2026)

- **RNAGs:** listed as the Power BI's `RNAG Activity HTML` measure does: "Unknown (pending investigation)" and
  "Other (not in list, …)" are hidden as well as "Not applicable", "Suspect data (Fish)" is added for an
  element whose data the EA suspects, and "None" is shown when there are none (`figures.reasons`).
- **Failing Elements:** the Power BI reads the EA's 2025 classification file, falling back to 2022. Tom
  (18 November 2026): wait for the EA's Catchment Data Explorer update (December 2026), then re-run
  `importer classifications`; Failing Elements then moves to 2025 with no code change. The EA's 2025 file
  isn't used anywhere.

## Staying as they are

- **Importers** (answer 1): `catchments`, `ea_classifications`, `ea_rnags`, `storm_overflows`,
  `river_obstacles`, `postcodes`.
- **Excel, 1 to 1:** `datasets` ("i" texts), `location_text` (one row per location, from several places,
  including the three texts in `Catchment dashboard summaries.xlsx`), and Intervention Management's three
  tables (from its website, not the Power BI).

## Left out (no panel on our dashboard: answer 2)

EA inspections (`EA Regulatory Enforcement.xlsx`), SWW phosphate permit limits, CaSTCo eutrophication risk,
the EA's programmes of measures (`RNAG POM.xlsx`), the WFD 2025 classifications file, the older
`Interventions table.xlsx`, per-operational-catchment summaries, the live SWW storm overflow feed, Main
pressure, and the ninth risk (SWW Treated Sewage). Any can be added later as an input, once it has a panel.
