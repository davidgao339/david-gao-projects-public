/* ============================================================
   SETUP: Populate date dropdowns
   ============================================================ */
const MONTHS = [
  'January','February','March','April','May','June',
  'July','August','September','October','November','December'
];

function populateSelects() {
  ['m','f'].forEach(prefix => {
    const dayEl   = document.getElementById(`${prefix}-day`);
    const monthEl = document.getElementById(`${prefix}-month`);
    const yearEl  = document.getElementById(`${prefix}-year`);

    for (let d = 1; d <= 31; d++) {
      const o = document.createElement('option');
      o.value = d; o.textContent = d;
      dayEl.appendChild(o);
    }

    MONTHS.forEach((m, i) => {
      const o = document.createElement('option');
      o.value = i + 1; o.textContent = m;
      monthEl.appendChild(o);
    });

    const currentYear = new Date().getFullYear();
    for (let y = currentYear; y >= 1920; y--) {
      const o = document.createElement('option');
      o.value = y; o.textContent = y;
      yearEl.appendChild(o);
    }
  });
}

/* ============================================================
   PROGRESS BAR
   ============================================================ */
const progressBar = document.getElementById('progress-bar');

function setProgress(pct) {
  progressBar.style.width = pct + '%';
}

/* ============================================================
   RENDER: CHAKRAS
   ============================================================ */
const CHAKRA_NAMES = {
  physical:  'Muladhara',
  emotional: 'Svadhisthana',
  intellect: 'Manipura',
  heart:     'Anahata',
  creative:  'Vishuddha',
  intuitive: 'Ajna',
  highest:   'Sahasrara'
};

function renderChakras(data) {
  const top     = data.bio_result_top;
  const chart   = data.bio_result_chart;
  const labels  = data.bio_result_chart_labels;
  const balance = data.bio_result_balance;

  document.getElementById('chakra-compat').textContent    = top.totalCompatibility;
  document.getElementById('chakra-dissonance').textContent = top.totalDissonance;
  document.getElementById('chakra-balance').textContent   = balance.balanceTotal;

  const barsEl = document.getElementById('chakra-bars');
  barsEl.innerHTML = '';

  Object.entries(CHAKRA_NAMES).forEach(([key, name]) => {
    const rawVal = chart[key] ?? 0;
    const pct    = Math.abs(rawVal);
    const label  = labels[`${key}-label`] || '';
    const isNeg  = rawVal < 0;

    const row = document.createElement('div');
    row.className = 'chakra-bar-row';
    row.innerHTML = `
      <div class="chakra-bar-label">${name}</div>
      <div class="chakra-bar-track">
        <div class="chakra-bar-fill ${isNeg ? 'negative' : ''}" style="width:${pct}%"></div>
      </div>
      <div class="chakra-bar-pct">${rawVal}% <span style="color:#aaa;font-size:11px">${label}</span></div>
    `;
    barsEl.appendChild(row);
  });
}

/* ============================================================
   RENDER: ZODIAC
   ============================================================ */
function renderZodiac(data) {
  const signs = data.zodiac_result_signs;
  const roles = data.zodiac_result_roles;

  document.getElementById('zodiac-sign-male').textContent    = signs.zodiacSignMale;
  document.getElementById('zodiac-element-male').textContent = signs.zodiacElementMale;
  document.getElementById('zodiac-period-male').textContent  = signs.zodiacPeriodMale;

  document.getElementById('zodiac-sign-female').textContent    = signs.zodiacSignFemale;
  document.getElementById('zodiac-element-female').textContent = signs.zodiacElementFemale;
  document.getElementById('zodiac-period-female').textContent  = signs.zodiacPeriodFemale;

  document.getElementById('zodiac-harmony').textContent   = signs.zodiacElementHarmony;
  document.getElementById('zodiac-role-title').textContent = roles.zodiacRoleTitle;
  document.getElementById('zodiac-role-diff').textContent  = roles.zodiacRoleDifference;
  document.getElementById('zodiac-role-desc').textContent  = roles.zodiacRoleDescription;
  document.getElementById('zodiac-pair-text').textContent  = roles.zodiacPairText;
}

/* ============================================================
   RENDER: NUMEROLOGY
   ============================================================ */
function buildPersonNumeraBlock(numData) {
  const c = numData.consText || [];
  const rows = [
    { key: 'Archetype',  val: `<div class="numera-num">${numData.cons?.[0] ?? ''}</div>${c[1] || ''}` },
    { key: 'Planet',     val: c[0] || '' },
    { key: 'Strengths',  val: c[2] || '' },
    { key: 'Challenges', val: c[3] || '' },
    { key: 'Love style', val: c[4] || '' },
    { key: 'Mission',    val: `<strong>${numData.mission}</strong> — ${numData.missionText || ''}` },
    { key: 'Action',     val: `<strong>${numData.action}</strong> — ${numData.actionText || ''}` },
    { key: 'Result',     val: `<strong>${numData.result}</strong> — ${numData.resultText || ''}` },
  ];
  return rows.map(r => `
    <div class="numera-row">
      <span class="numera-key">${r.key}</span>
      <span class="numera-val">${r.val}</span>
    </div>
  `).join('');
}

function renderNumerology(data) {
  document.getElementById('num-male-cons').innerHTML   = buildPersonNumeraBlock(data.numerologic_result_male);
  document.getElementById('num-female-cons').innerHTML = buildPersonNumeraBlock(data.numerologic_result_female);

  const pair = data.numerologic_result_pair;
  const pairCards = [
    { label: 'Shared Consciousness', num: pair.cons,    text: pair.consCharact },
    { label: 'Pair Mission',         num: pair.mission, text: pair.missionText },
    { label: 'Pair Action',          num: pair.action,  text: pair.actionText },
    { label: 'Pair Result',          num: pair.result,  text: pair.resultText },
  ];

  document.getElementById('num-pair').innerHTML = pairCards.map(c => `
    <div class="pair-card">
      <div class="pair-card-label">${c.label}</div>
      <div class="pair-card-num">${c.num}</div>
      ${c.text ? `<div class="pair-card-text">${c.text}</div>` : ''}
    </div>
  `).join('');
}

/* ============================================================
   RENDER: PYTHAGOREAN SQUARE
   ============================================================ */
const PIFAGOR_POSITIONS = [
  { pos: 1, label: 'Self' },
  { pos: 2, label: 'Bio' },
  { pos: 3, label: 'Reason' },
  { pos: 4, label: 'Health' },
  { pos: 5, label: 'Logic' },
  { pos: 6, label: 'Work' },
  { pos: 7, label: 'Luck' },
  { pos: 8, label: 'Duty' },
  { pos: 9, label: 'Mind' },
];

function buildPifagorGrid(cells) {
  return PIFAGOR_POSITIONS.map(({ pos, label }) => {
    const val = cells[pos - 1] || '';
    return `
      <div class="pifagor-cell">
        <span class="pifagor-cell-pos">${pos}</span>
        <span class="pifagor-cell-val ${val ? '' : 'empty'}">${val || '—'}</span>
      </div>
    `;
  }).join('');
}

function renderPifagor(data) {
  const maleCells   = data.pifagor_result_male.pifagorCells;
  const femaleCells = data.pifagor_result_female.pifagorCells;
  document.getElementById('pifagor-male').innerHTML   = buildPifagorGrid(maleCells);
  document.getElementById('pifagor-female').innerHTML = buildPifagorGrid(femaleCells);
}

/* ============================================================
   RENDER: LOVE SCENARIOS
   ============================================================ */
function renderScenarios(data) {
  const male   = data.scenario_result_male;
  const female = data.scenario_result_female;

  document.getElementById('scenario-male-month').textContent   = male.love_month;
  document.getElementById('scenario-male-text').textContent    = male.love_text;
  document.getElementById('scenario-female-month').textContent = female.love_month;
  document.getElementById('scenario-female-text').textContent  = female.love_text;
}

/* ============================================================
   RENDER: TAROT ARCANA
   ============================================================ */
function renderTarot(data) {
  const male   = data.arcane_result_male.arcane;
  const female = data.arcane_result_female.arcane;
  // [name, roman, number, type, description]
  document.getElementById('tarot-male-roman').textContent = male[1];
  document.getElementById('tarot-male-name').textContent  = male[0];
  document.getElementById('tarot-male-desc').textContent  = male[4];

  document.getElementById('tarot-female-roman').textContent = female[1];
  document.getElementById('tarot-female-name').textContent  = female[0];
  document.getElementById('tarot-female-desc').textContent  = female[4];
}

/* ============================================================
   RENDER: FATE & WILL CHARTS
   ============================================================ */
let maleChart   = null;
let femaleChart = null;

const CYCLE_LABELS = ['−6yr','−4yr','−2yr','Now','+2yr','+4yr','+6yr'];

function buildChartConfig(fateData, willData, isMale) {
  const accent = isMale ? '#4BAAD2' : '#FC468F';
  const accentFade = isMale ? 'rgba(75,170,210,0.12)' : 'rgba(252,70,143,0.12)';
  return {
    type: 'line',
    data: {
      labels: CYCLE_LABELS,
      datasets: [
        {
          label: 'Destiny',
          data: fateData,
          borderColor: accent,
          backgroundColor: accentFade,
          borderWidth: 2.5,
          fill: true,
          tension: 0.4,
          pointRadius: 4,
          pointBackgroundColor: accent,
        },
        {
          label: 'Will',
          data: willData,
          borderColor: '#aaa',
          backgroundColor: 'transparent',
          borderWidth: 1.5,
          borderDash: [5, 4],
          fill: false,
          tension: 0.4,
          pointRadius: 3,
          pointBackgroundColor: '#aaa',
        }
      ]
    },
    options: {
      responsive: true,
      plugins: {
        legend: { position: 'top', labels: { font: { size: 11 }, color: '#555' } }
      },
      scales: {
        y: {
          ticks: { font: { size: 10 }, color: '#aaa' },
          grid: { color: '#f0f0f0' }
        },
        x: {
          ticks: { font: { size: 10 }, color: '#aaa' },
          grid: { display: false }
        }
      }
    }
  };
}

function renderFawCharts(data) {
  const mFate = data.faw_result_male.fate;
  const mWill = data.faw_result_male.will;
  const fFate = data.faw_result_female.fate;
  const fWill = data.faw_result_female.will;

  if (maleChart)   { maleChart.destroy();   maleChart = null; }
  if (femaleChart) { femaleChart.destroy(); femaleChart = null; }

  maleChart   = new Chart(document.getElementById('chart-male'),   buildChartConfig(mFate, mWill, true));
  femaleChart = new Chart(document.getElementById('chart-female'), buildChartConfig(fFate, fWill, false));
}

/* ============================================================
   MAIN CALCULATE HANDLER
   ============================================================ */
function calculate() {
  const mDay   = document.getElementById('m-day').value;
  const mMonth = document.getElementById('m-month').value;
  const mYear  = document.getElementById('m-year').value;
  const fDay   = document.getElementById('f-day').value;
  const fMonth = document.getElementById('f-month').value;
  const fYear  = document.getElementById('f-year').value;

  const errEl = document.getElementById('calc-error');
  if (!mDay || !mMonth || !mYear || !fDay || !fMonth || !fYear) {
    errEl.classList.remove('hidden');
    return;
  }
  errEl.classList.add('hidden');

  const btn = document.getElementById('calc-btn');
  btn.disabled = true;
  btn.textContent = 'Calculating…';
  setProgress(20);

  try {
    setProgress(40);
    const data = calculateCompatibility(mDay, mMonth, mYear, fDay, fMonth, fYear);
    setProgress(80);

    renderChakras(data);
    renderZodiac(data);
    renderNumerology(data);
    renderPifagor(data);
    renderScenarios(data);
    renderTarot(data);
    renderFawCharts(data);

    setProgress(100);
    document.getElementById('results').classList.remove('hidden');

    setTimeout(() => {
      document.getElementById('results').scrollIntoView({ behavior: 'smooth', block: 'start' });
      setTimeout(() => setProgress(0), 600);
    }, 100);

  } catch (err) {
    console.error(err);
    errEl.textContent = 'Failed to calculate results. Please try again.';
    errEl.classList.remove('hidden');
    setProgress(0);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Calculate Compatibility';
  }
}

/* ============================================================
   INIT
   ============================================================ */
document.addEventListener('DOMContentLoaded', () => {
  populateSelects();
  document.getElementById('calc-btn').addEventListener('click', calculate);
});
