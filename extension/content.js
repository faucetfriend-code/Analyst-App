/**
 * Analyst Trade Panel — content script injected into tradingview.com
 *
 * Reads the current chart symbol from the page URL/title, then injects a
 * collapsible trade ticket panel on the right side of the screen.
 * All API calls go to http://localhost:5051 (the Analyst App backend).
 */

const API = 'http://localhost:5051';
let panelOpen = false;
let dir = null;
let entryMode = 'market';
let priceInterval = null;
let lastPrice = null;
let exchanges = [];
let defaultExchange = 'blofin';

// ── Detect symbol from TradingView URL / page title ───────────────────────
function detectSymbol() {
  // URL: /chart/?symbol=BINANCE:BTCUSDT  or  /symbols/BINANCE-BTCUSDT/
  const urlMatch = window.location.search.match(/[?&]symbol=([^&]+)/i)
    || window.location.pathname.match(/\/symbols\/[^/]+-([A-Z]+USDT)\//i);
  if (urlMatch) {
    const raw = decodeURIComponent(urlMatch[1]);
    const base = raw.replace(/.*[:]/,'').replace('USDT','');
    return base + '-USDT';
  }
  // Title: "BTCUSDT · 45000 · BINANCE — TradingView"
  const titleMatch = document.title.match(/^([A-Z]+)USDT\b/);
  if (titleMatch) return titleMatch[1] + '-USDT';
  return 'BTC-USDT';
}

// Watch for TradingView URL changes (SPA navigation)
let lastUrl = location.href;
new MutationObserver(() => {
  if (location.href !== lastUrl) {
    lastUrl = location.href;
    setTimeout(() => {
      const sym = detectSymbol();
      const inp = document.getElementById('ap-symbol');
      if (inp && inp.value !== sym) {
        inp.value = sym;
        document.getElementById('ap-sym-display').textContent = sym;
        startPrice();
      }
    }, 800);
  }
}).observe(document, { subtree: true, childList: true });

// ── Build panel HTML ──────────────────────────────────────────────────────
function buildPanel() {
  const sym = detectSymbol();

  // Tab (the clickable edge handle)
  const tab = document.createElement('div');
  tab.id = 'analyst-panel-tab';
  tab.textContent = 'TRADE';
  tab.title = 'Open Analyst Trade Panel';
  tab.addEventListener('click', togglePanel);
  document.body.appendChild(tab);

  // Panel
  const panel = document.createElement('div');
  panel.id = 'analyst-panel';
  panel.innerHTML = `
    <div class="ap-header">
      <span class="ap-brand">ANALYST</span>
      <span class="ap-sym-display" id="ap-sym-display">${sym}</span>
      <button class="ap-close" id="ap-close" title="Close panel">✕</button>
    </div>
    <div class="ap-body" id="ap-body">
      <div id="ap-content">
        <div class="ap-price">
          <span class="ap-price-val" id="ap-price">—</span>
          <span class="ap-price-chg" id="ap-price-chg"></span>
        </div>

        <div class="ap-field">
          <div class="ap-fl">Exchange</div>
          <select id="ap-exchange" class="ap-fi" onchange="apExChange()">
            <option value="">Loading…</option>
          </select>
        </div>

        <div class="ap-field">
          <div class="ap-fl">Symbol</div>
          <input id="ap-symbol" class="ap-fi" value="${sym}" list="ap-sym-list"
                 autocomplete="off" style="text-transform:uppercase"
                 oninput="apSymChange()" onchange="apSymChange()">
          <datalist id="ap-sym-list"></datalist>
        </div>

        <div class="ap-dir-row">
          <div class="ap-dir long-idle"  id="ap-long"  onclick="apDir('long')">▲ LONG</div>
          <div class="ap-dir short-idle" id="ap-short" onclick="apDir('short')">▼ SHORT</div>
        </div>

        <div class="ap-toggle">
          <div class="ap-tgl active" id="ap-tgl-mkt" onclick="apEntry('market')">Market</div>
          <div class="ap-tgl"        id="ap-tgl-lim" onclick="apEntry('limit')">Limit</div>
        </div>
        <div id="ap-limit-wrap" style="display:none;">
          <input id="ap-entry" class="ap-fi" type="number" step="any" placeholder="Limit price">
        </div>

        <div class="ap-field">
          <div class="ap-fl">Stop Loss</div>
          <input id="ap-sl" class="ap-fi" type="number" step="any" placeholder="SL price">
        </div>

        <div class="ap-fl" style="margin-bottom:4px;">Take Profit</div>
        <div id="ap-tp-rows">
          <div class="ap-tp-row">
            <span class="ap-tp-lbl">TP 1</span>
            <input class="ap-fi ap-tp" type="number" step="any" placeholder="TP price">
          </div>
        </div>
        <button class="ap-add-tp" id="ap-add-tp" onclick="apAddTP()">+ Add TP</button>

        <div class="ap-2col">
          <div>
            <div class="ap-fl">Risk %</div>
            <input id="ap-risk" class="ap-fi" type="number" step="0.1" min="0.1" max="10" value="1">
          </div>
          <div>
            <div class="ap-fl">Leverage</div>
            <input id="ap-lev" class="ap-fi" type="number" step="1" min="1" max="200" value="75">
          </div>
        </div>

        <button id="ap-fire" onclick="apFire()">FIRE</button>
        <div class="ap-result" id="ap-result"></div>

        <div class="ap-dry">
          <input type="checkbox" id="ap-dry">
          <label for="ap-dry">Dry run — Discord only</label>
        </div>
      </div>
    </div>
  `;
  document.body.appendChild(panel);

  document.getElementById('ap-close').addEventListener('click', togglePanel);
}

// ── Panel toggle ──────────────────────────────────────────────────────────
function togglePanel() {
  const panel = document.getElementById('analyst-panel');
  const tab   = document.getElementById('analyst-panel-tab');
  panelOpen = !panelOpen;
  panel.classList.toggle('open', panelOpen);
  tab.style.right = panelOpen ? '300px' : '0';
  if (panelOpen) {
    loadExchanges();
    startPrice();
  } else {
    if (priceInterval) clearInterval(priceInterval);
  }
}

// ── Load analyst's exchanges from backend ─────────────────────────────────
async function loadExchanges() {
  try {
    // Fetch the trader page to extract the analyst's exchanges
    // (We use the /api/positions call as an auth check — if it returns 401
    //  the analyst isn't logged in on localhost:5051 and we show a prompt.)
    const posResp = await fetch(`${API}/api/positions`, {credentials: 'include'});
    if (posResp.status === 401) {
      showNotLoggedIn();
      return;
    }

    // Get symbol list for the default exchange to also populate the exchange selector
    // We derive the exchange list from which symbols endpoint responds
    const labels = {blofin: 'BloFin', mexc: 'MEXC', bybit: 'Bybit'};
    const sel = document.getElementById('ap-exchange');
    if (!sel) return;

    // Try to fetch symbols for each exchange to discover which are configured
    const exList = [];
    for (const ex of ['blofin', 'mexc', 'bybit']) {
      try {
        const r = await fetch(`${API}/api/symbols/${ex}`, {credentials: 'include'});
        if (r.ok) {
          const syms = await r.json();
          if (syms.length > 0) {
            exList.push(ex);
            // Populate symbol datalist from first successful exchange
            if (exList.length === 1) {
              const dl = document.getElementById('ap-sym-list');
              if (dl) dl.innerHTML = syms.map(s => `<option value="${s}">`).join('');
            }
          }
        }
      } catch(e) {}
    }

    exchanges = exList;
    if (sel) {
      sel.innerHTML = exList.length
        ? exList.map(e => `<option value="${e}">${labels[e]||e}</option>`).join('')
        : '<option value="">No exchanges configured</option>';
      defaultExchange = exList[0] || 'blofin';

      // Load default risk/leverage from backend (grab from positions page meta)
      // For now just use sensible defaults already set in HTML
    }

  } catch(e) {
    showNotLoggedIn();
  }
}

function showNotLoggedIn() {
  const body = document.getElementById('ap-content');
  if (body) body.innerHTML = `
    <div class="ap-not-logged">
      <p>Sign in to the Analyst App first, then come back to TradingView.</p>
      <br>
      <a href="${API}/login" target="_blank">Open Analyst App login →</a>
    </div>`;
}

// ── Symbol ────────────────────────────────────────────────────────────────
function apSymChange() {
  const val = document.getElementById('ap-symbol')?.value?.trim()?.toUpperCase() || '';
  const disp = document.getElementById('ap-sym-display');
  if (disp) disp.textContent = val || '—';
  startPrice();
}

function apExChange() { startPrice(); }

// ── Price ─────────────────────────────────────────────────────────────────
function startPrice() {
  if (priceInterval) clearInterval(priceInterval);
  fetchPrice();
  priceInterval = setInterval(fetchPrice, 2000);
}
async function fetchPrice() {
  const sym = document.getElementById('ap-symbol')?.value?.trim();
  const ex  = document.getElementById('ap-exchange')?.value;
  if (!sym || !ex) return;
  try {
    const r = await fetch(`${API}/api/price/${encodeURIComponent(sym)}?exchange=${ex}`, {credentials: 'include'});
    const d = await r.json();
    if (!d.price) return;
    const el  = document.getElementById('ap-price');
    const chg = document.getElementById('ap-price-chg');
    if (!el) return;
    el.textContent = '$' + Number(d.price).toLocaleString('en-US',
      {minimumFractionDigits:2, maximumFractionDigits:6});
    if (lastPrice !== null && lastPrice !== d.price) {
      const up = d.price > lastPrice;
      chg.textContent = up ? ' ▲' : ' ▼';
      chg.className = 'ap-price-chg ' + (up ? 'ap-up' : 'ap-down');
      setTimeout(() => { if(chg) { chg.textContent = ''; chg.className = 'ap-price-chg'; } }, 1500);
    }
    lastPrice = d.price;
  } catch(e) {}
}

// ── Direction ─────────────────────────────────────────────────────────────
function apDir(d) {
  dir = d;
  document.getElementById('ap-long').className  = 'ap-dir ' + (d==='long'  ? 'long-active'  : 'long-idle');
  document.getElementById('ap-short').className = 'ap-dir ' + (d==='short' ? 'short-active' : 'short-idle');
  const btn = document.getElementById('ap-fire');
  btn.className = d === 'long' ? 'ready-long' : 'ready-short';
  btn.textContent = d === 'long' ? '▲ FIRE LONG' : '▼ FIRE SHORT';
}

// ── Entry mode ────────────────────────────────────────────────────────────
function apEntry(mode) {
  entryMode = mode;
  document.getElementById('ap-tgl-mkt').classList.toggle('active', mode==='market');
  document.getElementById('ap-tgl-lim').classList.toggle('active', mode==='limit');
  document.getElementById('ap-limit-wrap').style.display = mode==='limit' ? 'block' : 'none';
}

// ── TPs ───────────────────────────────────────────────────────────────────
function apAddTP() {
  const rows = document.getElementById('ap-tp-rows');
  const n = rows.querySelectorAll('.ap-tp-row').length;
  if (n >= 5) return;
  const d = document.createElement('div');
  d.className = 'ap-tp-row';
  d.innerHTML = `<span class="ap-tp-lbl">TP ${n+1}</span>
    <input class="ap-fi ap-tp" type="number" step="any" placeholder="TP price">
    <button class="ap-rm" onclick="apRmTP(this)">×</button>`;
  rows.appendChild(d);
  if (n+1 >= 5) document.getElementById('ap-add-tp').style.display = 'none';
}
function apRmTP(btn) {
  btn.closest('.ap-tp-row').remove();
  document.getElementById('ap-add-tp').style.display = 'block';
  document.querySelectorAll('#ap-tp-rows .ap-tp-lbl').forEach((l,i) => l.textContent = `TP ${i+1}`);
}

// ── Fire ──────────────────────────────────────────────────────────────────
async function apFire() {
  const btn = document.getElementById('ap-fire');
  const res = document.getElementById('ap-result');
  if (!dir) { apFlash('err', 'Select LONG or SHORT'); return; }
  const sym = document.getElementById('ap-symbol')?.value?.trim();
  if (!sym) { apFlash('err', 'Enter a symbol'); return; }

  const exchange = document.getElementById('ap-exchange')?.value;
  const sl    = parseFloat(document.getElementById('ap-sl')?.value)    || null;
  const entry = entryMode === 'limit' ? (parseFloat(document.getElementById('ap-entry')?.value) || null) : null;
  const tps   = Array.from(document.querySelectorAll('.ap-tp')).map(i=>parseFloat(i.value)).filter(v=>!isNaN(v)&&v>0);
  const lev   = parseInt(document.getElementById('ap-lev')?.value)   || 75;
  const risk  = parseFloat(document.getElementById('ap-risk')?.value) / 100 || 0.01;
  const dry   = document.getElementById('ap-dry')?.checked || false;

  btn.disabled = true;
  const orig = btn.textContent;
  btn.textContent = '…';

  try {
    const r = await fetch(`${API}/api/fire`, {
      method: 'POST',
      credentials: 'include',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ exchange, symbol: sym, side: dir,
        entry, sl, tps, leverage: lev, risk_pct: risk,
        notes: '', chart_png_b64: '', dry_run: dry })
    });
    const d = await r.json();
    btn.disabled = false; btn.textContent = orig;
    if (d.ok) {
      apFlash('ok', dry
        ? `Dry run · Discord ${d.discord_ok?'✓':'✗'}`
        : `Fired${d.order_id?' #'+d.order_id:''} · Discord ${d.discord_ok?'✓':'✗'}`);
    } else {
      apFlash('err', d.error || 'Error');
    }
  } catch(e) {
    btn.disabled = false; btn.textContent = orig;
    apFlash('err', 'Cannot reach Analyst App — is it running?');
  }
}

function apFlash(type, msg) {
  const btn = document.getElementById('ap-fire');
  const el  = document.getElementById('ap-result');
  if (!el || !btn) return;
  el.textContent = msg; el.className = 'ap-result ' + type;
  btn.classList.add(type==='ok' ? 'flash-ok' : 'flash-err');
  setTimeout(() => { if(btn) btn.classList.remove('flash-ok','flash-err'); }, 1400);
}

// ── Init ──────────────────────────────────────────────────────────────────
// Wait for TradingView's layout to settle before injecting
function init() {
  if (document.getElementById('analyst-panel')) return; // already injected
  buildPanel();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  // Small delay so TV's layout renders first (avoids z-index fights)
  setTimeout(init, 1500);
}
