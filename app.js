let DATA = null;
let currentView = "overview"; // "overview" or a station name
let granularity = "60"; // "30" or "60"
const openSlots = new Set();

const $app = document.getElementById("app");
const $tabs = document.getElementById("tabs");

function shortName(g){ return g.replace("Paris ", ""); }

function badgeClass(type){
  if(type.includes("TGV INOUI")) return "tgv";
  if(type.includes("OUIGO")) return "ouigo";
  if(type.includes("Intercités de nuit")) return "icn";
  if(type.includes("Intercités")) return "ic";
  if(type.includes("Eurostar (Londres)")) return "eurostar";
  if(type.includes("International") || type.includes("Lyria") || type.includes("ICE")) return "intl";
  return "";
}

function fmtDate(iso){
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}

async function loadData(){
  try {
    const res = await fetch("data.json", { cache: "no-store" });
    if(!res.ok) throw new Error("HTTP " + res.status);
    DATA = await res.json();
    document.getElementById("app-date").textContent = fmtDate(DATA.date);
    renderTabs();
    render();
  } catch (err) {
    document.getElementById("app-date").textContent = "Erreur de chargement";
    $app.innerHTML = `
      <div style="padding:30px 16px;text-align:center;color:#767680;">
        <p style="font-weight:700;color:#20212a;margin-bottom:8px;">Impossible de charger les données</p>
        <p style="font-size:13px;">Le fichier <code>data.json</code> est introuvable à côté de <code>index.html</code>
        sur ton dépôt GitHub. Vérifie qu'il a bien été uploadé au même niveau que les autres fichiers
        (pas dans un sous-dossier).</p>
        <p style="font-size:11px;margin-top:10px;color:#a0a0a8;">Détail technique : ${err.message}</p>
      </div>
    `;
  }
}

function renderTabs(){
  $tabs.innerHTML = "";
  const overviewBtn = document.createElement("button");
  overviewBtn.textContent = "Vue d'ensemble";
  overviewBtn.className = currentView === "overview" ? "active" : "";
  overviewBtn.onclick = () => { currentView = "overview"; renderTabs(); render(); };
  $tabs.appendChild(overviewBtn);

  DATA.stations.forEach(g => {
    const b = document.createElement("button");
    b.textContent = shortName(g);
    b.className = currentView === g ? "active" : "";
    b.onclick = () => { currentView = g; openSlots.clear(); renderTabs(); render(); };
    $tabs.appendChild(b);
  });
}

function sparkBars(slots60, max){
  return slots60.map(s => {
    const h = max > 0 ? Math.max(2, Math.round((s.count / max) * 32)) : 2;
    const cls = s.count === 0 ? "zero" : "";
    return `<i class="${cls}" style="height:${h}px" title="${s.start} : ${s.count}"></i>`;
  }).join("");
}

function render(){
  if(currentView === "overview") renderOverview();
  else renderStation(currentView);
  window.scrollTo(0, 0);
}

function renderOverview(){
  const g = DATA.global;
  let html = `
    <div class="global-card">
      <div class="big">${g.totalAll}</div>
      <div class="lbl">arrivées grandes lignes aujourd'hui — 6 gares</div>
      <div class="txt">${g.text}</div>
    </div>
    <div class="section-title">Par gare — du plus au moins chargé</div>
  `;

  DATA.stations.slice().sort((a,b) => DATA.summary[b].total - DATA.summary[a].total).forEach(gare => {
    const summ = DATA.summary[gare];
    const slots60 = DATA.slots60[gare];
    const max = Math.max(...slots60.map(s => s.count));
    const best = summ.bestHour[0];
    html += `
      <div class="gare-card" data-gare="${gare}">
        <div class="row-top">
          <div class="name">${shortName(gare)}</div>
          <div class="total">${summ.total} <span>arrivées</span></div>
        </div>
        <div class="spark">${sparkBars(slots60, max)}</div>
        <div class="best">
          ${best ? `<span class="pill">🕐 Pic : ${best.start}–${best.end} (${best.count})</span>` : `<span class="pill muted">Aucune arrivée</span>`}
        </div>
      </div>
    `;
  });

  $app.innerHTML = html;
  $app.querySelectorAll(".gare-card").forEach(card => {
    card.onclick = () => {
      currentView = card.dataset.gare;
      openSlots.clear();
      renderTabs();
      render();
    };
  });
}

function renderStation(gare){
  const summ = DATA.summary[gare];
  const slots = granularity === "30" ? DATA.slots30[gare] : DATA.slots60[gare];

  let bestRow = "";
  const bestList = granularity === "30" ? summ.bestHalfHour : summ.bestHour;
  bestList.forEach((s, i) => {
    bestRow += `<span class="pill">${i === 0 ? "🥇" : i === 1 ? "🥈" : "🥉"} ${s.start}–${s.end} · ${s.count} arrivées</span>`;
  });

  let html = `
    <div class="detail-header">
      <h2>${shortName(gare)}</h2>
      <div class="sub">${summ.total} arrivées grandes lignes prévues aujourd'hui</div>
      <div class="txt">${summ.text}</div>
      <div class="best-row">${bestRow}</div>
      <div class="toggle">
        <button data-g="60" class="${granularity === "60" ? "active" : ""}">Par heure</button>
        <button data-g="30" class="${granularity === "30" ? "active" : ""}">Par 30 min</button>
      </div>
    </div>
    <div class="legend">
      <span class="pill" style="background:#e1ecff;color:#0f4fb3;border-color:#c7dcff;">TGV INOUI</span>
      <span class="pill" style="background:#ffe1ee;color:#b3105f;border-color:#ffc7e0;">OUIGO</span>
      <span class="pill" style="background:#dff5e6;color:#137a38;border-color:#c3ecd0;">Intercités</span>
      <span class="pill" style="background:#eee0ff;color:#6a1fc9;border-color:#ddc7ff;">Lyria / ICE</span>
      <span class="pill" style="background:#ffe08a;color:#6e4600;border-color:#f0c95a;">Eurostar Londres</span>
    </div>
  `;

  slots.forEach(s => {
    const key = gare + "|" + s.start;
    const isOpen = openSlots.has(key);
    const hot = s.count >= 4 ? "hot" : "";
    html += `
      <div class="slot ${s.count === 0 ? "empty" : ""} ${isOpen ? "open" : ""}" data-key="${key}">
        <div class="slot-head">
          <div class="range">${s.start} – ${s.end}</div>
          <div class="count ${hot}">${s.count} train${s.count > 1 ? "s" : ""}</div>
        </div>
        <div class="slot-body">
          ${s.trains.map(t => `
            <div class="trow ${t.type === "Eurostar (Londres)" ? "eurostar-row" : ""}">
              <div class="h">${t.heure}</div>
              <div class="num">${t.numero}</div>
              <span class="badge ${badgeClass(t.type)}">${t.type}</span>
              <div class="orig">${t.origine}</div>
            </div>
          `).join("")}
        </div>
      </div>
    `;
  });

  $app.innerHTML = html;

  $app.querySelectorAll(".toggle button").forEach(b => {
    b.onclick = () => { granularity = b.dataset.g; openSlots.clear(); render(); };
  });

  $app.querySelectorAll(".slot").forEach(el => {
    el.querySelector(".slot-head").onclick = () => {
      const key = el.dataset.key;
      if(openSlots.has(key)) openSlots.delete(key);
      else openSlots.add(key);
      el.classList.toggle("open");
    };
  });
}

// PWA install prompt
let deferredPrompt = null;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  deferredPrompt = e;
  document.getElementById("install-btn").classList.add("show");
});
document.getElementById("install-btn").addEventListener("click", async () => {
  if(!deferredPrompt) return;
  deferredPrompt.prompt();
  await deferredPrompt.userChoice;
  deferredPrompt = null;
  document.getElementById("install-btn").classList.remove("show");
});

if("serviceWorker" in navigator){
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("service-worker.js").catch(() => {});
  });
}

loadData();
