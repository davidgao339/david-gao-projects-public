# Numerology Compatibility Calculator

Replica of https://in-contri.ru/ — a compatibility calculator based on 7 systems: chakras, zodiac, numerology, Pythagorean square, love scenarios, tarot arcana, and fate/will charts.

## Project goal

Build a **fully self-contained** version with no dependency on the external API. All calculation logic implemented in JavaScript (no backend needed).

## Current state

The app currently works but **depends on an external API** (`pink-api.ru`). The next session should replace all API calls with our own JS implementations.

### Files
- `index.html` — full page structure with all 7 result sections
- `style.css` — design matching in-contri.ru (pink `#FC468F`, blue `#4BAAD2`, Open Sans)
- `script.js` — form, API call to proxy, renders all 7 sections
- `proxy.js` — Node.js proxy that spoofs `Origin: https://in-contri.ru` (needed because pink-api.ru blocks other origins)
- `start.bat` — launches both proxy (port 8766) and web server (port 8765) and opens browser

### How to run (current state)
```
cd numerology-compatibility
node proxy.js        # port 8766 — forwards to pink-api.ru
python -m http.server 8765  # port 8765 — serves the frontend
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

### 🔶 7. Chakra Biorhythm Compatibility
**Formula partially known, needs validation.**

Based on biorhythm theory: each person has sinusoidal cycles. Compatibility = how synchronized two people's cycles are, depending only on the difference in their birth dates.

Reported cycle lengths (source: in-contri.ru, unverified precise values):
```
Physical  (Muladhara):    ~23.69 days
Emotional (Svadhisthana): ~28.43 days
Intellect (Manipura):     ~33.16 days
Heart     (Anahata):      ~37.90 days
Creative  (Vishuddha):    ~42.64 days
Intuitive (Ajna):         ~47.38 days
Highest   (Sahasrara):    ~52.11 days
```

Likely formula:
```
compat(chakra) = round(cos(2π × datesDiff / T_chakra) × 100)
```
Range: -100 to +100. The API shows negative values (e.g. physical: -0).

**TODO:** Validate formula against test case (datesDiff=1670):
Expected: physical:-0, emotional:50, intellect:29, heart:88, creative:67, intuitive:50, highest:91
Need to find exact T values and formula that reproduce these numbers.

Also need: balance formula (`balanceFemale`, `balanceMale`, `balanceTotal` text).

---

### 🔶 8. Fate & Will Chart (График судьбы и воли)
**Structure known, formula unknown.**

Returns two arrays of 7 integers each. Rendered as a line chart with 7 points representing a 12-year cycle.

Known test output:
- Male [15,1,1990]: fate=[3,0,0,4,9,0,3], will=[3,0,0,6,4,1,3]
- Female [20,6,1985]: fate=[4,0,8,9,1,0,4], will=[4,2,8,7,6,0,4]

**TODO:** Figure out the formula. Likely based on individual birth date digits and/or numerology numbers across 12-year windows.

---

## Implementation plan for next session

1. **Build `calc.js`** — pure JS implementation of all 8 algorithms (no API dependency)
2. **Replace `script.js` API call** with local `calc.js` functions
3. **Remove `proxy.js`** entirely — app becomes fully static (no servers needed)
4. **Write all lookup table data** (arcana descriptions, scenario texts, zodiac role texts, numerology planet texts)

### Suggested approach for unknowns
- **Chakra formula:** Try `cos(2π × D / T) × 100` with T values above. Validate against test case. Adjust T values until all 7 values match.
- **Fate/Will:** Try systematically — look at the birth date numerology numbers and map to chart points.
- **Texts:** Write plausible English descriptions for all lookup tables (arcana, scenarios, roles). Can also use the Russian texts from the API and translate.

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
