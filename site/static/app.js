const $ = s => document.querySelector(s);
let META = null, CARD = [], CUR = null, SORT = 'card', SHOWFORM = true;
const esc = s => (s ?? '').toString().replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const f1 = v => v == null ? '' : (Math.round(v * 10) / 10).toFixed(0);

// green (best) -> red (worst), ranked inside the race
function rankColours(values) {
  const vs = values.filter(v => v != null);
  const sorted = [...new Set(vs)].sort((a, b) => b - a);
  return v => {
    if (v == null || !sorted.length) return null;
    const i = sorted.indexOf(v), n = sorted.length;
    const t = n === 1 ? 0 : i / (n - 1);          // 0 best .. 1 worst
    return `hsl(${Math.round(125 * (1 - t))},${60 + 20 * Math.abs(t - .5)}%,${50 + 5 * (1 - Math.abs(t - .5) * 2)}%)`;
  };
}
// colour a single run's figure against the race's spread of ratings
function scaleColour(lo, hi) {
  return v => {
    if (v == null || hi == null) return null;
    let t = hi === lo ? 1 : (v - lo) / (hi - lo); t = Math.max(0, Math.min(1, t));
    return `hsl(${Math.round(125 * t)},65%,52%)`;
  };
}
const figHtml = (v, col) => v == null ? '<span class="fig na">–</span>' : `<span class="fig" style="background:${col(v)}">${f1(v)}</span>`;

async function init() {
  META = await (await fetch('/api/meta')).json();
  const date = META.dates.includes(META.today) ? META.today : (META.dates[0] || META.today);
  $('#dateLbl').textContent = new Date(date + 'T12:00').toLocaleDateString('en-GB', {weekday:'long', day:'numeric', month:'long', year:'numeric'});
  $('#figLbl').textContent = META.figs && META.figs.version ? `figures: ${META.figs.version} (to ${META.figs.max_date})` : 'no figures loaded';
  if (date !== META.today) $('#dateLbl').textContent += ' (latest cards – run GET_TODAYS_CARDS.bat for today)';
  CARD = await (await fetch('/api/card?date=' + date)).json();
  if (!CARD.length) { $('#main').innerHTML = '<div class="empty">No cards yet. Double-click <b>GET_TODAYS_CARDS.bat</b>, then refresh.</div>'; return; }
  const now = new Date().toTimeString().slice(0, 5);
  $('#tabs').innerHTML = CARD.map(m => `<div class="mtg"><div class="mname">${esc(m.course)}<small>${esc(m.going || '')}</small></div>` +
    m.races.map(r => `<span class="tab ${date === META.today && r.time < now ? 'done' : ''}" data-id="${r.race_id}" title="${esc(r.name)}">${r.time}<small>${esc(m.course.length > 9 ? m.course.slice(0, 7) + '.' : m.course)}</small></span>`).join('') + '</div>').join('');
  document.querySelectorAll('.tab').forEach(t => t.onclick = () => openRace(+t.dataset.id));
  const want = +location.hash.slice(1);
  const all = CARD.flatMap(m => m.races);
  const next = all.find(r => r.race_id === want) || (date === META.today ? all.slice().sort((a, b) => a.time.localeCompare(b.time)).find(r => r.time >= now) : null) || all[0];
  openRace(next.race_id);
}

async function openRace(id) {
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('on', +t.dataset.id === id));
  location.hash = id;
  $('#main').innerHTML = '<div class="empty">Loading race…</div>';
  CUR = await (await fetch('/api/race/' + id)).json();
  render();
}

function render() {
  const r = CUR, rs = r.runners, act = rs.filter(h => !h.nr);
  const cols = {};
  ['last', 'best', 'best3', 'avg3', 'best2yo', 'best3_2yo'].forEach(k => cols[k] = rankColours(act.map(h => h.ratings[k])));
  const rankCol = rankColours(act.map(h => h.rank == null ? null : -h.rank));
  const b3 = act.map(h => h.ratings.best3).filter(v => v != null);
  const runCol = scaleColour(Math.min(...b3) - 15, Math.max(...b3));
  const show2 = act.some(h => h.ratings.best2yo != null);
  const ranked = act.filter(h => h.rank).sort((a, b) => a.rank - b.rank);
  const list = SORT === 'rank' ? [...rs].sort((a, b) => (a.nr - b.nr) || ((a.rank ?? 99) - (b.rank ?? 99))) : rs;

  let h = `<div class="rhead"><h1>${r.time} ${esc(r.course)} — ${esc(r.name)}</h1>
   <div class="facts"><span>Class <b>${esc(r.race_class || '-')}</b></span><span>Distance <b>${esc(r.distance)}</b></span>
   <span>Going <b>${esc(r.going)}</b></span><span>Type <b>${esc(r.family)}${r.handicap ? ' handicap' : ''}</b></span>
   <span>Age <b>${esc(r.age_band || '')}</b></span><span>Runners <b>${r.active}</b></span><span>With figures <b>${r.rated}/${r.active}</b></span></div>
   ${ranked.length ? `<div class="ranking"><span class="muted" style="align-self:center">Figure ranking (${esc(r.rank_basis)}):</span>` +
     ranked.map(x => `<span class="chip" style="background:${rankCol(-x.rank)}">${x.rank}. ${esc(x.horse)} ${f1(r.rank_basis.startsWith('2yo') ? x.ratings.best3_2yo : x.ratings.best3)}</span>`).join('') + '</div>' : ''}
   ${r.verdict ? `<div class="verdict"><b>SL verdict:</b> ${esc(r.verdict)}</div>` : ''}</div>
   <div class="tools"><span class="legend">worst <i></i> best</span>
   <button id="sortBtn">${SORT === 'card' ? 'Sort by rating' : 'Sort by card no.'}</button>
   <button id="formBtn">${SHOWFORM ? 'Hide form' : 'Show form'}</button></div>
   <div class="wrap"><table class="card"><thead><tr><th>Rank</th><th>No (Dr)</th><th>Horse</th><th>Form</th><th>Age</th><th>Wgt</th><th>OR</th><th>Jockey / Trainer</th><th>Odds</th>
   <th class="num" title="Most recent figure">Last</th><th class="num" title="Best-3 of last 12 runs (ranking basis)">Best 3</th><th class="num" title="Average of last 3 figures">Avg 3</th><th class="num" title="Best ever figure">Best</th>${show2 ? '<th class="num" title="2yo scale: best-3 avg / best">2yo B3</th><th class="num">2yo Best</th>' : ''}</tr></thead><tbody>`;
  for (const x of list) {
    const top = x.rank === 1, rt = x.ratings;
    const hg = x.headgear ? `<span class="hg" title="headgear (1 = first time)">${esc(x.headgear)}</span>` : '';
    h += `<tr class="runner ${top ? 'top' : ''} ${x.nr ? 'nr' : ''}">
     <td class="num">${x.rank ? `<span class="rank" style="background:${rankCol(-x.rank)}">${x.rank}</span>` : '<span class="muted">–</span>'}</td>
     <td class="num"><span class="cloth">${x.cloth ?? ''}</span>${x.draw ? `<div class="draw">(${x.draw})</div>` : ''}</td>
     <td><span class="hname">${esc(x.horse)}</span>${top ? '<span class="badge">TOP RATED</span>' : ''} ${hg}
       <div class="hsub">${x.last_ran_days != null ? x.last_ran_days + ' days since last run · ' : ''}${x.runs ?? 0} runs, ${x.wins ?? 0} wins, ${x.places ?? 0} places${x.nr ? ' · NON-RUNNER' : ''}</div></td>
     <td class="form">${esc(x.form || '')}</td><td class="num">${x.age ?? ''}${esc(x.sex || '')}</td><td class="num">${esc(x.weight || '')}</td>
     <td class="num">${x.official_rating ?? '–'}</td>
     <td>${esc(x.jockey || '')}${x.jockey_claim ? ` <span class="muted">(${x.jockey_claim})</span>` : ''}<div class="hsub">${esc(x.trainer || '')}</div></td>
     <td class="num">${esc(x.odds || x.forecast_odds || '')}</td>
     <td class="num">${figHtml(rt.last, cols.last)}</td><td class="num">${figHtml(rt.best3, cols.best3)}</td>
     <td class="num">${figHtml(rt.avg3, cols.avg3)}</td><td class="num">${figHtml(rt.best, cols.best)}</td>
     ${show2 ? `<td class="num">${figHtml(rt.best3_2yo, cols.best3_2yo)}</td><td class="num">${figHtml(rt.best2yo, cols.best2yo)}</td>` : ''}</tr>`;
    if (SHOWFORM) h += `<tr class="formrow"><td colspan="${show2 ? 15 : 13}">${formTable(x.form_runs, runCol)}</td></tr>`;
  }
  h += `</tbody></table></div>
  <div class="soon"><div><b>Odds &amp; trading analysis</b>Coming later – needs backtesting first.</div>
  <div><b>Sectionals</b>Coming later – once the sectional data is scraped.</div></div>`;
  $('#main').innerHTML = h;
  $('#sortBtn').onclick = () => { SORT = SORT === 'card' ? 'rank' : 'card'; render(); };
  $('#formBtn').onclick = () => { SHOWFORM = !SHOWFORM; render(); };
}

function formTable(runs, col) {
  if (!runs || !runs.length) return '<span class="muted">No previous runs.</span>';
  return `<table class="runs"><tr><th>Date</th><th>Course</th><th>Dist</th><th>Going</th><th>Type</th><th>Cl</th><th>Pos</th><th>Btn</th><th>SP</th><th>OR</th><th>Fig</th><th>Comment</th></tr>` +
    runs.map(r => `<tr><td>${fmtDate(r.date)}</td><td>${esc(r.course)}</td><td>${esc(r.dist)}</td><td>${esc(shortGoing(r.going))}</td><td>${esc(r.type || '')}</td>
      <td>${esc(r.cls || '')}</td><td class="pos ${r.pos === '1' ? 'won' : ''}">${esc(r.pos)}${r.ran ? '/' + r.ran : ''}</td>
      <td>${r.btn == null ? '' : (r.pos === '1' ? '–' : r.btn)}</td><td>${esc(r.sp || '')}</td><td>${r.or ?? ''}</td>
      <td>${figHtml(r.fig, col)}</td><td class="cmt" title="${esc(r.comment || '')}"><div>${esc(r.comment || '')}</div></td></tr>`).join('') + '</table>';
}
const fmtDate = d => { const x = new Date(d + 'T12:00'); return x.toLocaleDateString('en-GB', {day: '2-digit', month: 'short', year: '2-digit'}); };
const shortGoing = g => (g || '').replace(/\s*\(.*\)/, '').replace('Good to ', 'Gd/').replace('Standard', 'Std');

$('#themeBtn').onclick = () => { document.body.classList.toggle('light'); localStorage.theme = document.body.classList.contains('light') ? 'light' : 'dark'; };
if (localStorage.theme === 'light') document.body.classList.add('light');
init();
window.addEventListener('hashchange', () => { const id = +location.hash.slice(1); if (id && (!CUR || CUR.race_id !== id)) openRace(id); });
