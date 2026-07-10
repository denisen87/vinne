/* =========================================================
   script.js (FULL, CLEAN, SINGLE-FILE VERSION)
   - Equity Calculator -> /equity
   - Live Coach polling -> /players/live_hint/3bet/auto
   - Villain profile inline -> /players/{name}/profile
   - "Denne Ã¸kten" hand log (auto) -> /actions?hand_id=...
   - Hand Viewer -> /actions?hand_id=...
   - Player Profile -> /players/{name}/profile
   - Dashboard tabs + Session Overview table -> /sessions/{id}/hud
   ========================================================= */

// ------------------------------
// Small utils
// ------------------------------
function $(id) { return document.getElementById(id); }
function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function extractCaptureName(text) {
  const m = String(text || "").match(/capture=([^;)\s]+\.png)/i);
  return m ? m[1] : "";
}

function renderLiveStatusWithCapture(text) {
  const capture = extractCaptureName(text);
  if (!capture) return escapeHtml(text);
  const before = text.slice(0, text.indexOf(`capture=${capture}`));
  const after = text.slice(text.indexOf(`capture=${capture}`) + `capture=${capture}`.length);
  const command = `& "C:\\Program Files\\Python311\\python.exe" .github\\vinne\\screen_reader.py --calibrate-file "fronted\\calibration_captures\\${capture}" "SKRIV_KORT_HER"`;
  return `${escapeHtml(before)}capture=<code style="user-select:all; background:#fff7ed; border:1px solid #fed7aa; border-radius:4px; padding:1px 4px;">${escapeHtml(capture)}</code><button type="button" id="copyLiveCapture" data-capture="${escapeHtml(capture)}" title="Kopier capture-filnavn" style="margin-left:6px; padding:2px 8px; border:1px solid #d6d3d1; background:#fff; border-radius:4px; cursor:pointer; font-size:11px;">Kopier fil</button>${escapeHtml(after)}<div style="margin-top:6px;"><code style="user-select:all; display:inline-block; max-width:100%; overflow-wrap:anywhere; background:#f8fafc; border:1px solid #cbd5e1; border-radius:4px; padding:4px 6px;">${escapeHtml(command)}</code><button type="button" id="copyLiveCalibrateCommand" data-command="${escapeHtml(command)}" title="Kopier kalibreringskommando" style="margin-left:6px; padding:3px 8px; border:1px solid #d6d3d1; background:#fff; border-radius:4px; cursor:pointer; font-size:11px;">Kopier kommando</button></div>`;
}

function wireLiveCaptureButtons() {
  const copyCaptureBtn = $("copyLiveCapture");
  if (copyCaptureBtn) copyCaptureBtn.addEventListener("click", async () => {
    const capture = copyCaptureBtn.dataset.capture || "";
    if (!capture) return;
    try {
      await navigator.clipboard.writeText(capture);
      copyCaptureBtn.innerText = "Kopiert";
    } catch (e) {
      window.prompt("Kopier capture-filnavn:", capture);
    }
  });

  const copyCommandBtn = $("copyLiveCalibrateCommand");
  if (copyCommandBtn) copyCommandBtn.addEventListener("click", async () => {
    const command = copyCommandBtn.dataset.command || "";
    if (!command) return;
    try {
      await navigator.clipboard.writeText(command);
      copyCommandBtn.innerText = "Kopiert";
    } catch (e) {
      window.prompt("Kopier kalibreringskommando:", command);
    }
  });
}

function apiBase() {
  // Dashboard input if you have it; else fallback to backend
  return $("apiBase")?.value?.trim() || "http://127.0.0.1:8010";
}

// Global variables for live game polling
let currentGamePoller = null;
let lastGameState = { hero: "", board: "" };
let lastAutoFeatureHandId = null;
let autoEquityRunning = false;
let pollInProgress = false;
let manualLiveMode = false;
let liveScreenActive = false;
let lastLiveHeroText = "";
let lastLiveBoardText = "";
let lastManualHeroText = "";
let lastManualBoardText = "";
let lastLiveCardsStatus = "Livekort: ikke lest ennå.";
let lastLiveCardsSeenAt = 0;
let pendingScreenHeroText = "";
let pendingScreenHeroCount = 0;
let startingHandsInFlight = false;
let startingHandsTimer = null;
let startingHandsFallbackTimer = null;
let lastStartingHandsRefreshKey = "";
let lastSavedLiveCardsKey = "";
let lastLiveCardsMeta = {};
let lastLiveCardsGameKey = "";
let knownPlayerNames = [];
let playerNamesLoaded = false;
let playerNameSearchTimer = null;
let playerProfileData = null;
let playerProfileEquityTimer = null;
let lastPlayerProfileEquityKey = "";
let ppPickerRank = "A";
let ppPickerTarget = "hero";
let ppHeroCards = [];
let ppBoardCards = [];
let ppEquityManualMode = false;
let ppLastDecisionState = null;
let backendCardHistory = [];
let backendCardHistoryLoadedAt = 0;
let backendCardHistoryInFlight = false;
let backendCardHistoryStartedAt = 0;
let backendCardHistoryLastAttemptAt = 0;
let backendCardHistorySessionId = "";
let backendCardHistoryWatchdogTimer = null;
let backendCardHistoryPendingRender = false;
let backendCardHistoryError = "";
const BACKEND_CARD_HISTORY_TTL_MS = 3000;

function clearMainHeroForNewLiveHand() {
  const heroEl = $("hero");
  const heroRegisterInput = $("heroRegisterInput");
  if (heroEl) heroEl.value = "";
  if (heroRegisterInput) heroRegisterInput.value = "";
  lastManualHeroText = "";
  heroCorrectionCards = [];
  if (typeof renderHeroCorrection === "function") renderHeroCorrection();
}

function dashSessionId() {
  const v = $("dashSession")?.value?.trim();
  return v ? Number(v) : null;
}
function dashHero() {
  return $("dashHero")?.value?.trim() || $("lhPlayer")?.value?.trim() || "angryshark";
}

function setDashStatus(t) {
  const el = $("dashStatus");
  if (el) el.innerText = t || "";
}

function syncActiveSessionFields(sessionId, source = "live") {
  const value = String(sessionId || "").trim();
  if (!value || !Number.isInteger(Number(value)) || Number(value) <= 0) return false;
  ["dashSession", "lhSession", "mtSession", "spSession", "ppSession", "shSession"].forEach(id => {
    const el = $(id);
    if (el) el.value = value;
  });
  lastGameState.session_id = value;
  const status = $("dashStatus");
  if (status) status.innerText = `Aktiv session ${value} (${source})`;
  return true;
}

function mergeKnownPlayerNames(names) {
  const seen = new Set(knownPlayerNames.map(n => n.toLowerCase()));
  (names || []).forEach(raw => {
    const name = String(raw || "").trim();
    const key = name.toLowerCase();
    if (!name || seen.has(key)) return;
    seen.add(key);
    knownPlayerNames.push(name);
  });
  knownPlayerNames.sort((a, b) => a.localeCompare(b));

  const datalist = $("boardPlayersDatalist");
  if (datalist) {
    datalist.innerHTML = "";
    knownPlayerNames.forEach(name => {
      const option = document.createElement("option");
      option.value = name;
      datalist.appendChild(option);
    });
  }
}

async function loadKnownPlayerNames(opts = {}) {
  if (playerNamesLoaded && !opts.force) return;
  const params = new URLSearchParams();
  params.set("limit", "500");
  const sid = dashSessionId() || $("lhSession")?.value?.trim() || $("ppSession")?.value?.trim();
  if (sid && Number.isInteger(Number(sid)) && Number(sid) > 0) params.set("session_id", String(Number(sid)));

  try {
    let res = await fetch(`${apiBase()}/players/names?${params.toString()}`);
    let data = res.ok ? await res.json() : { players: [] };
    let names = (data.players || []).map(p => p.name);

    if (sid && names.length < 3) {
      res = await fetch(`${apiBase()}/players/names?limit=500`);
      data = res.ok ? await res.json() : { players: [] };
      names = names.concat((data.players || []).map(p => p.name));
    }

    mergeKnownPlayerNames(names);
    playerNamesLoaded = true;
  } catch (e) {
    console.warn("Could not load player names", e);
  }
}

function searchKnownPlayerNames(query) {
  const q = String(query || "").trim();
  if (q.length < 2) return;
  if (playerNameSearchTimer) clearTimeout(playerNameSearchTimer);
  playerNameSearchTimer = setTimeout(async () => {
    try {
      const params = new URLSearchParams();
      params.set("q", q);
      params.set("limit", "50");
      const res = await fetch(`${apiBase()}/players/names?${params.toString()}`);
      if (!res.ok) return;
      const data = await res.json();
      mergeKnownPlayerNames((data.players || []).map(p => p.name));
    } catch (e) {
      console.warn("Could not search player names", e);
    }
  }, 200);
}

function bestPlayerNameMatch(value) {
  const needle = String(value || "").trim().toLowerCase();
  if (!needle) return "";
  const exact = knownPlayerNames.find(n => n.toLowerCase() === needle);
  if (exact) return exact;
  return (
    knownPlayerNames.find(n => n.toLowerCase().startsWith(needle)) ||
    knownPlayerNames.find(n => n.toLowerCase().includes(needle)) ||
    ""
  );
}

function autocompletePlayerField(el) {
  if (!el) return;
  const match = bestPlayerNameMatch(el.value);
  if (match) el.value = match;
}

function profileRangeFallback(playerType) {
  const ranges = {
    NIT: "AA,KK,QQ,JJ,TT,99,AKs,AQs,AJs,AKo,AQo",
    TAG: "AA,KK,QQ,JJ,TT,99,88,77,66,55,AKs,AQs,AJs,ATs,AKo,AQo,KQs,KJs",
    LAG: "AA,KK,QQ,JJ,TT,99,88,77,66,55,44,33,22,AKs,AQs,AJs,ATs,A9s,AKo,AQo,AJo,KQs,KJs,KTs,QJs,QTs,JTs,T9s,98s",
    FISH: "AA,KK,QQ,JJ,TT,99,88,77,66,55,44,33,22,AKs,AQs,AJs,ATs,A9s,A8s,A7s,AKo,AQo,AJo,ATo,KQs,KJs,KTs,QJs,QTs,JTs,T9s,98s",
    TP: "AA,KK,QQ,JJ,TT,99,88,77,AKs,AQs,AJs,ATs,AKo,AQo,KQs,KJs,QJs",
    LP: "AA,KK,QQ,JJ,TT,99,88,77,66,55,44,33,22,AKs,AQs,AJs,ATs,A9s,A8s,AKo,AQo,AJo,ATo,KQs,KJs,KTs,QJs,QTs,JTs",
    LOW_SAMPLE: "AA,KK,QQ,JJ,TT,99,88,77,66,55,AKs,AQs,AJs,KQs,KJs,AKo,AQo",
    UNKNOWN: "AA,KK,QQ,JJ,TT,99,88,77,66,55,AKs,AQs,AJs,KQs,KJs,AKo,AQo"
  };
  return ranges[String(playerType || "UNKNOWN").toUpperCase()] || ranges.UNKNOWN;
}

function setProfileEquityStatus(text) {
  const el = $("ppEquityStatus");
  if (el) el.innerText = text || "";
}

function profileNumber(value, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function stagePressureMultiplier(stage) {
  if (stage === "river") return 1.08;
  if (stage === "turn") return 1.03;
  if (stage === "flop") return 0.98;
  return 0.95;
}

function profileHistoryMatchSignal(heroCards, boardCards) {
  const hero = (heroCards || []).map(convertBetSolidCard).filter(isCard).slice(0, 2);
  const board = (boardCards || []).map(convertBetSolidCard).filter(isCard).slice(0, 5);
  if (hero.length !== 2 || !board.length) {
    return { sameHeroHands: 0, hitHands: 0, currentHits: 0, hitRate: 0 };
  }
  const heroKey = heroComboKey(hero);
  const boardRanks = new Set(board.map(card => card[0]));
  const currentHits = hero.filter(card => boardRanks.has(card[0])).length;
  let sameHeroHands = 0;
  let hitHands = 0;
  combinedCardHistory().forEach(entry => {
    const entryHero = (entry.hero || []).map(convertBetSolidCard).filter(isCard).slice(0, 2);
    if (entryHero.length !== 2 || heroComboKey(entryHero) !== heroKey) return;
    const entryBoard = (entry.board || []).map(convertBetSolidCard).filter(isCard).slice(0, 5);
    if (!entryBoard.length) return;
    sameHeroHands += 1;
    const ranks = new Set(entryBoard.map(card => card[0]));
    if (hero.some(card => ranks.has(card[0]))) hitHands += 1;
  });
  return {
    sameHeroHands,
    hitHands,
    currentHits,
    hitRate: sameHeroHands ? hitHands / sameHeroHands : 0
  };
}

function buildProfileDecision(data) {
  const winPct = profileNumber(data?.winPct, 0);
  const tiePct = profileNumber(data?.tiePct, 0);
  const equity = winPct + (tiePct * 0.5);
  const pot = Math.max(0, profileNumber($("ppPotChips")?.value, 0));
  const call = Math.max(0, profileNumber($("ppCallChips")?.value, 0));
  const stack = Math.max(0, profileNumber($("ppStackChips")?.value, 0));
  const betPct = stack > 0 && call > 0 ? (call / stack) * 100 : 0;
  const potOdds = call > 0 ? (call / Math.max(pot + call, 1)) * 100 : 0;
  const stage = data?.stage || "preflop";
  const profile = data?.profile || {};
  const strength = profileNumber(profile.strength_score, 50);
  const aggression = profileNumber(profile.aggression_score, 50);
  const fundamentals = profileNumber(profile.fundamentals_score, 50);
  const sampleHands = profileNumber(profile.results?.hands, 0);
  const sampleWeight = Math.min(1, sampleHands / 50);
  const historySignal = data?.historySignal || profileHistoryMatchSignal(data?.heroCards, data?.boardCards);

  let required = potOdds * stagePressureMultiplier(stage);
  required += ((strength - 50) / 100) * 5 * sampleWeight;
  required += ((fundamentals - 50) / 100) * 2 * sampleWeight;
  required -= ((aggression - 50) / 100) * 3 * sampleWeight;
  if (betPct >= 35) required += 5;
  else if (betPct >= 20) required += 2.5;
  else if (betPct > 0 && betPct <= 8) required -= 1.5;
  if (historySignal.currentHits > 0 && historySignal.sameHeroHands >= 5) {
    required -= Math.min(3, historySignal.hitRate * 4);
  }
  required = Math.max(0, Math.min(95, required));

  const edge = equity - required;
  let action = "CALL";
  let color = "#b45309";
  let tone = "#fffbeb";
  let confidence = Math.min(95, Math.max(35, Math.round(Math.abs(edge) * 5 + sampleWeight * 20)));
  let reason = "Tett spot: equity er nær kravet fra pot-odds og profil.";

  if (!call) {
    if (equity >= 58 && aggression < 70) {
      action = "BET";
      color = "#15803d";
      tone = "#ecfdf5";
      reason = "Ingen call-pris satt. Equity er sterk nok til value/semi-bluff mot profilen.";
    } else if (equity >= 50) {
      action = "CALL";
      reason = "Ingen call-pris satt. Ta billig showdown/check-call oftere enn å bygge stor pot.";
    } else {
      action = "FOLD";
      color = "#b91c1c";
      tone = "#fef2f2";
      reason = "Ingen call-pris satt og equity er lav mot range/profil.";
    }
  } else if (edge >= 8) {
    action = "BET";
    color = "#15803d";
    tone = "#ecfdf5";
    reason = "Equity ligger tydelig over kravet. Bet/raise er ok når sizing ikke er for stor.";
  } else if (edge >= -3) {
    action = "CALL";
    color = "#b45309";
    tone = "#fffbeb";
    reason = "Equity er nær pot-odds. Call er best før mer informasjon.";
  } else {
    action = "FOLD";
    color = "#b91c1c";
    tone = "#fef2f2";
    reason = "Equity ligger under kravet når pot-odds, sizing og profil vektes sammen.";
  }

  return {
    action, color, tone, confidence, reason,
    equity, required, edge, pot, call, stack, betPct, potOdds,
    profileText: `styrke ${Math.round(strength)}, aggro ${Math.round(aggression)}, sample ${sampleHands}`,
    historyText: historySignal.sameHeroHands
      ? `${historySignal.hitHands}/${historySignal.sameHeroHands} samme hero-hender traff board`
      : "ingen samme hero-historikk"
  };
}

function renderProfileDecisionPanel() {
  const out = $("ppDecisionOut");
  if (!out) return;
  if (!ppLastDecisionState) {
    out.innerHTML = `<div style="opacity:.65;">Beregn equity først. Fyll pot/call/stack for pot-odds.</div>`;
    return;
  }
  const d = buildProfileDecision(ppLastDecisionState);
  out.innerHTML = `
    <div style="border:1px solid #ddd; background:${d.tone}; padding:10px; border-radius:6px;">
      <div style="display:flex; justify-content:space-between; gap:10px; align-items:center;">
        <div>
          <div style="font-size:11px; opacity:.65;">Forslag</div>
          <div style="font-size:24px; font-weight:900; color:${d.color};">${escapeHtml(d.action)}</div>
        </div>
        <div style="text-align:right; font-size:12px;">
          <div><b>Equity:</b> ${d.equity.toFixed(1)}%</div>
          <div><b>Krav:</b> ${d.required.toFixed(1)}%</div>
          <div><b>Edge:</b> ${d.edge >= 0 ? "+" : ""}${d.edge.toFixed(1)}%</div>
        </div>
      </div>
      <div style="margin-top:8px; font-size:12px; line-height:1.35;">${escapeHtml(d.reason)}</div>
      <div style="margin-top:6px; font-size:11px; opacity:.72;">
        Call/bet: ${d.call.toLocaleString()} chips (${d.betPct.toFixed(1)}% av stack) |
        Pot odds: ${d.potOdds.toFixed(1)}% |
        Profil: ${escapeHtml(d.profileText)} |
        Historikk: ${escapeHtml(d.historyText)} |
        Konfidens: ${d.confidence}%
      </div>
    </div>
  `;
}

async function syncProfileEquityLiveCards(opts = {}) {
  const heroEl = $("ppHeroCards");
  const boardEl = $("ppBoardCards");
  if (!heroEl || !boardEl) return false;
  if (ppEquityManualMode && !opts.force) return false;

  try {
    const res = await fetch(`${apiBase()}/live-cards?ts=${Date.now()}`);
    if (!res.ok) return false;
    const data = await res.json();
    const heroText = normalizeSpaces(data.hero_cards || data.hero || "");
    const boardText = normalizeSpaces(data.board || "");
    if (heroText) heroEl.value = heroText;
    boardEl.value = boardText;
    syncProfileEquityPickerFromInputs({ manual: false });

    if (Array.isArray(data.players) && data.players.length) {
      mergeKnownPlayerNames(data.players.map(p => p.name || p.player_name));
    }

    if (!opts.silent) setProfileEquityStatus("Live kort hentet.");
    return Boolean(heroText || boardText);
  } catch (e) {
    if (!opts.silent) setProfileEquityStatus("Klarte ikke hente live kort.");
    return false;
  }
}

async function calculateProfileEquity(opts = {}) {
  const out = $("ppEquityOut");
  const heroText = normalizeSpaces($("ppHeroCards")?.value || "");
  const boardText = normalizeSpaces($("ppBoardCards")?.value || "");
  const rangeText = normalizeSpaces($("ppVillainRange")?.value || "");
  const iters = Math.max(500, Math.min(Number($("ppEquityIters")?.value || 12000), 60000));
  const player = playerProfileData?.player_name || $("ppPlayer")?.value?.trim() || "spiller";

  if (!out) return;
  const heroCards = parseCards(heroText);
  const boardCards = parseCards(boardText);
  const all = heroCards.concat(boardCards);

  if (heroCards.length !== 2 || !heroCards.every(isCard)) {
    ppLastDecisionState = null;
    renderProfileDecisionPanel();
    out.innerHTML = `<div style="opacity:.7;">Venter på 2 gyldige hero-kort.</div>`;
    return;
  }
  if (boardCards.length > 5 || !boardCards.every(isCard)) {
    ppLastDecisionState = null;
    renderProfileDecisionPanel();
    out.innerHTML = `<div style="color:#b91c1c;">Board kan ha maks 5 gyldige kort.</div>`;
    return;
  }
  if (new Set(all).size !== all.length) {
    ppLastDecisionState = null;
    renderProfileDecisionPanel();
    out.innerHTML = `<div style="color:#b91c1c;">Samme kort finnes flere steder.</div>`;
    return;
  }

  const key = `${heroCards.join(" ")}|${boardCards.join(" ")}|${rangeText}|${iters}`;
  if (opts.auto && key === lastPlayerProfileEquityKey) return;
  lastPlayerProfileEquityKey = key;

  setProfileEquityStatus("Beregner...");
  out.innerHTML = `<div style="opacity:.7;">Kjører simulering mot ${escapeHtml(player)}...</div>`;

  try {
    const res = await fetch(`${apiBase()}/equity`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        hero: heroCards,
        board: boardCards,
        villains: 1,
        iters,
        ranges: rangeText
      })
    });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    const win = Math.round(data.win * 1000) / 10;
    const tie = Math.round(data.tie * 1000) / 10;
    const lose = Math.round(data.lose * 1000) / 10;
    const stage = boardCards.length === 0 ? "preflop" : boardCards.length === 3 ? "flop" : boardCards.length === 4 ? "turn" : "river";

    out.innerHTML = `
      <div style="display:grid; grid-template-columns:repeat(3, minmax(90px, 1fr)); gap:8px; max-width:520px;">
        <div style="border:1px solid #ddd; padding:8px; background:#f0fdf4;"><b>Win</b><br><span style="font-size:20px; color:#15803d;">${win}%</span></div>
        <div style="border:1px solid #ddd; padding:8px; background:#fffbeb;"><b>Split</b><br><span style="font-size:20px; color:#b45309;">${tie}%</span></div>
        <div style="border:1px solid #ddd; padding:8px; background:#fef2f2;"><b>Lose</b><br><span style="font-size:20px; color:#b91c1c;">${lose}%</span></div>
      </div>
      <div style="margin-top:8px; font-size:12px; opacity:.8;">
        ${escapeHtml(heroCards.join(" "))} mot ${escapeHtml(player)} (${escapeHtml(stage)}), ${data.iters.toLocaleString()} simuleringer.
      </div>
      <div style="margin-top:4px; font-size:12px; opacity:.75;"><b>Range:</b> ${escapeHtml(rangeText || "random")}</div>
    `;
    ppLastDecisionState = {
      winPct: win,
      tiePct: tie,
      losePct: lose,
      stage,
      heroCards,
      boardCards,
      rangeText,
      player,
      historySignal: profileHistoryMatchSignal(heroCards, boardCards),
      profile: playerProfileData || {}
    };
    renderProfileDecisionPanel();
    setProfileEquityStatus("OK");
  } catch (e) {
    console.error(e);
    setProfileEquityStatus("Feil");
    ppLastDecisionState = null;
    renderProfileDecisionPanel();
    out.innerHTML = `<div style="color:#b91c1c;">Klarte ikke beregne equity.</div>`;
  }
}

function startProfileEquityAuto() {
  if (playerProfileEquityTimer) clearInterval(playerProfileEquityTimer);
  playerProfileEquityTimer = setInterval(async () => {
    const auto = $("ppEquityAuto");
    if (!auto || !auto.checked) return;
    const changed = await syncProfileEquityLiveCards({ silent: true });
    if (changed) calculateProfileEquity({ auto: true }).catch(console.warn);
  }, 3000);
}

function syncProfileEquityInputs(heroCards = ppHeroCards, boardCards = ppBoardCards) {
  ppHeroCards = (heroCards || []).slice();
  ppBoardCards = (boardCards || []).slice();
  const heroEl = $("ppHeroCards");
  const boardEl = $("ppBoardCards");
  if (heroEl) heroEl.value = cardsToText(ppHeroCards);
  if (boardEl) boardEl.value = cardsToText(ppBoardCards);
}

function setProfileEquityManualMode(on, message = "") {
  ppEquityManualMode = Boolean(on);
  if (ppEquityManualMode && $("ppEquityAuto")) $("ppEquityAuto").checked = false;
  if (message) setProfileEquityStatus(message);
}

function renderProfileEquityCardPicker() {
  const state = {
    rank: ppPickerRank,
    target: ppPickerTarget,
    heroCards: ppHeroCards.slice(),
    boardCards: ppBoardCards.slice(),
    onChange: (heroCards, boardCards) => {
      setProfileEquityManualMode(true, "Manuell: auto-live pauset.");
      syncProfileEquityInputs(heroCards, boardCards);
      lastPlayerProfileEquityKey = "";
      calculateProfileEquity({ auto: true }).catch(console.warn);
    },
    render: () => {
      ppPickerRank = state.rank;
      ppPickerTarget = state.target;
      ppHeroCards = state.heroCards.slice();
      ppBoardCards = state.boardCards.slice();
      renderProfileEquityCardPicker();
    }
  };
  renderCardPickerBox($("ppCardPicker"), state);
}

function syncProfileEquityPickerFromInputs(opts = {}) {
  if (opts.manual !== false) setProfileEquityManualMode(true, "Manuell: auto-live pauset.");
  const heroCards = parseCards($("ppHeroCards")?.value || "").filter(isCard).slice(0, 2);
  const boardCards = parseCards($("ppBoardCards")?.value || "").filter(isCard).slice(0, 5);
  ppHeroCards = heroCards;
  ppBoardCards = boardCards;
  ppPickerTarget = ppHeroCards.length < 2 ? "hero" : "board";
  renderProfileEquityCardPicker();
}

function clearProfileEquityCards() {
  setProfileEquityManualMode(true, "Kort slettet.");
  ppPickerTarget = "hero";
  syncProfileEquityInputs([], []);
  lastPlayerProfileEquityKey = "";
  ppLastDecisionState = null;
  renderProfileDecisionPanel();
  renderProfileEquityCardPicker();

  const out = $("ppEquityOut");
  if (out) out.innerHTML = `<div style="opacity:.7;">Venter på 2 gyldige hero-kort.</div>`;
}

function copyProfileEquityToMainEquity() {
  const hero = normalizeSpaces($("ppHeroCards")?.value || "");
  const board = normalizeSpaces($("ppBoardCards")?.value || "");
  const range = normalizeSpaces($("ppVillainRange")?.value || "");

  if ($("hero")) $("hero").value = hero;
  if ($("board")) $("board").value = board;
  if ($("numVillains")) $("numVillains").value = "1";
  if (range && $("villains")) $("villains").value = range;

  setManualCards(parseCards(hero).filter(isCard).slice(0, 2), parseCards(board).filter(isCard).slice(0, 5));
  setProfileEquityStatus("Kopiert til Equity Calculator.");
  $("hero")?.scrollIntoView({ behavior: "smooth", block: "center" });
}

function wirePlayerAutocomplete() {
  const ids = ["lhPlayer", "mtPlayer", "spPlayer", "ppPlayer", "shPlayer"];
  ids.forEach(id => {
    const el = $(id);
    if (!el) return;
    el.setAttribute("list", "boardPlayersDatalist");
    el.addEventListener("focus", () => loadKnownPlayerNames().catch(console.warn));
    el.addEventListener("input", () => searchKnownPlayerNames(el.value));
    el.addEventListener("blur", () => autocompletePlayerField(el));
    el.addEventListener("keydown", ev => {
      if (ev.key === "Enter") autocompletePlayerField(el);
    });
  });
  loadKnownPlayerNames().catch(console.warn);
}

function involvedPlayerNames(players) {
  const names = [];
  const seen = new Set();
  (players || []).forEach(p => {
    const name = String(p?.name || p?.player_name || "").trim();
    const key = name.toLowerCase();
    if (!name || seen.has(key)) return;
    seen.add(key);
    names.push(name);
  });
  return names;
}

function chooseAutoFeaturePlayer(players) {
  const names = involvedPlayerNames(players);
  const hero = dashHero();
  const heroMatch = names.find(n => n.toLowerCase() === hero.toLowerCase());
  return heroMatch || hero || names[0] || "";
}

function syncCurrentHandFeatureInputs(data) {
  const sessionId = data?.session_id || dashSessionId() || $("lhSession")?.value?.trim() || "";
  const player = chooseAutoFeaturePlayer(data?.players || []);

  if (sessionId) {
    syncActiveSessionFields(sessionId, data?.session_id ? "latest-hand" : "ui");
  }

  if (player) {
    ["lhPlayer", "mtPlayer", "spPlayer", "ppPlayer"].forEach(id => {
      const el = $(id);
      if (el) el.value = player;
    });
  }

  return { player, sessionId };
}

async function autoLoadCurrentHandFeatures(data) {
  const handId = data?.hand_id;
  if (!handId || handId === lastAutoFeatureHandId) return;
  lastAutoFeatureHandId = handId;

  const { player } = syncCurrentHandFeatureInputs(data);

  if ($("hvHandId")) $("hvHandId").value = String(handId);

  const status = $("liveGameStatus");
  if (status) {
    const names = involvedPlayerNames(data?.players || []);
    status.innerText = `Live polling aktiv - hand ${handId}${player ? `, auto-laster ${player}` : ""}${names.length ? ` (${names.join(", ")})` : ""}.`;
  }

  const tasks = [];
  if (typeof loadHand === "function") {
    tasks.push(loadHand(handId, { silent: true, skipEquityFill: true }));
  }
  if (player && typeof loadPlayerProfile === "function") {
    tasks.push(loadPlayerProfile());
  }
  if (player && typeof loadThreeBetMatrix === "function") {
    tasks.push(loadThreeBetMatrix());
  }
  if (player && typeof loadThreeBetSamplingPlan === "function") {
    tasks.push(loadThreeBetSamplingPlan());
  }
  if (typeof updateSessionHands === "function") {
    tasks.push(updateSessionHands(handId));
  }
  if (typeof fetchLiveHintOnce === "function" && player) {
    tasks.push(fetchLiveHintOnce());
  }

  await Promise.allSettled(tasks);
  startHandAutopoll();
}

// ------------------------------
// Cards parsing (Equity)
// ------------------------------
function normalizeSpaces(s) {
  return (s || "").trim().replace(/\s+/g, " ");
}
function isCard(token) {
  return /^[2-9TJQKA][shdc]$/.test(token);
}
function parseCards(text) {
  const t = normalizeSpaces(text);
  if (t === "") return [];

  return t.split(" ").map(convertBetSolidCard);
}

function convertBetSolidCard(card) {
  if (!card || card.length < 2) return card;
  card = String(card).trim();

  const standard = card[0].toUpperCase() + card.slice(1).toLowerCase();
  if (/^[2-9TJQKA][shdc]$/.test(standard)) return standard;

  const suitMap = {
    H: "h",
    D: "d",
    S: "s",
    C: "c"
  };

  const suit = suitMap[card[0].toUpperCase()];
  let rank = card.substring(1).toUpperCase();

  // Treys bruker T, ikke 10
  if (rank === "10") rank = "T";

  if (!suit) return card;

  return rank + suit;
}

// ------------------------------
// Card history (localStorage)
// ------------------------------
const CARD_HISTORY_KEY = "cardHistoryV1";
const HERO_BOARD_MATCH_HISTORY_KEY = "heroBoardMatchHistoryV1";
function loadCardHistory() {
  try {
    const raw = localStorage.getItem(CARD_HISTORY_KEY);
    if (!raw) return [];
    return JSON.parse(raw);
  } catch (e) {
    console.warn("Failed to load card history", e);
    return [];
  }
}
function saveCardHistory(list) {
  try {
    localStorage.setItem(CARD_HISTORY_KEY, JSON.stringify(list));
  } catch (e) {
    console.warn("Failed to save card history", e);
  }
}
function loadHeroBoardMatchHistory() {
  try {
    const raw = localStorage.getItem(HERO_BOARD_MATCH_HISTORY_KEY);
    if (!raw) return [];
    return JSON.parse(raw);
  } catch (e) {
    console.warn("Failed to load hero-board match history", e);
    return [];
  }
}
function saveHeroBoardMatchHistoryList(list) {
  try {
    localStorage.setItem(HERO_BOARD_MATCH_HISTORY_KEY, JSON.stringify(list));
  } catch (e) {
    console.warn("Failed to save hero-board match history", e);
  }
}
function liveBoardFallbackCards() {
  const sources = [
    lastLiveBoardText,
    lastGameState?.board,
    $("boardRegisterInput")?.value,
    $("board")?.value,
    $("ppBoardCards")?.value,
    lastManualBoardText
  ];
  for (const raw of sources) {
    const cards = parseCards(raw || "").filter(isCard).slice(0, 5);
    if (cards.length) return cards;
  }
  return [];
}
function normalizeHistoryEntry(e) {
  return {
    ...e,
    hero: Array.isArray(e?.hero) ? e.hero.map(convertBetSolidCard) : [],
    board: Array.isArray(e?.board) ? e.board.map(convertBetSolidCard) : [],
    showdown_class: e?.showdown_class || e?.hand_class || "",
    showdown_rank_class: e?.showdown_rank_class ?? e?.rank_class ?? null,
    at: e?.at || Date.now()
  };
}
function cardHistoryKey(e) {
  const n = normalizeHistoryEntry(e);
  if (n.hand_id) return `hand:${n.hand_id}`;
  if (n.site_hand_id) return `site:${n.site_hand_id}`;
  const heroKey = n.hero
    .filter(isCard)
    .slice(0, 2)
    .sort()
    .join("|");
  const boardKey = n.board
    .filter(isCard)
    .slice(0, 5)
    .join("|");
  return `${heroKey}::${boardKey}`;
}
function dedupeCardHistory(list) {
  const seen = new Set();
  const out = [];
  for (const raw of list || []) {
    const entry = normalizeHistoryEntry(raw);
    if (entry.hero.length !== 2) continue;
    const key = cardHistoryKey(entry);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(entry);
  }
  return out.sort((a, b) => {
    const atDiff = Number(b.at || 0) - Number(a.at || 0);
    if (atDiff) return atDiff;
    return Number(b.hand_id || 0) - Number(a.hand_id || 0);
  });
}

function normalizeHeroBoardMatchEntry(e) {
  const hero = (e?.hero || []).map(convertBetSolidCard).filter(isCard).slice(0, 2);
  const board = (e?.board || []).map(convertBetSolidCard).filter(isCard).slice(0, 5);
  const heroRanks = [...new Set(hero.map(card => card[0]))];
  const boardRanks = new Set(board.map(card => card[0]));
  const hits = heroRanks.filter(rank => boardRanks.has(rank));
  return {
    ...e,
    hero,
    board,
    hero_ranks: heroRanks,
    board_ranks: [...boardRanks],
    hits,
    misses: heroRanks.filter(rank => !boardRanks.has(rank)),
    any_hit: hits.length > 0,
    both_hit: heroRanks.length > 0 && hits.length === heroRanks.length,
    at: e?.at || Date.now()
  };
}
function heroBoardMatchHistoryKey(e) {
  const n = normalizeHeroBoardMatchEntry(e);
  if (n.hand_id) return `hand:${n.hand_id}`;
  if (n.site_hand_id) return `site:${n.site_hand_id}`;
  return `${n.hero.map(c => c[0]).sort().join("|")}::${n.board.join("|")}`;
}
function dedupeHeroBoardMatchHistory(list) {
  const seen = new Set();
  const out = [];
  for (const raw of list || []) {
    const entry = normalizeHeroBoardMatchEntry(raw);
    if (entry.hero.length !== 2 || !entry.board.length) continue;
    const key = heroBoardMatchHistoryKey(entry);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(entry);
  }
  return out.sort((a, b) => {
    const atDiff = Number(b.at || 0) - Number(a.at || 0);
    if (atDiff) return atDiff;
    return Number(b.hand_id || 0) - Number(a.hand_id || 0);
  });
}

function normalizeBackendCardHistoryEntry(entry, index = null) {
  const cards = Array.isArray(entry?.cards) ? entry.cards : entry?.hero;
  const rawStarted = entry?.started_at || entry?.at || "";
  const started = rawStarted ? Date.parse(String(rawStarted).replace(" ", "T")) : NaN;
  return normalizeHistoryEntry({
    hero: (cards || []).map(convertBetSolidCard),
    board: (entry?.board || []).map(convertBetSolidCard),
    at: Number.isFinite(started) ? started : Date.now(),
    hand_id: entry?.hand_id,
    site_hand_id: entry?.site_hand_id,
    session_id: entry?.session_id,
    showdown_class: entry?.showdown_class || entry?.hand_class || "",
    showdown_rank_class: entry?.showdown_rank_class ?? entry?.rank_class ?? null,
    overall_index: index,
    source: "backend"
  });
}

function validHistoryIndex(value) {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function sortCardHistoryNewestFirst(list) {
  return [...(list || [])].sort((a, b) => {
    const ai = validHistoryIndex(a?.overall_index);
    const bi = validHistoryIndex(b?.overall_index);
    if (ai !== null && bi !== null && ai !== bi) return ai - bi;
    const siteDiff = Number(b.site_hand_id || 0) - Number(a.site_hand_id || 0);
    if (siteDiff) return siteDiff;
    const handDiff = Number(b.hand_id || 0) - Number(a.hand_id || 0);
    if (handDiff) return handDiff;
    return Number(b.at || 0) - Number(a.at || 0);
  });
}

function combinedCardHistory() {
  return sortCardHistoryNewestFirst(dedupeCardHistory(
    backendCardHistory.map(normalizeHistoryEntry)
  ));
}

function isHistoricalMatchSource(entry) {
  return String(entry?.source || "").toLowerCase() === "backend";
}

function isLocalHistoricalMatchSource(entry) {
  const source = String(entry?.source || "").toLowerCase();
  return isHistoricalMatchSource(entry) && source !== "backend";
}

function historyEntriesWithBoards(list) {
  return (list || []).filter(entry => (entry.board || []).map(convertBetSolidCard).filter(isCard).length > 0);
}

async function refreshBackendCardHistory(opts = {}) {
  const now = Date.now();
  const historySessionKey = "file-history-all-db-showdown-made-hand-20260709i";
  if (
    !opts.force &&
    backendCardHistoryLoadedAt &&
    backendCardHistorySessionId === historySessionKey &&
    now - backendCardHistoryLoadedAt < BACKEND_CARD_HISTORY_TTL_MS
  ) {
    return backendCardHistory;
  }
  if (backendCardHistoryInFlight) {
    if (opts.render !== false) backendCardHistoryPendingRender = true;
    return backendCardHistory;
  }
  backendCardHistoryInFlight = true;
  backendCardHistoryStartedAt = Date.now();
  backendCardHistoryLastAttemptAt = backendCardHistoryStartedAt;
  backendCardHistoryError = "";
  let shouldRender = opts.render !== false;
  if (backendCardHistoryWatchdogTimer) clearTimeout(backendCardHistoryWatchdogTimer);
  backendCardHistoryWatchdogTimer = setTimeout(() => {
    if (!backendCardHistoryInFlight) return;
    backendCardHistoryInFlight = false;
    backendCardHistoryStartedAt = 0;
    backendCardHistoryError = "timeout";
    backendCardHistoryPendingRender = false;
    renderCardHistory();
    renderHeroHistoryMatches({ skipBackendRefresh: true });
  }, (opts.timeoutMs || 5000) + 1500);
  try {
    const params = new URLSearchParams();
    const heroName = dashHero();
    if (heroName) params.set("player_name", heroName);
    params.set("limit", String(opts.limit || 1000));
    params.set("include_showdown", "true");
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), opts.timeoutMs || 5000);
    let res;
    try {
      res = await fetch(`${apiBase()}/hands/card-history?${params.toString()}`, { signal: controller.signal });
    } finally {
      clearTimeout(timeout);
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    backendCardHistory = sortCardHistoryNewestFirst((data.history || [])
      .map(entry => normalizeBackendCardHistoryEntry(entry))
      .filter(e => e.hero.length === 2))
      .map((entry, index) => ({ ...entry, overall_index: index }));
    backendCardHistorySessionId = historySessionKey;
    backendCardHistoryLoadedAt = Date.now();
    renderHeroHistoryMatches({ skipBackendRefresh: true });
  } catch (e) {
    backendCardHistoryError = e?.name === "AbortError" ? "timeout" : String(e?.message || e);
    console.warn("Could not load backend card history", e);
  } finally {
    backendCardHistoryInFlight = false;
    backendCardHistoryStartedAt = 0;
    if (backendCardHistoryWatchdogTimer) {
      clearTimeout(backendCardHistoryWatchdogTimer);
      backendCardHistoryWatchdogTimer = null;
    }
  }
  if (shouldRender || backendCardHistoryPendingRender) {
    backendCardHistoryPendingRender = false;
    renderCardHistory();
  }
  return backendCardHistory;
}

function heroComboKey(cards) {
  return (cards || [])
    .map(convertBetSolidCard)
    .filter(isCard)
    .slice(0, 2)
    .map(card => card[0])
    .sort()
    .join("|");
}

function heroExactKey(cards) {
  return (cards || [])
    .map(convertBetSolidCard)
    .filter(isCard)
    .slice(0, 2)
    .sort()
    .join("|");
}

function boardExactKey(cards) {
  return (cards || [])
    .map(convertBetSolidCard)
    .filter(isCard)
    .slice(0, 5)
    .join("|");
}

function heroRankKey(cards) {
  return (cards || [])
    .map(convertBetSolidCard)
    .filter(isCard)
    .slice(0, 2)
    .map(card => card[0])
    .sort()
    .join("|");
}

function activeHistorySessionId() {
  const candidates = [
    $("shSession")?.value,
    $("dashSession")?.value,
    $("lhSession")?.value
  ];
  for (const raw of candidates) {
    const value = String(raw || "").trim();
    if (value && Number.isInteger(Number(value)) && Number(value) > 0) return value;
  }
  return "";
}

function roundsSinceLabel(index) {
  return index === 0 ? "forrige runde" : `${index + 1} runder siden`;
}

function matchSummaryWithLabel(indexes, labelFn) {
  const list = indexes || [];
  if (!list.length) {
    return { latest: "-", recent: "-", extra: 0 };
  }
  const shown = list.slice(0, 5).map(labelFn);
  const extra = Math.max(0, list.length - shown.length);
  return {
    latest: labelFn(list[0]),
    recent: `${shown.join(", ")}${extra ? `, +${extra} flere` : ""}`,
    extra
  };
}

function historyMatchSummary(indexes) {
  return matchSummaryWithLabel(indexes, roundsSinceLabel);
}

function sameHeroSinceLabel(index) {
  if (index === 0) return "nyeste samme hero";
  if (index === 1) return "forrige samme hero";
  return `${index + 1}. nyeste samme hero`;
}

function simpleMatchAgeLabel(index) {
  const rounds = Number(index || 0) + 1;
  return rounds === 1 ? "1 runde siden" : `${rounds} runder siden`;
}

function historyAgeLabel(item) {
  if (!item) return "-";
  if (item.manual) return "manuelt registrert";
  if (item.derivedBoardCache && item.overallHistoryIndex == null && item.roundAgeIndex == null) {
    return "ukjent rundeavstand";
  }
  const idx = Number(item.overallHistoryIndex ?? item.roundAgeIndex ?? item.historyIndex ?? item.index ?? 0);
  const rounds = idx + 1;
  return rounds === 1 ? "1 lagret runde siden" : `${rounds} lagrede runder siden`;
}

function boardHandsSinceLabel(item) {
  if (!item) return "-";
  if (item.manual) return "manuelt registrert";
  if (item.derivedBoardCache && item.overallHistoryIndex == null && item.roundAgeIndex == null) {
    return "ukjent";
  }
  const rounds = Number(item.overallHistoryIndex ?? item.roundAgeIndex ?? item.historyIndex ?? item.index ?? 0) + 1;
  return rounds === 1 ? "1 runde siden" : `${rounds} runder siden`;
}

function latestBoardHitLabel(matches) {
  const item = matches && matches.length ? matches[0] : null;
  if (!item) return "-";
  const label = boardHandsSinceLabel(item);
  return item.hit ? `${label} (${item.hit})` : label;
}

function latestBoardSourceLabel(matches, opts = {}) {
  const item = matches && matches.length ? matches[0] : null;
  if (!item || !item.board || !item.board.length) return "-";
  const id = item.site_hand_id || item.hand_id || "";
  const idText = id ? ` #${id}` : "";
  const showHero = opts.showHero !== false;
  const heroText = showHero && item.hero && item.hero.length ? `${item.hero.join(" ")} | board: ` : "board: ";
  return `${heroText}${item.board.join(" ")}${idText}`;
}

function buildHeroBoardRankStats(heroCards, historyList) {
  const heroRanks = [...new Set((heroCards || []).map(card => card[0]))];
  const rankMatches = {};
  heroRanks.forEach(rank => {
    rankMatches[rank] = [];
  });

  let boardRows = 0;
  (historyList || []).forEach((entry, index) => {
    const entryHero = (entry.hero || []).map(convertBetSolidCard).filter(isCard).slice(0, 2);
    const board = (entry.board || []).map(convertBetSolidCard).filter(isCard).slice(0, 5);
    if (entryHero.length !== 2 || !board.length) return;
    boardRows += 1;

    const entryHeroRanks = new Set(entryHero.map(card => card[0]));
    const boardRanks = new Set(board.map(card => card[0]));
    heroRanks.forEach(rank => {
      if (!entryHeroRanks.has(rank)) return;
      if (!boardRanks.has(rank)) return;
      rankMatches[rank].push({
        rank,
        hero: entryHero,
        board,
        historyIndex: index,
        roundAgeIndex: index,
        overallHistoryIndex: index,
        hand_id: entry.hand_id || "",
        site_hand_id: entry.site_hand_id || "",
        session_id: entry.session_id || ""
      });
    });
  });

  const singleHits = [];
  const comboHits = [];
  (historyList || []).forEach((entry, index) => {
    const entryHero = (entry.hero || []).map(convertBetSolidCard).filter(isCard).slice(0, 2);
    const board = (entry.board || []).map(convertBetSolidCard).filter(isCard).slice(0, 5);
    if (entryHero.length !== 2 || !board.length) return;
    const entryHeroRanks = new Set(entryHero.map(card => card[0]));
    const boardRanks = new Set(board.map(card => card[0]));
    const hits = heroRanks.filter(rank => entryHeroRanks.has(rank) && boardRanks.has(rank));
    if (hits.length === 1) {
      singleHits.push({
        hit: hits[0],
        hero: entryHero,
        board,
        historyIndex: index,
        roundAgeIndex: index,
        overallHistoryIndex: index,
        hand_id: entry.hand_id || "",
        site_hand_id: entry.site_hand_id || "",
        session_id: entry.session_id || ""
      });
    }
    if (heroRanks.length > 1 && hits.length === heroRanks.length) {
      comboHits.push({
        hit: heroRanks.join(" + "),
        hero: entryHero,
        board,
        historyIndex: index,
        roundAgeIndex: index,
        overallHistoryIndex: index,
        hand_id: entry.hand_id || "",
        site_hand_id: entry.site_hand_id || "",
        session_id: entry.session_id || ""
      });
    }
  });

  return {
    heroRanks,
    boardRows,
    rankMatches,
    singleHits,
    comboHits
  };
}

function sameHeroMatchSummary(indexes) {
  return matchSummaryWithLabel(indexes, sameHeroSinceLabel);
}

function sameHeroHitSummary(matches) {
  const list = matches || [];
  if (!list.length) {
    return { latest: "-", recent: "", extra: 0 };
  }
  const shown = list.slice(0, 5).map(item => `${item.hit} ${historyAgeLabel(item)}`);
  const extra = Math.max(0, list.length - shown.length);
  return {
    latest: historyAgeLabel(list[0]),
    recent: `${shown.join(", ")}${extra ? `, +${extra} flere` : ""}`,
    extra
  };
}

function sameHeroBoardSummary(matches) {
  const list = matches || [];
  if (!list.length) {
    return { latest: "-", recent: "", extra: 0 };
  }
  const shown = list.slice(0, 5).map(item => `${item.rank} ${historyAgeLabel(item)}`);
  const extra = Math.max(0, list.length - shown.length);
  return {
    latest: historyAgeLabel(list[0]),
    recent: `${shown.join(", ")}${extra ? `, +${extra} flere` : ""}`,
    extra
  };
}

const MADE_HAND_ORDER = [
  "Straight Flush",
  "Four of a Kind",
  "Full House",
  "Flush",
  "Straight",
  "Three of a Kind",
  "Two Pair",
  "Pair",
  "High Card"
];

function madeHandLabel(name) {
  const labels = {
    "Straight Flush": "Straight flush",
    "Four of a Kind": "Fire like",
    "Full House": "Hus",
    "Flush": "Flush",
    "Straight": "Straight",
    "Three of a Kind": "Trips",
    "Two Pair": "To par",
    "Pair": "Par",
    "High Card": "High card"
  };
  return labels[name] || name || "-";
}

function madeHandTone(name, count) {
  if (!count) return "#fff";
  if (["Straight Flush", "Four of a Kind", "Full House", "Flush", "Straight"].includes(name)) return "#ecfdf5";
  if (["Three of a Kind", "Two Pair"].includes(name)) return "#eff6ff";
  return "#fff7ed";
}

const RANK_STRAIGHT_VALUES = {
  "2": 2,
  "3": 3,
  "4": 4,
  "5": 5,
  "6": 6,
  "7": 7,
  "8": 8,
  "9": 9,
  "T": 10,
  "J": 11,
  "Q": 12,
  "K": 13,
  "A": 14
};

function straightHighValue(cards) {
  const values = new Set((cards || [])
    .map(card => RANK_STRAIGHT_VALUES[String(card || "")[0]])
    .filter(Boolean));
  if (values.has(14)) values.add(1);

  for (let high = 14; high >= 5; high -= 1) {
    let hasStraight = true;
    for (let value = high - 4; value <= high; value += 1) {
      if (!values.has(value)) {
        hasStraight = false;
        break;
      }
    }
    if (hasStraight) return high;
  }
  return null;
}

function straightWindowValues(high) {
  if (!high) return [];
  if (high === 5) return [1, 2, 3, 4, 5];
  return [high - 4, high - 3, high - 2, high - 1, high];
}

function cardStraightValues(card) {
  const value = RANK_STRAIGHT_VALUES[String(card || "")[0]];
  if (!value) return [];
  return value === 14 ? [14, 1] : [value];
}

function heroRankInStraight(heroCards, high) {
  const windowValues = new Set(straightWindowValues(high));
  return (heroCards || []).some(card =>
    cardStraightValues(card).some(value => windowValues.has(value))
  );
}

function straightHighValueWithHero(cards, heroCards) {
  const values = new Set((cards || [])
    .map(card => RANK_STRAIGHT_VALUES[String(card || "")[0]])
    .filter(Boolean));
  if (values.has(14)) values.add(1);

  for (let high = 14; high >= 5; high -= 1) {
    const needed = straightWindowValues(high);
    if (needed.every(value => values.has(value)) && heroRankInStraight(heroCards, high)) {
      return high;
    }
  }
  return null;
}

function rankCounts(cards) {
  const counts = {};
  (cards || []).forEach(card => {
    const rank = String(card || "")[0];
    if (rank) counts[rank] = (counts[rank] || 0) + 1;
  });
  return counts;
}

function hasDuplicateCards(cards) {
  const seen = new Set();
  for (const card of cards || []) {
    if (seen.has(card)) return true;
    seen.add(card);
  }
  return false;
}

function bestMadeHandForHeroBoard(heroCards, boardCards) {
  const hero = (heroCards || []).map(convertBetSolidCard).filter(isCard).slice(0, 2);
  const board = (boardCards || []).map(convertBetSolidCard).filter(isCard).slice(0, 5);
  if (hero.length !== 2 || board.length < 3) return null;
  if (hasDuplicateCards(hero.concat(board))) return null;

  const allCards = hero.concat(board);
  const heroRankSet = new Set(hero.map(card => card[0]));
  const boardRankSet = new Set(board.map(card => card[0]));
  const heroBoardMatchedRanks = [...heroRankSet].filter(rank => boardRankSet.has(rank));
  const suits = ["s", "h", "d", "c"];
  for (const suit of suits) {
    const suitedCards = allCards.filter(card => card[1] === suit);
    const suitedHeroCards = hero.filter(card => card[1] === suit);
    const sfHigh = suitedCards.length >= 5 && suitedHeroCards.length
      ? straightHighValueWithHero(suitedCards, suitedHeroCards)
      : null;
    if (sfHigh) return { name: "Straight Flush", suffix: sfHigh === 14 ? " A" : ` ${sfHigh}` };
  }

  const counts = rankCounts(allCards);
  const ranksByCount = Object.keys(counts);
  const tripsRanks = ranksByCount.filter(rank => counts[rank] >= 3);
  const pairRanks = ranksByCount.filter(rank => counts[rank] >= 2);
  const quadRank = ranksByCount.find(rank => counts[rank] >= 4 && heroBoardMatchedRanks.includes(rank));
  if (quadRank) {
    return { name: "Four of a Kind", suffix: ` ${quadRank}` };
  }
  let fullHouseMatch = null;
  for (const tripsRank of tripsRanks) {
    const pairRank = pairRanks.find(rank =>
      rank !== tripsRank &&
      (heroBoardMatchedRanks.includes(tripsRank) || heroBoardMatchedRanks.includes(rank))
    );
    if (pairRank) {
      fullHouseMatch = { tripsRank, pairRank };
      break;
    }
  }
  if (fullHouseMatch) {
    return { name: "Full House", suffix: ` ${fullHouseMatch.tripsRank}+${fullHouseMatch.pairRank}` };
  }

  const hasFlush = suits.some(suit =>
    allCards.filter(card => card[1] === suit).length >= 5 &&
    hero.some(card => card[1] === suit)
  );
  if (hasFlush) return { name: "Flush" };

  const straightHigh = straightHighValueWithHero(allCards, hero);
  if (straightHigh) return { name: "Straight", suffix: straightHigh === 14 ? " A" : ` ${straightHigh}` };

  const heroTripsRank = tripsRanks.find(rank => heroBoardMatchedRanks.includes(rank));
  if (heroTripsRank) return { name: "Three of a Kind", suffix: ` ${heroTripsRank}` };
  const madePairRanks = pairRanks.filter(rank => heroBoardMatchedRanks.includes(rank));
  if (madePairRanks.length >= 2) return { name: "Two Pair", suffix: ` ${madePairRanks.slice(0, 2).join("+")}` };
  if (madePairRanks.length === 1) {
    return { name: "Pair", suffix: ` ${madePairRanks[0]}` };
  }
  return { name: "High Card" };
}

function heroRankMadeHandSignals(heroCards, boardCards) {
  const hero = (heroCards || []).map(convertBetSolidCard).filter(isCard).slice(0, 2);
  const board = (boardCards || []).map(convertBetSolidCard).filter(isCard).slice(0, 5);
  if (hero.length !== 2 || !board.length) return [];

  const heroCounts = {};
  const boardCounts = {};
  const heroSuitCounts = {};
  const boardSuitCounts = {};
  hero.forEach(card => { heroCounts[card[0]] = (heroCounts[card[0]] || 0) + 1; });
  board.forEach(card => { boardCounts[card[0]] = (boardCounts[card[0]] || 0) + 1; });
  hero.forEach(card => { heroSuitCounts[card[1]] = (heroSuitCounts[card[1]] || 0) + 1; });
  board.forEach(card => { boardSuitCounts[card[1]] = (boardSuitCounts[card[1]] || 0) + 1; });

  const signals = [];
  const combinedCounts = {};
  hero.concat(board).forEach(card => {
    combinedCounts[card[0]] = (combinedCounts[card[0]] || 0) + 1;
  });
  const heroRankSet = new Set(Object.keys(heroCounts));
  const tripsRanks = Object.keys(combinedCounts).filter(rank => combinedCounts[rank] >= 3);
  const pairRanks = Object.keys(combinedCounts).filter(rank => combinedCounts[rank] >= 2);
  const quadAnyRank = Object.keys(combinedCounts).find(rank => combinedCounts[rank] >= 4);
  if (quadAnyRank) {
    signals.push({ name: "Four of a Kind", rank: quadAnyRank });
  }
  const fullHouseRank = tripsRanks.find(tripsRank =>
    pairRanks.some(pairRank => pairRank !== tripsRank) &&
    (heroRankSet.has(tripsRank) || pairRanks.some(pairRank => pairRank !== tripsRank && heroRankSet.has(pairRank)))
  );
  if (fullHouseRank) {
    signals.push({ name: "Full House", rank: fullHouseRank });
  }
  Object.keys(heroCounts).forEach(rank => {
    const boardCount = boardCounts[rank] || 0;
    if (!boardCount) return;
    const total = heroCounts[rank] + boardCount;
    if (total >= 4) {
      signals.push({ name: "Four of a Kind", rank });
      signals.push({ name: "Three of a Kind", rank });
    } else if (total === 3) {
      signals.push({ name: "Three of a Kind", rank });
    }
  });
  const pairedHeroRanks = Object.keys(heroCounts).filter(rank => (boardCounts[rank] || 0) > 0);
  if (pairedHeroRanks.length >= 2) {
    signals.push({ name: "Two Pair", rank: pairedHeroRanks.join("+") });
  } else if (pairedHeroRanks.length === 1) {
    const pairedRank = pairedHeroRanks[0];
    const boardHasOtherPair = Object.keys(boardCounts).some(rank => rank !== pairedRank && boardCounts[rank] >= 2);
    if (boardHasOtherPair) {
      signals.push({ name: "Two Pair", rank: pairedRank });
    } else {
      signals.push({ name: "Pair", rank: pairedRank });
    }
  }
  Object.keys(heroSuitCounts).forEach(suit => {
    const boardCount = boardSuitCounts[suit] || 0;
    if (!boardCount) return;
    if (heroSuitCounts[suit] + boardCount >= 5) {
      signals.push({ name: "Flush", suit });
    }
  });

  const allCards = hero.concat(board);
  const straightHigh = straightHighValue(allCards);
  if (straightHigh) {
    signals.push({ name: "Straight", rank: straightHigh === 14 ? "A" : String(straightHigh) });
  }

  const suits = ["s", "h", "d", "c"];
  for (const suit of suits) {
    const suitedCards = allCards.filter(card => card[1] === suit);
    if (suitedCards.length >= 5 && straightHighValue(suitedCards)) {
      signals.push({ name: "Straight Flush", suit });
      break;
    }
  }
  return signals;
}

function madeHandSignalText(signals) {
  const list = signals || [];
  if (!list.length) return "";
  return list
    .map(signal => signal.rank
      ? `${madeHandLabel(signal.name)} ${signal.rank}`
      : madeHandLabel(signal.name))
    .join(" / ");
}

function activeManualHeroCardsForHistory() {
  const sources = [
    lastManualHeroText,
    cardsToText(manualPickerHeroCards),
    $("heroRegisterInput")?.value || "",
    $("hero")?.value || ""
  ];
  for (const raw of sources) {
    const cards = parseCards(raw || "").filter(isCard).slice(0, 2);
    if (cards.length === 2) return cards;
  }
  return [];
}

function renderHeroHistoryMatches(opts = {}) {
  const box = $("heroHistoryMatchBox");
  if (!box) return;

  const heroCards = activeManualHeroCardsForHistory();
  if (heroCards.length !== 2) {
    box.innerHTML = `<div style="opacity:.65;">Historikkmatch: legg inn 2 hero-kort.</div>`;
    return;
  }

  if (!opts.skipBackendRefresh) {
    refreshBackendCardHistory({ limit: 1000, timeoutMs: 15000, render: true }).catch(console.warn);
  }

  const backendHistoryForMatch = sortCardHistoryNewestFirst(
    backendCardHistory.map(normalizeHistoryEntry)
  )
    .filter(isHistoricalMatchSource)
    .map((entry, index) => ({
      ...entry,
      history_order_index: index,
      overall_index: index
    }));
  const backendBoardHands = historyEntriesWithBoards(backendHistoryForMatch);
  const list = backendHistoryForMatch;
  const matchSourceLabel = backendBoardHands.length
    ? "database/filhistorikk"
    : backendCardHistoryInFlight
      ? "laster database/filhistorikk"
      : backendCardHistoryError
        ? `database/filhistorikk feilet: ${backendCardHistoryError}`
        : "database/filhistorikk uten board";
  const storedHeroHands = list.filter(entry => (entry.hero || []).map(convertBetSolidCard).filter(isCard).length === 2).length;
  const storedBoardHands = list.filter(entry => (entry.board || []).map(convertBetSolidCard).filter(isCard).length > 0).length;
  const historyNotice = !list.length
    ? (backendCardHistoryInFlight ? "Laster database/filhistorikk..." : "Ingen filhistorikk lagret.")
    : backendCardHistoryInFlight && !backendBoardHands.length
      ? "Laster database/filhistorikk og boardkort..."
      : "";

  const minHistoricalBoardCards = 1;

  const heroKey = heroExactKey(heroCards);
  const heroRanks = [...new Set(heroCards.map(card => card[0]))];
  const sameHeroHands = [];
  const olderSameHeroHands = [];
  let allBoardCount = 0;
  let sameHeroWithBoardCount = 0;

  const collectSameHeroRows = (sourceList, includeStats, matchMode = "exact") => {
    const rows = [];
    sourceList.forEach((entry, historyIndex) => {
    const entryHero = (entry.hero || []).map(convertBetSolidCard).filter(isCard).slice(0, 2);
    if (entryHero.length !== 2) return;

    const entryBoard = (entry.board || []).map(convertBetSolidCard).filter(isCard).slice(0, 5);
    const manualEntry = String(entry.site_hand_id || "").startsWith("manual-") || String(entry.source || "").includes("manual");
    const entryOverallIndex = validHistoryIndex(entry.history_order_index ?? entry.overall_index);
    const hasOverallIndex = entryOverallIndex !== null;
    const derivedWithoutOrder = Boolean(entry.derived_board_cache && !hasOverallIndex);
    const historyAgeIndex = hasOverallIndex ? entryOverallIndex : historyIndex;
    const ageMeta = derivedWithoutOrder
      ? { derivedBoardCache: true }
      : { roundAgeIndex: historyAgeIndex, overallHistoryIndex: historyAgeIndex };

    const entryHeroRanks = new Set(entryHero.map(card => card[0]));
    const boardRanks = new Set(entryBoard.map(card => card[0]));

    if (matchMode === "exact" && heroExactKey(entryHero) !== heroKey) return;
    if (matchMode === "rank" && heroRankKey(entryHero) !== heroRankKey(heroCards)) return;
    if (matchMode === "any-rank" && !heroRanks.some(rank => entryHeroRanks.has(rank))) return;
    if (!entryBoard.length) return;
    if (entryBoard.length < minHistoricalBoardCards) return;

    const relevantHeroRanks = heroRanks.filter(rank => entryHeroRanks.has(rank));
    const hitRanks = relevantHeroRanks.filter(rank => boardRanks.has(rank));
    if (matchMode === "all-boards" && !hitRanks.length) return;

    if (includeStats) allBoardCount += 1;

    const boardIndex = includeStats ? sameHeroWithBoardCount : rows.length;
    if (includeStats) sameHeroWithBoardCount += 1;

    rows.push({
      index: historyAgeIndex,
      boardMatchIndex: boardIndex,
      historyIndex: historyAgeIndex,
      ...ageMeta,
      label: manualEntry ? "manuelt registrert" : historyAgeLabel(ageMeta),
      manual: manualEntry,
      hero: entryHero,
      board: entryBoard,
      hits: hitRanks,
      showdown_class: entry.showdown_class || "",
      showdown_rank_class: entry.showdown_rank_class ?? null,
      made_hand_signals: heroRankMadeHandSignals(entryHero, entryBoard),
      source: entry.source || (entry.hand_id ? "database" : "lokal"),
      hand_id: entry.hand_id || "",
      site_hand_id: entry.site_hand_id || "",
      session_id: entry.session_id || "",
      derivedBoardCache: derivedWithoutOrder,
      overall_index: entry.overall_index
    });
  });
    return rows;
  };

  sameHeroHands.push(...collectSameHeroRows(list, true, "all-boards"));
  const rankStats = buildHeroBoardRankStats(heroCards, list);
  sameHeroWithBoardCount = rankStats.boardRows;
  const boardHitRows = sameHeroHands.map(row => {
    return {
      ...row,
      hitRanks: row.hits || []
    };
  });
  const madeHandStats = {};
  const madeHandSeen = {};
  const addMadeHandStat = (name, row, suffix = "") => {
    if (!name) return;
    if (!madeHandStats[name]) {
      madeHandStats[name] = { name, count: 0, matches: [] };
    }
    const uniqueKey = [
      name,
      row.hand_id || "",
      row.site_hand_id || "",
      (row.hero || heroCards).join("|"),
      row.board.join("|")
    ].join("::");
    if (madeHandSeen[uniqueKey]) return;
    madeHandSeen[uniqueKey] = true;
    madeHandStats[name].count += 1;
    madeHandStats[name].matches.push({
      index: row.index,
      historyIndex: row.historyIndex,
      roundAgeIndex: row.roundAgeIndex,
      overallHistoryIndex: row.overallHistoryIndex,
      derivedBoardCache: row.derivedBoardCache,
      manual: row.manual,
      hero: row.hero || heroCards,
      board: row.board,
      hand_id: row.hand_id,
      site_hand_id: row.site_hand_id,
      suffix
    });
  };
  backendBoardHands.forEach((entry, historyIndex) => {
    const entryHero = (entry.hero || []).map(convertBetSolidCard).filter(isCard).slice(0, 2);
    const board = (entry.board || []).map(convertBetSolidCard).filter(isCard).slice(0, 5);
    const entryHeroRanks = new Set(entryHero.map(card => card[0]));
    const sharedRanks = heroRanks.filter(rank => entryHeroRanks.has(rank));
    if (!sharedRanks.length) return;
    const entryOverallIndex = validHistoryIndex(entry.history_order_index ?? entry.overall_index);
    const historyAgeIndex = entryOverallIndex !== null ? entryOverallIndex : historyIndex;
    const showdownClass = String(entry.showdown_class || "").trim();
    const localSignals = heroRankMadeHandSignals(entryHero, board);
    const signalRows = showdownClass
      ? [{ name: showdownClass, rank: "" }, ...localSignals]
      : localSignals;
    const madeSignals = signalRows.length
      ? signalRows
      : [{ name: "High Card", rank: "" }];
    madeSignals.forEach(signal => addMadeHandStat(signal.name, {
      index: historyAgeIndex,
      historyIndex: historyAgeIndex,
      roundAgeIndex: historyAgeIndex,
      overallHistoryIndex: historyAgeIndex,
      manual: String(entry.site_hand_id || "").startsWith("manual-") || String(entry.source || "").includes("manual"),
      hero: entryHero,
      board,
      hand_id: entry.hand_id || "",
      site_hand_id: entry.site_hand_id || "",
      source: entry.source || "database"
    }, signal.rank ? ` ${signal.rank}` : ""));
  });

  const exactSingleHitMatches = rankStats.singleHits;
  const exactComboMatches = rankStats.comboHits;
  const rankRows = heroRanks.map(rank => {
    const details = rankStats.rankMatches[rank] || [];
      return {
        type: `${rank} treff board`,
        count: details.length,
        latest: latestBoardHitLabel(details),
        latestBoard: latestBoardSourceLabel(details, { showHero: true }),
        tone: details.length ? "#eff6ff" : "#fff"
      };
    });
  const rows = heroRanks.length === 1
    ? rankRows
    : [
      {
        type: "Ett treff",
        count: exactSingleHitMatches.length,
        latest: latestBoardHitLabel(exactSingleHitMatches),
        latestBoard: latestBoardSourceLabel(exactSingleHitMatches, { showHero: true }),
        tone: exactSingleHitMatches.length ? "#fff7ed" : "#fff"
      },
      {
        type: "Begge treff",
        count: exactComboMatches.length,
        latest: latestBoardHitLabel(exactComboMatches),
        latestBoard: latestBoardSourceLabel(exactComboMatches, { showHero: true }),
        tone: exactComboMatches.length ? "#ecfdf5" : "#fff"
      },
      ...rankRows
    ];

  const tableRows = rows.map(row => `
    <tr style="background:${row.tone};">
      <td style="border-top:1px solid #e5e7eb; padding:7px 8px; opacity:.75;">${escapeHtml(row.type)}</td>
      <td style="border-top:1px solid #e5e7eb; padding:7px 8px; text-align:center; font-weight:800;">${row.count}</td>
      <td style="border-top:1px solid #e5e7eb; padding:7px 8px; font-weight:700;">${escapeHtml(row.latest)}</td>
      <td style="border-top:1px solid #e5e7eb; padding:7px 8px; font-size:11px; opacity:.75;">${escapeHtml(row.latestBoard || "-")}</td>
    </tr>
  `).join("");

  const madeHandRows = MADE_HAND_ORDER
    .map(name => madeHandStats[name] || { name, count: 0, matches: [] })
    .map(stat => {
      const matches = stat.matches.map(item => ({
        hit: `${madeHandLabel(stat.name)}${item.suffix || ""}`,
        historyIndex: item.historyIndex,
        roundAgeIndex: item.roundAgeIndex,
        overallHistoryIndex: item.overallHistoryIndex,
        derivedBoardCache: item.derivedBoardCache,
        manual: item.manual,
        hero: item.hero,
        board: item.board,
        hand_id: item.hand_id,
        site_hand_id: item.site_hand_id
      }));
      const count = stat.count;
      return `
        <tr style="background:${madeHandTone(stat.name, stat.count)};">
          <td style="border-top:1px solid #e5e7eb; padding:7px 8px; font-weight:800;">${escapeHtml(madeHandLabel(stat.name))}<div style="font-size:10px; opacity:.55; font-weight:400;">lagret hero + board</div></td>
          <td style="border-top:1px solid #e5e7eb; padding:7px 8px; text-align:center; font-weight:800;">${count}</td>
          <td style="border-top:1px solid #e5e7eb; padding:7px 8px; font-weight:700;">${escapeHtml(latestBoardHitLabel(matches))}</td>
          <td style="border-top:1px solid #e5e7eb; padding:7px 8px; font-size:11px; opacity:.75;">${escapeHtml(latestBoardSourceLabel(matches, { showHero: false }))}</td>
        </tr>
      `;
    }).join("");

  const madeHandTable = `
    <div style="margin-top:10px; font-weight:800;">Håndtype i matchende historikk</div>
    <div style="margin-top:2px; opacity:.6; font-size:11px;">Teller lagret hero + board der lagret hero hadde en av dine nåværende ranker.</div>
    <table style="width:100%; border-collapse:collapse; font-size:12px; background:#fff; border:1px solid #e5e7eb; margin-top:5px;">
      <thead>
        <tr style="background:#f3f4f6;">
          <th style="text-align:left; padding:7px 8px; border-bottom:1px solid #d1d5db;">Håndtype</th>
          <th style="text-align:center; padding:7px 8px; border-bottom:1px solid #d1d5db;">Antall</th>
          <th style="text-align:left; padding:7px 8px; border-bottom:1px solid #d1d5db;">Sist treff</th>
          <th style="text-align:left; padding:7px 8px; border-bottom:1px solid #d1d5db;">Siste board</th>
        </tr>
      </thead>
      <tbody>${madeHandRows}</tbody>
    </table>
  `;

  box.innerHTML = `
    <div style="border:1px solid #e5e7eb; background:#fafafa; padding:8px; border-radius:6px;">
      <div style="display:flex; justify-content:space-between; gap:10px; align-items:flex-start; margin-bottom:8px;">
        <div>
          <div style="font-weight:800; margin-bottom:2px;">Hero-ranker mot board</div>
          <div style="font-size:10px; opacity:.45; margin-bottom:2px;">visning: file-history-all-db-registered-hero-rank-match-20260708b</div>
          <div style="font-size:11px; opacity:.65;">${escapeHtml(heroCards.join(" "))} sjekket mot ${sameHeroWithBoardCount} lagrede boards totalt. Radene teller bare lagrede hender der lagret hero hadde ranken og samme rank kom på lagret board.</div>
          <div style="font-size:11px; opacity:.55; margin-top:2px;">Lagrede boards brukt i match: ${sameHeroWithBoardCount}.</div>
          ${historyNotice ? `<div style="font-size:12px; color:#b45309; margin-top:6px; font-weight:700;">${escapeHtml(historyNotice)}</div>` : ""}
          ${storedHeroHands && !storedBoardHands ? `<div style="font-size:12px; color:#b45309; margin-top:6px; font-weight:700;">Du har ${storedHeroHands} hero-hender lagret, men ingen boardkort på dem. Registrer board for at match-historikken skal få treff.</div>` : ""}
          <div style="font-size:11px; opacity:.55; margin-top:2px;">Historikkilde: ${escapeHtml(matchSourceLabel)}</div>
        </div>
      </div>
      <table style="width:100%; border-collapse:collapse; font-size:12px; background:#fff; border:1px solid #e5e7eb;">
        <thead>
          <tr style="background:#f3f4f6;">
            <th style="text-align:left; padding:7px 8px; border-bottom:1px solid #d1d5db;">Type</th>
            <th style="text-align:center; padding:7px 8px; border-bottom:1px solid #d1d5db;">Antall</th>
            <th style="text-align:left; padding:7px 8px; border-bottom:1px solid #d1d5db;">Sist treff</th>
            <th style="text-align:left; padding:7px 8px; border-bottom:1px solid #d1d5db;">Siste board</th>
          </tr>
        </thead>
        <tbody>${tableRows}</tbody>
      </table>
      ${madeHandTable}
      <div style="margin-top:6px; opacity:.6; font-size:11px;">Matchhistorikk hentes kun fra database/filhistorikk. Nyeste runde først.</div>
    </div>
  `;
}

function addCardHistoryEntry() {
  return false;
}

function saveHeroBoardMatchHistory() {
  return false;
}

function renderCardHistory() {
  const box = $("cardHistoryBox");
  if (!box) return;
  const canRetryBackendHistory = !backendCardHistoryError || (Date.now() - backendCardHistoryLastAttemptAt > 15000);
  if (!backendCardHistory.length && !backendCardHistoryInFlight && canRetryBackendHistory) {
    refreshBackendCardHistory({ force: true, limit: 1000, timeoutMs: 15000, render: true }).catch(console.warn);
  }
  if (backendCardHistoryInFlight && !backendCardHistory.length) {
    const elapsed = backendCardHistoryStartedAt ? Date.now() - backendCardHistoryStartedAt : 0;
    if (elapsed > 10000) {
      backendCardHistoryInFlight = false;
      backendCardHistoryStartedAt = 0;
      backendCardHistoryError = "timeout";
    } else {
      const seconds = Math.max(1, Math.ceil(elapsed / 1000));
      box.innerHTML = `<div style="opacity:.7; font-style:italic;">Laster kort historikk fra backend... ${seconds}s</div>`;
      return;
    }
  }
  const list = sortCardHistoryNewestFirst(dedupeCardHistory(backendCardHistory))
    .map((entry, index) => ({
      ...entry,
      history_order_index: index,
      overall_index: index
    }));
  if (!list.length) {
    box.innerHTML = `
      <div style="opacity:.7; font-style:italic;">Ingen kort historikk enna.</div>
      <div style="margin-top:6px; font-size:12px; opacity:.6;">${backendCardHistoryError ? `Filhistorikk: ${escapeHtml(backendCardHistoryError)}.` : "Historikken hentes kun fra database/filhistorikk."}</div>
    `;
    renderHeroHistoryMatches();
    return;
  }

  // aggregate counts
  const cardCount = {}; // e.g. Ah: 3
  const rankCount = {}; // A,K,Q,...
  const suitCount = { s: 0, h: 0, d: 0, c: 0 };
  let pairs = 0, suited = 0, offsuit = 0;

  for (const e of list) {
    const [a, b] = e.hero;
    if (!a || !b) continue;
    cardCount[a] = (cardCount[a] || 0) + 1;
    cardCount[b] = (cardCount[b] || 0) + 1;

    const ra = a[0], rb = b[0];
    const sa = a[1], sb = b[1];
    rankCount[ra] = (rankCount[ra] || 0) + 1;
    rankCount[rb] = (rankCount[rb] || 0) + 1;
    if (suitCount[sa] !== undefined) suitCount[sa]++;
    if (suitCount[sb] !== undefined) suitCount[sb]++;

    if (ra === rb) pairs++;
    else if (sa === sb) suited++;
    else offsuit++;
  }

  // build HTML with saved history updates
  const recent = list.slice(0, 12).map((e, idx) => {
    const d = new Date(e.at);
    const time = d.toLocaleTimeString();
    const boardTxt = (e.board && e.board.length) ? ` | board: <span style="color:#666;">${e.board.join(" ")}</span>` : "";
    const rowStyle = idx === 0 ? ' style="background:#e8f5e9; padding:4px; margin:0 -4px; border-radius:3px;"' : '';
    return `<div${rowStyle} style="margin-bottom:4px;"><b style="color:#1976D2;">${e.hero.join(" ")}</b>${boardTxt} <span style="opacity:.5; font-size:11px; margin-left:8px;">â° ${time}</span></div>`;
  }).join("");

  const cardLines = Object.keys(cardCount).sort((a,b)=>cardCount[b]-cardCount[a]).map(c=>`<span style="color:#D32F2F;"><b>${c}</b>:${cardCount[c]}</span>`).join("  ");
  const rankLines = Object.keys(rankCount).sort((a,b)=>rankCount[b]-rankCount[a]).map(r=>`<span style="color:#1976D2;"><b>${r}</b></span>:${rankCount[r]}`).join(" ");
  const suitLines = `<span style="color:#388E3C;">â™ </span>:${suitCount.s} <span style="color:#D32F2F;">â™¥</span>:${suitCount.h} <span style="color:#1976D2;">â™¦</span>:${suitCount.d} <span style="color:#F57C00;">â™£</span>:${suitCount.c}`;

  box.innerHTML = `
    <div style="margin-bottom:10px; display:flex; justify-content:space-between; align-items:center;">
      <div style="font-weight:600;">Filhistorikk (${list.length} totalt)</div>
      <div style="font-size:11px; opacity:.6;">database/filhistorikk - oppdateres automatisk</div>
    </div>
    <div style="margin-bottom:10px; background:#fafafa; padding:8px; border-radius:4px; max-height:120px; overflow-y:auto; border-left:3px solid #1976D2;">${recent}</div>
    <div style="margin-top:8px; font-size:12px; opacity:.9;"><strong>Kort:</strong> ${cardLines}</div>
    <div style="margin-top:4px; font-size:12px; opacity:.85;"><strong>Rank:</strong> ${rankLines}</div>
    <div style="margin-top:4px; font-size:12px; opacity:.85;"><strong>Suit:</strong> ${suitLines}</div>
    <div style="margin-top:6px; font-size:12px; opacity:.8;"><strong>Typer:</strong> <span style="color:#4CAF50;">pairs</span>:${pairs} <span style="color:#2196F3;">suited</span>:${suited} <span style="color:#FF9800;">offsuit</span>:${offsuit}</div>
  `;
  const copyCaptureBtn = $("copyLiveCapture");
  if (copyCaptureBtn) copyCaptureBtn.addEventListener("click", async () => {
    const capture = copyCaptureBtn.dataset.capture || "";
    if (!capture) return;
    try {
      await navigator.clipboard.writeText(capture);
      copyCaptureBtn.innerText = "Kopiert";
    } catch (e) {
      window.prompt("Kopier capture-filnavn:", capture);
    }
  });
  renderHeroHistoryMatches();
}

// ------------------------------
// Equity Calculator
// ------------------------------
let equityRunning = false;
let equityTimer = null;
let equityRerunRequested = false;
let equityRerunOpts = null;

// Trigges naar kortfeltene oppdateres av live-leser eller manuell input.
function handleCardInput() {
  manualLiveMode = true;
  renderHeroHistoryMatches();
  const autoStatus = $("autoEquityStatus");
  if (autoStatus) autoStatus.innerText = "Manuell laas: setup styres av deg.";
  const autoEquity = $("autoEquity");
  if (autoEquity && autoEquity.checked) {
    console.log(`ðŸŽ¯ Cards manually updated, triggering equity calculation...`);
    const autoStatus = $("autoEquityStatus");
    if (autoStatus) autoStatus.innerText = "Equity: venter...";
    if (equityTimer) clearTimeout(equityTimer);
    equityTimer = setTimeout(() => {
      runEquityCalculation({ auto: true, manual: true, live: true, saveHistory: false }).catch(console.error);
    }, 350);
  }
}

async function runEquityCalculation(opts = { auto: false }) {
  console.log(`ðŸŽ² runEquityCalculation called, opts:`, opts);
  const heroText = normalizeSpaces((opts.heroText ?? $("hero")?.value) || lastLiveHeroText);
  const fallbackBoardText = opts.live ? "" : cardsToText(liveBoardFallbackCards());
  const boardText = normalizeSpaces((opts.boardText ?? (opts.live ? "" : $("board")?.value)) || fallbackBoardText);
  const villains = Number($("numVillains")?.value || 1);
  const rangesText = normalizeSpaces($("villains")?.value || "");
  console.log(`  heroText="${heroText}", boardText="${boardText}", villains=${villains}`);
  const resultEl = $(opts.resultId || "result");
  const detailsEl = $(opts.detailsId || "equityDetails");
  const autoStatus = $("autoEquityStatus");
  const statusPrefix = opts.label || (opts.manual ? "Manuell" : "Live");
  if (!resultEl) {
    console.warn("âš ï¸ resultEl not found");
    return;
  }

  const heroCards = parseCards(heroText);
  const boardCards = parseCards(boardText);
  console.log(`  heroCards:`, heroCards, `boardCards:`, boardCards);

  // Basic validation
  if (heroCards.length !== 2) {
    console.log(`âš ï¸ Validation failed: heroCards.length=${heroCards.length}, expected 2`);
    if (!opts.auto) {
      resultEl.innerText = "âŒ Feil: Du mÃ¥ skrive inn nÃ¸yaktig 2 kort, f.eks. 'Ah Kh'.";
      if (detailsEl) detailsEl.innerText = "";
    }
    if (autoStatus) autoStatus.innerText = `${statusPrefix}: vent pa 2 kort.`;
    return;
  }
  if (boardCards.length > 5) {
    resultEl.innerText = "âŒ Feil: Board kan maks ha 5 kort.";
    if (detailsEl) detailsEl.innerText = "";
    return;
  }

  const all = heroCards.concat(boardCards);
  for (const c of all) {
    if (!isCard(c)) {
      console.log(`âš ï¸ Invalid card format: "${c}"`);
      resultEl.innerText = `âŒ Feil: Kortet '${c}' har feil format. Bruk f.eks. Ah, Td, 7c. (T=10)`;
      if (detailsEl) detailsEl.innerText = "";
      if (autoStatus) autoStatus.innerText = `${statusPrefix}: ugyldig kortformat.`;
      return;
    }
  }
  const uniq = new Set(all);
  if (uniq.size !== all.length) {
    console.log(`âš ï¸ Duplicate cards detected`);
    resultEl.innerText = "âŒ Feil: Du har skrevet inn samme kort flere ganger.";
    if (detailsEl) detailsEl.innerText = "";
    if (autoStatus) autoStatus.innerText = `${statusPrefix}: duplikatkort.`;
    return;
  }

  if (equityRunning) {
    console.log(`âš ï¸ Equity already running, skipping (equityRunning=${equityRunning})`);
    if (autoStatus && opts.auto) autoStatus.innerText = `${statusPrefix}: beregner...`;
    if (opts.auto) {
      equityRerunRequested = true;
      equityRerunOpts = opts;
    }
    return;
  }

  console.log(`âœ… Validation passed, starting equity calculation...`);
  equityRunning = true;
  const iters = opts.auto ? 8000 : 20000;
  resultEl.innerText = `â³ Beregner equity (${iters.toLocaleString()} iterasjoner)â€¦`;
  if (detailsEl) detailsEl.innerText = "";
  if (autoStatus && opts.auto) autoStatus.innerText = `${statusPrefix}: beregner...`;

  // Fallback timeout: hvis fetch tar >30s, reset equityRunning
  const timeoutId = setTimeout(() => {
    if (equityRunning) {
      console.error("âš ï¸ Equity calculation timeout after 30s, resetting");
      equityRunning = false;
      if (autoStatus) autoStatus.innerText = `${statusPrefix}: timeout, retry...`;
    }
  }, 30000);

  try {
    const payload = { hero: heroCards, board: boardCards, villains, iters, ranges: rangesText };
    console.log(`ðŸŒ Fetching equity from ${apiBase()}/equity with:`, payload);
    const res = await fetch(`${apiBase()}/equity`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    console.log(`ðŸ“¡ Fetch response status: ${res.status}`);
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    if (manualLiveMode && !opts.manual) {
      console.log("Skipping stale live equity result while manual mode is active");
      return;
    }
    console.log(`ðŸ“Š Received equity data:`, data);
    const win = Math.round(data.win * 1000) / 10;
    const tie = Math.round(data.tie * 1000) / 10;
    const lose = Math.round(data.lose * 1000) / 10;
    if (!opts.preview) {
      window.lastEquity = {
        win,
        tie,
        lose,
        villains,
        heroCards,
        boardCards
      };
    }
    console.log(`ðŸ“ˆ Calculated percentages: Win=${win}%, Tie=${tie}%, Lose=${lose}%`);
    
    // Format main result
    const mainResult = `
      <div style="font-size:18px; font-weight:bold; margin-bottom:8px;">
        Win: <span style="color:#4CAF50;">${win}%</span> | 
        Tie: <span style="color:#FF9800;">${tie}%</span> | 
        Lose: <span style="color:#f44336;">${lose}%</span>
      </div>
    `;
    
    // Format details
    let detailsHtml = `
      <div style="background:#f5f5f5; padding:8px; border-radius:4px; font-size:12px;">
        <div><strong>Setup:</strong> ${heroCards.join(" ")} vs ${villains} villain${villains > 1 ? "s" : ""}</div>
    `;
    
    if (boardCards.length > 0) {
      const boardState = boardCards.length === 0 ? "preflop" : 
                        boardCards.length === 3 ? "flop" : 
                        boardCards.length === 4 ? "turn" : "river";
      detailsHtml += `<div><strong>Board:</strong> ${boardCards.join(" ")} (${boardState})</div>`;
    } else {
      detailsHtml += `<div><strong>Stage:</strong> Preflop</div>`;
    }
    
    detailsHtml += `<div style="margin-top:6px; opacity:.7;"><strong>Iterasjoner:</strong> ${data.iters.toLocaleString()}</div>`;
    if (rangesText) {
      detailsHtml += `<div style="margin-top:6px; opacity:.7;"><strong>Range:</strong> ${escapeHtml(rangesText)}</div>`;
    }
    detailsHtml += `</div>`;
    
    console.log(`ðŸ–¼ï¸ Updating DOM: resultEl=${resultEl}, detailsEl=${detailsEl}`);
    console.log(`   mainResult HTML:`, mainResult);
    if (!resultEl) {
      console.error("âŒ resultEl not found! Looking for id='result'");
    } else {
      resultEl.innerHTML = mainResult;
      console.log(`âœ… resultEl.innerHTML set. Current content:`, resultEl.innerHTML);
    }
    if (detailsEl) {
      detailsEl.innerHTML = detailsHtml;
      console.log(`âœ… detailsEl.innerHTML set. Current content:`, detailsEl.innerHTML);
    }
    if (autoStatus && opts.auto) autoStatus.innerText = `${statusPrefix}: oppdatert`;
    console.log(`âœ¨ DOM updated successfully`);
    
    const shouldSaveHistory = opts.saveHistory === true;
    if (shouldSaveHistory) {
      try { addCardHistoryEntry(heroCards, boardCards, "equity-calculation"); } catch(e) { console.warn(e); }
    }
  } catch (e) {
    console.error("âŒ Equity fetch failed:", e);
    resultEl.innerText = "âŒ Feil: klarte ikke Ã¥ kontakte backend (/equity).";
    if (detailsEl) detailsEl.innerText = "";
    if (autoStatus && opts.auto) autoStatus.innerText = `${statusPrefix}: feil mot backend`;
  } finally {
    clearTimeout(timeoutId);
    console.log(`ðŸ”“ Setting equityRunning = false`);
    equityRunning = false;
    if (equityRerunRequested) {
      const nextOpts = equityRerunOpts || { auto: true };
      equityRerunRequested = false;
      equityRerunOpts = null;
      setTimeout(() => runEquityCalculation(nextOpts).catch(console.error), 50);
    }
  }
}

function scheduleAutoEquity(opts = {}) {
  if (typeof renderManualCardPicker === "function") renderManualCardPicker();
  const auto = $("autoEquity");
  const autoStatus = $("autoEquityStatus");
  if (manualLiveMode && !opts.manual && !opts.live) {
    if (autoStatus) autoStatus.innerText = "Manuell laas: setup styres av deg.";
    return;
  }
  if (!auto || !auto.checked) {
    if (autoStatus) autoStatus.innerText = "Manuell: sla pa auto";
    return;
  }
  if (autoStatus) autoStatus.innerText = opts.live ? "Live: venter..." : "Manuell: venter...";
  if (equityTimer) clearTimeout(equityTimer);
  equityTimer = setTimeout(() => {
    runEquityCalculation({
      auto: true,
      manual: !opts.live,
      live: Boolean(opts.live),
      heroText: opts.heroText,
      boardText: opts.boardText,
      saveHistory: false
    }).catch(console.error);
  }, 450);
}

async function runHandProbabilities() {
  const heroCards = parseCards($("hero")?.value || "");
  const boardCards = parseCards($("board")?.value || "");
  const out = $("handProbResult");
  if (!out) return;

  if (heroCards.length !== 2 || !heroCards.every(isCard)) {
    out.innerText = "Skriv inn 2 gyldige kort først, f.eks. Ah Kh.";
    return;
  }
  if (boardCards.length > 5 || !boardCards.every(isCard)) {
    out.innerText = "Board kan ha maks 5 gyldige kort.";
    return;
  }
  const all = heroCards.concat(boardCards);
  if (new Set(all).size !== all.length) {
    out.innerText = "Samme kort finnes flere ganger.";
    return;
  }

  const history = combinedCardHistory().slice(0, 500);
  out.innerText = `Beregner håndsjanser (${history.length} historikk-hender)...`;

  try {
    const res = await fetch(`${apiBase()}/hand-probabilities`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        hero: heroCards,
        board: boardCards,
        history,
        iters: 25000
      })
    });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    const labels = [
      ["High Card", "High card"],
      ["Pair", "Par"],
      ["Two Pair", "To par"],
      ["Three of a Kind", "Trips"],
      ["Straight", "Straight"],
      ["Flush", "Flush"],
      ["Full House", "Full house"],
      ["Four of a Kind", "Quads"],
      ["Straight Flush", "Straight flush"]
    ];
    const rows = labels.map(([key, label]) => {
      const pct = Math.round((data.probabilities?.[key] || 0) * 1000) / 10;
      return `
        <div style="display:flex; justify-content:space-between; gap:10px; border-bottom:1px solid #eee; padding:3px 0;">
          <span>${label}</span>
          <strong>${pct}%</strong>
        </div>
      `;
    }).join("");
    out.innerHTML = `
      <div style="background:#f5f5f5; padding:8px; border-radius:4px;">
        <div style="font-weight:700; margin-bottom:6px;">Håndsjanser fra historikk</div>
        ${rows}
        <div style="margin-top:6px; opacity:.65;">${data.iters.toLocaleString()} simuleringer, ${data.history_cards} historikk-kort brukt som vekting.</div>
      </div>
    `;
  } catch (e) {
    console.error("Hand probabilities failed:", e);
    out.innerText = "Klarte ikke å beregne håndsjanser.";
  }
}

const MANUAL_CARD_RANKS = ["A", "K", "Q", "J", "T", "9", "8", "7", "6", "5", "4", "3", "2"];
const MANUAL_CARD_SUITS = [
  { label: "&spades;", value: "s", color: "#111" },
  { label: "&hearts;", value: "h", color: "#c62828" },
  { label: "&diams;", value: "d", color: "#c62828" },
  { label: "&clubs;", value: "c", color: "#111" }
];
let manualPickerRank = "A";
let manualPickerTarget = "hero";
let manualPickerHeroCards = [];
let manualPickerBoardCards = [];
let hvPickerRank = "A";
let hvPickerTarget = "hero";
let hvHeroCards = [];
let hvBoardCards = [];
let hvEquityManualMode = false;
let heroCorrectionCards = [];
let heroCorrectionSelected = 0;
let boardCorrectionCards = [];
let boardCorrectionSelected = 0;

function cardsToText(cards) {
  return (cards || []).join(" ");
}

function setCardInputValue(id, value) {
  const el = $(id);
  if (!el) return;
  el.value = value;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

function selectedManualCards() {
  return {
    hero: manualPickerHeroCards.slice(),
    board: manualPickerBoardCards.slice()
  };
}

function activateManualCardMode() {
  manualLiveMode = true;
  const autoStatus = $("autoEquityStatus");
  if (autoStatus) autoStatus.innerText = "Manuell laas: setup styres av deg.";
}

function setManualCards(heroCards, boardCards) {
  activateManualCardMode();
  manualPickerHeroCards = (heroCards || []).slice();
  manualPickerBoardCards = (boardCards || []).slice();
  lastManualHeroText = cardsToText(manualPickerHeroCards);
  const heroEl = $("hero");
  const boardEl = $("board");
  if (heroEl) heroEl.value = cardsToText(manualPickerHeroCards);
  if (boardEl) boardEl.value = cardsToText(manualPickerBoardCards);
  renderManualCardPicker();
  renderHeroHistoryMatches();
  scheduleAutoEquity({ manual: true });
}

function manualPickerStatus(text) {
  const el = $("manualCardPickerStatus");
  if (el) el.innerText = text || "";
}

function chooseManualCard(suit) {
  const picked = `${manualPickerRank}${suit}`;
  const { hero, board } = selectedManualCards();
  const all = hero.concat(board);
  if (all.includes(picked)) {
    manualPickerStatus(`${picked} er allerede valgt.`);
    return;
  }

  if (manualPickerTarget === "hero" && hero.length < 2) {
    hero.push(picked);
    if (hero.length >= 2) manualPickerTarget = "board";
  } else if (manualPickerTarget === "hero" && board.length < 5) {
    manualPickerTarget = "board";
    board.push(picked);
  } else if (manualPickerTarget === "board" && board.length < 5) {
    board.push(picked);
  } else {
    manualPickerStatus("Hero og board er fullt. Bruk Angre eller Tom.");
    return;
  }

  setManualCards(hero, board);
  manualPickerStatus(`La til ${picked}.`);
}

function undoManualCard() {
  const { hero, board } = selectedManualCards();
  if (manualPickerTarget === "hero" && hero.length) {
    hero.pop();
  } else if (board.length) {
    board.pop();
  } else if (hero.length) {
    hero.pop();
  }
  if (hero.length < 2) manualPickerTarget = "hero";
  setManualCards(hero, board);
  manualPickerStatus("Angret siste kort.");
}

function clearManualCards() {
  manualPickerTarget = "hero";
  manualPickerHeroCards = [];
  manualPickerBoardCards = [];
  manualLiveMode = false;
  lastManualHeroText = "";
  lastManualBoardText = "";
  const heroEl = $("hero");
  const boardEl = $("board");
  if (heroEl) heroEl.value = "";
  if (boardEl) boardEl.value = "";
  renderManualCardPicker();
  const resultEl = $("result");
  const detailsEl = $("equityDetails");
  if (resultEl) resultEl.innerText = "Fyll inn kortene og trykk \"Beregn Equity\"";
  if (detailsEl) detailsEl.innerText = "";
  const autoStatus = $("autoEquityStatus");
  if (autoStatus) autoStatus.innerText = "Auto-leser aktiv.";
  manualPickerStatus("Klar for ny hand.");
}

function setHeroRegisterStatus(text) {
  const el = $("heroRegisterStatus");
  if (el) el.innerText = text || "";
}

function showHeroClipboardPreview(dataUrl) {
  const wrap = $("heroClipboardPreview");
  const img = $("heroClipboardImage");
  if (!wrap || !img || !dataUrl) return;
  img.src = dataUrl;
  wrap.style.display = "block";
}

async function readCardsFromImageDataUrl(dataUrl) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort("Kortlesing tok for lang tid."), 30000);
  let res;
  try {
    res = await fetch(`${apiBase()}/read-board-image`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image_data: dataUrl }),
      signal: controller.signal
    });
  } catch (e) {
    if (e?.name === "AbortError" || controller.signal.aborted) {
      throw new Error("Kortlesing tok over 30 sekunder. Prov igjen, eller klipp tettere rundt kortene.");
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }

  let data = {};
  try {
    data = await res.json();
  } catch (_) {
    data = {};
  }

  if (!res.ok) {
    const detail = data?.detail || data?.error || `HTTP ${res.status}`;
    throw new Error(detail);
  }

  return parseCards(data.board || "").filter(isCard).slice(0, 5);
}

function syncHeroCorrectionInput() {
  const input = $("heroRegisterInput");
  if (input) input.value = cardsToText(heroCorrectionCards);
}

function renderHeroCorrection() {
  const box = $("heroCorrectionBox");
  if (!box) return;
  if (!heroCorrectionCards.length) {
    box.style.display = "none";
    box.innerHTML = "";
    return;
  }
  box.style.display = "block";

  const cardButtons = heroCorrectionCards.map((card, idx) => `
    <button type="button" class="heroCorrectionCard" data-idx="${idx}" style="min-width:42px; height:30px; border:1px solid ${idx === heroCorrectionSelected ? "#111" : "#ccc"}; background:${idx === heroCorrectionSelected ? "#111" : "#fff"}; color:${idx === heroCorrectionSelected ? "#fff" : "#111"}; border-radius:4px; font-weight:700; cursor:pointer;">
      ${escapeHtml(card)}
    </button>
  `).join("");
  const rankButtons = MANUAL_CARD_RANKS.map(rank => `
    <button type="button" class="heroCorrectionRank" data-rank="${rank}" style="width:28px; height:26px; border:1px solid #ccc; background:#fff; border-radius:4px; font-weight:700; cursor:pointer;">${rank}</button>
  `).join("");
  const suitButtons = MANUAL_CARD_SUITS.map(suit => `
    <button type="button" class="heroCorrectionSuit" data-suit="${suit.value}" style="width:34px; height:28px; border:1px solid #ccc; background:#fff; color:${suit.color}; border-radius:4px; font-size:17px; cursor:pointer;">${suit.label}</button>
  `).join("");

  box.innerHTML = `
    <div style="font-weight:700; margin-bottom:6px;">Rett hero-forslag</div>
    <div style="display:flex; gap:6px; flex-wrap:wrap; margin-bottom:8px;">${cardButtons}</div>
    <div style="display:flex; gap:5px; flex-wrap:wrap; margin-bottom:6px;">${rankButtons}</div>
    <div style="display:flex; gap:6px; flex-wrap:wrap; align-items:center;">
      ${suitButtons}
      <button type="button" id="heroCorrectionRemove" style="height:28px;">Fjern</button>
      <button type="button" id="heroCorrectionAdd" style="height:28px;">Legg til</button>
      <button type="button" id="heroCorrectionApply" style="height:28px; font-weight:700;">Bruk forslag</button>
    </div>
  `;

  box.querySelectorAll(".heroCorrectionCard").forEach(btn => {
    btn.addEventListener("click", () => {
      heroCorrectionSelected = Number(btn.dataset.idx || 0);
      renderHeroCorrection();
    });
  });
  box.querySelectorAll(".heroCorrectionRank").forEach(btn => {
    btn.addEventListener("click", () => {
      const idx = Math.max(0, Math.min(heroCorrectionSelected, heroCorrectionCards.length - 1));
      const old = heroCorrectionCards[idx] || "As";
      heroCorrectionCards[idx] = `${btn.dataset.rank || "A"}${old[1] || "s"}`;
      syncHeroCorrectionInput();
      renderHeroCorrection();
    });
  });
  box.querySelectorAll(".heroCorrectionSuit").forEach(btn => {
    btn.addEventListener("click", () => {
      const idx = Math.max(0, Math.min(heroCorrectionSelected, heroCorrectionCards.length - 1));
      const old = heroCorrectionCards[idx] || "As";
      heroCorrectionCards[idx] = `${old[0] || "A"}${btn.dataset.suit || "s"}`;
      syncHeroCorrectionInput();
      renderHeroCorrection();
    });
  });
  $("heroCorrectionRemove")?.addEventListener("click", () => {
    if (!heroCorrectionCards.length) return;
    heroCorrectionCards.splice(heroCorrectionSelected, 1);
    heroCorrectionSelected = Math.max(0, Math.min(heroCorrectionSelected, heroCorrectionCards.length - 1));
    syncHeroCorrectionInput();
    renderHeroCorrection();
  });
  $("heroCorrectionAdd")?.addEventListener("click", () => {
    if (heroCorrectionCards.length >= 2) {
      setHeroRegisterStatus("Hero kan maks ha 2 kort.");
      return;
    }
    heroCorrectionCards.push("As");
    heroCorrectionSelected = heroCorrectionCards.length - 1;
    syncHeroCorrectionInput();
    renderHeroCorrection();
  });
  $("heroCorrectionApply")?.addEventListener("click", () => {
    registerHeroCards(heroCorrectionCards, "Hero registrert fra rettet forslag.");
  });
}

function setHeroCorrectionCards(cards) {
  heroCorrectionCards = (cards || []).map(convertBetSolidCard).filter(isCard).slice(0, 2);
  heroCorrectionSelected = 0;
  syncHeroCorrectionInput();
  renderHeroCorrection();
}

function registerHeroCards(heroCards, source = "Hero registrert.") {
  const normalizedHero = (heroCards || []).map(convertBetSolidCard).filter(Boolean).slice(0, 2);
  const boardCards = [];

  if (normalizedHero.length !== 2) {
    setHeroRegisterStatus("Hero må ha 2 kort.");
    return false;
  }
  if (!normalizedHero.every(isCard)) {
    setHeroRegisterStatus("Ugyldig hero-format. Bruk f.eks. Ah Kh.");
    return false;
  }
  if (new Set(normalizedHero.concat(boardCards)).size !== normalizedHero.length + boardCards.length) {
    setHeroRegisterStatus("Samme kort finnes i hero/board.");
    return false;
  }

  manualLiveMode = true;
  manualPickerHeroCards = normalizedHero.slice();
  if (boardCards.length) manualPickerBoardCards = boardCards.slice();
  manualPickerTarget = manualPickerHeroCards.length < 2 ? "hero" : "board";

  const heroText = cardsToText(normalizedHero);
  lastManualHeroText = heroText;
  setCardInputValue("hero", heroText);
  setCardInputValue("heroRegisterInput", heroText);
  heroCorrectionCards = [];
  renderHeroCorrection();

  renderManualCardPicker();
  renderHeroHistoryMatches();
  scheduleAutoEquity({ manual: true });
  setHeroRegisterStatus(source);
  return true;
}

async function readHeroFromClipboard() {
  try {
    setHeroRegisterStatus("Leser utklipp...");

    if (navigator.clipboard?.readText) {
      try {
        const text = await navigator.clipboard.readText();
        const cards = parseBoardCardsFromClipboardText(text).slice(0, 2);
        if (cards.length) {
          if (cards.length === 2) registerHeroCards(cards, "Hero lest fra clipboard-tekst.");
          else {
            const input = $("heroRegisterInput");
            if (input) input.value = cardsToText(cards);
            setHeroCorrectionCards(cards);
            setHeroRegisterStatus("Fant bare 1 kort i teksten. Rett og legg til ett kort.");
          }
          return;
        }
      } catch (_) {
        // Clipboard text can be blocked while image read still works.
      }
    }

    if (!navigator.clipboard?.read) {
      setHeroRegisterStatus("Nettleseren støtter ikke bildelesing fra clipboard her.");
      return;
    }

    const items = await navigator.clipboard.read();
    for (const item of items) {
      const imageType = item.types.find(type => type.startsWith("image/"));
      if (!imageType) continue;

      const blob = await item.getType(imageType);
      await readHeroImageBlob(blob, "Hero lest fra clipboard-bilde.");
      return;
    }

    setHeroRegisterStatus("Ingen tekst eller bilde funnet i clipboard.");
  } catch (e) {
    console.warn("Clipboard hero read failed", e);
    $("heroPasteZone")?.focus();
    setHeroRegisterStatus("Nettleseren blokkerte direkte lesing. Klikk paste-sonen og trykk Ctrl+V.");
  }
}

async function readHeroImageBlob(blob, sourceLabel = "Hero lest fra bilde.") {
  heroCorrectionCards = [];
  renderHeroCorrection();
  const input = $("heroRegisterInput");
  if (input) input.value = "";

  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
  showHeroClipboardPreview(dataUrl);

  let cards = [];
  try {
    cards = await readCardsFromImageDataUrl(dataUrl);
  } catch (e) {
    setHeroRegisterStatus(e?.message || "Bildet ble limt inn, men automatisk bildelesing er ikke aktiv.");
    return false;
  }
  if (!cards.length) {
    setHeroRegisterStatus("Fant ingen hero-kort i bildet.");
    return false;
  }

  cards = cards.length > 2 ? [cards[0], cards[cards.length - 1]] : cards.slice(0, 2);
  if (input) input.value = cardsToText(cards);
  setHeroCorrectionCards(cards);
  setHeroRegisterStatus(`Forslag fra bilde: ${cardsToText(cards)}. Rett ved behov og trykk Registrer hero.`);
  return true;
}

async function handleHeroPaste(ev) {
  try {
    const data = ev.clipboardData;
    if (!data) return;
    ev.preventDefault();
    setHeroRegisterStatus("Leser innlimt utklipp...");

    const text = data.getData("text/plain") || "";
    const textCards = parseBoardCardsFromClipboardText(text).slice(0, 2);
    if (textCards.length) {
      if (textCards.length === 2) registerHeroCards(textCards, "Hero lest fra innlimt tekst.");
      else {
        const input = $("heroRegisterInput");
        if (input) input.value = cardsToText(textCards);
        setHeroCorrectionCards(textCards);
        setHeroRegisterStatus("Fant bare 1 kort i teksten. Rett og legg til ett kort.");
      }
      return;
    }

    const imageItem = Array.from(data.items || []).find(item => item.type && item.type.startsWith("image/"));
    if (!imageItem) {
      setHeroRegisterStatus("Fant ingen korttekst eller bilde i innlimingen.");
      return;
    }

    const blob = imageItem.getAsFile();
    if (!blob) {
      setHeroRegisterStatus("Klarte ikke hente bilde fra innliming.");
      return;
    }
    await readHeroImageBlob(blob, "Hero lest fra innlimt bilde.");
  } catch (e) {
    console.warn("Hero paste failed", e);
    setHeroRegisterStatus("Klarte ikke lese innlimt utklipp.");
  }
}

function sendHeroToProfileEquity() {
  const heroCards = parseCards($("heroRegisterInput")?.value || $("hero")?.value || "").filter(isCard).slice(0, 2);
  if (heroCards.length !== 2) {
    setHeroRegisterStatus("Trenger 2 hero-kort før sending.");
    return false;
  }
  if (!$("ppHeroCards")) {
    setHeroRegisterStatus("Åpne/last Live equity mot først.");
    return false;
  }

  if ($("ppEquityAuto")) $("ppEquityAuto").checked = false;
  $("ppHeroCards").value = cardsToText(heroCards);
  if ($("ppBoardCards") && $("board")?.value) $("ppBoardCards").value = normalizeSpaces($("board").value);
  syncProfileEquityPickerFromInputs({ manual: true });
  lastPlayerProfileEquityKey = "";
  setHeroRegisterStatus("Hero sendt til Live equity mot.");
  setProfileEquityStatus("Hero-kort kopiert fra Equity Calculator.");
  calculateProfileEquity().catch(console.warn);
  $("ppHeroCards")?.scrollIntoView({ behavior: "smooth", block: "center" });
  return true;
}

async function useLiveHeroForMainEquity() {
  try {
    setHeroRegisterStatus("Henter live hero...");
    const res = await fetch(`${apiBase()}/live-cards?ts=${Date.now()}`);
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    const heroCards = parseCards(data.hero_cards || data.hero || "").filter(isCard).slice(0, 2);
    if (heroCards.length !== 2) {
      setHeroRegisterStatus("Fant ikke 2 live hero-kort.");
      return false;
    }
    return registerHeroCards(heroCards, "Live hero registrert.");
  } catch (e) {
    console.warn("Could not fetch live hero", e);
    setHeroRegisterStatus("Klarte ikke hente live hero.");
    return false;
  }
}

function sendManualPickerToHeroRegister() {
  const { hero } = selectedManualCards();
  const heroCards = hero.map(convertBetSolidCard).filter(isCard).slice(0, 2);
  const status = $("manualCardPickerStatus");

  if (heroCards.length !== 2 || !heroCards.every(isCard)) {
    if (status) status.innerText = "Velg 2 manuelle hero-kort før sending.";
    return false;
  }

  const sent = registerHeroCards(heroCards, "Manuell hero registrert fra kortvelger.");
  if (sent && status) status.innerText = "Manuell hero sendt til Hero-register.";
  return sent;
}

function setBoardRegisterStatus(text) {
  const el = $("boardRegisterStatus");
  if (el) el.innerText = text || "";
}

function showBoardClipboardPreview(dataUrl) {
  const wrap = $("boardClipboardPreview");
  const img = $("boardClipboardImage");
  if (!wrap || !img || !dataUrl) return;
  img.src = dataUrl;
  wrap.style.display = "block";
}

function syncBoardCorrectionInput() {
  const input = $("boardRegisterInput");
  if (input) input.value = cardsToText(boardCorrectionCards);
}

function renderBoardCorrection() {
  const box = $("boardCorrectionBox");
  if (!box) return;
  if (!boardCorrectionCards.length) {
    box.style.display = "none";
    box.innerHTML = "";
    return;
  }
  box.style.display = "block";

  const cardButtons = boardCorrectionCards.map((card, idx) => `
    <button type="button" class="boardCorrectionCard" data-idx="${idx}" style="min-width:42px; height:30px; border:1px solid ${idx === boardCorrectionSelected ? "#111" : "#ccc"}; background:${idx === boardCorrectionSelected ? "#111" : "#fff"}; color:${idx === boardCorrectionSelected ? "#fff" : "#111"}; border-radius:4px; font-weight:700; cursor:pointer;">
      ${escapeHtml(card)}
    </button>
  `).join("");
  const rankButtons = MANUAL_CARD_RANKS.map(rank => `
    <button type="button" class="boardCorrectionRank" data-rank="${rank}" style="width:28px; height:26px; border:1px solid #ccc; background:#fff; border-radius:4px; font-weight:700; cursor:pointer;">${rank}</button>
  `).join("");
  const suitButtons = MANUAL_CARD_SUITS.map(suit => `
    <button type="button" class="boardCorrectionSuit" data-suit="${suit.value}" style="width:34px; height:28px; border:1px solid #ccc; background:#fff; color:${suit.color}; border-radius:4px; font-size:17px; cursor:pointer;">${suit.label}</button>
  `).join("");

  box.innerHTML = `
    <div style="font-weight:700; margin-bottom:6px;">Rett forslag</div>
    <div style="display:flex; gap:6px; flex-wrap:wrap; margin-bottom:8px;">${cardButtons}</div>
    <div style="display:flex; gap:5px; flex-wrap:wrap; margin-bottom:6px;">${rankButtons}</div>
    <div style="display:flex; gap:6px; flex-wrap:wrap; align-items:center;">
      ${suitButtons}
      <button type="button" id="boardCorrectionRemove" style="height:28px;">Fjern</button>
      <button type="button" id="boardCorrectionAdd" style="height:28px;">Legg til</button>
      <button type="button" id="boardCorrectionApply" style="height:28px; font-weight:700;">Bruk forslag</button>
    </div>
  `;

  box.querySelectorAll(".boardCorrectionCard").forEach(btn => {
    btn.addEventListener("click", () => {
      boardCorrectionSelected = Number(btn.dataset.idx || 0);
      renderBoardCorrection();
    });
  });
  box.querySelectorAll(".boardCorrectionRank").forEach(btn => {
    btn.addEventListener("click", () => {
      const idx = Math.max(0, Math.min(boardCorrectionSelected, boardCorrectionCards.length - 1));
      const old = boardCorrectionCards[idx] || "As";
      boardCorrectionCards[idx] = `${btn.dataset.rank || "A"}${old[1] || "s"}`;
      syncBoardCorrectionInput();
      renderBoardCorrection();
    });
  });
  box.querySelectorAll(".boardCorrectionSuit").forEach(btn => {
    btn.addEventListener("click", () => {
      const idx = Math.max(0, Math.min(boardCorrectionSelected, boardCorrectionCards.length - 1));
      const old = boardCorrectionCards[idx] || "As";
      boardCorrectionCards[idx] = `${old[0] || "A"}${btn.dataset.suit || "s"}`;
      syncBoardCorrectionInput();
      renderBoardCorrection();
    });
  });
  $("boardCorrectionRemove")?.addEventListener("click", () => {
    if (!boardCorrectionCards.length) return;
    boardCorrectionCards.splice(boardCorrectionSelected, 1);
    boardCorrectionSelected = Math.max(0, Math.min(boardCorrectionSelected, boardCorrectionCards.length - 1));
    syncBoardCorrectionInput();
    renderBoardCorrection();
  });
  $("boardCorrectionAdd")?.addEventListener("click", () => {
    if (boardCorrectionCards.length >= 5) {
      setBoardRegisterStatus("Board kan maks ha 5 kort.");
      return;
    }
    boardCorrectionCards.push("As");
    boardCorrectionSelected = boardCorrectionCards.length - 1;
    syncBoardCorrectionInput();
    renderBoardCorrection();
  });
  $("boardCorrectionApply")?.addEventListener("click", () => {
    registerBoardCards(boardCorrectionCards, "Board registrert fra rettet forslag.");
  });
}

function setBoardCorrectionCards(cards) {
  boardCorrectionCards = (cards || []).map(convertBetSolidCard).filter(isCard).slice(0, 5);
  boardCorrectionSelected = 0;
  syncBoardCorrectionInput();
  renderBoardCorrection();
}

function parseBoardCardsFromClipboardText(text) {
  let t = String(text || "")
    .replace(/♠|♤/g, "s")
    .replace(/♥|♡/g, "h")
    .replace(/♦|♢/g, "d")
    .replace(/♣|♧/g, "c")
    .replace(/\b(spades?|spar|spa?r)\b/gi, "s")
    .replace(/\b(hearts?|hjerter?)\b/gi, "h")
    .replace(/\b(diamonds?|ruter?)\b/gi, "d")
    .replace(/\b(clubs?|klo?ver?)\b/gi, "c")
    .replace(/10/g, "T")
    .toUpperCase();

  const cards = [];
  const compact = t.match(/[2-9TJQKA]\s*[SHDC]/g) || [];
  compact.forEach(raw => {
    const card = raw.replace(/\s+/g, "");
    cards.push(card[0] + card[1].toLowerCase());
  });

  return cards.filter(isCard).slice(0, 5);
}

function registerBoardCards(boardCards, source = "Board registrert.") {
  const normalizedBoard = (boardCards || []).map(convertBetSolidCard).filter(Boolean);
  const heroCards = parseCards($("hero")?.value || $("heroRegisterInput")?.value || $("ppHeroCards")?.value || lastLiveHeroText || "").filter(isCard).slice(0, 2);

  if (normalizedBoard.length > 5) {
    setBoardRegisterStatus("Board kan maks ha 5 kort.");
    return false;
  }
  if (!normalizedBoard.every(isCard)) {
    setBoardRegisterStatus("Ugyldig board-format. Bruk f.eks. Qs Jd 2c.");
    return false;
  }
  if (new Set(heroCards.concat(normalizedBoard)).size !== heroCards.length + normalizedBoard.length) {
    setBoardRegisterStatus("Samme kort finnes i hero/board.");
    return false;
  }

  manualLiveMode = true;
  manualPickerBoardCards = normalizedBoard.slice();
  if (heroCards.length === 2) manualPickerHeroCards = heroCards.slice();
  manualPickerTarget = manualPickerHeroCards.length < 2 ? "hero" : "board";

  const boardEl = $("board");
  if (boardEl) boardEl.value = cardsToText(normalizedBoard);
  const input = $("boardRegisterInput");
  if (input) input.value = cardsToText(normalizedBoard);
  lastManualBoardText = cardsToText(normalizedBoard);
  boardCorrectionCards = [];
  renderBoardCorrection();

  renderManualCardPicker();
  renderHeroHistoryMatches();
  scheduleAutoEquity({ manual: true });
  setBoardRegisterStatus(`${source} Historikkmatch hentes kun fra fil/database.`);
  return true;
}

async function readBoardFromClipboard() {
  try {
    setBoardRegisterStatus("Leser utklipp...");

    if (navigator.clipboard?.readText) {
      try {
        const text = await navigator.clipboard.readText();
        const cards = parseBoardCardsFromClipboardText(text);
        if (cards.length) {
          registerBoardCards(cards, "Board lest fra clipboard-tekst.");
          return;
        }
      } catch (_) {
        // Clipboard text can be blocked while image read still works.
      }
    }

    if (!navigator.clipboard?.read) {
      setBoardRegisterStatus("Nettleseren støtter ikke bildelesing fra clipboard her.");
      return;
    }

    const items = await navigator.clipboard.read();
    for (const item of items) {
      const imageType = item.types.find(type => type.startsWith("image/"));
      if (!imageType) continue;

      const blob = await item.getType(imageType);
      await readBoardImageBlob(blob, "Board lest fra clipboard-bilde.");
      return;
    }

    setBoardRegisterStatus("Ingen tekst eller bilde funnet i clipboard.");
  } catch (e) {
    console.warn("Clipboard board read failed", e);
    $("boardPasteZone")?.focus();
    setBoardRegisterStatus("Nettleseren blokkerte direkte lesing. Klikk paste-sonen og trykk Ctrl+V.");
  }
}

async function readBoardImageBlob(blob, sourceLabel = "Board lest fra bilde.") {
  boardCorrectionCards = [];
  renderBoardCorrection();
  const input = $("boardRegisterInput");
  if (input) input.value = "";

  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
  showBoardClipboardPreview(dataUrl);

  let cards = [];
  try {
    cards = await readCardsFromImageDataUrl(dataUrl);
  } catch (e) {
    setBoardRegisterStatus(e?.message || "Bildet ble limt inn, men automatisk bildelesing er ikke aktiv.");
    return false;
  }
  if (!cards.length) {
    setBoardRegisterStatus("Fant ingen boardkort i bildet.");
    return false;
  }
  if (input) input.value = cardsToText(cards);
  setBoardCorrectionCards(cards);
  setBoardRegisterStatus(`Forslag fra bilde: ${cardsToText(cards)}. Rett ved behov og trykk Registrer board.`);
  return true;
}

async function handleBoardPaste(ev) {
  try {
    const data = ev.clipboardData;
    if (!data) return;
    ev.preventDefault();
    setBoardRegisterStatus("Leser innlimt utklipp...");

    const text = data.getData("text/plain") || "";
    const textCards = parseBoardCardsFromClipboardText(text);
    if (textCards.length) {
      registerBoardCards(textCards, "Board lest fra innlimt tekst.");
      return;
    }

    const imageItem = Array.from(data.items || []).find(item => item.type && item.type.startsWith("image/"));
    if (!imageItem) {
      setBoardRegisterStatus("Fant ingen korttekst eller bilde i innlimingen.");
      return;
    }

    const blob = imageItem.getAsFile();
    if (!blob) {
      setBoardRegisterStatus("Klarte ikke hente bilde fra innliming.");
      return;
    }
    await readBoardImageBlob(blob, "Board lest fra innlimt bilde.");
  } catch (e) {
    console.warn("Board paste failed", e);
    setBoardRegisterStatus("Klarte ikke lese innlimt utklipp.");
  }
}

async function useLiveBoardForMainEquity() {
  try {
    setBoardRegisterStatus("Henter live board...");
    const res = await fetch(`${apiBase()}/live-cards?ts=${Date.now()}`);
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    const boardCards = parseCards(data.board || "");
    registerBoardCards(boardCards, "Live board registrert.");
  } catch (e) {
    console.warn("Could not fetch live board", e);
    setBoardRegisterStatus("Klarte ikke hente live board.");
  }
}

async function copyMainBoardToClipboard() {
  const boardText = normalizeSpaces($("board")?.value || $("boardRegisterInput")?.value || "");
  if (!boardText) {
    setBoardRegisterStatus("Ingen board å kopiere.");
    return;
  }
  try {
    await navigator.clipboard.writeText(boardText);
    setBoardRegisterStatus(`Kopiert: ${boardText}`);
  } catch (e) {
    console.warn("Clipboard failed", e);
    setBoardRegisterStatus(`Board: ${boardText}`);
  }
}

function sendBoardToProfileEquity() {
  const boardCards = parseCards($("boardRegisterInput")?.value || $("board")?.value || "").filter(isCard).slice(0, 5);
  if (!boardCards.length) {
    setBoardRegisterStatus("Trenger board-kort før sending.");
    return false;
  }
  if (!$("ppBoardCards")) {
    setBoardRegisterStatus("Åpne/last Live equity mot først.");
    return false;
  }

  if ($("ppEquityAuto")) $("ppEquityAuto").checked = false;
  $("ppBoardCards").value = cardsToText(boardCards);
  if ($("ppHeroCards") && $("hero")?.value && !normalizeSpaces($("ppHeroCards").value)) {
    $("ppHeroCards").value = normalizeSpaces($("hero").value);
  }
  const heroCards = parseCards($("hero")?.value || $("heroRegisterInput")?.value || $("ppHeroCards")?.value || "").filter(isCard).slice(0, 2);
  if (heroCards.length === 2 && new Set(heroCards.concat(boardCards)).size === heroCards.length + boardCards.length) {
    addCardHistoryEntry(heroCards, boardCards, "board-register");
  }
  syncProfileEquityPickerFromInputs({ manual: true });
  lastPlayerProfileEquityKey = "";
  setBoardRegisterStatus("Board sendt til Live equity mot.");
  setProfileEquityStatus("Board-kort kopiert fra Equity Calculator.");
  calculateProfileEquity().catch(console.warn);
  $("ppBoardCards")?.scrollIntoView({ behavior: "smooth", block: "center" });
  return true;
}

function sendManualPickerToProfileEquity() {
  const { hero, board } = selectedManualCards();
  const status = $("manualCardPickerStatus");

  if (hero.length !== 2 || !hero.every(isCard)) {
    if (status) status.innerText = "Trenger 2 hero-kort før sending.";
    return false;
  }
  if (board.length > 5 || !board.every(isCard)) {
    if (status) status.innerText = "Ugyldige board-kort.";
    return false;
  }
  if (new Set(hero.concat(board)).size !== hero.length + board.length) {
    if (status) status.innerText = "Samme kort finnes i hero/board.";
    return false;
  }
  if (!$("ppHeroCards") || !$("ppBoardCards")) {
    if (status) status.innerText = "Åpne/last Live equity mot først.";
    return false;
  }

  if ($("ppEquityAuto")) $("ppEquityAuto").checked = false;
  $("ppHeroCards").value = cardsToText(hero);
  $("ppBoardCards").value = cardsToText(board);
  if (board.length) {
    addCardHistoryEntry(hero, board, "board-register");
  }
  syncProfileEquityPickerFromInputs({ manual: true });
  lastPlayerProfileEquityKey = "";
  if (status) status.innerText = "Sendt til Live equity mot.";
  setProfileEquityStatus("Kort kopiert fra øverste kortvelger.");
  calculateProfileEquity().catch(console.warn);
  $("ppHeroCards")?.scrollIntoView({ behavior: "smooth", block: "center" });
  return true;
}

function renderManualCardPicker() {
  const box = $("manualCardPicker");
  if (!box) return;

  const { hero, board } = selectedManualCards();
  const slot = (card, label) => `
    <span style="display:inline-flex; align-items:center; justify-content:center; min-width:34px; height:28px; padding:0 8px; border:1px solid #ddd; border-radius:6px; background:${card ? "#fff" : "#f7f7f7"}; font-weight:${card ? "700" : "400"}; color:${card ? "#111" : "#999"};">
      ${card || label}
    </span>
  `;
  const rankButtons = MANUAL_CARD_RANKS.map(rank => `
    <button type="button" data-rank="${rank}" class="manualRankBtn" style="min-width:28px; height:28px; border:1px solid ${manualPickerRank === rank ? "#111" : "#ddd"}; background:${manualPickerRank === rank ? "#111" : "#fff"}; color:${manualPickerRank === rank ? "#fff" : "#111"}; border-radius:5px; cursor:pointer; font-weight:700;">${rank}</button>
  `).join("");
  const suitButtons = MANUAL_CARD_SUITS.map(suit => `
    <button type="button" data-suit="${suit.value}" class="manualSuitBtn" style="min-width:36px; height:30px; border:1px solid #ddd; background:#fff; color:${suit.color}; border-radius:5px; cursor:pointer; font-size:18px; line-height:1;">${suit.label}</button>
  `).join("");

  box.innerHTML = `
    <div style="border:1px solid #ededed; border-radius:22px; padding:14px 20px; background:#fafafa; box-shadow:0 1px 0 rgba(0,0,0,.03);">
      <div style="display:flex; align-items:flex-start; justify-content:space-between; gap:12px;">
        <div style="min-width:0;">
          <div style="display:flex; gap:10px; flex-wrap:wrap; margin-bottom:8px;">${rankButtons}</div>
          <div style="display:flex; gap:10px; flex-wrap:wrap;">${suitButtons}</div>
        </div>
        <div style="display:flex; align-items:center; gap:6px; flex-shrink:0;">
          <button type="button" id="manualTargetHero" title="Velg hero-kort" style="width:28px; height:28px; border:1px solid ${manualPickerTarget === "hero" ? "#2196F3" : "#ddd"}; background:${manualPickerTarget === "hero" ? "#e3f2fd" : "#fff"}; border-radius:6px; cursor:pointer; font-weight:700;">H</button>
          <button type="button" id="manualTargetBoard" title="Velg board-kort" style="width:28px; height:28px; border:1px solid ${manualPickerTarget === "board" ? "#2196F3" : "#ddd"}; background:${manualPickerTarget === "board" ? "#e3f2fd" : "#fff"}; border-radius:6px; cursor:pointer; font-weight:700;">B</button>
          <button type="button" id="manualUndoCard" title="Angre siste kort" style="width:28px; height:28px; border:1px solid #ddd; background:#fff; border-radius:6px; cursor:pointer; font-size:16px; line-height:1;">&larr;</button>
          <button type="button" id="manualClearCards" title="Tom alle kort" style="width:28px; height:28px; border:1px solid #ddd; background:#fff; border-radius:6px; cursor:pointer; font-size:16px; line-height:1;">C</button>
          <button type="button" id="manualSendHeroRegister" title="Send hero-kortene til Hero-register" style="height:28px; border:1px solid #ddd; background:#fff; border-radius:6px; cursor:pointer; font-size:12px; white-space:nowrap;">Send til hero</button>
          <button type="button" id="manualSendLiveMot" title="Send disse kortene til Live equity mot" style="height:28px; border:1px solid #ddd; background:#fff; border-radius:6px; cursor:pointer; font-size:12px; white-space:nowrap;">Send til live mot</button>
        </div>
      </div>
      <div style="display:grid; gap:6px; font-size:12px; margin-top:12px;">
        <div><span style="display:inline-block; width:44px; opacity:.7;">Hero</span>${slot(hero[0], "1")} ${slot(hero[1], "2")}</div>
        <div><span style="display:inline-block; width:44px; opacity:.7;">Board</span>${[0,1,2,3,4].map(i => slot(board[i], String(i + 1))).join(" ")}</div>
      </div>
      <div id="manualCardPickerStatus" style="font-size:11px; opacity:.65; margin-top:8px;">Velg rank, klikk suit.</div>
    </div>
  `;

  box.querySelectorAll(".manualRankBtn").forEach(btn => {
    btn.addEventListener("click", () => {
      activateManualCardMode();
      manualPickerRank = btn.dataset.rank || "A";
      renderManualCardPicker();
    });
  });
  box.querySelectorAll(".manualSuitBtn").forEach(btn => {
    btn.addEventListener("click", () => {
      activateManualCardMode();
      chooseManualCard(btn.dataset.suit || "s");
    });
  });
  $("manualTargetHero")?.addEventListener("click", () => {
    activateManualCardMode();
    manualPickerTarget = "hero";
    renderManualCardPicker();
  });
  $("manualTargetBoard")?.addEventListener("click", () => {
    activateManualCardMode();
    manualPickerTarget = "board";
    renderManualCardPicker();
  });
  $("manualUndoCard")?.addEventListener("click", undoManualCard);
  $("manualClearCards")?.addEventListener("click", clearManualCards);
  $("manualSendHeroRegister")?.addEventListener("click", sendManualPickerToHeroRegister);
  $("manualSendLiveMot")?.addEventListener("click", sendManualPickerToProfileEquity);
}

function renderCardPickerBox(box, state) {
  if (!box) return;
  const hero = state.heroCards || [];
  const board = state.boardCards || [];
  const slot = (card, label) => `
    <span style="display:inline-flex; align-items:center; justify-content:center; min-width:34px; height:28px; padding:0 8px; border:1px solid #ddd; border-radius:6px; background:${card ? "#fff" : "#f7f7f7"}; font-weight:${card ? "700" : "400"}; color:${card ? "#111" : "#999"};">
      ${card || label}
    </span>
  `;
  const rankButtons = MANUAL_CARD_RANKS.map(rank => `
    <button type="button" data-rank="${rank}" class="cardPickerRankBtn" style="min-width:28px; height:28px; border:1px solid ${state.rank === rank ? "#111" : "#ddd"}; background:${state.rank === rank ? "#111" : "#fff"}; color:${state.rank === rank ? "#fff" : "#111"}; border-radius:5px; cursor:pointer; font-weight:700;">${rank}</button>
  `).join("");
  const suitButtons = MANUAL_CARD_SUITS.map(suit => `
    <button type="button" data-suit="${suit.value}" class="cardPickerSuitBtn" style="min-width:36px; height:30px; border:1px solid #ddd; background:#fff; color:${suit.color}; border-radius:5px; cursor:pointer; font-size:18px; line-height:1;">${suit.label}</button>
  `).join("");

  box.innerHTML = `
    <div style="border:1px solid #ededed; border-radius:8px; padding:12px; background:#fafafa;">
      <div style="display:flex; align-items:flex-start; justify-content:space-between; gap:12px;">
        <div style="min-width:0;">
          <div style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:8px;">${rankButtons}</div>
          <div style="display:flex; gap:8px; flex-wrap:wrap;">${suitButtons}</div>
        </div>
        <div style="display:flex; align-items:center; gap:6px; flex-shrink:0;">
          <button type="button" class="cardPickerTargetHero" title="Velg hero-kort" style="width:30px; height:28px; border:1px solid ${state.target === "hero" ? "#2196F3" : "#ddd"}; background:${state.target === "hero" ? "#e3f2fd" : "#fff"}; border-radius:6px; cursor:pointer; font-weight:700;">H</button>
          <button type="button" class="cardPickerTargetBoard" title="Velg board-kort" style="width:30px; height:28px; border:1px solid ${state.target === "board" ? "#2196F3" : "#ddd"}; background:${state.target === "board" ? "#e3f2fd" : "#fff"}; border-radius:6px; cursor:pointer; font-weight:700;">B</button>
          <button type="button" class="cardPickerUndo" title="Angre siste kort" style="width:30px; height:28px; border:1px solid #ddd; background:#fff; border-radius:6px; cursor:pointer; font-size:16px; line-height:1;">&larr;</button>
          <button type="button" class="cardPickerClear" title="Tom alle kort" style="width:30px; height:28px; border:1px solid #ddd; background:#fff; border-radius:6px; cursor:pointer; font-size:13px; line-height:1;">C</button>
        </div>
      </div>
      <div style="display:grid; gap:6px; font-size:12px; margin-top:12px;">
        <div><span style="display:inline-block; width:44px; opacity:.7;">Hero</span>${slot(hero[0], "1")} ${slot(hero[1], "2")}</div>
        <div><span style="display:inline-block; width:44px; opacity:.7;">Board</span>${[0,1,2,3,4].map(i => slot(board[i], String(i + 1))).join(" ")}</div>
      </div>
      <div class="cardPickerStatus" style="font-size:11px; opacity:.65; margin-top:8px;">Velg rank, klikk suit.</div>
    </div>
  `;

  const setStatus = (text) => {
    const el = box.querySelector(".cardPickerStatus");
    if (el) el.innerText = text || "";
  };
  const sync = () => {
    state.onChange(state.heroCards.slice(), state.boardCards.slice());
    state.render();
  };

  box.querySelectorAll(".cardPickerRankBtn").forEach(btn => {
    btn.addEventListener("click", () => {
      state.rank = btn.dataset.rank || "A";
      state.render();
    });
  });
  box.querySelectorAll(".cardPickerSuitBtn").forEach(btn => {
    btn.addEventListener("click", () => {
      const picked = `${state.rank}${btn.dataset.suit || "s"}`;
      const all = state.heroCards.concat(state.boardCards);
      if (all.includes(picked)) {
        setStatus(`${picked} er allerede valgt.`);
        return;
      }
      if (state.target === "hero" && state.heroCards.length < 2) {
        state.heroCards.push(picked);
        if (state.heroCards.length >= 2) state.target = "board";
      } else if (state.boardCards.length < 5) {
        state.target = "board";
        state.boardCards.push(picked);
      } else {
        setStatus("Hero og board er fullt. Bruk Angre eller C.");
        return;
      }
      sync();
    });
  });
  box.querySelector(".cardPickerTargetHero")?.addEventListener("click", () => {
    state.target = "hero";
    state.render();
  });
  box.querySelector(".cardPickerTargetBoard")?.addEventListener("click", () => {
    state.target = "board";
    state.render();
  });
  box.querySelector(".cardPickerUndo")?.addEventListener("click", () => {
    if (state.target === "hero" && state.heroCards.length) state.heroCards.pop();
    else if (state.boardCards.length) state.boardCards.pop();
    else if (state.heroCards.length) state.heroCards.pop();
    if (state.heroCards.length < 2) state.target = "hero";
    sync();
  });
  box.querySelector(".cardPickerClear")?.addEventListener("click", () => {
    state.target = "hero";
    state.heroCards = [];
    state.boardCards = [];
    sync();
  });
}

function wireEquityCalculator() {
  const btn = $("calcBtn");
  if (!btn) return;

  btn.addEventListener("click", () => {
    runEquityCalculation({ auto: false, manual: true, live: true, saveHistory: false });
  });

  $("handProbBtn")?.addEventListener("click", () => {
    runHandProbabilities().catch(console.error);
  });

  $("heroRegisterBtn")?.addEventListener("click", () => {
    registerHeroCards(parseCards($("heroRegisterInput")?.value || ""), "Hero registrert.");
  });
  $("heroClipboardBtn")?.addEventListener("click", () => {
    readHeroFromClipboard().catch(console.warn);
  });
  $("heroPasteZone")?.addEventListener("paste", (ev) => {
    handleHeroPaste(ev).catch(console.warn);
  });
  $("heroPasteZone")?.addEventListener("click", () => {
    setHeroRegisterStatus("Trykk Ctrl+V her for tekst eller bilde fra Utklippsverktøy.");
  });
  $("heroUseLiveBtn")?.addEventListener("click", () => {
    useLiveHeroForMainEquity().catch(console.warn);
  });
  $("heroSendLiveMotBtn")?.addEventListener("click", () => {
    sendHeroToProfileEquity();
  });
  $("heroRegisterInput")?.addEventListener("keydown", (ev) => {
    if (ev.key !== "Enter") return;
    ev.preventDefault();
    registerHeroCards(parseCards($("heroRegisterInput")?.value || ""), "Hero registrert.");
  });

  $("boardRegisterBtn")?.addEventListener("click", () => {
    registerBoardCards(parseCards($("boardRegisterInput")?.value || ""), "Board registrert.");
  });
  $("boardClipboardBtn")?.addEventListener("click", () => {
    readBoardFromClipboard().catch(console.warn);
  });
  $("boardPasteZone")?.addEventListener("paste", (ev) => {
    handleBoardPaste(ev).catch(console.warn);
  });
  $("boardPasteZone")?.addEventListener("click", () => {
    setBoardRegisterStatus("Trykk Ctrl+V her for tekst eller bilde fra Utklippsverktøy.");
  });
  $("boardUseLiveBtn")?.addEventListener("click", () => {
    useLiveBoardForMainEquity().catch(console.warn);
  });
  $("boardSendLiveMotBtn")?.addEventListener("click", () => {
    sendBoardToProfileEquity();
  });
  $("boardCopyBtn")?.addEventListener("click", () => {
    copyMainBoardToClipboard().catch(console.warn);
  });
  $("boardRegisterInput")?.addEventListener("keydown", (ev) => {
    if (ev.key !== "Enter") return;
    ev.preventDefault();
    registerBoardCards(parseCards($("boardRegisterInput")?.value || ""), "Board registrert.");
  });

  // Live auto updates when hero/board/numVillains/villains change
  ["hero", "board", "numVillains", "villains"].forEach(id => {
    const el = $(id);
    if (el) {
      const onEquityInput = () => {
        if (id === "hero" || id === "board") renderHeroHistoryMatches();
        scheduleAutoEquity();
      };
      el.addEventListener("input", onEquityInput);
      el.addEventListener("change", onEquityInput);
    }
  });
  const autoBox = $("autoEquity");
  if (autoBox) autoBox.addEventListener("change", scheduleAutoEquity);
  renderManualCardPicker();
  
  // Import handler
  const importBtn = $("btnImport");
  const importFile = $("importFile");
  if (importBtn && importFile) {
    importBtn.addEventListener("click", async () => {
      const file = importFile.files[0];
      if (!file) {
        $("importStatus").innerText = "âŒ Please select a file";
        return;
      }
      
      $("importStatus").innerText = "ðŸ“¤ Uploading...";
      try {
        const xml = await file.text();
        const res = await fetch(`${apiBase()}/import/betsolid`, {
          method: "POST",
          headers: { "Content-Type": "text/plain" },
          body: xml
        });
        
        if (res.ok) {
          const result = await res.json();
          $("importStatus").innerText = `âœ… Imported! ${result.imported_hands} hand(s)`;
          importFile.value = "";
          await refreshBackendCardHistory({ force: true, render: true });
          // Auto-refresh polling to show new hand
          if (typeof pollCurrentGame === 'function') {
            setTimeout(pollCurrentGame, 500);
          }
        } else {
          $("importStatus").innerText = `âŒ Error: ${res.status}`;
        }
      } catch (err) {
        $("importStatus").innerText = `âŒ ${err.message}`;
      }
    });
  }
}

// PRESET RANGES
const PRESET_RANGES = {
  btn_open: "AA,KK,QQ,JJ,TT,99,88,77,66,55,44,33,22, AKs,AQs,AJs,ATs, AKo,AQo, KQs, KJs",
  sb_open: "AA,KK,QQ,JJ,TT,99,88,77,66,55,44,33,22, AKs,AQs,AJs,ATs,A9s,A8s,A7s,A5s,A4s,A3s, KQs,KJs,KTs, QJs,QTs, JTs,J9s, T9s,T8s, 98s, AKo,AQo,AJo, KQo, KJo",
  bb_defense: "AA,KK,QQ,JJ,TT,99,88,77,66,55,44,33,22, AKs,AQs,AJs,ATs,A9s,A8s,A7s,A6s,A5s,A4s,A3s,A2s, KQs,KJs,KTs,K9s, QJs,QTs,Q9s, JTs,J9s,J8s, T9s,T8s,T7s, 98s,97s, 87s,86s, 76s, AKo,AQo,AJo,ATo, KQo,KJo, QJo",
  four_bet_value: "AA,KK,QQ, AKs, AKo",
  four_bet_bluff: "AJs,ATs,A9s, KQs, QJs",
  flush_draw: "As2s,As3s,As4s,As5s,As6s,As7s,As8s,As9s,AsTs,AsJs,AsQs,AsKs, 2s3s,2s4s,2s5s,2s6s,2s7s,2s8s,2s9s,2sTs,2sJs,2sQs,2sKs, 3s4s,3s5s,3s6s,3s7s,3s8s,3s9s,3sTs,3sJs,3sQs,3sKs"
};

function wirePresetRangeBuilder() {
  const display = $("presetDisplay");
  if (!display) return;

  const btns = document.querySelectorAll(".presetBtn");
  btns.forEach(btn => {
    btn.addEventListener("click", () => {
      const preset = btn.getAttribute("data-preset");
      const range = PRESET_RANGES[preset] || "";
      display.innerText = range || "Preset ikke funnet";
    });
  });
}

// MULTI-HAND COMPARISON
async function compareHands() {
  const status = $("compareStatus");
  const out = $("compareOut");
  if (!status || !out) return;

  const hand1Text = normalizeSpaces($("mhHand1")?.value || "AK");
  const hand2Text = normalizeSpaces($("mhHand2")?.value || "TT");
  const hand3Text = normalizeSpaces($("mhHand3")?.value || "");
  const boardText = normalizeSpaces($("mhBoard")?.value || "");

  const hands = [hand1Text, hand2Text];
  if (hand3Text) hands.push(hand3Text);

  // Parse all hands
  const parsedHands = hands.map(h => {
    const cards = parseCards(h);
    if (cards.length === 2) return cards;
    // Try to match common hand notations like "AK", "TT", etc.
    h = h.toUpperCase().replace(/\s/g, "");
    if (h.length === 2) {
      const rank1 = h[0], rank2 = h[1];
      if (rank1 === rank2) {
        return [rank1 + "h", rank1 + "d"]; // Pair
      } else {
        return [rank1 + "s", rank2 + "s"]; // Suited
      }
    }
    return null;
  }).filter(h => h !== null);

  if (parsedHands.length < 2) {
    status.innerText = "âŒ MÃ¥ ha minst 2 hender";
    out.innerHTML = "";
    return;
  }

  const boardCards = parseCards(boardText);
  status.innerText = "â³ Sammenligner...";

  try {
    // Fetch equity for each hand vs 1 villain (randomized)
    const results = [];
    
    for (let i = 0; i < parsedHands.length; i++) {
      const res = await fetch(`${apiBase()}/equity`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          hero: parsedHands[i],
          board: boardCards,
          villains: parsedHands.length - 1,
          iters: 20000
        })
      });
      
      if (!res.ok) throw new Error("HTTP " + res.status);
      const data = await res.json();
      const win = Math.round(data.win * 1000) / 10;
      
      results.push({
        hand: hands[i],
        win: win,
        parsed: parsedHands[i].join(" ")
      });
    }

    // Sort by win%
    results.sort((a, b) => b.win - a.win);

    // Render table
    let html = `<table style="width:100%; border-collapse:collapse;">
      <thead>
        <tr style="background:#f5f5f5;">
          <th style="border:1px solid #ddd; padding:8px; text-align:left;">HÃ¥nd</th>
          <th style="border:1px solid #ddd; padding:8px; text-align:right;">Win %</th>
        </tr>
      </thead>
      <tbody>`;

    results.forEach((r, i) => {
      const bgColor = i === 0 ? "#e8f5e9" : i === results.length - 1 ? "#ffebee" : "#fff";
      html += `<tr style="background:${bgColor};">
        <td style="border:1px solid #ddd; padding:8px; font-weight:600;">${escapeHtml(r.hand)}</td>
        <td style="border:1px solid #ddd; padding:8px; text-align:right; font-weight:600; color:${r.win > 50 ? "#4CAF50" : r.win < 40 ? "#f44336" : "#FF9800"};">${r.win}%</td>
      </tr>`;
    });

    html += `</tbody></table>`;
    
    if (boardCards.length > 0) {
      html += `<div style="margin-top:8px; font-size:12px; opacity:.7;">Board: ${boardCards.join(" ")}</div>`;
    } else {
      html += `<div style="margin-top:8px; font-size:12px; opacity:.7;">Preflop</div>`;
    }

    out.innerHTML = html;
    status.innerText = `âœ… Sammenlignet ${results.length} hender`;
  } catch (e) {
    console.error(e);
    status.innerText = "âŒ Feil: klarte ikke Ã¥ kontakte backend.";
    out.innerHTML = "";
  }
}

function wireMultiHandComparison() {
  const btn = $("btnCompare");
  if (!btn) return;
  btn.addEventListener("click", compareHands);
}

function syncHvEquityInputs(heroCards = hvHeroCards, boardCards = hvBoardCards) {
  hvHeroCards = (heroCards || []).slice();
  hvBoardCards = (boardCards || []).slice();
  const heroEl = $("hvHeroCards");
  const boardEl = $("hvBoardCards");
  if (heroEl) heroEl.value = cardsToText(hvHeroCards);
  if (boardEl) boardEl.value = cardsToText(hvBoardCards);
}

function setHvManualMode(on, message = "") {
  hvEquityManualMode = Boolean(on);
  const status = $("hvEquityStatus");
  if (status && message) status.innerText = message;
}

function renderHvCardPicker() {
  const state = {
    rank: hvPickerRank,
    target: hvPickerTarget,
    heroCards: hvHeroCards.slice(),
    boardCards: hvBoardCards.slice(),
    onChange: (heroCards, boardCards) => {
      setHvManualMode(true, "Manuell: auto-fyll pauset.");
      syncHvEquityInputs(heroCards, boardCards);
    },
    render: () => {
      hvPickerRank = state.rank;
      hvPickerTarget = state.target;
      hvHeroCards = state.heroCards.slice();
      hvBoardCards = state.boardCards.slice();
      renderHvCardPicker();
    }
  };
  renderCardPickerBox($("hvCardPicker"), state);
}

function refreshHvPickerFromInputs() {
  setHvManualMode(true, "Manuell: auto-fyll pauset.");
  const heroCards = parseCards($("hvHeroCards")?.value || "");
  const boardCards = parseCards($("hvBoardCards")?.value || "");
  hvHeroCards = heroCards.filter(isCard).slice(0, 2);
  hvBoardCards = boardCards.filter(isCard).slice(0, 5);
  hvPickerTarget = hvHeroCards.length < 2 ? "hero" : "board";
  renderHvCardPicker();
}

async function calculateHvEquity() {
  const status = $("hvEquityStatus");
  const out = $("hvEquityResult");
  const heroCards = parseCards($("hvHeroCards")?.value || "");
  const boardCards = parseCards($("hvBoardCards")?.value || "");
  const villains = Math.max(1, Math.min(Number($("hvVillains")?.value || 1), 8));
  const ranges = normalizeSpaces($("hvRanges")?.value || "");

  if (!out) return;
  if (heroCards.length !== 2 || !heroCards.every(isCard)) {
    out.innerHTML = `<div style="color:#b91c1c;">Velg 2 gyldige hero-kort.</div>`;
    return;
  }
  if (boardCards.length > 5 || !boardCards.every(isCard)) {
    out.innerHTML = `<div style="color:#b91c1c;">Board kan ha maks 5 gyldige kort.</div>`;
    return;
  }
  if (new Set(heroCards.concat(boardCards)).size !== heroCards.length + boardCards.length) {
    out.innerHTML = `<div style="color:#b91c1c;">Samme kort finnes flere steder.</div>`;
    return;
  }

  if (status) status.innerText = "Beregner...";
  out.innerHTML = `<div style="opacity:.7;">Kjører equity...</div>`;

  try {
    const res = await fetch(`${apiBase()}/equity`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hero: heroCards, board: boardCards, villains, ranges, iters: 20000 })
    });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    const win = Math.round(data.win * 1000) / 10;
    const tie = Math.round(data.tie * 1000) / 10;
    const lose = Math.round(data.lose * 1000) / 10;
    out.innerHTML = `
      <div style="font-size:16px; font-weight:700;">
        Win <span style="color:#15803d;">${win}%</span> |
        Split <span style="color:#b45309;">${tie}%</span> |
        Lose <span style="color:#b91c1c;">${lose}%</span>
      </div>
      <div style="font-size:12px; opacity:.75; margin-top:5px;">
        ${escapeHtml(heroCards.join(" "))} vs ${villains}, board: ${escapeHtml(boardCards.join(" ") || "preflop")}, ${data.iters.toLocaleString()} sim.
      </div>
    `;
    if (status) status.innerText = "OK";
  } catch (e) {
    console.error(e);
    if (status) status.innerText = "Feil";
    out.innerHTML = `<div style="color:#b91c1c;">Klarte ikke beregne equity.</div>`;
  }
}

function copyHvToMainEquity() {
  const hero = $("hvHeroCards")?.value || "";
  const board = $("hvBoardCards")?.value || "";
  const villains = $("hvVillains")?.value || "1";
  const ranges = $("hvRanges")?.value || "";
  if ($("hero")) $("hero").value = hero;
  if ($("board")) $("board").value = board;
  if ($("numVillains")) $("numVillains").value = villains;
  if ($("villains")) $("villains").value = ranges;
  setManualCards(parseCards(hero).filter(isCard).slice(0, 2), parseCards(board).filter(isCard).slice(0, 5));
  runEquityCalculation({ auto: false, manual: true, live: true, saveHistory: false }).catch(console.warn);
}

function copyHvToProfileEquity() {
  const hero = normalizeSpaces($("hvHeroCards")?.value || "");
  const board = normalizeSpaces($("hvBoardCards")?.value || "");
  const ranges = normalizeSpaces($("hvRanges")?.value || "");
  const status = $("hvEquityStatus");

  if (!$("ppHeroCards") || !$("ppBoardCards")) {
    if (status) status.innerText = "Last Player Profile først.";
    return;
  }

  if ($("ppEquityAuto")) $("ppEquityAuto").checked = false;
  $("ppHeroCards").value = hero;
  $("ppBoardCards").value = board;
  if (ranges && $("ppVillainRange")) $("ppVillainRange").value = ranges;
  syncProfileEquityPickerFromInputs({ manual: true });

  lastPlayerProfileEquityKey = "";
  if (status) status.innerText = "Kopiert til live mot.";
  setProfileEquityStatus("Kort kopiert fra Hand Viewer.");
  calculateProfileEquity().catch(console.warn);
  $("ppHeroCards")?.scrollIntoView({ behavior: "smooth", block: "center" });
}

function wireHvEquity() {
  renderHvCardPicker();
  $("hvEquityCalc")?.addEventListener("click", () => calculateHvEquity().catch(console.warn));
  $("hvUseHandCards")?.addEventListener("click", () => {
    setHvManualMode(false, "Henter kort fra hand...");
    loadHand($("hvHandId")?.value, { silent: true, forceEquityFill: true, allowManualOverwrite: true, saveHistory: false }).catch(console.warn);
  });
  $("hvCopyToMainEquity")?.addEventListener("click", copyHvToMainEquity);
  $("hvCopyToProfileEquity")?.addEventListener("click", copyHvToProfileEquity);
  ["hvHeroCards", "hvBoardCards"].forEach(id => {
    $(id)?.addEventListener("input", refreshHvPickerFromInputs);
  });
}

// ------------------------------
// Hand Viewer
// ------------------------------
function streetName(st) {
  return st === 0 ? "blinds" :
         st === 1 ? "preflop" :
         st === 2 ? "flop" :
         st === 3 ? "turn" :
         st === 4 ? "river" : String(st);
}

let hvLoadInFlight = false;
let hvPollTimer = null;
let hvPlayersLiveTimer = null;
let hvCurrentPlayers = [];

function renderHandViewerPlayers(players) {
  const box = $("hvPlayersBox");
  if (!box) return;

  const hero = dashHero();
  const names = [];
  const seen = new Set();
  (players || []).forEach(raw => {
    const name = String(raw?.name || raw?.player_name || raw || "").trim();
    const key = name.toLowerCase();
    if (!name || seen.has(key)) return;
    seen.add(key);
    names.push(name);
  });
  hvCurrentPlayers = names.slice();

  mergeKnownPlayerNames(names);

  if (!names.length) {
    box.innerHTML = `<div style="opacity:.65; font-size:12px;">Ingen spillere funnet for denne hånden ennå.</div>`;
    return;
  }

  box.innerHTML = `
    <div style="border:1px solid #ddd; background:#fff; padding:8px;">
      <div style="font-weight:700; margin-bottom:6px;">Spillere i hånden / bordet</div>
      <div style="display:flex; gap:6px; flex-wrap:wrap;">
        ${names.map((name, idx) => {
          const isHero = hero && name.toLowerCase() === hero.toLowerCase();
          return `<button type="button" class="hvPlayerBtn" data-player-idx="${idx}" style="padding:4px 8px; border:1px solid ${isHero ? "#15803d" : "#ccc"}; background:${isHero ? "#ecfdf5" : "#f8f8f8"}; cursor:pointer;">
            ${escapeHtml(name)}${isHero ? " (hero)" : ""}
          </button>`;
        }).join("")}
      </div>
    </div>
  `;

  box.querySelectorAll(".hvPlayerBtn").forEach(btn => {
    btn.addEventListener("click", () => {
      const idx = Number(btn.getAttribute("data-player-idx"));
      const name = names[idx] || "";
      if (!name) return;
      ["ppPlayer", "mtPlayer", "spPlayer"].forEach(id => {
        const el = $(id);
        if (el) el.value = name;
      });
      if (typeof loadPlayerProfile === "function") loadPlayerProfile().catch(console.warn);
      const status = $("hvEquityStatus");
      if (status) status.innerText = `Valgt spiller: ${name}`;
    });
  });
}

async function updateHandViewerPlayersFromLive(existingPlayers = []) {
  try {
    const res = await fetch(`${apiBase()}/live-cards?ts=${Date.now()}`);
    if (!res.ok) return false;
    const data = await res.json();
    const livePlayers = Array.isArray(data.players) ? data.players : [];
    if (!livePlayers.length) return false;

    renderHandViewerPlayers((existingPlayers || []).concat(livePlayers));
    const status = $("hvEquityStatus");
    if (status) status.innerText = "Bordspillere oppdatert fra live.";
    return true;
  } catch (e) {
    console.warn("Could not update hand viewer players from live", e);
    return false;
  }
}

function startHandViewerPlayersLivePoll() {
  if (hvPlayersLiveTimer) clearInterval(hvPlayersLiveTimer);
  updateHandViewerPlayersFromLive(hvCurrentPlayers).catch(console.warn);
  hvPlayersLiveTimer = setInterval(() => {
    updateHandViewerPlayersFromLive(hvCurrentPlayers).catch(console.warn);
  }, 3000);
}

function stopHandViewerPlayersLivePoll() {
  if (hvPlayersLiveTimer) clearInterval(hvPlayersLiveTimer);
  hvPlayersLiveTimer = null;
}

async function loadHand(handId, opts = { silent: false }) {
  const status = $("hvStatus");
  const autoStatus = $("hvAutoStatus");
  const meta = $("hvMeta");
  const wrap = $("hvTableWrap");
  if (!meta || !wrap) return;

  const hid = String(handId || "").trim();
  if (!hid || Number.isNaN(Number(hid))) {
    if (status) status.innerText = "Skriv inn en gyldig hand_id.";
    if (autoStatus && opts.silent) autoStatus.innerText = "Auto: trenger hand_id";
    return;
  }

  if (hvLoadInFlight) return;
  hvLoadInFlight = true;

  if (!opts.silent && status) status.innerText = "Lasterâ€¦";
  if (!opts.silent) {
    meta.innerText = "";
    wrap.innerHTML = "";
  }

  try {
    const res = await fetch(`${apiBase()}/actions?hand_id=${encodeURIComponent(hid)}`);
    if (!res.ok) {
      if (status) status.innerText = `Feil: ${res.status}`;
      return;
    }
    const rows = await res.json();
    if (status) status.innerText = `OK (${rows.length} actions)`;
    meta.innerText = `hand_id=${hid} â€” actions=${rows.length}`;
    const actionPlayers = rows.map(r => r.player_name).filter(Boolean);
    let hvPlayers = actionPlayers.slice();
    renderHandViewerPlayers(hvPlayers);
    if (hvPlayers.length <= 1) {
      updateHandViewerPlayersFromLive(hvPlayers).catch(console.warn);
    }

    if (!rows.length) {
      wrap.innerHTML = `<div style="opacity:.7;">Ingen actions funnet for denne hand_id.</div>`;
    } else {
      wrap.innerHTML = `
      <table style="width:100%; border-collapse:collapse;">
        <thead>
          <tr>
            <th style="text-align:left; border-bottom:1px solid #ccc; padding:6px;">street</th>
            <th style="text-align:left; border-bottom:1px solid #ccc; padding:6px;">seq</th>
            <th style="text-align:left; border-bottom:1px solid #ccc; padding:6px;">player</th>
            <th style="text-align:left; border-bottom:1px solid #ccc; padding:6px;">action</th>
            <th style="text-align:left; border-bottom:1px solid #ccc; padding:6px;">amount</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map(r => `
            <tr>
              <td style="border-bottom:1px solid #eee; padding:6px;">${streetName(r.street)} (${r.street})</td>
              <td style="border-bottom:1px solid #eee; padding:6px;">${r.seq}</td>
              <td style="border-bottom:1px solid #eee; padding:6px;">${escapeHtml(r.player_name)}</td>
              <td style="border-bottom:1px solid #eee; padding:6px;">${escapeHtml(r.action)}</td>
              <td style="border-bottom:1px solid #eee; padding:6px;">${(r.amount ?? 0)}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    `;
    }

    // try to fetch hole cards for this hand and auto-fill/save hero cards if available
    await (async () => {
      try {
        const cardsRes = await fetch(`${apiBase()}/hands/${encodeURIComponent(hid)}/cards`);
        if (!cardsRes.ok) return;
        const cardData = await cardsRes.json();
        const cardPlayers = (cardData.hole_cards || []).map(h => h.player_name).filter(Boolean);
        if (cardPlayers.length) {
          hvPlayers = actionPlayers.concat(cardPlayers);
          renderHandViewerPlayers(hvPlayers);
        }
        if (hvPlayers.length <= 1) {
          updateHandViewerPlayersFromLive(hvPlayers).catch(console.warn);
        }
        const heroName = ($("dashHero")?.value?.trim()) || ($("lhPlayer")?.value?.trim()) || null;
        if (!heroName) return;

        // find hero hole_cards entry
        const hole = (cardData.hole_cards || []).find(h => String(h.player_name).toLowerCase() === heroName.toLowerCase());
        if (!hole) return;
        if (!hole.card1 || !hole.card2) return;

        // fill the helper input if present
        const hvInput = $("hvSaveHero");
        if (hvInput) hvInput.value = `${hole.card1} ${hole.card2}`;

        const newHero = `${hole.card1} ${hole.card2}`;
        const newBoard = (cardData.board && cardData.board.length > 0) ? cardData.board.join(" ") : "";
        console.log(`Kort lest fra hand ${hid} til historikk: ${newHero}${newBoard ? " / " + newBoard : ""}`);

        const canForceFill = opts.forceEquityFill && (!hvEquityManualMode || opts.allowManualOverwrite);
        if (canForceFill || (!opts.skipEquityFill && !hvEquityManualMode)) {
          syncHvEquityInputs([hole.card1, hole.card2], cardData.board || []);
          hvPickerTarget = "board";
          renderHvCardPicker();
          hvEquityManualMode = false;
          if ($("hvEquityStatus")) $("hvEquityStatus").innerText = "Kort fra hand lastet.";
        }

        if (opts.saveHistory === true) {
          try {
            const statusEl = $("hvSaveStatus");
            if (statusEl) statusEl.innerText = "Filhistorikk";
            setTimeout(() => {
                if ($("hvSaveStatus")) $("hvSaveStatus").innerText = "";
            }, 1400);
          } catch (e) {
            console.warn("save failed", e);
          }
        }
      } catch (e) {
        // ignore
      }
    })();

    // small helper UI: allow saving hero hole cards to Card History for this hand
    try {
      const helper = document.createElement("div");
      helper.style.marginTop = "8px";
      helper.style.padding = "8px";
      helper.style.background = "#fff";
      helper.style.border = "1px solid #f0f0f0";
      helper.style.borderRadius = "6px";
      helper.innerHTML = `
        <label>Save Hero Cards:
          <input id="hvSaveHero" placeholder="Ah Kh" style="width:100px; margin-left:6px;">
        </label>
        <label style="margin-left:8px;">Hero name:
          <input id="hvSaveHeroName" placeholder="hero" style="width:120px; margin-left:6px;">
        </label>
        <button id="hvSaveBtn" style="margin-left:8px;">Save to Card History</button>
        <span id="hvSaveStatus" style="opacity:.7; margin-left:8px;"></span>
      `;
      wrap.prepend(helper);

      const heroDefault = $("dashHero")?.value?.trim() || $("lhPlayer")?.value?.trim() || "";
      const nameInput = $("hvSaveHeroName");
      if (nameInput) nameInput.value = heroDefault;

      const saveBtn = $("hvSaveBtn");
      if (saveBtn) {
        saveBtn.addEventListener("click", () => {
          const hv = $("hvSaveHero")?.value?.trim() || "";
          const heroCards = parseCards(hv);
          const status = $("hvSaveStatus");
          if (heroCards.length !== 2) {
            if (status) status.innerText = "Skriv inn 2 kort (f.eks. Ah Kh).";
            return;
          }
          try {
            addCardHistoryEntry(heroCards, [], "hand-viewer");
            if (status) status.innerText = "Saved";
            setTimeout(() => { if (status) status.innerText = ""; }, 1200);
          } catch (e) {
            console.warn(e);
            if (status) status.innerText = "Feil";
          }
        });
      }
    } catch (e) {
      console.warn("hv helper failed", e);
    }
  } catch (e) {
    console.error(e);
    if (status) status.innerText = "Feil (se console)";
  } finally {
    hvLoadInFlight = false;
    if (autoStatus && opts.silent) autoStatus.innerText = "Auto: oppdatert";
  }
}

function stopHandAutopoll() {
  if (hvPollTimer) clearInterval(hvPollTimer);
  hvPollTimer = null;
  stopHandViewerPlayersLivePoll();
  const autoStatus = $("hvAutoStatus");
  if (autoStatus) autoStatus.innerText = "Auto: stoppet";
}

function startHandAutopoll() {
  stopHandAutopoll();
  const box = $("hvAuto");
  const autoStatus = $("hvAutoStatus");
  if (!box || !box.checked) {
    if (autoStatus) autoStatus.innerText = "Auto: av";
    return;
  }
  const hid = $("hvHandId")?.value?.trim();
  if (!hid) {
    if (autoStatus) autoStatus.innerText = "Auto: trenger hand_id";
    return;
  }
  hvPollTimer = setInterval(() => loadHand(hid, { silent: true, skipEquityFill: liveScreenActive || manualLiveMode || hvEquityManualMode }).catch(console.error), 4000);
  startHandViewerPlayersLivePoll();
  if (autoStatus) autoStatus.innerText = "Auto: pÃ¥ (4s)";
}

function wireHandViewer() {
  $("hvLoad")?.addEventListener("click", () => {
    setHvManualMode(false);
    loadHand($("hvHandId")?.value, { forceEquityFill: true });
    startHandAutopoll();
  });
  $("hvHandId")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      setHvManualMode(false);
      loadHand($("hvHandId")?.value, { forceEquityFill: true });
      startHandAutopoll();
    }
  });
  $("hvHandId")?.addEventListener("input", () => setHvManualMode(false));
  $("hvAuto")?.addEventListener("change", startHandAutopoll);

  // If live coach auto-opens a hand, keep auto-refresh aligned

  window.openHandViewer = function(handId) {
    if ($("hvHandId")) $("hvHandId").value = String(handId);
    loadHand(handId);
    startHandAutopoll();
    $("hvHandId")?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  startHandViewerPlayersLivePoll();
}

// ------------------------------
// Player Profile (classic table)
// ------------------------------
async function loadPlayerProfile() {
  const status = $("ppStatus");
  const card = $("ppCard");
  const player = $("ppPlayer")?.value?.trim();
  const sessionVal = $("ppSession")?.value?.trim();

  if (!status || !card) return;
  if (!player) {
    status.innerText = "Skriv inn spiller.";
    return;
  }

  const preservedEquity = {
    manual: ppEquityManualMode,
    hero: parseCards($("ppHeroCards")?.value || cardsToText(ppHeroCards)).filter(isCard).slice(0, 2),
    board: parseCards($("ppBoardCards")?.value || cardsToText(ppBoardCards)).filter(isCard).slice(0, 5)
  };
  const keepManualEquityCards = preservedEquity.manual && (preservedEquity.hero.length || preservedEquity.board.length);

  status.innerText = "Lasterâ€¦";
  card.innerHTML = "";

  const params = new URLSearchParams();
  if (sessionVal) params.set("session_id", sessionVal);
  params.set("hero_name", dashHero() || "angryshark");
  params.set("rounds_limit", "150");

  const qs = params.toString();
  const url = `${apiBase()}/players/${encodeURIComponent(player)}/profile${qs ? "?" + qs : ""}`;

  try {
    const res = await fetch(url);
    if (!res.ok) {
      status.innerText = `Feil: ${res.status}`;
      card.innerHTML = `<div style="opacity:.7;">Kunne ikke hente profil.</div>`;
      return;
    }

    const p = await res.json();
    playerProfileData = p;
    status.innerText = "OK";

    const notesHtml = (p.notes || []).length
      ? `<ul style="margin:0 0 0 18px;">${p.notes.map(n => `<li>${escapeHtml(n)}</li>`).join("")}</ul>`
      : `<span style="opacity:.7;">Ingen notater</span>`;
    const suggestedRange = p.suggested_range || profileRangeFallback(p.player_type);

    const profileEquityHtml = `
      <div style="margin-top:14px; max-width:980px; border:1px solid #ddd; padding:10px; background:#fff;">
        <h3 style="margin:0 0 8px 0;">Live equity mot ${escapeHtml(p.player_name)}</h3>
        <div id="ppCardPicker" style="margin-bottom:10px;"></div>
        <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
          <label>Mine kort:
            <input id="ppHeroCards" type="text" placeholder="As Kh" style="width:105px;">
          </label>
          <label>Board:
            <input id="ppBoardCards" type="text" placeholder="Qs Jd 2c" style="width:155px;">
          </label>
          <label>Sim:
            <input id="ppEquityIters" type="number" value="12000" min="500" max="60000" step="500" style="width:80px;">
          </label>
          <label style="display:flex; align-items:center; gap:5px;">
            <input id="ppEquityAuto" type="checkbox" checked>
            Auto live
          </label>
          <button id="ppUseLiveCards">Hent live</button>
          <button id="ppCalcEquity">Beregn</button>
          <button id="ppClearEquityCards" title="Slett kort">C</button>
          <button id="ppCopyToMainEquity">Kopier til Equity</button>
          <span id="ppEquityStatus" style="opacity:.7;"></span>
        </div>
        <div style="margin-top:8px;">
          <label>Range motspiller:
            <input id="ppVillainRange" type="text" value="${escapeHtml(suggestedRange)}" style="width:min(760px, 100%);">
          </label>
        </div>
        <div id="ppEquityOut" style="margin-top:10px;">
          <div style="opacity:.7;">Henter live kort...</div>
        </div>
        <div style="margin-top:10px; border:1px solid #ddd; background:#fafafa; padding:10px;">
          <div style="font-weight:800; margin-bottom:7px;">Beslutning</div>
          <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:8px;">
            <label>Pot:
              <input id="ppPotChips" type="number" min="0" step="1" placeholder="chips" style="width:90px;">
            </label>
            <label>Call/bet:
              <input id="ppCallChips" type="number" min="0" step="1" placeholder="chips" style="width:90px;">
            </label>
            <label>Stack:
              <input id="ppStackChips" type="number" min="0" step="1" placeholder="chips" style="width:90px;">
            </label>
            <button id="ppDecisionRefresh" type="button">Oppdater</button>
          </div>
          <div id="ppDecisionOut" style="max-width:560px;">
            <div style="opacity:.65;">Beregn equity først. Fyll pot/call/stack for pot-odds.</div>
          </div>
        </div>
      </div>
    `;

    const matchup = p.matchup || {};
    const matchupHtml = matchup.hands !== undefined ? `
      <div style="margin-top:14px; max-width:980px;">
        <h3 style="margin:0 0 8px 0;">Meg vs ${escapeHtml(p.player_name)}</h3>
        <table style="border-collapse:collapse; width:100%;">
          <tbody>
            <tr>
              <td style="border:1px solid #ddd; padding:8px; font-weight:700;">Runder sammen</td>
              <td style="border:1px solid #ddd; padding:8px;">${matchup.hands ?? 0}</td>
              <td style="border:1px solid #ddd; padding:8px; font-weight:700;">Vinn/tap</td>
              <td style="border:1px solid #ddd; padding:8px;">${matchup.hero_wins ?? 0} - ${matchup.villain_wins ?? 0}${matchup.ties ? ` (${matchup.ties} split)` : ""}</td>
            </tr>
            <tr>
              <td style="border:1px solid #ddd; padding:8px; font-weight:700;">${escapeHtml(matchup.hero_name || "Hero")} net</td>
              <td style="border:1px solid #ddd; padding:8px;">${num(matchup.hero_net_total, 2)} (${num(matchup.hero_bb_per_100, 1)} bb/100)</td>
              <td style="border:1px solid #ddd; padding:8px; font-weight:700;">${escapeHtml(p.player_name)} net</td>
              <td style="border:1px solid #ddd; padding:8px;">${num(matchup.villain_net_total, 2)} (${num(matchup.villain_bb_per_100, 1)} bb/100)</td>
            </tr>
          </tbody>
        </table>
      </div>
    ` : "";

    const rounds = p.rounds || [];
    const roundsHtml = rounds.length ? `
      <div style="margin-top:14px; max-width:1100px; overflow-x:auto;">
        <h3 style="margin:0 0 8px 0;">Alle runder mot spilleren</h3>
        <table style="border-collapse:collapse; width:100%; min-width:960px; font-size:13px;">
          <thead>
            <tr>
              <th style="border:1px solid #ddd; padding:6px; text-align:left;">Hand</th>
              <th style="border:1px solid #ddd; padding:6px; text-align:left;">Tid</th>
              <th style="border:1px solid #ddd; padding:6px; text-align:left;">Mine kort</th>
              <th style="border:1px solid #ddd; padding:6px; text-align:left;">Spillerens kort</th>
              <th style="border:1px solid #ddd; padding:6px; text-align:left;">Board</th>
              <th style="border:1px solid #ddd; padding:6px; text-align:right;">Min net</th>
              <th style="border:1px solid #ddd; padding:6px; text-align:right;">Hans net</th>
              <th style="border:1px solid #ddd; padding:6px; text-align:left;">Vinner</th>
              <th style="border:1px solid #ddd; padding:6px; text-align:left;">Spillerens action</th>
            </tr>
          </thead>
          <tbody>
            ${rounds.map(r => {
              const heroNet = Number(r.hero_net || 0);
              const villainNet = Number(r.villain_net || 0);
              const winner = r.winner || (r.result === "tie" ? "split" : "-");
              return `<tr>
                <td style="border:1px solid #ddd; padding:6px;"><a href="#" class="hvLink" data-hand="${r.hand_id}">${r.hand_id}</a></td>
                <td style="border:1px solid #ddd; padding:6px;">${escapeHtml(r.started_at || "-")}</td>
                <td style="border:1px solid #ddd; padding:6px;"><b>${escapeHtml(r.hero_cards || "-")}</b></td>
                <td style="border:1px solid #ddd; padding:6px;"><b>${escapeHtml(r.villain_cards || "-")}</b></td>
                <td style="border:1px solid #ddd; padding:6px;">${escapeHtml(r.board || "-")}</td>
                <td style="border:1px solid #ddd; padding:6px; text-align:right; color:${heroNet >= 0 ? "#15803d" : "#b91c1c"};">${num(heroNet, 2)}</td>
                <td style="border:1px solid #ddd; padding:6px; text-align:right; color:${villainNet >= 0 ? "#15803d" : "#b91c1c"};">${num(villainNet, 2)}</td>
                <td style="border:1px solid #ddd; padding:6px;">${escapeHtml(winner)}</td>
                <td style="border:1px solid #ddd; padding:6px; max-width:360px; white-space:normal;">${escapeHtml(r.villain_actions || "-")}</td>
              </tr>`;
            }).join("")}
          </tbody>
        </table>
      </div>
    ` : `<div style="margin-top:14px; opacity:.7;">Ingen lagrede runder mellom ${escapeHtml(matchup.hero_name || "hero")} og ${escapeHtml(p.player_name)} ennå.</div>`;

    card.innerHTML = `
      <table style="border-collapse:collapse; width:100%; max-width:820px;">
        <tbody>
          <tr><td style="border:1px solid #ddd; padding:8px; font-weight:700; width:180px;">Spiller</td><td style="border:1px solid #ddd; padding:8px;">${escapeHtml(p.player_name)}</td></tr>
          <tr><td style="border:1px solid #ddd; padding:8px; font-weight:700;">Type</td><td style="border:1px solid #ddd; padding:8px;">${escapeHtml(p.player_type || "-")}</td></tr>
          <tr><td style="border:1px solid #ddd; padding:8px; font-weight:700;">Confidence</td><td style="border:1px solid #ddd; padding:8px;">${escapeHtml(p.confidence || "-")}</td></tr>
          <tr><td style="border:1px solid #ddd; padding:8px; font-weight:700;">Filter</td><td style="border:1px solid #ddd; padding:8px;">${p.session_id ? `session ${p.session_id}` : "global"}</td></tr>

          <tr><td colspan="2" style="padding:10px 0; font-weight:800;">Scores</td></tr>
          <tr><td style="border:1px solid #ddd; padding:8px; font-weight:700;">Aggression</td><td style="border:1px solid #ddd; padding:8px;">${p.aggression_score} (${escapeHtml(p.aggression_label)})</td></tr>
          <tr><td style="border:1px solid #ddd; padding:8px; font-weight:700;">Fundamentals</td><td style="border:1px solid #ddd; padding:8px;">${p.fundamentals_score} (${escapeHtml(p.fundamentals_label)})</td></tr>
          <tr><td style="border:1px solid #ddd; padding:8px; font-weight:700;">Strength</td><td style="border:1px solid #ddd; padding:8px;">${p.strength_score} (${escapeHtml(p.strength_label)})</td></tr>

          <tr><td colspan="2" style="padding:10px 0; font-weight:800;">Results</td></tr>
          <tr><td style="border:1px solid #ddd; padding:8px; font-weight:700;">Hands</td><td style="border:1px solid #ddd; padding:8px;">${p.results?.hands ?? 0}</td></tr>
          <tr><td style="border:1px solid #ddd; padding:8px; font-weight:700;">Net</td><td style="border:1px solid #ddd; padding:8px;">${p.results?.net_total ?? 0}</td></tr>
          <tr><td style="border:1px solid #ddd; padding:8px; font-weight:700;">bb / 100</td><td style="border:1px solid #ddd; padding:8px;">${p.results?.bb_per_100 ?? 0}</td></tr>
          <tr><td style="border:1px solid #ddd; padding:8px; font-weight:700;">Results conf</td><td style="border:1px solid #ddd; padding:8px;">${escapeHtml(p.results?.confidence ?? "-")}</td></tr>

          <tr><td style="border:1px solid #ddd; padding:8px; font-weight:700;">Notes</td><td style="border:1px solid #ddd; padding:8px;">${notesHtml}</td></tr>
        </tbody>
      </table>
      ${profileEquityHtml}
      ${matchupHtml}
      ${roundsHtml}
    `;

    card.querySelectorAll(".hvLink").forEach(a => {
      a.addEventListener("click", (ev) => {
        ev.preventDefault();
        const hid = a.getAttribute("data-hand");
        if (hid && typeof window.openHandViewer === "function") window.openHandViewer(hid);
      });
    });

    $("ppUseLiveCards")?.addEventListener("click", async () => {
      setProfileEquityManualMode(false, "Henter live kort...");
      if ($("ppEquityAuto")) $("ppEquityAuto").checked = true;
      await syncProfileEquityLiveCards({ force: true });
      calculateProfileEquity().catch(console.warn);
    });
    $("ppEquityAuto")?.addEventListener("change", async () => {
      if (!$("ppEquityAuto")?.checked) return;
      setProfileEquityManualMode(false, "Auto live aktiv.");
      const changed = await syncProfileEquityLiveCards({ silent: true, force: true });
      if (changed) calculateProfileEquity({ auto: true }).catch(console.warn);
    });
    $("ppCalcEquity")?.addEventListener("click", () => calculateProfileEquity().catch(console.warn));
    $("ppClearEquityCards")?.addEventListener("click", clearProfileEquityCards);
    $("ppCopyToMainEquity")?.addEventListener("click", copyProfileEquityToMainEquity);
    $("ppDecisionRefresh")?.addEventListener("click", renderProfileDecisionPanel);
    ["ppPotChips", "ppCallChips", "ppStackChips"].forEach(id => {
      $(id)?.addEventListener("input", renderProfileDecisionPanel);
    });
    ["ppHeroCards", "ppBoardCards"].forEach(id => {
      $(id)?.addEventListener("input", () => {
        syncProfileEquityPickerFromInputs({ manual: true });
        lastPlayerProfileEquityKey = "";
        setTimeout(() => calculateProfileEquity({ auto: true }).catch(console.warn), 250);
      });
    });
    ["ppVillainRange", "ppEquityIters"].forEach(id => {
      $(id)?.addEventListener("input", () => {
        lastPlayerProfileEquityKey = "";
        setTimeout(() => calculateProfileEquity({ auto: true }).catch(console.warn), 250);
      });
    });
    if (keepManualEquityCards) {
      setProfileEquityManualMode(true, "Manuelle kort beholdt.");
      syncProfileEquityInputs(preservedEquity.hero, preservedEquity.board);
      ppPickerTarget = preservedEquity.hero.length < 2 ? "hero" : "board";
      renderProfileEquityCardPicker();
      calculateProfileEquity({ auto: true }).catch(console.warn);
    } else {
      ppEquityManualMode = false;
      syncProfileEquityInputs([], []);
      renderProfileEquityCardPicker();
      syncProfileEquityLiveCards({ silent: true, force: true })
        .then(() => calculateProfileEquity({ auto: true }))
        .catch(console.warn);
    }
    renderProfileDecisionPanel();
    startProfileEquityAuto();
  } catch (e) {
    console.error(e);
    status.innerText = "Feil (se console)";
    card.innerHTML = `<div style="opacity:.7;">Klarte ikke Ã¥ kontakte backend.</div>`;
  }
}

function wirePlayerProfile() {
  $("ppLoad")?.addEventListener("click", loadPlayerProfile);
}

function openPlayerProfileFromTable(playerName) {
  const name = String(playerName || "").trim();
  if (!name) return;
  const ppPlayer = $("ppPlayer");
  if (ppPlayer) ppPlayer.value = name;
  const mtPlayer = $("mtPlayer");
  if (mtPlayer && !mtPlayer.value) mtPlayer.value = name;
  const spPlayer = $("spPlayer");
  if (spPlayer && !spPlayer.value) spPlayer.value = name;
  const lhPlayer = $("lhPlayer");
  if (lhPlayer && !lhPlayer.value) lhPlayer.value = name;
  loadPlayerProfile().catch(console.error);
}


// ------------------------------
// Villain profile cache + renderer (inline in Live Coach card)
// ------------------------------
const villainProfileCache = new Map(); // key -> { ts, data }
const PROFILE_TTL_MS = 2 * 60 * 1000;


function cacheKey(playerName, sessionId) {
  return `${playerName}::${sessionId || "global"}`;
}

async function fetchPlayerProfileCached(playerName, sessionId) {
  const key = cacheKey(playerName, sessionId);
  const now = Date.now();
  const cached = villainProfileCache.get(key);
  if (cached && (now - cached.ts) < PROFILE_TTL_MS) return cached.data;

  const params = new URLSearchParams();
  if (sessionId) params.set("session_id", sessionId);

  const qs = params.toString();
  const url = `${apiBase()}/players/${encodeURIComponent(playerName)}/profile${qs ? "?" + qs : ""}`;

  const res = await fetch(url);
  if (!res.ok) throw new Error("Profile HTTP " + res.status);
  const data = await res.json();

  villainProfileCache.set(key, { ts: now, data });
  return data;
}

function renderVillainProfileLine(p) {
  const bb100 = p?.results?.bb_per_100 ?? 0;
  const hands = p?.results?.hands ?? 0;
  const rconf = p?.results?.confidence ?? "low";

  return `
    <div style="margin-top:6px; padding:8px; border:1px solid #eee; border-radius:8px; background:#fff;">
      <div style="font-weight:700; margin-bottom:4px;">Villain Profile</div>
      <div style="opacity:.85;">
        type: <b>${escapeHtml(p.player_type || "UNKNOWN")}</b> |
        aggro: <b>${p.aggression_score}</b> (${escapeHtml(p.aggression_label)}) |
        fund: <b>${p.fundamentals_score}</b> (${escapeHtml(p.fundamentals_label)})
      </div>
      <div style="opacity:.85; margin-top:2px;">
        strength: <b>${p.strength_score}</b> (${escapeHtml(p.strength_label)}) |
        results: <b>${bb100}</b> bb/100 over <b>${hands}</b> hands (conf: <b>${escapeHtml(rconf)}</b>)
      </div>
    </div>
  `;
}

// ------------------------------
// "Denne Ã¸kten" hand log
// ------------------------------
const sessionHandCache = new Map(); // hand_id -> { summary, ts }

async function updateSessionHands(handId) {
  const listEl = $("sessionHandsList");
  if (!listEl || !handId) return;

  const hid = String(handId);
  if (sessionHandCache.has(hid)) return;

  try {
    const res = await fetch(`${apiBase()}/actions?hand_id=${encodeURIComponent(hid)}`);
    if (!res.ok) return;
    const rows = await res.json();

    const pre = rows.filter(r => r.street === 1);
    const raises = pre.filter(r => r.action === "raise").length;

    let summary = "hand";
    if (raises >= 2) summary = "open â†’ 3-bet";
    else if (raises === 1) summary = "open";
    else summary = "limp/blinds";

    const hero = $("lhPlayer")?.value?.trim();
    const heroFold = hero ? pre.some(r => r.player_name === hero && r.action === "fold") : false;
    if (heroFold && raises >= 2) summary = "open â†’ 3-bet â†’ fold";
    else if (heroFold && raises === 1) summary = "open â†’ fold";

    sessionHandCache.set(hid, { summary, ts: Date.now() });
    renderSessionHands();
  } catch (e) {
    console.error("updateSessionHands error", e);
  }
}

function renderSessionHands() {
  const listEl = $("sessionHandsList");
  if (!listEl) return;

  const items = [...sessionHandCache.entries()].sort((a, b) => b[1].ts - a[1].ts);
  if (!items.length) {
    listEl.innerText = "Ingen hender registrert enna.";
    return;
  }

  listEl.innerHTML = `
    <ul style="margin:0; padding-left:18px;">
      ${items.map(([hid, info]) => `
        <li>
          <a href="#" class="sessionHandLink" data-hand="${hid}">Hand ${hid}</a>
          - ${escapeHtml(info.summary)}
        </li>
      `).join("")}
    </ul>
  `;

  listEl.querySelectorAll(".sessionHandLink").forEach(a => {
    a.addEventListener("click", (ev) => {
      ev.preventDefault();
      const hid = a.getAttribute("data-hand");
      if (hid) window.openHandViewer(hid);
    });
  });
}

// ------------------------------
// Live Coach polling
// ------------------------------
let lhTimer = null;
let lastHintKey = null;

function setRunningStatus(text) {
  const el = $("lhStatus");
  if (el) el.innerText = text;
}
function setLastUpdate(text) {
  const el = $("lhLast");
  if (el) el.innerText = text;
}

function flashCoachCard() {
  const card = $("lhCard");
  if (!card) return;

  const old = card.style.boxShadow;
  card.style.boxShadow = "0 0 0 3px rgba(0, 200, 0, 0.35)";
  setTimeout(() => (card.style.boxShadow = old || ""), 900);

  let toast = $("lhToast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "lhToast";
    Object.assign(toast.style, {
      position: "fixed",
      right: "16px",
      bottom: "16px",
      padding: "10px 12px",
      borderRadius: "10px",
      background: "#111",
      color: "#fff",
      opacity: "0",
      transition: "opacity 200ms ease",
      fontSize: "13px",
      zIndex: "9999",
    });
    document.body.appendChild(toast);
  }

  toast.textContent = "Nytt hint funnet âœ…";
  toast.style.opacity = "1";
  setTimeout(() => (toast.style.opacity = "0"), 1200);
}

function renderHintCard(data) {
  const card = $("lhCard");
  if (!card) return;

  // 1) Ingen spot funnet
  if (!data || !data.found) {
    const mode = $("lhMode")?.value || "targeted";
    const sess = $("lhSession")?.value?.trim();
    const detail = data?.reason || "Ingen match i lookback-vinduet.";

    card.innerHTML = `
      <div><b>Venter pÃ¥ riktig spotâ€¦</b></div>
      <div style="opacity:.75; margin-top:6px;">
        ${mode === "targeted"
          ? "Targeted: leter etter topp-target (f.eks. LATE/IP/vs_medium_3bet)."
          : "Latest: leter etter siste openâ†’face 3-bet."}
      </div>
      <div style="opacity:.75;">
        ${sess ? `Session filter: <b>${escapeHtml(sess)}</b>` : "Ingen session filter (globalt)."}
      </div>
      <div style="opacity:.6; margin-top:6px;">${escapeHtml(detail)}</div>
    `;
    return;
  }

  // 2) Spot funnet
  const watchoutsHtml = (data.watchouts || []).map(x => `<li>${escapeHtml(x)}</li>`).join("");

  const evidenceIds = data.evidence_hand_ids || [];
  const evidenceHtml = evidenceIds.length
    ? `Evidence hand_id: ${evidenceIds.map(id =>
        `<a href="#" class="hvLink" data-hand="${id}">${id}</a>`
      ).join(", ")}`
    : "Ingen evidence.";

  card.innerHTML = `
    <div><b>${escapeHtml(data.situation || `${data.open_group}/${data.stance}/${data.bucket}`)}</b></div>

<div style="margin:6px 0; font-size:16px; font-weight:700;">
  ${escapeHtml(data.one_liner || data.hint || "")}
</div>

<div style="opacity:.8; margin-bottom:6px;">
  villain: <b>${escapeHtml(data.villain_name || "-")}</b> |
  hand_id: <b>${data.hand_id || "-"}</b> |
  confidence: <b>${escapeHtml(data.confidence || "low")}</b>
</div>

${window.lastEquity ? `
<div style="
  margin:8px 0;
  padding:8px;
  background:#eef8ee;
  border:1px solid #c8e6c9;
  border-radius:6px;
  font-weight:bold;
">
  ðŸŽ² Equity:
  ${window.lastEquity.win}% |
  Tie ${window.lastEquity.tie}% |
  Lose ${window.lastEquity.lose}%
</div>
` : ""}

<div id="villProfile" style="opacity:.7;">Villain profile: Lasterâ€¦</div>

    <details style="margin-top:8px;">
      <summary style="cursor:pointer; opacity:.8;">Detaljer</summary>
      <ul style="margin:6px 0 6px 18px;">${watchoutsHtml}</ul>
      <div style="opacity:.7;">${evidenceHtml}</div>
    </details>
  `;

  // klikkbare evidence lenker
  card.querySelectorAll(".hvLink").forEach(a => {
    a.addEventListener("click", (ev) => {
      ev.preventDefault();
      const id = a.getAttribute("data-hand");
      if (id) window.openHandViewer(id);
    });
  });

  // 3) Last villain profile async (uten Ã¥ krÃ¦sje UI)
  (async () => {
    const vp = $("villProfile");
    if (!vp) return;

    const villain = data?.villain_name;
    if (!villain || villain === "-") {
      vp.innerText = "Villain profile: (ingen navn)";
      return;
    }

    const sess = $("lhSession")?.value?.trim() || null;

    try {
      const prof = await fetchPlayerProfileCached(villain, sess);
      vp.innerHTML = renderVillainProfileLine(prof);
    } catch (e) {
      console.warn("Villain profile failed:", e);
      vp.innerText = "Villain profile: (ikke tilgjengelig ennÃ¥)";
    }
  })();
}


async function fetchLiveHintOnce() {
  const player = document.getElementById("lhPlayer")?.value?.trim();
  const sessionVal = document.getElementById("lhSession")?.value?.trim();
  const mode = document.getElementById("lhMode")?.value || "targeted";

  if (!player) return;

  const params = new URLSearchParams();
  params.set("player_name", player);     // âœ… her mÃ¥ det vÃ¦re player
  params.set("mode", mode);
  params.set("target_rank", "1");
  params.set("lookback_hands", "50");
  if (sessionVal) params.set("session_id", sessionVal);

  const url = `${apiBase()}/players/live_hint/3bet/auto?${params.toString()}`;



  try {
    const res = await fetch(url);
    const data = await res.json();

    const key = data?.found ? `${data.hand_id}-${data.bucket}-${data.stance}` : "none";

    if (key !== lastHintKey) {
      lastHintKey = key;
      renderHintCard(data);

      if (data?.found) flashCoachCard();

      if (data?.found && data.hand_id) {
        updateSessionHands(data.hand_id);
      }
    }

    if (data?.found) setLastUpdate(`Oppdatert (hand ${data.hand_id})`);
    else setLastUpdate(mode === "targeted" ? "Oppdatert â€“ venter pÃ¥ target-spot" : "Oppdatert â€“ ingen 3-bet spot funnet");
  } catch (err) {
    console.error(err);
    setLastUpdate("Backend nede / Feil (se console)");
  }
}


function startLiveHint() {
  stopLiveHint();
  setRunningStatus("KjÃ¸rer (hver 4. sekund)");
  setLastUpdate("Starterâ€¦");

  fetchLiveHintOnce().catch(console.error);
  lhTimer = setInterval(() => fetchLiveHintOnce().catch(console.error), 4000);
}

function stopLiveHint() {
  if (lhTimer) clearInterval(lhTimer);
  lhTimer = null;
  setRunningStatus("Stoppet");
}

function wireLiveCoach() {
  $("lhStart")?.addEventListener("click", startLiveHint);
  $("lhStop")?.addEventListener("click", stopLiveHint);
  setRunningStatus("Stoppet");
  setLastUpdate("");
}

// ------------------------------
// Dashboard tabs + Session Overview table
// ------------------------------
function showTab(tab) {
  document.querySelectorAll(".tabPage").forEach(p => {
    p.style.display = (p.getAttribute("data-tab") === tab) ? "" : "none";
  });
}

function wireTabs() {
  document.querySelectorAll(".tabBtn").forEach(btn => {
    btn.addEventListener("click", () => showTab(btn.getAttribute("data-tab")));
  });
  showTab("live");
}

function badge(text, tone) {
  const bg =
    tone === "high" ? "#d1fae5" :
    tone === "medium" ? "#fef3c7" :
    tone === "low" ? "#e5e7eb" :
    "#e5e7eb";
  return `<span style="padding:2px 8px; border-radius:999px; background:${bg}; font-size:12px;">${escapeHtml(text)}</span>`;
}
function num(x, digits=1) {
  if (x === null || x === undefined) return "-";
  const n = Number(x);
  if (Number.isNaN(n)) return "-";
  return n.toFixed(digits);
}

function buildSessionHudTable(data) {
  const wrap = $("sessionHudTableWrap") || $("sessionHudBox");
  if (!wrap) return;

  const players = data?.players || [];
  if (!players.length) {
    wrap.innerHTML = `<div style="opacity:.7;">Ingen spillere funnet (sjekk session_id / min_hands).</div>`;
    return;
  }

  players.sort((a, b) => (b.hands_played || 0) - (a.hands_played || 0));

  wrap.innerHTML = `
    <div style="border:1px solid #ddd; border-radius:10px; overflow:hidden;">
      <table style="width:100%; border-collapse:collapse; font-size:14px;">
        <thead style="background:#fafafa;">
          <tr>
            <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">Player</th>
            <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">Hands</th>
            <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">VPIP</th>
            <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">PFR</th>
            <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">3bet</th>
            <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">Cbet</th>
            <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">Fold Cbet</th>
            <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">Fold 3bet</th>
            <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">Type</th>
            <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">Conf</th>
          </tr>
        </thead>
        <tbody>
          ${players.map(p => {
            const conf = p.confidence || "low";
            const type = p.player_type || "UNKNOWN";
            return `
              <tr class="pRow" data-player="${escapeHtml(p.player_name)}" style="cursor:pointer;">
                <td style="padding:8px; border-bottom:1px solid #eee;"><b>${escapeHtml(p.player_name)}</b></td>
                <td style="padding:8px; border-bottom:1px solid #eee;">${p.hands_played ?? "-"}</td>
                <td style="padding:8px; border-bottom:1px solid #eee;">${num(p.vpip_pct,1)}%</td>
                <td style="padding:8px; border-bottom:1px solid #eee;">${num(p.pfr_pct,1)}%</td>
                <td style="padding:8px; border-bottom:1px solid #eee;">${num(p.threebet_pct,1)}%</td>
                <td style="padding:8px; border-bottom:1px solid #eee;">${num(p.cb_flop_pct,1)}%</td>
                <td style="padding:8px; border-bottom:1px solid #eee;">${num(p.fold_to_cb_flop_pct,1)}%</td>
                <td style="padding:8px; border-bottom:1px solid #eee;">${num(p.fold_to_3bet_pct,1)}%</td>
                <td style="padding:8px; border-bottom:1px solid #eee;">${badge(type, conf)}</td>
                <td style="padding:8px; border-bottom:1px solid #eee;">${badge(conf, conf)}</td>
              </tr>
            `;
          }).join("")}
        </tbody>
      </table>
    </div>
    <div style="opacity:.7; margin-top:8px;">
      Klikk pÃ¥ en spiller for Ã¥ laste Player Profile.
    </div>
  `;

  wrap.querySelectorAll(".pRow").forEach(tr => {
    tr.addEventListener("click", () => {
      const name = tr.getAttribute("data-player");
      if (!name) return;

      if ($("ppPlayer")) $("ppPlayer").value = name;
      const sid = $("dashSession")?.value?.trim() || $("lhSession")?.value?.trim();
      if ($("ppSession") && sid) $("ppSession").value = sid;

      // click load
      $("ppLoad")?.click();
      // show live tab (optional)
      showTab("live");
    });
  });
}

async function loadSessionHud() {
  const sid = dashSessionId();
  if (!sid) return setDashStatus("Sett Session fÃ¸rst.");

  const minHands = Number($("sessMinHands")?.value || 5);
  const statusEl = $("sessionHudStatus");
  if (statusEl) statusEl.innerText = "Lasterâ€¦";
  setDashStatus("Laster Session HUDâ€¦");

  try {
    const res = await fetch(`${apiBase()}/sessions/${sid}/hud?min_hands=${encodeURIComponent(minHands)}`);
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    buildSessionHudTable(data);
    if (statusEl) statusEl.innerText = "OK";
    setDashStatus("OK");
  } catch (e) {
    console.error(e);
    if (statusEl) statusEl.innerText = "Feil";
    setDashStatus("Feil (se console)");
  }
}

async function loadStartingHands(opts = {}) {
  const status = $("startingHandsStatus");
  const out = $("startingHandsOut");
  if (!out) return;
  if (startingHandsInFlight) return;
  startingHandsInFlight = true;

  const player = $("shPlayer")?.value?.trim() || dashHero();
  const rawSession = $("shSession")?.value?.trim() || $("dashSession")?.value?.trim() || "";
  const sessionNum = Number(rawSession);
  const minHands = Math.max(0, Number($("shMinHands")?.value || 0) || 0);
  const limit = Math.max(1, Math.min(Number($("shLimit")?.value || 1000) || 1000, 10000));
  const includeAll = $("shIncludeAll")?.checked !== false;
  const probIters = Math.max(25, Math.min(Number($("shProbIters")?.value || 250) || 250, 2000));
  const villains = Math.max(1, Math.min(Number($("shVillains")?.value || 1) || 1, 8));

  if (status) status.innerText = opts.silent ? "Auto oppdaterer..." : "Laster...";
  if (!opts.silent) out.innerHTML = "";

  const params = new URLSearchParams();
  params.set("min_hands", String(minHands));
  params.set("limit", String(limit));
  params.set("include_all", String(includeAll));
  params.set("calc_prob", "true");
  params.set("prob_iters", String(probIters));
  params.set("villains", String(villains));
  if (player) params.set("player_name", player);
  if (rawSession && Number.isInteger(sessionNum) && sessionNum > 0) {
    params.set("session_id", String(sessionNum));
  }

  try {
    const res = await fetch(`${apiBase()}/hands/starting-hands?${params.toString()}`);
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    const rows = data.ranking || [];
    const updatedAt = new Date().toLocaleTimeString();

    lastStartingHandsRefreshKey = opts.key || lastStartingHandsRefreshKey;
    if (status) status.innerText = `OK - ${rows.length} grupper, sist ${updatedAt}`;
    if (!rows.length) {
      out.innerHTML = `<div style="opacity:.7;">Ingen kjente starthender funnet for filteret.</div>`;
      return;
    }

    const topRows = rows.slice(0, 80);
    let html = `
      <div style="opacity:.75; margin-bottom:8px;">
        Sortert paa beregnet win %. Historikk: <b>${data.total_rows}</b> hender / <b>${data.history_cards || 0}</b> kort. Sim: <b>${data.prob_iters}</b> per hand mot <b>${data.villains}</b>.
      </div>
      <table style="border-collapse:collapse; width:100%; font-size:13px;">
        <thead>
          <tr style="background:#f5f5f5;">
            <th style="border:1px solid #ddd; padding:7px; text-align:right;">#</th>
            <th style="border:1px solid #ddd; padding:7px; text-align:left;">Hand</th>
            <th style="border:1px solid #ddd; padding:7px; text-align:right;">Win %</th>
            <th style="border:1px solid #ddd; padding:7px; text-align:right;">Styrke</th>
            <th style="border:1px solid #ddd; padding:7px; text-align:right;">Base</th>
            <th style="border:1px solid #ddd; padding:7px; text-align:right;">Hands</th>
            <th style="border:1px solid #ddd; padding:7px; text-align:right;">bb/100</th>
            <th style="border:1px solid #ddd; padding:7px; text-align:right;">Net bb</th>
            <th style="border:1px solid #ddd; padding:7px; text-align:right;">Flop</th>
            <th style="border:1px solid #ddd; padding:7px; text-align:right;">River</th>
            <th style="border:1px solid #ddd; padding:7px; text-align:left;">Vanlig slutt</th>
            <th style="border:1px solid #ddd; padding:7px; text-align:left;">Conf</th>
            <th style="border:1px solid #ddd; padding:7px; text-align:left;">Eksempler</th>
          </tr>
        </thead>
        <tbody>
    `;

    topRows.forEach((r, idx) => {
      const tone = r.observed ? (r.score >= 0 ? "#ecfdf5" : "#fff7ed") : "#fff";
      const winPct = r.win_prob === null || r.win_prob === undefined ? null : r.win_prob * 100;
      const scoreColor = winPct === null ? "#777" : winPct >= 50 ? "#047857" : "#b45309";
      const examples = (r.examples || []).slice(0, 3).map(e =>
        `<a href="#" class="shHandLink" data-hand="${e.hand_id}">${e.hand_id}</a>`
      ).join(", ");

      html += `
        <tr style="background:${idx < 10 ? tone : "#fff"};">
          <td style="border:1px solid #ddd; padding:7px; text-align:right;">${idx + 1}</td>
          <td style="border:1px solid #ddd; padding:7px;"><b>${escapeHtml(r.hand)}</b></td>
          <td style="border:1px solid #ddd; padding:7px; text-align:right; color:${scoreColor};"><b>${winPct === null ? "-" : num(winPct, 1) + "%"}</b></td>
          <td style="border:1px solid #ddd; padding:7px; text-align:right; color:${scoreColor};"><b>${num(r.score, 1)}</b></td>
          <td style="border:1px solid #ddd; padding:7px; text-align:right;">${num(r.baseline_score, 1)}</td>
          <td style="border:1px solid #ddd; padding:7px; text-align:right;">${r.hands}</td>
          <td style="border:1px solid #ddd; padding:7px; text-align:right;">${num(r.bb_per_100, 1)}</td>
          <td style="border:1px solid #ddd; padding:7px; text-align:right;">${num(r.bb_total, 2)}</td>
          <td style="border:1px solid #ddd; padding:7px; text-align:right;">${num(r.flop_seen_pct, 1)}%</td>
          <td style="border:1px solid #ddd; padding:7px; text-align:right;">${num(r.river_seen_pct, 1)}%</td>
          <td style="border:1px solid #ddd; padding:7px;">${escapeHtml(r.top_showdown_class || "-")}</td>
          <td style="border:1px solid #ddd; padding:7px;">${badge(r.confidence, r.confidence)}</td>
          <td style="border:1px solid #ddd; padding:7px;">${examples || "-"}</td>
        </tr>
      `;
    });

    html += `</tbody></table>`;
    out.innerHTML = html;

    out.querySelectorAll(".shHandLink").forEach(a => {
      a.addEventListener("click", ev => {
        ev.preventDefault();
        const hid = a.getAttribute("data-hand");
        if (hid && typeof window.openHandViewer === "function") {
          window.openHandViewer(hid);
          showTab("live");
        }
      });
    });
  } catch (e) {
    console.error(e);
    if (status) status.innerText = "Feil";
    if (!opts.silent) {
      out.innerHTML = `<div style="color:red;">Feil: ${escapeHtml(e.message)}</div>`;
    }
  } finally {
    startingHandsInFlight = false;
  }
}

async function saveLiveCardsToCurrentHand(heroCards, boardCards = [], meta = {}) {
  const gamecode = String(meta?.gamecode || meta?.site_hand_id || "").trim();
  const source = String(meta?.source || "");
  const isScreenSource = source.includes("screen");
  const explicitHandId = meta?.hand_id || meta?.id || "";
  const handId = explicitHandId || lastGameState?.hand_id || $("hvHandId")?.value?.trim() || "";
  const hero = (heroCards || []).map(convertBetSolidCard).filter(isCard);
  const board = (boardCards || []).map(convertBetSolidCard).filter(isCard);
  if (hero.length !== 2) return false;
  if (!gamecode && (!handId || Number.isNaN(Number(handId)))) return false;
  if (new Set(hero.concat(board)).size !== hero.length + board.length) {
    const status = $("startingHandsStatus");
    if (status) status.innerText = "Livekort ikke lagret: duplikate kort lest fra skjerm.";
    return false;
  }

  const key = `${gamecode || handId}:${hero.join(" ")}:${board.join(" ")}`;
  if (key === lastSavedLiveCardsKey) return false;
  lastSavedLiveCardsKey = key;

  try {
    const body = {
      player_name: dashHero(),
      hero,
      board
    };
    if (gamecode) {
      body.gamecode = gamecode;
      body.session_code = meta?.session_code || "";
      body.session_id = meta?.session_id || null;
      body.started_at = meta?.started_at || meta?.updated_at || null;
      body.players = Array.isArray(meta?.players) ? meta.players : [];
    }

    const url = gamecode
      ? `${apiBase()}/hands/live-cards`
      : `${apiBase()}/hands/${encodeURIComponent(handId)}/cards`;
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    if (!res.ok) {
      let detail = "";
      try {
        const err = await res.json();
        detail = err?.detail ? `: ${typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail)}` : "";
      } catch (_) {}
      throw new Error(`HTTP ${res.status}${detail}`);
    }
    const saved = await res.json();
    if (saved?.hand_id) {
      lastGameState.hand_id = saved.hand_id;
      if ($("hvHandId")) $("hvHandId").value = String(saved.hand_id);
    }
    if (saved?.session_id) {
      syncActiveSessionFields(saved.session_id, "saved-live");
    }
    const status = $("startingHandsStatus");
    if (status) {
      const handLabel = saved?.hero?.length === 2 ? saved.hero.join(" ") : hero.join(" ");
      status.innerText = `Lagret live hand ${saved?.hand_id || handId}: ${handLabel}`;
    }
    scheduleStartingHandsRefresh("saved-live-cards", key);
    await refreshBackendCardHistory({ force: true });
    renderHeroHistoryMatches();
    return true;
  } catch (e) {
    console.warn("Could not save live cards to hand", e);
    const status = $("startingHandsStatus");
    if (status) status.innerText = `Livekort ikke lagret: ${e.message || e}`;
    return false;
  }
}

function scheduleStartingHandsRefresh(reason = "auto", key = "") {
  const auto = $("shAuto");
  if (auto && !auto.checked) return;
  if (!$("startingHandsOut")) return;

  const refreshKey = key || reason;
  if (refreshKey && refreshKey === lastStartingHandsRefreshKey) return;

  if (startingHandsTimer) clearTimeout(startingHandsTimer);
  startingHandsTimer = setTimeout(() => {
    loadStartingHands({ silent: true, reason, key: refreshKey }).catch(console.error);
  }, 700);
}

function wireStartingHands() {
  const player = $("shPlayer");
  const session = $("shSession");
  if (player && !player.value) player.value = dashHero();
  if (session && !session.value && $("dashSession")?.value) session.value = $("dashSession").value;
  $("btnStartingHands")?.addEventListener("click", loadStartingHands);
  $("shAuto")?.addEventListener("change", ev => {
    if (ev.target.checked) scheduleStartingHandsRefresh("auto-enabled", `auto-${Date.now()}`);
  });
  $("shIncludeAll")?.addEventListener("change", () => loadStartingHands({ silent: false }).catch(console.error));
  scheduleStartingHandsRefresh("boot", "boot");
}

// ------------------------------
// 3-bet Response Matrix & Sampling Plan
// ------------------------------
async function loadThreeBetMatrix() {
  const player = $("mtPlayer")?.value?.trim() || dashHero();
  const sessionVal = $("mtSession")?.value?.trim();
  const groupOpenPos = $("mtGroupOpenPos")?.checked !== false;

  if (!player) {
    alert("Spiller mÃ¥ oppgis");
    return;
  }

  const status = $("mtStatus");
  const out = $("mtOut");
  if (!status || !out) return;

  status.innerText = "Lasterâ€¦";
  out.innerHTML = "";

  const params = new URLSearchParams();
  params.set("min_faced", "1");
  params.set("group_openpos", groupOpenPos);
  if (sessionVal) params.set("session_id", sessionVal);

  try {
    const url = `${apiBase()}/players/${encodeURIComponent(player)}/threebet_response_matrix?${params.toString()}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();

    status.innerText = "OK";

    const cells = data.cells || [];
    if (!cells.length) {
      out.innerHTML = `<div style="opacity:.7;">Ingen data for denne spilleren enna.</div>`;
      return;
    }

    // build matrix table
    let html = `<h3>${escapeHtml(player)} - 3-bet Response Matrix</h3>`;
    html += `<div style="opacity:.8; margin-bottom:10px;">Total faced: <b>${data.total_faced}</b> | Cells returned: <b>${data.cells_returned}</b> | Recommendation: >=<b>${data.recommended_min_faced}</b> faced per cell</div>`;

    html += `<table style="border-collapse:collapse; width:100%; font-size:13px;">`;
    html += `<thead><tr style="background:#f0f0f0;">
      <th style="border:1px solid #ddd; padding:6px; text-align:left;">Open Pos</th>
      <th style="border:1px solid #ddd; padding:6px; text-align:left;">Stance</th>
      <th style="border:1px solid #ddd; padding:6px; text-align:left;">Bucket</th>
      <th style="border:1px solid #ddd; padding:6px; text-align:right;">Faced</th>
      <th style="border:1px solid #ddd; padding:6px; text-align:right;">Fold</th>
      <th style="border:1px solid #ddd; padding:6px; text-align:right;">Call</th>
      <th style="border:1px solid #ddd; padding:6px; text-align:right;">4-bet</th>
      <th style="border:1px solid #ddd; padding:6px; text-align:left;">Conf</th>
      <th style="border:1px solid #ddd; padding:6px; text-align:left;">Note</th>
    </tr></thead>`;

    html += `<tbody>`;
    cells.forEach(c => {
      const confColor = c.confidence === "high" ? "#d1fae5" : c.confidence === "medium" ? "#fef3c7" : "#f3f4f6";
      html += `<tr style="background:${confColor};">
        <td style="border:1px solid #ddd; padding:6px;">${escapeHtml(c.open_group)}</td>
        <td style="border:1px solid #ddd; padding:6px;">${escapeHtml(c.stance)}</td>
        <td style="border:1px solid #ddd; padding:6px;">${escapeHtml(c.bucket)}</td>
        <td style="border:1px solid #ddd; padding:6px; text-align:right;"><b>${c.faced}</b></td>
        <td style="border:1px solid #ddd; padding:6px; text-align:right;">${c.fold} (${num(c.fold_pct)}%)</td>
        <td style="border:1px solid #ddd; padding:6px; text-align:right;">${c.call} (${num(c.call_pct)}%)</td>
        <td style="border:1px solid #ddd; padding:6px; text-align:right;">${c.fourbet} (${num(c.fourbet_pct)}%)</td>
        <td style="border:1px solid #ddd; padding:6px;">${badge(c.confidence, c.confidence)}</td>
        <td style="border:1px solid #ddd; padding:6px; opacity:.75; font-size:12px;">${escapeHtml(c.note || "")}</td>
      </tr>`;
    });
    html += `</tbody></table>`;

    out.innerHTML = html;
  } catch (e) {
    console.error(e);
    status.innerText = "Feil";
    out.innerHTML = `<div style="color:red; opacity:.8;">Feil: ${escapeHtml(e.message)}</div>`;
  }
}

async function loadThreeBetSamplingPlan() {
  const player = $("spPlayer")?.value?.trim() || dashHero();
  const sessionVal = $("spSession")?.value?.trim();
  const groupOpenPos = $("spGroupOpenPos")?.checked !== false;

  if (!player) {
    alert("Spiller mÃ¥ oppgis");
    return;
  }

  const status = $("spStatus");
  const out = $("spOut");
  if (!status || !out) return;

  status.innerText = "Lasterâ€¦";
  out.innerHTML = "";

  const params = new URLSearchParams();
  params.set("group_openpos", groupOpenPos);
  if (sessionVal) params.set("session_id", sessionVal);

  try {
    const url = `${apiBase()}/players/${encodeURIComponent(player)}/threebet_sampling_plan?${params.toString()}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();

    status.innerText = "OK";

    const targets = data.targets || [];
    if (!targets.length) {
      out.innerHTML = `<div style="opacity:.7;">Ingen targets for denne spilleren.</div>`;
      return;
    }

    // build plan
    let html = `<h3>${escapeHtml(player)} â€“ 3-bet Sampling Plan</h3>`;
    html += `<div style="opacity:.8; margin-bottom:10px;">Total faced: <b>${data.total_faced}</b> | Top ${targets.length} targets:</div>`;

    html += `<div style="display:grid; gap:12px; margin-top:12px;">`;
    targets.forEach((t, idx) => {
      const priority = t.priority || 0;
      const need = t.need_more_for_medium || 0;
      const priColor = priority >= 100 ? "#fee2e2" : priority >= 80 ? "#fef3c7" : priority >= 60 ? "#e0f2fe" : "#f3f4f6";

      html += `<div style="border:1px solid #ddd; padding:10px; border-radius:8px; background:${priColor};">
        <div style="font-weight:700; margin-bottom:4px;">
          ${idx + 1}. ${escapeHtml(t.open_group)}/${escapeHtml(t.stance)}/${escapeHtml(t.bucket)}
          <span style="opacity:.7; font-weight:400; font-size:12px;">(priority: ${t.priority})</span>
        </div>
        <div style="opacity:.85; margin-bottom:6px;">Faced: <b>${t.faced}</b> | Need +${need} for medium confidence</div>
        <div style="opacity:.8; margin-bottom:6px;">ðŸ“‹ ${escapeHtml(t.why)}</div>
        <div style="background:#fff; padding:8px; border-radius:4px; margin-bottom:6px; font-size:13px; opacity:.75;">
          ${escapeHtml(t.micro_rule)}
        </div>
        ${t.example_hand_ids && t.example_hand_ids.length ? `
          <div style="opacity:.7; font-size:12px;">
            Example hands: ${t.example_hand_ids.map(id => `<a href="#" class="spLink" data-hand="${id}">${id}</a>`).join(", ")}
          </div>
        ` : ""}
      </div>`;
    });
    html += `</div>`;

    out.innerHTML = html;

    // attach click handlers for example hands
    out.querySelectorAll(".spLink").forEach(a => {
      a.addEventListener("click", (ev) => {
        ev.preventDefault();
        const hid = a.getAttribute("data-hand");
        if (hid) window.openHandViewer(hid);
      });
    });
  } catch (e) {
    console.error(e);
    status.innerText = "Feil";
    out.innerHTML = `<div style="color:red; opacity:.8;">Feil: ${escapeHtml(e.message)}</div>`;
  }
}

function wireLiveCoachEnhanced() {
  $("btnLoadMatrix")?.addEventListener("click", loadThreeBetMatrix);
  $("btnLoadSamplingPlan")?.addEventListener("click", loadThreeBetSamplingPlan);
}

function wireDashboard() {
  wireTabs();
  $("btnSessionHud")?.addEventListener("click", loadSessionHud);
}

function wireCollapsibleSections() {
  document.querySelectorAll("section").forEach((section, idx) => {
    if (section.dataset.collapsibleReady === "1") return;
    const heading = Array.from(section.children).find(el => /^H[1-4]$/i.test(el.tagName || ""));
    if (!heading) return;

    section.dataset.collapsibleReady = "1";
    const title = normalizeSpaces(heading.textContent || `seksjon-${idx}`) || `seksjon-${idx}`;
    const key = `vinne.section.collapsed.${idx}.${title.slice(0, 40)}`;
    const collapsed = localStorage.getItem(key) === "1";

    heading.classList.add("section-toggle-head");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "section-toggle-btn";
    btn.dataset.sectionToggle = "1";
    heading.appendChild(btn);

    const setCollapsed = (isCollapsed) => {
      Array.from(section.children).forEach(child => {
        if (child === heading) return;
        child.style.display = isCollapsed ? "none" : "";
      });
      btn.textContent = isCollapsed ? "Vis" : "Skjul";
      btn.title = isCollapsed ? "Vis denne delen" : "Skjul denne delen";
      localStorage.setItem(key, isCollapsed ? "1" : "0");
    };

    btn.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      setCollapsed(btn.textContent !== "Vis");
    });
    setCollapsed(collapsed);
  });
}

// ------------------------------
// Boot
// ------------------------------

document.addEventListener("DOMContentLoaded", () => {
  const safeCall = (fn, name) => {
    if (typeof fn === "function") {
      fn();
    } else {
      console.warn(`âš ï¸ ${name}() mangler`);
    }
  };

  safeCall(wireDashboard, "wireDashboard");
  safeCall(wireLiveCoach, "wireLiveCoach");
  safeCall(wireLiveCoachEnhanced, "wireLiveCoachEnhanced");
  safeCall(wireHandViewer, "wireHandViewer");
  safeCall(wireHvEquity, "wireHvEquity");
  safeCall(wirePlayerProfile, "wirePlayerProfile");
  safeCall(wireEquityCalculator, "wireEquityCalculator");
  safeCall(wirePresetRangeBuilder, "wirePresetRangeBuilder");
  safeCall(wireMultiHandComparison, "wireMultiHandComparison");
  safeCall(wireStartingHands, "wireStartingHands");
  safeCall(wirePlayerAutocomplete, "wirePlayerAutocomplete");
  safeCall(wireCollapsibleSections, "wireCollapsibleSections");

  const autoEquityBox = $("autoEquity");
  if (autoEquityBox) autoEquityBox.checked = false;
  const autoEquityStatus = $("autoEquityStatus");
  if (autoEquityStatus) {
    autoEquityStatus.innerText = "";
  }

  // Render any saved card history
  try { renderCardHistory(); } catch (e) { console.warn(e); }
  try { renderHeroHistoryMatches(); } catch (e) { console.warn(e); }

  // Auto-update card history when other tabs/windows change localStorage
  window.addEventListener("storage", (ev) => {
    try {
      if (ev && ev.key === CARD_HISTORY_KEY) {
        renderCardHistory();
        renderHeroHistoryMatches();
      }
    } catch (e) {
      console.warn("cardHistory storage event failed", e);
    }
  });

  // Session Insights
  function loadSessionInsights() {
    const sessionId = dashSessionId();
    if (!sessionId) {
      alert("Velg en sesjon fÃ¸rst!");
      return;
    }

    const url = `${apiBase()}/players/session/${sessionId}/stats`;
    fetch(url)
      .then(r => r.json())
      .then(data => {
        const out = $("sessionInsightsOut");
        if (!data.players || data.players.length === 0) {
          out.innerHTML = "<p>Ingen spillere funnet i denne sesjonen.</p>";
          return;
        }

        let html = `<h3>Sesjon ${data.session_code}</h3>`;
        html += `<p><strong>Totalt:</strong> ${data.total_players} spillere, ${data.total_hands} hender</p>`;
        html += `<table border="1" cellpadding="8"><tr><th>Spiller</th><th>Hender</th><th>Innsats</th><th>Gevinst</th><th>Netto</th><th>BB/hÃ¥nd</th></tr>`;

        data.players.forEach(p => {
          const netClass = p.net_total > 0 ? 'style="color:green;"' : 'style="color:red;"';
          html += `<tr>
            <td>${p.player_name}</td>
            <td>${p.hands}</td>
            <td>${p.bet_total.toFixed(2)}</td>
            <td>${p.win_total.toFixed(2)}</td>
            <td ${netClass}>${p.net_total.toFixed(2)}</td>
            <td>${p.bb_per_hand.toFixed(2)}</td>
          </tr>`;
        });

        html += `</table>`;
        out.innerHTML = html;
      })
      .catch(err => {
        $("sessionInsightsOut").innerHTML = `<p style="color:red;">Feil: ${err.message}</p>`;
      });
  }

  // ========== LIVE GAME POLLING (fra database) ==========
async function applyLiveScreenCards() {
  try {
    const cardsRes = await fetch(`${apiBase()}/live-cards?ts=${Date.now()}`);
    if (!cardsRes.ok) return false;

    const cardsData = await cardsRes.json();
    lastLiveCardsMeta = cardsData || {};
    const liveGameKey = String(cardsData.gamecode || cardsData.hand_id || "");
    const liveGameChanged = Boolean(liveGameKey && lastLiveCardsGameKey && liveGameKey !== lastLiveCardsGameKey);
    if (liveGameChanged) {
      lastLiveHeroText = "";
      lastLiveBoardText = "";
      pendingScreenHeroText = "";
      pendingScreenHeroCount = 0;
    }
    if (liveGameKey) lastLiveCardsGameKey = liveGameKey;
    if (Array.isArray(cardsData.players) && cardsData.players.length) {
      mergeKnownPlayerNames(cardsData.players.map(p => p.name || p.player_name));
    }
    const liveTimestamp = Number(cardsData.timestamp || 0);
    const liveAgeSeconds = liveTimestamp ? (Date.now() / 1000 - liveTimestamp) : Infinity;
    const rawHeroText = normalizeSpaces(cardsData.hero_cards || cardsData.hero || "");
    const rawBoardText = normalizeSpaces(cardsData.board || "");
    const liveHeroCards = parseCards(rawHeroText);
    const liveBoardCards = parseCards(rawBoardText);
    const heroText = liveHeroCards.join(" ");
    const boardText = liveBoardCards.join(" ");
    const validLiveHero = liveHeroCards.length === 2 && liveHeroCards.every(isCard);
    const validLiveBoard = [3, 4, 5].includes(liveBoardCards.length) && liveBoardCards.every(isCard);
    const hasUsableCards = validLiveHero || (Boolean(boardText) && validLiveBoard);
    const source = String(cardsData.source || "");
    const isScreenSource = source.startsWith("screen_");
    if (cardsData.error === "stale_live_cards" || source === "stale_live_cards") {
      lastLiveHeroText = "";
      lastLiveBoardText = "";
      lastLiveCardsStatus = "Livekort: skjermlesing er stale.";
      pendingScreenHeroText = "";
      pendingScreenHeroCount = 0;
      liveScreenActive = false;
      clearMainHeroForNewLiveHand();
      const autoStatus = $("autoEquityStatus");
      if (autoStatus) autoStatus.innerText = "Live: venter på fersk skjermlesing.";
      return false;
    }
    if (liveGameChanged && !validLiveHero) {
      clearMainHeroForNewLiveHand();
    }

    if (liveAgeSeconds > 15 && !hasUsableCards) {
      lastLiveHeroText = "";
      lastLiveBoardText = "";
      lastLiveCardsStatus = lastLiveHeroText
        ? `Livekort: ${lastLiveHeroText}${lastLiveBoardText ? ` / board ${lastLiveBoardText}` : ""}`
        : "Livekort: venter på fersk skjermlesing.";
      pendingScreenHeroText = "";
      pendingScreenHeroCount = 0;
      liveScreenActive = false;
      return false;
    }

    if (isScreenSource && !hasUsableCards) {
      const autoStatus = $("autoEquityStatus");
      lastLiveHeroText = "";
      lastLiveBoardText = "";
      const confirmingNewRead = String(cardsData.error || "").includes("confirming_new_read");
      lastLiveCardsStatus = confirmingNewRead
        ? "Livekort: bekrefter nytt skjermkort."
        : `Livekort: lesefeil${cardsData.error ? ` (${cardsData.error})` : ""}`;
      pendingScreenHeroText = "";
      pendingScreenHeroCount = 0;
      liveScreenActive = false;
      if (autoStatus) autoStatus.innerText = confirmingNewRead ? "Live: bekrefter skjermkort." : "Live: venter på kort.";
      return false;
    }

    pendingScreenHeroText = "";
    pendingScreenHeroCount = 0;

    liveScreenActive = hasUsableCards;
    if (validLiveHero) {
      if (heroText !== lastLiveHeroText && (!boardText || !validLiveBoard)) {
        lastLiveBoardText = "";
      }
      lastLiveHeroText = heroText;
      lastLiveCardsSeenAt = Date.now();
      lastLiveCardsStatus = `Livekort: ${heroText}`;
      console.log("Live screen hero cards read:", heroText);
    }

    if (boardText && validLiveBoard) {
      lastLiveBoardText = boardText;
      lastLiveCardsSeenAt = Date.now();
      lastLiveCardsStatus = `Livekort: ${heroText || "-"} / board ${boardText}`;
      console.log("Live screen board read:", boardText);
    }

    if (validLiveHero || (Boolean(boardText) && validLiveBoard)) {
      const autoStatus = $("autoEquityStatus");
      if (autoStatus) {
        const liveParts = [];
        if (lastLiveHeroText) liveParts.push(lastLiveHeroText);
        if (lastLiveBoardText) liveParts.push(`board ${lastLiveBoardText}`);
        autoStatus.innerText = liveParts.length ? `Livekort: ${liveParts.join(" / ")}` : "Live: venter på kort.";
      }
      if (validLiveHero) {
        scheduleAutoEquity({
          live: true,
          heroText,
          boardText: validLiveBoard ? boardText : undefined
        });
      }
    }

    return validLiveHero || (Boolean(boardText) && validLiveBoard);
  } catch (e) {
    console.warn("Could not read current_live_cards.json");
    lastLiveHeroText = "";
    lastLiveBoardText = "";
    lastLiveCardsStatus = "Livekort: kunne ikke hente skjermlesing.";
    liveScreenActive = false;
    return false;
  }
}

async function pollCurrentGame() {

  if (pollInProgress) {
    console.log("â­ï¸ Skipping poll - previous still running");
    return;
  }

  pollInProgress = true;

  try {
console.time("latest-with-stats");

const controller = new AbortController();
const timeout = setTimeout(() => controller.abort("Timeout after 6s"), 6000);

console.log("ðŸš€ BEFORE race");
let res;
try {
  res = await fetch(`${apiBase()}/hands/latest/with-adaptive-stats`, { signal: controller.signal });
} finally {
  clearTimeout(timeout);
}
console.log("âœ… AFTER race");

console.timeEnd("latest-with-stats");
      
      if (!res.ok) {
        console.warn(`âš ï¸ /hands/latest/with-adaptive-stats returned ${res.status}, skipping`);
        return;
      }
      
      const data = await res.json();
      console.log("ðŸ“¡ got adaptive stats:", data);
      lastGameState = {
        hero: lastGameState.hero || "",
        board: data.board || lastGameState.board || "",
        hand_id: data.hand_id || lastGameState.hand_id || "",
        session_id: data.session_id || lastGameState.session_id || "",
        session_code: data.session_code || lastGameState.session_code || ""
      };
      if (data?.session_id) syncActiveSessionFields(data.session_id, "poll");
      await applyLiveScreenCards();

      // Sjekk om board har endra
      if (false && !data.board) {
        console.log("ðŸ“¡ no board yet, skipping");
        return;
      }
      
      // Manual entry is the source of truth for hero/board. Polling only updates players/ranges.
      
      // AUTO-FILL VILLAINS BASERT PÃ… ADAPTIVE STATS
      if (data.players && data.players.length > 0) {
        // ===== OPPDATER DATALIST MED SPILLERNAVN =====
        const datalist = $("boardPlayersDatalist");
        if (datalist) {
          mergeKnownPlayerNames(data.players.map(p => p.name));
          console.log("âœ… Updated player datalist with:", data.players.map(p => p.name).join(", "));
        }
        
        // ===== AUTO-FYLLE SPILLER-FELTENE MED FÃ˜RSTE SPILLER =====
        const heroName = String(dashHero?.() || "angryshark").trim().toLowerCase();
        const firstPlayer = data.players
          .map(p => String(p.name || p.player_name || "").trim())
          .find(name => name && name.toLowerCase() !== heroName)
          || String(data.players[0]?.name || data.players[0]?.player_name || "").trim();
        if (firstPlayer) {
          const playerFields = ["mtPlayer", "spPlayer", "ppPlayer", "lhPlayer"];
          playerFields.forEach(fieldId => {
            const field = $(fieldId);
            const current = String(field?.value || "").trim().toLowerCase();
            if (field && (!current || current === heroName || current === "angryshark")) {
              field.value = firstPlayer;
              console.log(`âœ… Auto-set ${fieldId} to ${firstPlayer}`);
            }
          });
        }
        
        // Lag comma-separated list av ranges fra alle motspillere
        const villainsList = data.players
          .filter(p => p.suggested_range)
          .map(p => p.suggested_range)
          .join(", ");
        
        if (villainsList) {
          console.log("Adaptive ranges read, setup inputs left unchanged");
        }
        
        // VIS MOTSPILLER-INFO I CONSOLE
        console.log("ðŸŽ¯ ADAPTIVE MOTSPILLERE VED BORDET:");
        data.players.forEach(p => {
          console.log(`  ${p.name}: ${p.player_type.toUpperCase()} (VPIP=${p.vpip_pct.toFixed(1)}%, PFR=${p.pfr_pct.toFixed(1)}%) â†’ Range: ${p.suggested_range}`);
        });
        
        // Vis spillerne ved bordet som klikkbare motspillere.
        const playerDetailsEl = $("adaptivePlayerDetails");
        if (playerDetailsEl) {
          const players = data.players
            .map(p => ({ ...p, name: String(p.name || p.player_name || "").trim() }))
            .filter(p => p.name);
          let html = "<div style='font-size:11px; opacity:.9;'>";
          html += "<div style='font-weight:700; margin-bottom:6px;'>Motspillere ved bordet</div>";
          players.forEach(p => {
            const typeColor = { "nit": "#4CAF50", "tag": "#2196F3", "lag": "#FF9800", "fish": "#f44336", "unknown": "#999" }[p.player_type] || "#999";
            const vpip = Number(p.vpip_pct || 0).toFixed(1);
            const pfr = Number(p.pfr_pct || 0).toFixed(1);
            html += `<div style='margin:4px 0; padding:6px; background:#fff; border:1px solid #eee; border-left:3px solid ${typeColor}; border-radius:4px;'>
              <button type="button" class="tablePlayerProfileBtn" data-player="${escapeHtml(p.name)}" style="font-weight:700; color:#0b66c3; background:transparent; border:0; padding:0; cursor:pointer; text-decoration:underline;">
                ${escapeHtml(p.name)}
              </button>
              <span style="opacity:.75;">${escapeHtml(String(p.player_type || "unknown").toUpperCase())}</span>
              <span style="opacity:.75;">VPIP ${vpip}% / PFR ${pfr}% / ${Number(p.hands_played || 0)} hender</span>
            </div>`;
          });
          html += "</div>";
          playerDetailsEl.innerHTML = html;
          playerDetailsEl.querySelectorAll(".tablePlayerProfileBtn").forEach(btn => {
            btn.addEventListener("click", () => openPlayerProfileFromTable(btn.getAttribute("data-player")));
          });
        }
      }
    
    
      
      // AUTO-UPDATE HAND_ID IN LIVE COACH IF NEW HAND DETECTED
const previousHandId = lastGameState.hand_id;

// AUTO-UPDATE HAND_ID IN LIVE COACH IF NEW HAND DETECTED
if (data.hand_id && data.hand_id !== previousHandId) {
  lastManualBoardText = "";
  lastLiveBoardText = "";
  await autoLoadCurrentHandFeatures(data);
  if (data.session_id) syncActiveSessionFields(data.session_id, "new-hand");
  scheduleStartingHandsRefresh("new-hand", `hand-${data.hand_id}`);
  console.log(`Auto-updated current-hand features for hand_id: ${data.hand_id}`);
}

lastGameState = {
  hero: lastGameState.hero || "",
  board: data.board || lastGameState.board || "",
  hand_id: data.hand_id || "",
  session_id: data.session_id || "",
  session_code: data.session_code || lastGameState.session_code || ""
};

await applyLiveScreenCards();

} catch (err) {
  console.warn("âš ï¸ pollCurrentGame error:", err.message);
} finally {
  pollInProgress = false;
}
  }

  function startLiveGamePolling() {
    manualLiveMode = false;
    liveScreenActive = false;
    lastLiveCardsStatus = "Livekort: venter på kort.";
    // Stopp eventuelle eksisterande polling
    if (currentGamePoller) {
      clearInterval(currentGamePoller);
      currentGamePoller = null;
    }
    console.log(`Starting live polling...`);
    
    const autoStatus = $("autoEquityStatus");
    if (autoStatus) autoStatus.innerText = "Live: venter på kort.";
    

// Bruk setInterval - det er meir reliable

pollCurrentGame();

currentGamePoller = setInterval(() => {
  try {
    console.log("ðŸ“¡ INTERVAL TICK - calling pollCurrentGame");

    pollCurrentGame().catch(err => {
      console.error("âŒ pollCurrentGame error:", err);
    });

  } catch (err) {
    console.error("âŒ ERROR in interval:", err);
  }
}, 3000);

if (startingHandsFallbackTimer) clearInterval(startingHandsFallbackTimer);
startingHandsFallbackTimer = setInterval(() => {
  scheduleStartingHandsRefresh("live-fallback", `fallback-${Math.floor(Date.now() / 15000)}`);
}, 15000);

    }

  function stopLiveGamePolling() {
    manualLiveMode = false;
    liveScreenActive = false;
    lastLiveCardsStatus = "Livekort: polling av.";
    if (currentGamePoller) {
      clearInterval(currentGamePoller);
      currentGamePoller = null;
      console.log(`Stopped live polling`);
    }
    if (startingHandsFallbackTimer) {
      clearInterval(startingHandsFallbackTimer);
      startingHandsFallbackTimer = null;
    }
    const btnStart = $("btnStartLiveGame");
    const btnStop = $("btnStopLiveGame");
    if (btnStart) btnStart.style.display = "block";
    if (btnStop) btnStop.style.display = "none";
    const status = $("liveGameStatus");
    if (status) status.innerText = "Ikke aktiv";
    const autoStatus = $("autoEquityStatus");
    if (autoStatus) autoStatus.innerText = "Live polling av";
  }

  const startLiveButton = $("btnStartLiveGame");
  const stopLiveButton = $("btnStopLiveGame");
  if (startLiveButton) startLiveButton.innerText = "Start Live Polling";
  if (stopLiveButton) stopLiveButton.innerText = "Stop Live Polling";
  const manualLiveBox = startLiveButton?.parentElement?.parentElement;
  const manualLiveTitle = manualLiveBox?.firstElementChild;
  const manualLiveHelp = manualLiveBox?.lastElementChild;
  if (manualLiveTitle) manualLiveTitle.innerText = "Live Polling";
  if (manualLiveHelp) {
    manualLiveHelp.innerText = "Kortleseren kan vise livekort og motspillere når du starter den. Historikk hentes separat fra databasen.";
  }

  // Event listeners for live polling buttons
  $("btnStartLiveGame")?.addEventListener("click", () => {
    console.log("START LIVE POLLING BUTTON CLICKED");
    startLiveGamePolling();
    const btnStart = $("btnStartLiveGame");
    const btnStop = $("btnStopLiveGame");
    if (btnStart) btnStart.style.display = "none";
    if (btnStop) btnStop.style.display = "block";
    const status = $("liveGameStatus");
    if (status) status.innerText = "Live polling aktiv - kortleseren leser hele tiden.";
    console.log("Live polling button updated, polling should be running");
  });

  $("btnStopLiveGame")?.addEventListener("click", () => {
    stopLiveGamePolling();
  });

  if (startLiveButton) startLiveButton.style.display = "block";
  if (stopLiveButton) stopLiveButton.style.display = "none";
  const liveStatus = $("liveGameStatus");
  if (liveStatus) liveStatus.innerText = "Ikke aktiv";

  $("btnSessionInsights")?.addEventListener("click", loadSessionInsights);

  console.log("script.js loaded âœ…");
});

