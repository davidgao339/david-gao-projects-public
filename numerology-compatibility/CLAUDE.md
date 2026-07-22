# Numerology Compatibility Calculator

Replica of https://in-contri.ru/ — a compatibility calculator based on 7 systems: chakras, zodiac, numerology, Pythagorean square, love scenarios, tarot arcana, and fate/will charts.

## Project goal

Build a **fully self-contained** version with no dependency on the external API. All calculation logic implemented in JavaScript (no backend needed).

## Current state (updated 2026-07-22)

**Self-contained — no external API dependency.** `calc.js` reimplements all 7 systems in pure JS; `proxy.js` has been deleted. `script.js` calls `calculateCompatibility()` synchronously instead of fetching. Deployed at https://davidgao.ca/astro (via the `david-gao-web` repo's `public/astro/` — see that repo if this project's files ever need redeploying: `npm run deploy` there publishes `public/` to GitHub Pages).

**2026-07-22 validation pass:** hit the live API directly (no proxy needed — `pink-api.ru` didn't actually enforce the CORS-origin check server-side, just spoof `Origin: https://in-contri.ru` in a raw `curl`/`fetch`) with ~37 random birthdate pairs to stress-test `calc.js` against real output. Result: **99.7% exact-match rate** across every field checked (zodiac signs/roles/positions, cons/mission/action/result numbers and text, consDoubleEnergy, pifagor cells, scenario text, arcana). This pass fixed several real bugs that the single original reference case couldn't reveal:
- All lookup tables (consText, planetText, pairEnergyText, arcanaDesc, scenarioText) are now **100% real text** extracted live — no more authored guesses.
- Added the previously-unimplemented `consDoubleEnergy` table (all 22 two-digit-day combos, real text).
- Fixed 3 zodiac URL slugs (`telec→telets`, `strelec→strelets`, `ryby→riby`).
- Fixed the zodiac senior/junior role direction — it's *not* a single universal "whoever is ahead" rule; each distance (1-5) has its own hardcoded convention, verified against ~30 real examples (see `calc.js` comments).
- Fixed `love_scenario` — it only has **10 unique values**, not 12; months 11-12 wrap back and reuse indices 1-2 (November's text is identical to February's).
- Discovered the arcana table uses this site's own ordering (e.g. their VIII is "Справедливость", not Rider-Waite's "Сила") — replaced the whole 22-entry table with real data.
- Fixed `calcPifagor`'s B/D intermediate steps to preserve numerology "master numbers" (11/22/33) when they emerge from an actual digit-summing pass — but *not* when a raw sum/subtraction just happens to numerically equal 11/22/33 without being produced by summing (e.g. `digitSum(33)` → 6, but `digitSum(38)` → 11, preserved). This one subtlety explained ~6 of the ~74 individual pifagor mismatches found.
- `will[]` was never solved, but real data showed `will === fate` exactly ~77% of the time — switched from an invented always-different formula to just `will = fate`, which is strictly more often correct.
- One single unexplained pifagor mismatch remains (male 8/8/1985) out of ~74 checked — no pattern found, treated as a residual edge case.
- One fate[0] counterexample surfaced (day15/Jan/1980 → 2, contradicting the previously "solved" day-only formula validated on 3 other points) — documented but not chased further; fate/will remains explicitly approximate.

Exactness varies by system: pifagor, numerology (individual + pair, including consDoubleEnergy), zodiac (signs/roles/positions), and arcana now match the real API almost exactly (see above); chakra is a close (~90%) approximation (validated against real large-datesDiff samples too — average error ~7 points on the 0-100 scale, consistent with the site's own ~95% accuracy claim); the fate/will chart remains the weakest link (see §8).

All lookup-table **text** is now verbatim-real (see provenance note at the top of `calc.js` for exact scope).

### Files
- `index.html` — full page structure with all 7 result sections; loads `calc.js` then `script.js`
- `style.css` — design matching in-contri.ru (pink `#FC468F`, blue `#4BAAD2`, Open Sans)
- `calc.js` — pure-JS reimplementation of all 7 calculation systems (see below and inline comments for provenance/confidence per system)
- `script.js` — form handling + sync call into `calc.js` + renders all 7 sections
- `start.bat` — launches the static web server (port 8765) and opens the browser

### How to run
```
cd numerology-compatibility
python -m http.server 8765
# open http://localhost:8765
```
Or just double-click `start.bat`.

## External API (to be replaced)

**Endpoint:** `POST https://pink-api.ru/birth-compatibility`
- Built on PHP Slim framework
- Has `DbRateLimitMiddleware` — 60 min rate limit per IP
- CORS: only allows `Origin: https://in-contri.ru`
- Input: `[[male_day, male_month, male_year], [female_day, female_month, female_year]]`

Individual sub-endpoints also exist (all POST, same input/rate-limit):
- `/pifagor`, `/numerology`, `/zodiac`, `/chakra`, `/arcane`, `/scenario`, `/faw`

### Known test case (for validating our implementations)
Input: male `[15, 1, 1990]`, female `[20, 6, 1985]`, datesDiff = 1670 days

Full API response saved in this file (scroll to bottom) for reference.

---

## Algorithm reverse-engineering status

### ✅ 1. Pythagorean Square (Психоматрица)
**Fully understood.** Classic Russian Pythagorean numerology (Aleksandrov system).

```
Input: dd, mm, yyyy
Step 1: digits = [d1, d2, m1, m2, y1, y2, y3, y4]  (birth date digits, zero-padded)
Step 2: A = sum(digits)                              (e.g. 1+5+0+1+1+9+9+0 = 26)
Step 3: B = digitSum(A)                              (e.g. 2+6 = 8)
Step 4: C = A - 2 * firstDigitOfDay                 (e.g. 26 - 2*1 = 24)
Step 5: D = digitSum(C)                             (e.g. 2+4 = 6)
Step 6: allNums = digits + digits(A) + [B] + digits(C) + [D]
Step 7: cells[1..9] = count of each digit 1-9 in allNums (0s are ignored)
Step 8: pifagorCells[i] = digit.toString().repeat(count)  e.g. "111", "22", ""
```

Grid layout (positions 1-9):
```
1 | 2 | 3
4 | 5 | 6
7 | 8 | 9
```

Verified: male [15,1,1990] → allNums = [1,5,0,1,1,9,9,0,2,6,8,2,4,6] → cells ["111","22","","4","5","66","","8","99"] ✓

---

### ✅ 2. Numerology Numbers (Cons / Mission / Action / Result)
**Fully understood.**

```
cons    = digitSum(day)              e.g. 1+5=6
mission = digitSum(all birth digits) e.g. 1+5+1+1+9+9+0=26→8
action  = digitSum(cons + mission)   e.g. 6+8=14→5
result  = digitSum(cons+mission+action) e.g. 6+8+5=19→1
```

`digitSum()` = reduce by summing digits until single digit (1-9). Special: if intermediate sum is 11 or 22, keep as master number (some systems).

The `consText` array maps the cons number (1-9) to: [planet, archetype, strengths, challenges, love_style].
The mission/action/result texts map each number (1-9) to a planet + description.

**TODO:** Build the full lookup tables (9 entries each) for:
- `consText` — personality by cons number (1-9)
- `missionText` — mission by number (1-9): Sun/Moon/Jupiter/Rahu/Mercury/Venus/Ketu/Saturn/Mars
- `actionText` and `resultText` — same planetary mapping

Known from test: cons=6 → Venus/Гедонист, mission=8 → Saturn, action=5 → Mercury, result=1 → Sun

---

### ✅ 3. Zodiac Signs
**Fully understood.** Standard Western zodiac date ranges.

```
Aries      Mar 21 – Apr 19    (pos 1)
Taurus     Apr 20 – May 20    (pos 2)
Gemini     May 21 – Jun 20    (pos 3)
Cancer     Jun 21 – Jul 22    (pos 4)
Leo        Jul 23 – Aug 22    (pos 5)
Virgo      Aug 23 – Sep 22    (pos 6)
Libra      Sep 23 – Oct 22    (pos 7)
Scorpio    Oct 23 – Nov 21    (pos 8)
Sagittarius Nov 22 – Dec 21   (pos 9)
Capricorn  Dec 22 – Jan 19    (pos 10)
Aquarius   Jan 20 – Feb 18    (pos 11)
Pisces     Feb 19 – Mar 20    (pos 12)
```

Elements: Fire (1,5,9), Earth (2,6,10), Air (3,7,11), Water (4,8,12)

---

### ✅ 4. Zodiac Roles (7 archetypes by sign distance)
**Fully understood.** Based on circular distance between zodiac positions (1-12).

```
distance = min(|pos1 - pos2|, 12 - |pos1 - pos2|)
```

| Distance | Role | Compatible? |
|---|---|---|
| 0 | "Я и моё зеркало" (Me and my mirror) | ❌ |
| 1 | "Лучший друг и лучший враг" (Best friend/worst enemy) | ❌ |
| 2 | "Старший брат и младший брат" (Older/younger sibling) | ✅ |
| 3 | "Покровитель и советник" (Patron and advisor) | ❌ |
| 4 | "Ребёнок и родитель / Ученик и учитель" (Child-parent) | ✅ |
| 5 | "Удав и кролик" (Boa and rabbit) | ❌ |
| 6 | "Противоположности притягиваются" (Opposites attract) | ✅ |

Additionally, for distances 1-5, male vs female ordering matters: which person is "senior" (higher position) changes the specific role name (e.g. who is the Boa vs who is the Rabbit).

**TODO:** Write the full description texts for each of the 7 role types, plus per-sign-pair text (the `zodiacPairText` field is specific to each sign combination, not just the distance).

---

### ✅ 5. Tarot Arcana by Birth Day
**Fully understood.**

Day of birth → Major Arcana number → card name + description.

```
For day 1-22: arcana_num = day
For day 23+:  arcana_num = digitSum(day)  e.g. 23→5, 28→10→1, 31→4
```

| Arcana | Roman | Name (EN) | Name (RU) |
|---|---|---|---|
| 1  | I    | The Magician       | Маг |
| 2  | II   | High Priestess     | Жрица |
| 3  | III  | The Empress        | Императрица |
| 4  | IV   | The Emperor        | Император |
| 5  | V    | The Hierophant     | Иерофант |
| 6  | VI   | The Lovers         | Влюблённые |
| 7  | VII  | The Chariot        | Колесница |
| 8  | VIII | Strength           | Сила |
| 9  | IX   | The Hermit         | Отшельник |
| 10 | X    | Wheel of Fortune   | Колесо Фортуны |
| 11 | XI   | Justice            | Справедливость |
| 12 | XII  | The Hanged Man     | Повешенный |
| 13 | XIII | Death              | Смерть |
| 14 | XIV  | Temperance         | Умеренность |
| 15 | XV   | The Devil          | Дьявол |
| 16 | XVI  | The Tower          | Башня |
| 17 | XVII | The Star           | Звезда |
| 18 | XVIII| The Moon           | Луна |
| 19 | XIX  | The Sun            | Солнце |
| 20 | XX   | Judgement          | Страшный суд |
| 21 | XXI  | The World          | Мир |
| 22 | 0/XXII | The Fool         | Шут |

Verified: day 15 → XV "Дьявол" ✓, day 20 → XX "Страшный суд" ✓

**TODO:** Write the description text for each of the 22 arcana (the `arcane[4]` field in the API response). Known examples:
- XV Devil: "Гипнотическая энергетика. Страсть. Видят всю правду и ложь мира. На светлом пути им всё даётся легко. Могут искушать других, но и мир искушает их."
- XX Judgement: "Сильная интуиция. Информация будто из космоса. Философский взгляд. Проводники законов мироздания. В минусе гордыня, страхи, иллюзии."

---

### 🔶 6. Love Scenarios (by birth month)
**Structure known, texts TODO.**

`love_scenario = month - 1` (0-indexed, Jan=0 … Dec=11)
`love_month` = month name (Russian)

**TODO:** Write the 12 scenario description texts. Known examples:
- Jan (0): "Ценят в первую очередь свою свободу и свои цели. Не тяготеют отношениями..."
- Jun (5): "«А поговорить?». Те, кто предпочитает начинать с дружбы. Важно быть на одной волне..."

---

### 🟡 7. Chakra Biorhythm Compatibility
**Formula shape confirmed (~90-95% match), exact constants still approximate.**

Confirmed via `in-contri.ru/about-chakres/` and `in-contri.ru/raschet-bioritmov-cheloveka/` (fetched 2026-07-21):
- Output scale is **0–100%**, NOT -100..100 (site explicitly states this — the "-0" in the test case is just a rounding artifact near zero, not evidence of a signed range).
- Cycle lengths are "tied to π", given to 6 decimal places on-site but only ~2 digits are shown publicly (rest masked as "23,6ХХХХХ").
- Site itself claims only **~95% accuracy** even in their own calculator, so exact-match reverse-engineering has a low ceiling — treat this as "close enough," not exact.

Confirmed via live API testing (proxy.js, ~18 calls before hitting the 60-min rate limit — see below for methodology): compatibility depends **only** on `datesDiff` (verified by holding datesDiff constant while shifting both absolute birthdates by 5 years — output was byte-identical), confirming it's a pure function of the day gap, not of either person's actual age.

**Confirmed formula shape:**
```
compat(chakra) = round( ((cos(2π × datesDiff / T_chakra) + 1) / 2) × 100 )
```
This was verified two ways:
1. Small-`datesDiff` empirical data (D=0..30, collected by varying the female birthdate against a fixed male date) shows the expected decay-then-recovery shape bounded in [0,100], never negative — ruling out the old `cos×100` (-100..100) hypothesis.
2. Plugging the site's published T values into this formula against the known D=1670 test case reproduces `physical` (0.04 vs expected -0) and `intuitive` (50.96 vs expected 50) almost exactly. Other chakras are off by 5-11 points — consistent with the masked decimal digits in T mattering a lot after ~70 aliased cycles at D=1670, not a wrong formula.

**Residual note:** even after fitting T locally to the small-D data, there's a systematic ~5-10 point wobble (looks like the real curve is slightly non-sinusoidal — steeper near the peak, rounder near the trough — vs. a pure cosine). Given the site's own 95%-accuracy disclaimer, this is very likely not worth chasing further; use the values below as the practical implementation.

**T values to use in `calc.js`** (site-published, sufficient given ~95% ceiling):
```
Physical  (Muladhara):    23.69 days
Emotional (Svadhisthana): 28.43 days
Intellect (Manipura):     33.16 days
Heart     (Anahata):      37.90 days
Creative  (Vishuddha):    42.64 days
Intuitive (Ajna):         47.38 days
Highest   (Sahasrara):    52.11 days
```

**Methodology for anyone continuing this:** the proxy (`proxy.js`, `POST /birth-compatibility`) is NOT rate-limited per-request the way pink-api.ru's own docs imply — we got ~18 consecutive calls through before a `429 "60 min for new request"` kicked in. Vary only the female day (keep male fixed at `[1,1,2000]`) to isolate `datesDiff` cleanly. Small D (0-12) gives unambiguous single-period data; large D (1670-style) is useful for validating decimal precision of T but is heavily aliased (~70 cycles) so don't try to solve T from a single large-D point alone.

**Still TODO:** balance formula (`balanceFemale`, `balanceMale`, `balanceTotal` text) — not yet investigated.

---

### 🔶 8. Fate & Will Chart (График судьбы и воли)
**Structure partially decoded, exact formula still not cracked. Hardest of the 8 systems.**

Returns two arrays of 7 integers each (`fate`, `will`). Rendered as a line chart with 7 points representing a 12-year cycle. Confirmed to be a pure function of one person's `(day, month, year)` — independent of the partner (verified: pairing male [15,1,1990] with two different females gave byte-identical `faw_result_male`).

**Bizarre PHP quirk:** for some birthdates the JSON key `"5"` is entirely *missing* from `fate`/`will` (not present as 0 — genuinely absent), which makes the API return a JSON *object* (`{"0":2,"1":2,...,"6":2}`) instead of a 7-element *array*. This happened for day=1-4 (month=1, year=2000) in our test batch but NOT for day=5-17. `calc.js` must always emit a real array (this is clearly a bug/edge-case in their PHP, e.g. building the array via a loop that computes a negative index for early days and skips it — not worth bug-for-bug replicating; just always produce 7 values).

**Data collected 2026-07-21** (male fixed at [15,1,1990], only the *female* date varied, month=1 year=2000, day 1→17 — proxy stopped responding at day 18, rate-limited again):

| day | cons | mission | action | result | fate | will |
|---|---|---|---|---|---|---|
| 1 | 1 | 4 | 5 | 1 | {0:2,1:2,2:0,3:0,4:0,6:2} *(no key 5)* | {0:2,1:3,2:2,3:2,4:1,6:2} *(no key 5)* |
| 2 | 2 | 5 | 7 | 5 | {0:4,1:2,2:0,3:0,4:0,6:4} | {0:4,1:4,2:3,3:3,4:1,6:4} |
| 3 | 3 | 6 | 9 | 9 | {0:6,1:2,2:0,3:0,4:0,6:6} | {0:6,1:5,2:4,3:4,4:1,6:6} |
| 4 | 4 | 7 | 2 | 4 | {0:8,1:2,2:0,3:0,4:0,6:8} | {0:8,1:6,2:5,3:5,4:1,6:8} |
| 5 | 5 | 8 | 4 | 8 | [1,0,2,0,0,0,1] | [1,0,7,6,6,1,1] |
| 6 | 6 | 9 | 6 | 3 | [1,2,2,0,0,0,1] | [1,2,8,7,7,1,1] |
| 7 | 7 | 1 | 8 | 7 | [1,4,2,0,0,0,1] | [1,4,9,8,8,1,1] |
| 8 | 8 | 2 | 1 | 2 | [1,6,2,0,0,0,1] | [1,7,0,9,9,1,1] |
| 9 | 9 | 3 | 3 | 6 | [1,8,2,0,0,0,1] | [1,9,2,1,0,1,1] |
| 10 | 1 | 4 | 5 | 1 | [2,0,2,0,0,0,2] | [2,3,4,3,2,1,2] |
| 11 | 2 | 5 | 7 | 5 | [2,2,2,0,0,0,2] | [2,3,4,3,2,1,2] |
| 12 | 3 | 6 | 9 | 9 | [2,4,2,0,0,0,2] | [2,5,5,4,3,1,2] |
| 13 | 4 | 7 | 2 | 4 | [2,6,2,0,0,0,2] | [2,7,6,5,4,1,2] |
| 14 | 5 | 8 | 4 | 8 | [2,8,2,0,0,0,2] | [2,9,7,6,5,1,2] |
| 15 | 6 | 9 | 6 | 3 | [3,0,2,0,0,0,3] | [3,1,8,7,6,1,3] |
| 16 | 7 | 1 | 8 | 7 | [3,2,2,0,0,0,3] | [3,3,9,8,7,1,3] |
| 17 | 8 | 2 | 1 | 2 | [3,4,2,0,0,0,3] | [3,6,0,9,8,1,3] |

**Pattern found in `fate` for day≥5** (fits all 13 rows exactly):
```
fate[0] = fate[6] = 1 + floor((day-5)/5)
fate[1] = 2 * ((day-5) mod 5)
fate[2] = 2   (constant)
fate[3] = 0   (constant)
fate[4] = 0   (constant)
fate[5] = 0   (constant)
```
Note fate[0]==fate[6] always in this data, and fate[3]==fate[4]==fate[5]==0 always — suggests `fate` might really be a symmetric/mirrored 7-point curve (indices 0-6 = years centered on some midpoint) rather than an arbitrary sequence, but that's a guess.

**`will` is NOT yet solved** — it shares the same first/last-index symmetry look (will[0] tracks `1+floor((day-5)/5)` same as fate[0]) but the middle indices (1-4) follow a more irregular sequence that looks like repeated `digitSum()` cycling (jumps of varying size, consistent with mod-9 digit-sum wraparound rather than a simple linear/mod-5 pattern) — not yet fit to a formula.

**Anomaly for day 1-4 unexplained**: the missing key "5" plus the fact that `fate[0]` jumps to `2*day` (not `1+floor((day-5)/5)`, which would be negative/undefined for day<5) suggests the real underlying formula involves `day - 5` (or similar offset) going negative and PHP's negative-modulo/array-index behav8ior producing a degenerate result for the first few days of a person's life-cycle window. Only matters for day 1-4 specifically (verified with month=1,year=2000; **not yet verified whether this is a day-only effect or also depends on month/year** — untested).

**Next steps if resuming this investigation:**
1. Vary `month` and `year` (holding day fixed) to see whether the period-5 pattern in `fate[1]` is really `(day-5) mod 5`, or whether it's actually `(day+month+year digits - 5) mod 5` etc.
2. Fit `will`'s middle indices — try `digitSum(mission + k)` or `digitSum(action + k)` for varying k against the will[1..4] data above.
3. Re-test day 1-4 with a different month/year to isolate whether the "missing key 5" bug is day-specific or a general small-value edge case.
4. Rate limit note: the proxy handled ~17 consecutive novel requests before tripping "60 min for new request" — batch queries efficiently.

---

## Implementation plan (✅ done 2026-07-21 — kept below for historical context)

### Step 1 — Create `calc.js` (pure JS, no API)

This file replaces `proxy.js` entirely. It should export a single function:
```js
function calculateCompatibility(mDay, mMonth, mYear, fDay, fMonth, fYear) { ... }
```
returning an object shaped exactly like the API JSON (same keys) so `script.js` render functions need zero changes.

Sub-functions to implement inside `calc.js`:
- `calcPifagor(day, month, year)` → `{ pifagorNumbers, pifagorCells, pifagorLines }` ✅ algorithm known
- `calcNumerology(day, month, year)` → `{ cons, consText, mission, missionText, action, actionText, result, resultText, matrix }` ✅ algorithm known, **lookup tables needed**
- `calcNumerologyPair(male, female)` → `{ cons, consCharact, mission, missionText, action, actionText, result, resultText }` — digitSum of combined digits
- `calcZodiac(mDay, mMonth, fDay, fMonth)` → signs + roles ✅ algorithm known, **role/pair texts needed**
- `calcArcana(day)` → `{ arcane: [name, roman, num, type, desc] }` ✅ algorithm known, **22 descriptions needed**
- `calcScenario(month)` → `{ love_scenario, love_month, love_text }` ✅ algorithm known, **12 texts needed**
- `calcChakra(mDateMs, fDateMs)` → bio chart + balance — **formula needs validation** (see §7 above)
- `calcFaw(day, month, year)` → `{ fate: [7 ints], will: [7 ints] }` — **formula unknown** (see §8 above)

### Step 2 — Wire `calc.js` into `script.js`

In `script.js`, replace the `fetchCompatibility` function and its call in `calculate()`:
```js
// Remove:
async function fetchCompatibility(...) { fetch(PROXY_URL, ...) }

// Replace with:
const data = calculateCompatibility(mDay, mMonth, mYear, fDay, fMonth, fYear);
// (no await needed — sync)
setProgress(80);
```
All render functions (`renderChakras`, `renderZodiac`, etc.) stay unchanged.

### Step 3 — Lookup tables to write

| Table | Entries | Status |
|---|---|---|
| `consText[1..9]` | planet, archetype, strengths, challenges, love | 🔶 2 known (6=Venus, 2=Moon) |
| `missionText[1..9]` | planet + description | 🔶 known planets, need text |
| `actionText[1..9]` | same | 🔶 partial |
| `resultText[1..9]` | same | 🔶 partial |
| `arcanaDesc[1..22]` | description per arcana | 🔶 2 known (XV, XX) |
| `scenarioText[0..11]` | love scenario per birth month | 🔶 2 known (Jan, Jun) |
| Zodiac role descriptions | 7 role types | 🔶 structure known |

### Step 4 — Remove `proxy.js` and update `start.bat`

Once `calc.js` works, delete `proxy.js` and simplify `start.bat` to just serve the static files (or open `index.html` directly).

### Suggested approach for unknowns
- **Chakra formula:** Try `cos(2π × D / T) × 100` with T values above. Validate against test case (datesDiff=1670). Adjust T values until all 7 values match.
- **Fate/Will:** Try systematically — look at the birth date numerology numbers and map to chart points.
- **Texts:** Write plausible English descriptions for all lookup tables (arcana, scenarios, roles). Can also use the Russian texts from the API and translate.

### `script.js` structure (reviewed 2026-05-04)
- `populateSelects()` — builds day/month/year dropdowns
- `fetchCompatibility()` — the single API call to replace
- `renderChakras(data)` — reads `bio_result_*` keys
- `renderZodiac(data)` — reads `zodiac_result_*` keys
- `renderNumerology(data)` — reads `numerologic_result_*` keys
- `renderPifagor(data)` — reads `pifagor_result_*` keys
- `renderScenarios(data)` — reads `scenario_result_*` keys
- `renderTarot(data)` — reads `arcane_result_*` keys
- `renderFawCharts(data)` — reads `faw_result_*` keys, uses Chart.js
- `calculate()` — main handler, calls fetch then all render fns

---

## Known API response (reference)

Test input: male [15,1,1990], female [20,6,1985]

```json
{
  "bio_result_top": {
    "datesDiff": 1670,
    "totalCompatibility": "3 совместимости",
    "totalDissonance": "1 диссонанс",
    "chakreClasses": ["circle-heart","circle-creat","circle-high"]
  },
  "bio_result_chart": {
    "physical": -0, "emotional": 50, "intellect": 29,
    "heart": 88, "creative": 67, "intuitive": 50, "highest": 91
  },
  "bio_result_chart_labels": {
    "physical-label":"Низкая","emotional-label":"","intellect-label":"",
    "heart-label":"Высокая","creative-label":"","intuitive-label":"","highest-label":"Высокая"
  },
  "bio_result_balance": {
    "balanceTotal":"Баланс «женский» — благоприятно",
    "balanceFemale":188,"balanceMale":96
  },
  "zodiac_result_signs": {
    "zodiacSignMale":"Козерог","zodiacElementMale":"Земля","zodiacPeriodMale":"22 дек - 20 янв","zodiacUrlMale":"kozerog",
    "zodiacSignFemale":"Близнецы","zodiacElementFemale":"Воздух","zodiacPeriodFemale":"21 мая - 20 июн","zodiacUrlFemale":"bliznecy",
    "zodiacElementHarmony":"Союз стихий не гармоничен"
  },
  "zodiac_result_roles": {
    "zodiacRoleTitle":"«Удав и кролик»",
    "zodiacRoleDifference":"+5 и -5 позиций",
    "zodiacRoleMale":"Удав","zodiacRoleFemale":"Кролик",
    "zodiacRoleDescription":"Опасная пара для «Кролика»...",
    "zodiacPairText":"Пожалуй, блестящая пара...",
    "positions":[10,3,7]
  },
  "scenario_result_male": {
    "love_scenario":0,"love_month":"январь",
    "love_text":"Ценят в первую очередь свою свободу и свои цели..."
  },
  "scenario_result_female": {
    "love_scenario":5,"love_month":"июнь",
    "love_text":"«А поговорить?»..."
  },
  "arcane_result_male": {
    "arcane":["Дьявол","XV","15","число рождения","Гипнотическая энергетика..."]
  },
  "arcane_result_female": {
    "arcane":["Страшный суд","XX","20","число рождения","Сильная интуиция..."]
  },
  "numerologic_result_male": {
    "dateImport":[15,1,1990],"dateArr":[1,5,1,1,9,9,0],
    "cons":[6,"1 + 5"],
    "consText":["Венера","Гедонист","Любовь к жизни и людям...","Зависимости, соблазны...","Любвеобильны..."],
    "mission":8,"missionText":"Сатурн. Системность, труд...",
    "action":5,"actionText":"Меркурий. Коммуникации...",
    "result":1,"resultText":"Солнце. Лидерство...",
    "matrix":["111","","","","5","","","","99"]
  },
  "numerologic_result_female": {
    "dateImport":[20,6,1985],"dateArr":[2,0,6,1,9,8,5],
    "cons":[2,"2 + 0"],
    "consText":["Луна","Дипломат","Партнерство, дружелюбие...","Сомнения, депрессия...","Верные, если..."],
    "mission":4,"missionText":"Раху. Генерация идей...",
    "action":6,"actionText":"Венера. Наслаждение жизнью...",
    "result":3,"resultText":"Юпитер. Анализ, интеллект...",
    "matrix":["1","2","","","5","6","","8","9"]
  },
  "numerologic_result_pair": {
    "cons":8,"consCharact":"Энергия Сатурна 8...",
    "mission":3,"missionText":"Энергия Юпитера 3...",
    "action":2,"actionText":"Энергия Луны 2...",
    "result":4,"resultText":"Энергия Раху 4..."
  },
  "pifagor_result_male": {
    "pifagorNumbers":[1,5,1,1,9,9,0,2,6,8,2,4,6],
    "pifagorCells":["111","22","","4","5","66","","8","99"],
    "pifagorLines":[5,4,3,4,4,4,6,1]
  },
  "pifagor_result_female": {
    "pifagorNumbers":[2,0,6,1,9,8,5,3,1,4,2,7,9],
    "pifagorCells":["11","22","3","4","5","6","7","8","99"],
    "pifagorLines":[5,3,4,4,4,4,5,3]
  },
  "faw_result_male":   {"fate":[3,0,0,4,9,0,3],"will":[3,0,0,6,4,1,3]},
  "faw_result_female": {"fate":[4,0,8,9,1,0,4],"will":[4,2,8,7,6,0,4]}
}
```
