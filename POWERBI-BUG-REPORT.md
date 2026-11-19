# Bug report: the original Power BI dashboard

**Reviewed 19 November 2026:** `Reference/ReferenceData/Waterbody Scorecards/Waterbody Scorecard Dashboard v9.pbix`.
All of it was read: the 27 Power Query queries, the 42 relationships, the 64 calculated columns, the 284
DAX measures, and the report's 29 pages (which visuals use which fields). Findings were checked against
the data inside the file and against the source files in `Source data/`.

The technical methods (the WFD rules, the bands, the weights) are taken as right. This report is about
mistakes in how they're applied: a formula using the wrong year or column, a visual adding up something
that shouldn't be added, labels that don't match. For each, it says whether our dashboard has the same
problem ("Ours"). Our code's own findings are in [BUG-REPORT.md](BUG-REPORT.md).

**How to use this:** these are for whoever looks after the Power BI (and for us, so we don't copy them).
For each, decide whether to pass it on, fix it there, or leave it, then change its **Status** in the
table and add a line under it saying what was done and when.

| Severity | Meaning |
|---|---|
| **High** | A wrong figure or status on the Scorecard (the main page) now |
| **Medium** | Wrong on another page now, or wrong for some waterbodies |
| **Low** | Only in unusual cases, only once the data changes, or on a test page |
| **Nit** | Tidying: unused or broken measures nothing shows |

The Scorecard and Scorecard EA Data pages are the ones our Waterbody Dashboard copies.

---

## Summary

| # | Severity | What | Ours? | Status |
|---|---|---|---|---|
| [P1](#p1) | High | Invertebrates "2022" shows the 2019 class | No | To do |
| [P2](#p2) | High | Biological quality elements 2025 uses the 2019 invertebrates class | No | To do |
| [P3](#p3) | High | Failing Elements 2025 reads the wrong columns for macrophytes and phytobenthos | No (not yet on 2025) | To do |
| [P4](#p4) | High | The River Obstacles table merges obstacles and adds up their EA IDs | No | To do |
| [P5](#p5) | Medium | Two storm overflows are missed, so one waterbody's Untreated Sewage is too low | No | To do |
| [P6](#p6) | Medium | "SWW sewage outflows" counts five years of overflows, not one | No | To do |
| [P7](#p7) | Medium | Asset Improvement Plans adds two overflows' years together (e.g. 4070) | No | To do |
| [P8](#p8) | Medium | The heavily modified and Venn exceptions differ between years and pages | No (not added) | To do |
| [P9](#p9) | Medium | Eutrophication pressure labels are one step higher than the query's | Not shown | To do |
| [P10](#p10) | Medium | The CSOs page's table adds up years when more than one is selected | No | To do |
| [P11](#p11) | Low | Colour rules: gaps at the boundaries, and statuses with no colour of their own | No (was partly: BUG-REPORT C8, fixed) | To do |
| [P12](#p12) | Low | 2025 hydromorphology says "Good" where the other measures expect "Not High" | No | To do |
| [P13](#p13) | Low | Overflows with no figure show "::" as their duration | No | To do |
| [P14](#p14) | Low | Smaller formula slips (wrong fallback year, missing cycle, blank as Very Low, text maximum) | No | To do |
| [P15](#p15) | Low | The 2025 class counts are England's if the slicer is cleared | No | To do |
| [P16](#p16) | Low | Biosphere Ranking is stored as text, so it sorts 1, 10, 11 … 2 | No | To do |
| [P17](#p17) | Low | The live SWW feed (Map testing page): no paging, and times in UTC | Not shown | To do |
| [P18](#p18) | Low | Many tables are joined by waterbody name, so a spelling change drops data silently | No (by ID) | To do |
| [P19](#p19) | Nit | Broken or unused measures | – | To do |

Also at the end: [questions rather than errors](#questions-rather-than-errors), and
[what was checked and found right](#checked-and-found-right).

---

## High

### P1

**Invertebrates "2022" shows the 2019 class.**

- **Where:** measure `EA Classification Data[Inverts2022]`.
- **What's wrong:** it works out `Worst2022` (the worst site class in 2022), then never uses it: it returns
  `COALESCE(Worst2019, Worst2016)`.
- **Shown on:** the Scorecard and Scorecard EA Data tables' 2022 column (through `[2022]` and
  `[EAColour2022]`), and through `[BQE2022]` → `[ECO2022]` on the Achieving Good, Achieving Moderate, EA
  Data Overview and POMs pages.
- **Evidence:** 10 waterbodies' 2022 Invertebrates differ from the EA's own 2022 class (found when building
  step 9 of POWERBI-INPUTS-PLAN.md).
- **Fix:** return `COALESCE(Worst2022, Worst2019, Worst2016)`, or just `Worst2022` if the column should only
  show 2022.
- **Ours:** shows the EA's own 2022 status.

### P2

**Biological quality elements 2025 uses the 2019 invertebrates class.**

- **Where:** measures `[BQE2025]` and `[Inverts2025DELETE]`.
- **What's wrong:** `[BQE2025]` takes its invertebrates from `[Inverts2025DELETE]`, which has the same
  slip as P1: it works out 2025 and 2022, then returns `COALESCE(Worst2019, Worst2016)`. So the 2025
  biological status uses the 2019 invertebrates. The measure's name suggests it was meant to be deleted,
  but `[BQE2025]` still uses it.
- **Shown on:** the Scorecard's 2025 "Biological quality elements" row and its colour, and the 2025
  ecological class worked out by `[ECO2025]` (Scorecard and POMs). The same table's 2025 "Invertebrates"
  row uses the EA's 2025 file (`[InvertsClass2025]`), so the two rows can disagree.
- **Fix:** use `[InvertsClass2025]`, falling back to the corrected `[Inverts2022]`.
- **Ours:** no 2025 biological status until the EA's own (December 2026).

### P3

**Failing Elements 2025 reads the wrong columns for macrophytes and phytobenthos.**

- **Where:** measure `WFD 2025 Classifications[Failing Parameters 2025 precedence over 2022 HTML]` (and the
  two earlier versions, `Failing Parameters 2025 HTML` and `… 2025 and 2022 HTML`).
- **What's wrong:** "Macrophytes sub element" is read from `MACROALGAE_CLASS` and "Phytobenthos sub
  element" from `PHYTOPLANKTON_BLOOMS_CLASS`. Macroalgae and phytoplankton blooms are other elements
  (mostly for estuaries, coasts and lakes). The 2025 file has no sub elements for rivers; their result is
  `MACROPHYTES_PHYTOBENTHOS_COMBINED_CLASS`.
- **Evidence:** for North Devon's 92 rivers in the 2025 file, `MACROALGAE_CLASS` has 1 value (Moderate) and
  `PHYTOPLANKTON_BLOOMS_CLASS` has 3 (Moderate), while `MACROPHYTES_PHYTOBENTHOS_COMBINED_CLASS` has 86
  (53 Moderate, 1 Poor). So:
  - for 3 waterbodies (Whiteleigh Water, Crooked Oak and Waldon), a phytoplankton or macroalgae result is
    listed as "Phytobenthos sub element" or "Macrophytes sub element"
  - for the rest, the 2025 result is never seen, and 2022's sub element results are shown instead
- **Shown on:** the Scorecard's Failing Elements.
- **Fix:** read "Macrophytes and Phytobenthos Combined" from `MACROPHYTES_PHYTOBENTHOS_COMBINED_CLASS`, and
  let it take precedence over 2022's two sub elements.
- **Ours:** uses the EA's 2022 results until the Catchment Data Explorer has 2025. When it does, it'll read
  the EA's own items, so it won't copy this. (See also BUG-REPORT.md, C1.)

### P4

**The River Obstacles table merges obstacles and adds up their EA IDs.**

- **Where:** the Scorecard's River Obstacles table (a table visual of `Sum(ea_obstructid)`, `site_name`,
  `obstacle_type` and `origin`).
- **What's wrong:** a table visual adds up its number columns over the rows that share the others. Most
  obstacles have no site name, so all the unnamed culverts (say) in a waterbody become one row, and its
  "EA ID" is the sum of their IDs: a number that isn't any obstacle's.
- **Evidence:** 344 of the 423 obstacles are in rows shared with others (88 merged rows). For example,
  Bray (Mole to Hole Water)'s 15 unnamed artificial culverts are one row, and Taw (Source to Bullow
  Brook)'s 11 culverts another.
- **Fix:** set `ea_obstructid` to "Don't summarize" in the visual (or add `globalid`), so each obstacle has
  its own row.
- **Ours:** a row for each obstacle.

---

## Medium

### P5

**Two storm overflows are missed, so one waterbody's Untreated Sewage is too low.**

- **Where:** the relationship `EDM 2021 to 2025 SWW …[WFD Waterbody Catchment Name (discharge outlet)]` →
  `Waterbody Lookup[water_body_name]` (by name).
- **What's wrong:** the water company typed two waterbody names differently ("MOLE" and "TIDAL TORRIDGE",
  each ending in a non-breaking space), though their waterbody IDs are right. Matched by name, they're
  missed.
- **Evidence:** Alswear No 1 STW (Mole (Bray to Yeo), 67 hours in 2025) and Frithelstock Stone STW
  (Langtree Lake, 8 hours). Mole (Bray to Yeo)'s Untreated Sewage tile says Low (214 hours) where it should
  be Medium (281 hours). (Found in step 4 of POWERBI-INPUTS-PLAN.md.)
- **Fix:** relate by `WFD Waterbody ID (discharge outlet)` → `Waterbody Lookup[WBID]` instead.
- **Ours:** matched by ID.

### P6

**"SWW sewage outflows (CSO & STW)" counts five years of overflows, not one.**

- **Where:** measure `[Count of overflows]` (Catchment Summaries page).
- **What's wrong:** it's `DISTINCTCOUNT` of the site names over every return, 2021 to 2025. An overflow
  that was renamed, closed or added in those years is counted as well as its successor.
- **Evidence:** it shows 167 for North Devon: the different site names in all five years' returns.
  Counting only 2025's returns gives 150 (152 with P5's two overflows, which is what ours shows).
  PROGRESS.md puts the difference down to overflows with no waterbody ID, but those aren't counted by
  either.
- **Fix:** count only the latest year's returns (`Annual Return Year = 2025`, or the maximum year).
- **Ours:** counts the latest year (152).

### P7

**Asset Improvement Plans adds two overflows' years together (e.g. 4070).**

- **Where:** the Scorecard's table of `Water Company Asset Plans` (site, improvements list,
  `Sum(Spill improvements planned?)` and the summed predicted spills).
- **What's wrong:** two things.
  - In the source file the headings "Spill improvements planned?" and "Rainfall Improvement Target
    Delivery Year" are the wrong way round, so the table's year comes from a column headed
    "Spill improvements planned?".
  - It's summed: where one works has two or more overflows with the same improvements list (12 sites in
    North Devon have several overflows, e.g. Okehampton STW), they become one row with their years added
    together (e.g. 4070) and their predicted spills added up.
- **Fix:** set both columns to "Don't summarize" and add `Unique ID` (or use `Min` for the year); and ask
  Water UK about the swapped headings, or rename them in Power Query.
- **Ours:** a row per overflow, named with Water UK's ID where a site has several (step 8 of
  POWERBI-INPUTS-PLAN.md).

### P8

**The heavily modified and Venn exceptions differ between years and pages.**

- **Where:** measures `[ECO2025]`, `[ECO2022]`, `[ECO2019]`, `[ECO2016]`, `[LatestECO]`,
  `[Tooltip EA Class table]` and `[EAScoringMessage]`.
- **What's wrong:** the tooltip and the Scorecard's message say Coney Gut and Taw Estuary are raised to
  Moderate and Venn reduced to Moderate. The formulas don't agree with each other:

  | Measure | Coney Gut | Taw Estuary | Venn | Used on |
  |---|---|---|---|---|
  | `[ECO2025]` | Moderate | Moderate | – | Scorecard, POMs |
  | `[ECO2022]` | – | – | – | Achieving Good, Achieving Moderate, EA Data Overview, POMs |
  | `[ECO2019]` | Moderate | Moderate | – | POMs |
  | `[ECO2016]` | – | Moderate | – | (not used, and broken: P19) |
  | `[LatestECO]` | Moderate | Moderate | Moderate | Achieving Good, Achieving Moderate, EA Data Overview |

  They also test the name in two ways: `[ECO2025]` and `[ECO2019]` use `[Selected Waterbody Title]` ("…
  Scorecard", from the classification facts); `[LatestECO]` uses `[DashboardTitleOverview]` (from the
  Waterbody Lookup).
- **Fix:** one measure (or a small table) listing the exceptions, used by all of them.
- **Ours:** none of these exceptions are added (an open point in POWERBI-INPUTS-PLAN.md). Our maps and
  counts use the Waterbody Lookup's 2025 class, which the EA set.

### P9

**Eutrophication pressure labels are one step higher than the query's.**

- **Where:** Power Query `WeightofEvidenceEutroph_Clip`, and the measure `[Eutrophication Pressure]` (POMs page).
- **What's wrong:** the query turns the EA's certainty into a risk level, then a score:
  "Certain no eutrophication problem" → None → 0, "Uncertain" → Low → 1, "Quite certain" → Medium → 2,
  "Very certain" → High → 3. The measure then labels 0 to 3 as Low, Medium, High and Very High. So "certain
  there's no problem" is shown as Low pressure, and "uncertain" as Medium. Its colour for "Very Low" is
  never used.
- **Fix:** decide which labels were meant. If the query's, label 0 to 3 as Very Low (or None), Low, Medium
  and High.
- **Ours:** eutrophication isn't on our dashboard.

### P10

**The CSOs page's table adds up years when more than one is selected.**

- **Where:** the CSOs page's table visual: `Sum(Annual Return Year)`, with the site name, receiving water,
  duration (hh:mm:ss) and investigation text as its other columns, and summed spills and seconds.
- **What's wrong:** the year is summed rather than listed. With more than one year in the page's year
  slicer (or none chosen), a site whose returns have the same duration text and investigation text in
  several years (e.g. 00:00:00 every year) becomes one row, with its year shown as e.g. 4043 (2021 + 2022)
  or 6066, and its spills added up.
- **Evidence:** 46 such rows, covering 102 returns, with all five years shown.
- **Fix:** "Don't summarize" on `Annual Return Year`.
- **Ours:** a column per year.

---

## Low

### P11

**Colour rules: gaps at the boundaries, and statuses with no colour of their own.**

- **Where:** measures `[EAColour2016]`, `[EAColour2019]`, `[EAColour2022]`, `[EAColour2025]` and
  `[EAColourLatest]` (the Scorecard tables' colours).
- **What's wrong:** each has rules for each item, then falls back to "lower is better" comparisons that
  were meant for numbers. Anything the item's rules miss lands there:
  - **"Not Assessed" would be red.** As text compared with a blank threshold, it ends up red. In the file,
    only seven reservoirs' 2016 Hydrological Regime is "Not Assessed", and reservoirs aren't on the
    Scorecard, so nothing shows wrong today.
  - **A value exactly on the Poor/Bad boundary:** dissolved oxygen and pH Lower get blue (High); ammonia
    gets no colour.
  - **pH Upper's red rule repeats `< Poor`**, so it can never apply (red comes from the fallback instead).
  - **Macrophytes and Phytobenthos values are never red:** everything at or below the Moderate threshold is
    orange, so a Bad value (0.2 or below) looks Poor. No value is that low today.
  - **Invertebrates and pH have no colour for Bad, and Physico-chemical none for Poor or Bad**: they fall
    back to red, so Poor shows as red there. None today.
- **Fix:** give each status its own colour explicitly, and end with grey for anything unknown, rather than
  falling back to the number comparisons.
- **Ours:** statuses are coloured by their names, and values by explicit rules, so "Not Assessed" and the
  boundaries are fine. We copied the "never red" macrophytes rule until 19 November 2026, when it was changed
  so they can be Bad: see BUG-REPORT.md, C8.

### P12

**2025 hydromorphology says "Good" where the other measures expect "Not High".**

- **Where:** measures `[HydroMorph2025]`, `[ECO2025]`, `[LatestECO]`, `[EAColour2025]`.
- **What's wrong:** `[HydroMorph2025]` returns "Good" or "High". But `[ECO2025]` and `[LatestECO]` test for
  "Not High" (the EA's word), and `[EAColour2025]` only colours "High" and "Not High" for that row. Once
  there's 2025 hydrology or morphology data:
  - the Scorecard's 2025 hydromorphology cell would say "Good", in red
  - a waterbody with High biology and High physico-chemistry would get a blank 2025 ecological class
- **Evidence:** there's no 2025 hydrology or morphology in the file yet, so it falls back to the EA's 2022
  "Not High" and nothing is wrong today.
- **Fix:** return "Not High" instead of "Good" in `[HydroMorph2025]` (and in `[HydroMorph2022_delete]` and
  `[HydroMorph2019_delete]`, with `[ECO2022]` and `[ECO2019]` testing "Not High" too).

### P13

**Overflows with no figure show "::" as their duration.**

- **Where:** calculated column `EDM …[Annual Spill Duration (hh:mm:ss)]` (CSOs page).
- **What's wrong:** when a return has no duration (e.g. no monitor yet), it formats the blank as "::"
  rather than leaving it empty. Separately, a duration in hours that isn't a whole number of seconds can
  round to ":60" seconds.
- **Evidence:** 73 returns show "::"; one shows ":60".
- **Fix:** return `BLANK()` when there's no duration, and round the seconds before splitting them up.

### P14

**Smaller formula slips.**

- **`[HydroMorph2019_delete]` falls back to 2022** (`[ClassHydroMorph2022]`) instead of 2019, when 2019 has
  no hydrology or morphology. Used by `[ECO2019]` (POMs).
- **`[ClassHydroMorph2019]` doesn't choose cycle 3**, unlike the other 2019 measures (`[ClassECO2019]` and
  so on). 2019 was classified in cycles 2 and 3; today both say "Not High" for every waterbody, so it makes
  no difference yet.
- **`Waterbody Lookup[Private sewerage rating]` rates a blank as Very Low** (a blank is below 0.1). Every
  waterbody has a figure today. (Ours gives no rating.)
- **`[Most Recent FACTVALUE]` takes the largest of a text column** (`FACTVALUE`), so "9.1" beats "10.5".
  Notes page only. Use `FACT_VALUE_NUM`.
- **`[Total Spill Duration 2025]` and `[Sewage Overflow Pressure]` name 2025**, so they'll need editing when
  the 2026 returns arrive. (Ours uses the latest year.)

### P15

**The 2025 class counts are England's if the slicer is cleared.**

- **Where:** measure `[WFD Eco Stats HTML]` (Catchment Summaries).
- **What's wrong:** it counts rows of `WFD 2025 Classifications`, which is the whole of England (3,928
  waterbodies). With North Devon chosen in the page's Management catchment slicer it's right (92); if the
  slicer is cleared, the table counts England's.
- **Fix:** filter the measure to North Devon, or make the slicer single-select and required.

### P16

**Biosphere Ranking is stored as text, so it sorts 1, 10, 11 … 2.**

- **Where:** Power Query `Waterbody Lookup` (no type for `Biosphere Ranking`, then `Sorted Rows` by it).
- **What's wrong:** the query sorts it as text, and any visual sorted by it would too. It's only shown
  through the `Biosphere Ranking Display` measure today, so nothing looks wrong.
- **Fix:** give it `Int64.Type` in the Changed Type step.

### P17

**The live SWW feed (Map testing page): no paging, and times in UTC.**

- **Where:** Power Query `API SWW EDM`.
- **What's wrong:** it asks the map service for everything in one request. The service returns at most a
  set number of features per request (1,345 come back today, under the limit), and anything over would be
  dropped silently. And the event times are converted from milliseconds without a time zone, so they're
  UTC: an hour behind in summer.
- **Fix:** page through with `resultOffset` (as our River Obstacles importer does), and convert to UK time.
  Only matters if the page is used.

### P18

**Many tables are joined by waterbody name, so a spelling change drops data silently.**

- **Where:** the relationships. Joined by name: APHA, Habitat, Hydrology, Morphology, EA Classification
  Data, the RNAGs, River Obstacles, Water Company Asset Plans (all of England), EA POMs and the storm
  overflows (P5). Improvement Information reaches the lookup through `WeightofEvidenceEutroph_Clip` by name;
  its direct WBID relationship is inactive.
- **What's wrong:** all of them match today (checked: all 92 names, apart from P5's two overflows). But if
  one file spells a waterbody differently (e.g. "Okemont" and "Okement" both appear in the source files),
  its data quietly disappears from that waterbody's pages. Water Company Asset Plans is national, so a
  same-named waterbody elsewhere in England would be added in.
- **Fix:** join by waterbody ID wherever the file has one (most do).

---

## Nit

### P19

**Broken or unused measures.**

- **Broken (refer to a measure that doesn't exist):** `[ECO2016]` uses `[HydroMorph2016_delete]`, and
  `[Std Score]` uses `[PhosphateStdScore]`. Neither is on a page, so nothing shows wrong, but they'd error
  if used.
- **Copy-paste slip:** `[DORank]` breaks ties with `[LatestFish]` instead of `[LatestDO]`. Not on a page.
- **Not used on any page (23):** AmmoniaReductionToAchieveMod, BQE2016, DOIncreaseToAchieveMod, DORank,
  DashboardTitleEA, DashboardTitlePressures, ECO2016, Failing Parameters 2025 HTML, Failing Parameters
  2025 and 2022 HTML, Failing Parameters HTML, FishRank, InvertsHigh, InvertsNTAXARank, MorphValue2019old,
  MorphValue2022old, MorphValue2025old, PhosphateBad, PhosphateReductionRank, PhosphateReductionToAchieveMod,
  River Total Area (ha), Sewerage, Show Rivers Trust Data, Std Score.
- **Spelling that works only because DAX ignores case:** `[Good]` and `[Poor]` say "ph Lower";
  `[FishValue2019]` and `[FishValue2016]` say "FISH"; `[EAColour…]` say "Macrophytes and PhytoBenthos
  Combined".

---

## Questions rather than errors

These look deliberate, so they're not listed as errors, but they're worth a second look:

- **Several "2025" figures fall back to older years without saying so.** `[BQE2025]` uses the newest fish
  EQR from 2025, 2022, 2019 or 2016; `[MacrophytesPhytoCombined2025]` (and 2022, 2019) do the same for
  macrophytes and phytobenthos; `[pH2025]`, `[PhysChem2025_Status]` and `[HydroMorph2025]` fall back to
  2022. A cell in the 2025 column can be an older year's result.
- **`[Phosphate from Treated Sewage (2030)]`** multiplies today's phosphate concentration by the 2030 share
  from treated sewage, so it doesn't include any change in the total by 2030. Fine if that's the intent
  (it's the ninth risk, not on our dashboard).

---

## Checked and found right

- **Power Query:** the CSV files are read with `QuoteStyle.None`, which only goes wrong if a quoted value
  has a line break in it. Checked every CSV the queries read: none has. APHA's "Less than 5" values are
  only in columns typed "any", so no errors. The eutrophication query's chain of replacements (1→0, 2→1,
  3→2, 4→3) gives the intended scores.
- **Formulas our source files copy**, all as intended: APHA's blanks as 0, nitrogen and phosphate weights,
  pressure and density bands; private sewerage per ha and its bands; the five ESME mappings; habitat
  shares and coverage bands; the Untreated Sewage bands in seconds.
- **The EA values:** each physico-chemical median only picks up its own facts (all "Sample" facts of one
  item); Fish EQR leaves out the species' own EQRs; the thresholds are each taken from their latest year.
- **Names:** every source file's waterbody names match the Waterbody Lookup's 92, apart from the two
  overflows in P5.
