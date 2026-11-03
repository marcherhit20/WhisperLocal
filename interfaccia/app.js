"use strict";

// WhisperLocal — logica della pagina locale.
// Tutto il testo arriva dal server su 127.0.0.1 e viene inserito con textContent, mai come HTML.

const ESTENSIONI = [".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".wma", ".aif", ".aiff",
  ".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".mpeg", ".mpg", ".3gp"];
const SEZIONI = [
  { chiave: "allucinazione", nome: "Allucinazioni" },
  { chiave: "alta", nome: "Alta" },
  { chiave: "bassa", nome: "Bassa" },
];
const GRAVITA = { bassa: 1, alta: 2, allucinazione: 3 };
const ETICHETTE_STATO = { "in coda": "In coda", "in corso": "In corso", finito: "Completata", errore: "Errore", annullato: "Annullata" };

const $ = (id) => document.getElementById(id);
// "mac" o "windows": lo dice il server (/api/ping); cambia solo nomi di tasti e programmi
let sistema = "mac";
const tasto = (lettera) => (sistema === "mac" ? `⌘${lettera}` : `Ctrl+${lettera}`);

// ---------------------------------------------------------------- utilità

function el(tag, proprieta = {}, ...figli) {
  const nodo = document.createElement(tag);
  for (const [k, v] of Object.entries(proprieta)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") nodo.className = v;
    else if (k === "text") nodo.textContent = v;
    else if (k.startsWith("on")) nodo.addEventListener(k.slice(2), v);
    else if (typeof v !== "string" && k in nodo) nodo[k] = v;
    else nodo.setAttribute(k, v === true ? "" : v);
  }
  for (const f of figli.flat()) if (f !== null && f !== undefined && f !== false) nodo.append(f);
  return nodo;
}

async function api(percorso, opzioni = {}) {
  let risposta;
  try {
    risposta = await fetch(percorso, opzioni);
  } catch {
    throw new Error("Il server non risponde: la finestra di WhisperLocal (Terminale o Prompt dei comandi) è ancora aperta?");
  }
  const testo = await risposta.text();
  let dati = null;
  try { dati = JSON.parse(testo); } catch { /* risposta non JSON */ }
  if (!risposta.ok) throw new Error((dati && dati.errore) || testo || `Errore ${risposta.status}`);
  return dati;
}

function invia(percorso, corpo = {}) {
  return api(percorso, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corpo) });
}

let timerAvviso;
function avviso(testo, tipo = "") {
  const n = $("avviso");
  n.textContent = testo;
  n.className = "avviso " + tipo;
  n.hidden = false;
  clearTimeout(timerAvviso);
  timerAvviso = setTimeout(() => (n.hidden = true), tipo === "errore" ? 8000 : 4000);
}

const due = (n) => String(n).padStart(2, "0");

// Stesso formato di da_verificare.txt: mm:ss oppure h:mm:ss
function tempo(s) {
  s = Math.max(0, Math.floor(s || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h ? `${h}:${due(m)}:${due(s % 60)}` : `${due(m)}:${due(s % 60)}`;
}

function durata(s) {
  if (s === null || s === undefined) return "?";
  s = Math.floor(s); // come il riepilogo del run.log
  if (s < 60) return `${s} s`;
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h ? `${h} h ${due(m)} min` : `${m} min ${due(s % 60)} s`;
}

const circa = (s) => `circa ${Math.max(1, Math.round(s / 60))} min`;

function dimensione(byte) {
  const [valore, unita] = byte >= 1e9 ? [byte / 1e9, "GB"] : [Math.max(0.1, byte / 1e6), "MB"];
  return `${valore.toFixed(1).replace(".", ",")} ${unita}`;
}

function dataLeggibile(d) {
  if (!d) return "";
  const x = new Date(d.replace(" ", "T"));
  if (isNaN(x)) return d;
  return x.toLocaleString("it-IT", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function conteggi(punti, corretta) {
  const nodi = [];
  if (punti) {
    if (punti.allucinazioni) {
      nodi.push(el("span", { class: "conteggio allucinazione",
        text: `⚠ ${punti.allucinazioni} ${punti.allucinazioni === 1 ? "allucinazione" : "allucinazioni"}` }));
    }
    nodi.push(el("span", { class: "conteggio alta", text: `${punti.alta} priorità alta` }));
    nodi.push(el("span", { class: "conteggio bassa", text: `${punti.bassa} priorità bassa` }));
  }
  if (corretta) nodi.push(el("span", { class: "conteggio corretta", text: "✓ corretta" }));
  return el("span", { class: "conteggi" }, nodi);
}

// ---------------------------------------------------------------- navigazione

let vistaCorrente = null;
let hashCorrente = null;
let ignoraCambio = false;

function instrada() {
  const h = location.hash || "#/";
  if (ignoraCambio) {
    ignoraCambio = false;
    return;
  }
  if (vistaCorrente === "editor" && editor.modificato && h !== hashCorrente) {
    if (!confirm("Ci sono correzioni non salvate. Uscire comunque?")) {
      ignoraCambio = true;
      location.hash = hashCorrente;
      return;
    }
    editor.modificato = false;
  }
  hashCorrente = h;
  if (h.startsWith("#/t/")) mostra("editor", () => apriEditor(decodeURIComponent(h.slice(4))));
  else if (h === "#/archivio") mostra("archivio", caricaArchivio);
  else mostra("trascrivi");
}

function mostra(vista, poi) {
  vistaCorrente = vista;
  for (const v of ["trascrivi", "archivio", "editor"]) $("vista-" + v).hidden = v !== vista;
  document.querySelectorAll(".navigazione a").forEach((a) => a.classList.toggle("attiva", a.dataset.vista === vista));
  if (vista !== "editor") {
    $("audio").pause();
    titoloBase = "WhisperLocal";
  }
  aggiornaIndicatore();
  if (poi) poi();
}

// ---------------------------------------------------------------- nuova trascrizione

const scelti = [];
const avanzamentoCaricamento = new Map();
let caricamentoInCorso = false;

$("diarize").addEventListener("change", () => {
  const attivo = $("diarize").checked;
  $("campo-speakers").hidden = !attivo;
  $("speakers").disabled = !attivo;
  $("diarize").setAttribute("aria-expanded", String(attivo));
});

function aggiungiFile(lista) {
  for (const f of lista) {
    const estensione = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
    if (!ESTENSIONI.includes(estensione)) {
      avviso(`«${f.name}» non sembra un file audio o video.`, "errore");
      continue;
    }
    if (!scelti.some((s) => s.name === f.name && s.size === f.size)) scelti.push(f);
  }
  disegnaScelti();
}

function disegnaScelti() {
  $("file-scelti").replaceChildren(...scelti.map((f, i) => {
    const parte = avanzamentoCaricamento.get(f);
    let coda;
    if (parte !== undefined) {
      const barra = el("div", { class: "barra" }, el("div"));
      barra.firstChild.style.width = `${Math.round(parte * 100)}%`;
      coda = [barra, el("small", { text: `caricamento ${Math.round(parte * 100)}%` })];
    } else {
      coda = [
        el("small", { text: dimensione(f.size) }),
        caricamentoInCorso ? null : el("button", { class: "leggero", text: "Rimuovi",
          onclick: () => { scelti.splice(i, 1); disegnaScelti(); } }),
      ];
    }
    return el("li", {}, el("span", { class: "nome", text: f.name }), coda);
  }));
  $("avvia").disabled = scelti.length === 0 || caricamentoInCorso;
}

function caricaFile(file, parole, senzaVerifica, diarize, speakers, progresso) {
  // XMLHttpRequest invece di fetch: serve l'avanzamento del caricamento per i file grandi
  return new Promise((risolvi, rifiuta) => {
    const dati = new FormData();
    dati.append("parole", parole);
    dati.append("senza_verifica", senzaVerifica ? "1" : "0");
    dati.append("diarize", diarize ? "1" : "0");
    dati.append("speakers", diarize ? speakers : "");
    dati.append("file", file, file.name);
    const richiesta = new XMLHttpRequest();
    richiesta.open("POST", "/api/carica");
    richiesta.upload.onprogress = (e) => e.lengthComputable && progresso(e.loaded / e.total);
    richiesta.onload = () => {
      let risposta = {};
      try { risposta = JSON.parse(richiesta.responseText); } catch { /* non JSON */ }
      if (richiesta.status < 300) risolvi(risposta);
      else rifiuta(new Error(risposta.errore || richiesta.responseText || `Errore ${richiesta.status}`));
    };
    richiesta.onerror = () => rifiuta(new Error("Caricamento non riuscito: la finestra di WhisperLocal (Terminale o Prompt dei comandi) è ancora aperta?"));
    richiesta.send(dati);
  });
}

async function avviaTrascrizioni() {
  if (caricamentoInCorso || !scelti.length) return;
  if ($("diarize").checked && !$("speakers").reportValidity()) return;
  caricamentoInCorso = true;
  const parole = $("parole").value;
  const senzaVerifica = $("senza-verifica").checked;
  const diarize = $("diarize").checked;
  const speakers = $("speakers").value;
  try {
    while (scelti.length) {
      const file = scelti[0];
      avanzamentoCaricamento.set(file, 0);
      disegnaScelti();
      await caricaFile(file, parole, senzaVerifica, diarize, speakers, (parte) => {
        avanzamentoCaricamento.set(file, parte);
        disegnaScelti();
      });
      avanzamentoCaricamento.delete(file);
      scelti.shift();
      disegnaScelti();
      aggiornaStato();
    }
    // I termini valgono per queste registrazioni: non riusarli per sbaglio con le prossime
    $("parole").value = "";
    $("senza-verifica").checked = false;
    $("diarize").checked = false;
    $("diarize").dispatchEvent(new Event("change"));
    $("speakers").value = "2";
  } catch (e) {
    avviso(e.message, "errore");
    avanzamentoCaricamento.clear();
  } finally {
    caricamentoInCorso = false;
    disegnaScelti();
  }
}

// ---------------------------------------------------------------- lavori

const nodiLavori = new Map();
const statiVisti = new Map();
let ultimiLavori = [];
let serverRaggiungibile = true;
let titoloBase = "WhisperLocal";
let timerStato;

function creaLavoro(l) {
  const n = { ultimoStato: null };
  n.stato = el("span", { class: "etichetta-stato" });
  n.apri = el("button", { class: "primario", text: "Apri", onclick: () => (location.hash = "#/t/" + encodeURIComponent(n.cartella)) });
  n.annulla = el("button", { class: "pericolo", text: "Annulla", onclick: () => annullaLavoro(l.id, l.nome) });
  n.dettaglio = el("div", { class: "dettaglio" });
  n.barra = el("div", { class: "barra" }, el("div"));
  n.conteggi = el("div");
  n.errore = el("div", { class: "errore" });
  n.log = el("pre");
  n.details = el("details", {}, el("summary", { text: "Dettagli tecnici" }), n.log);
  n.radice = el("li", { class: "lavoro" },
    el("div", { class: "intestazione" }, el("span", { class: "nome", text: l.nome }), n.stato, n.apri, n.annulla),
    n.dettaglio, n.barra, n.conteggi, n.errore, n.details);
  return n;
}

function aggiornaLavoro(n, l) {
  n.cartella = l.cartella;
  n.stato.textContent = ETICHETTE_STATO[l.stato] || l.stato;
  n.stato.className = "etichetta-stato " + l.stato.replace(" ", "-");
  n.annulla.hidden = !(l.stato === "in coda" || l.stato === "in corso");
  n.apri.hidden = !(l.stato === "finito" && l.cartella);
  n.barra.hidden = l.stato !== "in corso";
  n.barra.firstChild.style.width = `${l.complessivo}%`;

  let testo = "";
  if (l.stato === "in coda") {
    testo = `In attesa · audio ${durata(l.durata)}` + (l.previsto ? ` · tempo previsto ${circa(l.previsto)}` : "");
  } else if (l.stato === "in corso") {
    const fase = l.percentuale !== null ? `${l.fase} ${Math.round(l.percentuale)}%` : l.fase;
    testo = `Passo ${l.passo} di ${l.passi} (${l.passo_nome}) — ${fase} · trascorsi ${tempo(l.trascorso)}`
      + (l.previsto ? ` su ${circa(l.previsto)}` : "");
  } else if (l.stato === "finito") {
    testo = `Audio ${durata(l.durata)} · completata in ${durata(l.trascorso)}`
      + (l.verifica ? "" : " · senza verifica");
  }
  if (testo && l.diarize) testo += l.speakers ? ` · ${l.speakers} interlocutori` : " · interlocutori automatici";
  n.dettaglio.textContent = testo;
  n.dettaglio.hidden = !testo;
  n.conteggi.replaceChildren(l.stato === "finito" && l.punti ? conteggi(l.punti) : "");
  n.errore.hidden = l.stato !== "errore";
  n.errore.textContent = l.errore || "";

  const log = l.righe.join("\n");
  if (n.log.textContent !== log) {
    const inFondo = n.log.scrollTop + n.log.clientHeight >= n.log.scrollHeight - 4;
    n.log.textContent = log;
    if (inFondo) n.log.scrollTop = n.log.scrollHeight;
  }
  if (l.stato === "errore" && n.ultimoStato !== "errore") n.details.open = true;
  n.ultimoStato = l.stato;
}

function disegnaLavori(lavori) {
  const ordinati = [...lavori].reverse(); // i più recenti in alto
  for (const l of ordinati) {
    if (!nodiLavori.has(l.id)) nodiLavori.set(l.id, creaLavoro(l));
    aggiornaLavoro(nodiLavori.get(l.id), l);
  }
  const ul = $("lavori");
  const ordine = ordinati.map((l) => l.id).join(",");
  // Reinserire i nodi azzererebbe lo scorrimento dei dettagli: solo se l'ordine cambia
  if (ul.dataset.ordine !== ordine) {
    ul.replaceChildren(...ordinati.map((l) => nodiLavori.get(l.id).radice));
    ul.dataset.ordine = ordine;
  }
  $("nessun-lavoro").hidden = lavori.length > 0;
}

async function aggiornaStato() {
  clearTimeout(timerStato);
  let attivi = false;
  try {
    const { lavori } = await api("/api/stato");
    serverRaggiungibile = true;
    ultimiLavori = lavori;
    disegnaLavori(lavori);
    for (const l of lavori) {
      const prima = statiVisti.get(l.id);
      if (prima && prima !== l.stato) {
        if (l.stato === "finito") {
          avviso(`Trascrizione completata: ${l.nome}`);
          if (vistaCorrente === "archivio") caricaArchivio();
        } else if (l.stato === "errore") {
          avviso(`Trascrizione non riuscita: ${l.nome}`, "errore");
        }
      }
      statiVisti.set(l.id, l.stato);
    }
    attivi = lavori.some((l) => l.stato === "in corso" || l.stato === "in coda");
  } catch {
    serverRaggiungibile = false;
  }
  aggiornaIndicatore();
  timerStato = setTimeout(aggiornaStato, attivi ? 1000 : 4000);
}

function aggiornaIndicatore() {
  const indicatore = $("indicatore");
  const inCorso = ultimiLavori.find((l) => l.stato === "in corso");
  const inCoda = ultimiLavori.filter((l) => l.stato === "in coda").length;
  indicatore.classList.toggle("errore", !serverRaggiungibile);
  if (!serverRaggiungibile) {
    indicatore.hidden = false;
    indicatore.textContent = "Server chiuso: riapri WhisperLocal";
  } else {
    indicatore.hidden = !inCorso || vistaCorrente === "trascrivi";
    if (inCorso) {
      indicatore.textContent = `In corso: ${inCorso.nome} · ${Math.round(inCorso.complessivo)}%`
        + (inCoda ? ` · ${inCoda} in coda` : "");
    }
  }
  document.title = (inCorso && serverRaggiungibile ? `${Math.round(inCorso.complessivo)}% · ` : "") + titoloBase;
}

async function annullaLavoro(id, nome) {
  if (!confirm(`Annullare la trascrizione di «${nome}»?`)) return;
  try {
    await invia(`/api/annulla/${id}`);
  } catch (e) {
    avviso(e.message, "errore");
  }
  aggiornaStato();
}

// ---------------------------------------------------------------- archivio

function descriviFile(nome) {
  if (nome === "da_verificare.txt") return "punti da riascoltare";
  if (nome === "da_verificare.json") return "punti da riascoltare (dati)";
  if (nome === "run.log") return "registro tecnico";
  const corretto = /_corretto\.[^.]+$/.test(nome);
  const tipo = { txt: "testo", srt: "sottotitoli", vtt: "sottotitoli web", tsv: "tabella", json: "dati completi" }[
    nome.split(".").pop().toLowerCase()] || "";
  return corretto ? `${tipo}, corretto` : tipo;
}

// Prima le versioni corrette, poi testo e sottotitoli, in fondo i file tecnici
function ordineFile(nome) {
  const estensione = nome.split(".").pop().toLowerCase();
  const gruppo = nome.includes("_corretto.") ? 0 : nome.startsWith("da_verificare") ? 2 : nome === "run.log" ? 3 : 1;
  const posizione = ["txt", "srt", "vtt", "tsv", "json"].indexOf(estensione);
  return gruppo * 10 + (posizione < 0 ? 9 : posizione);
}

function voceArchivio(t) {
  const percorso = "/api/trascrizioni/" + encodeURIComponent(t.cartella);
  const meta = [dataLeggibile(t.data), t.durata != null && `audio ${durata(t.durata)}`, t.modello,
    t.parole && "con nomi e termini"].filter(Boolean).join(" · ");
  const menu = el("details", { class: "menu" }, el("summary", { text: "Scarica" }),
    el("ul", {}, [...t.file].sort((a, b) => ordineFile(a) - ordineFile(b)).map((nome) => el("li", {},
      el("a", { href: `${percorso}/file/${encodeURIComponent(nome)}`, download: nome },
        el("span", { text: nome }), el("small", { text: descriviFile(nome) }))))));
  return el("li", { class: "voce-archivio" },
    el("div", { class: "testo" },
      el("div", { class: "nome", text: t.nome }),
      el("div", { class: "meta", text: meta }),
      conteggi(t.punti, t.corretto)),
    el("div", { class: "comandi" },
      el("button", { class: "primario", text: "Apri", onclick: () => (location.hash = "#/t/" + encodeURIComponent(t.cartella)) }),
      menu,
      el("button", { text: sistema === "windows" ? "Mostra in Esplora risorse" : "Mostra nel Finder", onclick: () => invia(`${percorso}/mostra`).catch((e) => avviso(e.message, "errore")) })));
}

async function caricaArchivio() {
  let dati;
  try {
    dati = await api("/api/trascrizioni");
  } catch (e) {
    avviso(e.message, "errore");
    return;
  }
  $("archivio-vuoto").hidden = dati.trascrizioni.length > 0;
  $("archivio").replaceChildren(...dati.trascrizioni.map(voceArchivio));
}

// Un menu Scarica aperto si chiude cliccando altrove
document.addEventListener("click", (e) => {
  document.querySelectorAll(".menu[open]").forEach((m) => { if (!m.contains(e.target)) m.open = false; });
});

// ---------------------------------------------------------------- verifica e correzione

const editor = {
  cartella: null,
  segmenti: [],
  aree: [],
  righe: [],
  punti: [],
  controllati: new Set(),
  verifica: false,
  filtro: "alta",
  selezionato: null,
  attivo: -1,
  modificato: false,
  versione: 0,
  salvato: null,
  salvataggio: false,
  conversioneTentata: false,
};
const ridimensionaDaSolo = CSS.supports("field-sizing", "content");

async function apriEditor(cartella) {
  let d;
  try {
    d = await api("/api/trascrizioni/" + encodeURIComponent(cartella));
  } catch (e) {
    avviso(e.message, "errore");
    location.hash = "#/archivio";
    return;
  }
  Object.assign(editor, {
    cartella, segmenti: d.segmenti, controllati: new Set(d.controllati), verifica: Boolean(d.verifica),
    selezionato: null, attivo: -1, modificato: false, salvato: d.salvato, conversioneTentata: false,
  });
  $("editor-titolo").textContent = d.nome;
  titoloBase = `${d.nome} · WhisperLocal`;
  aggiornaIndicatore();
  aggiornaSalvataggio();

  const audio = $("audio");
  if (d.audio) {
    audio.hidden = false;
    audio.src = `/api/trascrizioni/${encodeURIComponent(cartella)}/audio`;
    audio.playbackRate = audio.defaultPlaybackRate = Number($("velocita").value);
  } else {
    audio.removeAttribute("src");
    audio.hidden = true;
    avviso("Il file audio originale non è più dov'era: puoi correggere il testo ma non ascoltarlo.", "errore");
  }

  editor.punti = (d.verifica ? d.verifica.voci : []).map((p) => ({ ...p, segmento: indiceAlTempo(p.inizio + 0.01) }));
  const daFare = (chiave) => editor.punti.some((p) => p.sezione === chiave && !editor.controllati.has(p.id));
  editor.filtro = (SEZIONI.find((s) => daFare(s.chiave)) || SEZIONI[1]).chiave;
  disegnaSegmenti();
  disegnaFiltri();
  disegnaPunti();
  $("segmenti").scrollTop = 0;
}

function indiceAlTempo(t) {
  const s = editor.segmenti;
  let basso = 0, alto = s.length - 1, trovato = 0;
  while (basso <= alto) {
    const medio = (basso + alto) >> 1;
    if (s[medio].inizio <= t) {
      trovato = medio;
      basso = medio + 1;
    } else {
      alto = medio - 1;
    }
  }
  return trovato;
}

function disegnaSegmenti() {
  editor.aree = [];
  editor.righe = editor.segmenti.map((s) => {
    const area = el("textarea", { name: "segmento", rows: 1, spellcheck: "false", "aria-label": `Testo da ${tempo(s.inizio)}` });
    area.value = s.testo;
    area.addEventListener("input", () => {
      s.testo = area.value;
      segnaModificato();
      adatta(area);
    });
    editor.aree.push(area);
    return el("li", { class: "segmento" },
      el("button", { class: "tempo", text: tempo(s.inizio), title: "Ascolta da qui", onclick: () => ascoltaDa(s.inizio) }),
      s.speaker ? el("span", { class: "speaker", text: s.speaker }) : null,
      area);
  });
  $("segmenti").replaceChildren(...editor.righe);
  aggiornaSegni();
  adattaTutte();
}

// Altezza delle caselle di testo sul contenuto, dove il browser non lo fa già (field-sizing)
function adatta(area) {
  if (ridimensionaDaSolo) return;
  area.style.height = "auto";
  area.style.height = `${area.scrollHeight + 2}px`;
}

function adattaTutte() {
  if (ridimensionaDaSolo) return;
  for (const a of editor.aree) a.style.height = "auto";
  const altezze = editor.aree.map((a) => a.scrollHeight); // una sola misura per tutte
  editor.aree.forEach((a, i) => (a.style.height = `${altezze[i] + 2}px`));
}

let timerRidimensiona;
window.addEventListener("resize", () => {
  clearTimeout(timerRidimensiona);
  timerRidimensiona = setTimeout(() => vistaCorrente === "editor" && adattaTutte(), 150);
});

// Bordo colorato sui segmenti con punti ancora da controllare (verde se tutti controllati)
function aggiornaSegni() {
  const gravita = new Map();
  const conPunti = new Set();
  for (const p of editor.punti) {
    conPunti.add(p.segmento);
    if (editor.controllati.has(p.id)) continue;
    if ((GRAVITA[p.sezione] || 0) > (GRAVITA[gravita.get(p.segmento)] || 0)) gravita.set(p.segmento, p.sezione);
  }
  editor.righe.forEach((riga, i) => {
    riga.classList.remove("allucinazione", "alta", "bassa", "controllato");
    if (gravita.has(i)) riga.classList.add(gravita.get(i));
    else if (conPunti.has(i)) riga.classList.add("controllato");
  });
}

function disegnaFiltri() {
  $("filtri").hidden = !editor.verifica;
  $("filtri").replaceChildren(...SEZIONI.map(({ chiave, nome }) => {
    const tutti = editor.punti.filter((p) => p.sezione === chiave);
    const fatti = tutti.filter((p) => editor.controllati.has(p.id)).length;
    const attivo = editor.filtro === chiave;
    return el("button", {
      class: `${chiave}${attivo ? " attivo" : ""}`, role: "tab", "aria-selected": String(attivo),
      title: `${fatti} controllati su ${tutti.length}`, text: `${nome} ${fatti}/${tutti.length}`,
      onclick: () => { editor.filtro = chiave; disegnaFiltri(); disegnaPunti(); },
    });
  }));
}

function disegnaPunti() {
  const nascondi = $("nascondi-controllati").checked;
  const sezione = editor.punti.filter((p) => p.sezione === editor.filtro);
  const visibili = sezione.filter((p) => !(nascondi && editor.controllati.has(p.id)));
  const vuoto = $("punti-vuoto");
  vuoto.hidden = visibili.length > 0;
  vuoto.textContent = !editor.verifica
    ? "Questa trascrizione è stata fatta senza verifica: non c'è un elenco di punti da controllare."
    : sezione.length ? "Tutti i punti di questa sezione sono controllati. ✓" : "Nessun punto in questa sezione.";
  $("punti").replaceChildren(...visibili.map(vocePunto));
}

function vocePunto(p) {
  const fatto = editor.controllati.has(p.id);
  const casella = el("input", { type: "checkbox", name: "controllato", checked: fatto, title: "Controllato", "aria-label": "Segna come controllato" });
  const li = el("li", { class: `punto${fatto ? " fatto" : ""}${editor.selezionato === p.id ? " selezionato" : ""}` });
  casella.addEventListener("change", () => {
    if (casella.checked) editor.controllati.add(p.id);
    else editor.controllati.delete(p.id);
    li.classList.toggle("fatto", casella.checked);
    segnaModificato();
    aggiornaSegni();
    disegnaFiltri();
  });

  let corpo, extra = null;
  if (p.sezione === "allucinazione") {
    corpo = [
      el("span", { class: "riga-1" },
        el("span", { class: "ora", text: `${tempo(p.inizio)} → ${tempo(p.fine)}` }),
        el("span", { class: "parola", text: `«${p.testo}» ripetuto ${p.ripetizioni} volte` })),
      el("span", { class: "motivo", text: "Il parlato reale in questo tratto potrebbe mancare: riascoltare." }),
    ];
    if (p.alternativa !== null && p.alternativa !== undefined) {
      // Fuori dal pulsante, così il testo si può selezionare e copiare
      extra = el("div", { class: "alternativa" },
        el("small", { text: "L'altro modello qui scrive: " }), p.alternativa || "(niente)", " ",
        p.alternativa ? el("button", { class: "leggero", text: "Copia", onclick: () => copia(p.alternativa) }) : null);
    }
  } else {
    corpo = [
      el("span", { class: "riga-1" },
        el("span", { class: "ora", text: tempo(p.inizio) }),
        el("span", { class: "parola", text: `«${p.testo || "(niente)"}»` })),
      el("span", { class: "motivo", text: p.motivi.join("; ") }),
      el("span", { class: "contesto" }, `…${p.prima} `, el("mark", { text: p.testo || "(niente)" }), ` ${p.dopo}…`),
    ];
  }
  li.append(casella, el("div", {},
    el("button", { class: "corpo", title: "Ascolta e mostra nel testo", onclick: () => vaiAlPunto(p, li) }, corpo),
    extra));
  return li;
}

async function copia(testo) {
  try {
    await navigator.clipboard.writeText(testo);
    avviso("Testo copiato: incollalo al posto della frase ripetuta.");
  } catch {
    avviso(`Copia non riuscita: seleziona il testo e usa ${tasto("C")}.`, "errore");
  }
}

function vaiAlPunto(p, li) {
  editor.selezionato = p.id;
  document.querySelectorAll(".punto.selezionato").forEach((n) => n.classList.remove("selezionato"));
  li.classList.add("selezionato");
  ascoltaDa(Math.max(0, p.inizio - 2));
  const riga = editor.righe[p.segmento];
  const area = editor.aree[p.segmento];
  if (!riga) return;
  riga.scrollIntoView({ block: "center", behavior: "smooth" });
  riga.classList.remove("lampeggia");
  void riga.offsetWidth; // riavvia l'animazione
  riga.classList.add("lampeggia");
  // Seleziona la parola segnalata, usando le parole precedenti se compare più volte
  if (!p.testo) return;
  const testo = area.value;
  const prima = (p.prima || "").split(" ").slice(-2).join(" ");
  let pos = prima ? testo.indexOf(`${prima} ${p.testo}`) : -1;
  if (pos >= 0) pos += prima.length + 1;
  else pos = testo.indexOf(p.testo);
  if (pos < 0) pos = testo.toLowerCase().indexOf(p.testo.toLowerCase());
  if (pos >= 0) {
    area.focus({ preventScroll: true });
    area.setSelectionRange(pos, pos + p.testo.length);
  }
}

function ascoltaDa(secondi) {
  const audio = $("audio");
  if (!audio.getAttribute("src")) return;
  audio.currentTime = secondi;
  audio.play().catch(() => {});
}

function segnaModificato() {
  editor.modificato = true;
  editor.versione++;
  aggiornaSalvataggio();
}

function aggiornaSalvataggio() {
  const n = $("stato-salvataggio");
  n.classList.toggle("modificato", editor.modificato);
  n.textContent = editor.modificato ? "Modifiche non salvate"
    : editor.salvato ? `Correzioni salvate · ${dataLeggibile(editor.salvato)}` : "Testo originale";
}

async function salva() {
  if (!editor.cartella || editor.salvataggio) return;
  editor.salvataggio = true;
  $("salva").disabled = true;
  const versione = editor.versione;
  try {
    const r = await invia(`/api/trascrizioni/${encodeURIComponent(editor.cartella)}/correzione`,
      { segmenti: editor.segmenti, controllati: [...editor.controllati] });
    editor.salvato = r.salvato;
    editor.modificato = editor.versione !== versione; // modifiche fatte durante il salvataggio
    aggiornaSalvataggio();
    avviso("Correzioni salvate nei file _corretto (gli originali restano com'erano).");
  } catch (e) {
    avviso(e.message, "errore");
  } finally {
    editor.salvataggio = false;
    $("salva").disabled = false;
  }
}

const audio = $("audio");

// Evidenzia il segmento in riproduzione e, se richiesto, lo tiene in vista
audio.addEventListener("timeupdate", () => {
  if (vistaCorrente !== "editor" || !editor.righe.length) return;
  const i = indiceAlTempo(audio.currentTime);
  if (i === editor.attivo) return;
  editor.righe[editor.attivo]?.classList.remove("attivo");
  editor.attivo = i;
  editor.righe[i].classList.add("attivo");
  const staScrivendo = document.activeElement?.closest?.(".segmenti") && document.activeElement.tagName === "TEXTAREA";
  if ($("segui").checked && !audio.paused && !staScrivendo) {
    editor.righe[i].scrollIntoView({ block: "center", behavior: "smooth" });
  }
});

// Formato non riproducibile dal browser: il server ne prepara una copia m4a (una volta sola)
audio.addEventListener("error", () => {
  if (!audio.getAttribute("src") || vistaCorrente !== "editor") return;
  if (editor.conversioneTentata) {
    avviso("Il browser non riesce a riprodurre questo audio.", "errore");
    return;
  }
  editor.conversioneTentata = true;
  avviso("Preparo una copia dell'audio leggibile dal browser…");
  audio.src = `/api/trascrizioni/${encodeURIComponent(editor.cartella)}/audio?converti=1`;
});

$("velocita").addEventListener("change", (e) => {
  audio.playbackRate = audio.defaultPlaybackRate = Number(e.target.value);
});

document.addEventListener("keydown", (e) => {
  if (vistaCorrente !== "editor") return;
  if (e.key === "Escape" && !e.metaKey && !e.ctrlKey && !e.altKey) {
    if (!audio.getAttribute("src")) return;
    e.preventDefault();
    if (audio.paused) {
      audio.currentTime = Math.max(0, audio.currentTime - 1); // riparte un secondo prima
      audio.play().catch(() => {});
    } else {
      audio.pause();
    }
  } else if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
    e.preventDefault();
    salva();
  }
});

window.addEventListener("beforeunload", (e) => {
  if (editor.modificato) {
    e.preventDefault();
    e.returnValue = "";
  }
});

// ---------------------------------------------------------------- avvio

const zona = $("zona");
zona.addEventListener("dragover", () => zona.classList.add("sopra"));
zona.addEventListener("dragleave", () => zona.classList.remove("sopra"));
// Un file lasciato in un punto qualsiasi della pagina non deve aprirsi nel browser
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => {
  e.preventDefault();
  zona.classList.remove("sopra");
  if (vistaCorrente === "trascrivi") aggiungiFile(e.dataTransfer.files);
});
$("scelta-file").addEventListener("change", (e) => {
  aggiungiFile(e.target.files);
  e.target.value = "";
});
$("avvia").addEventListener("click", avviaTrascrizioni);
$("salva").addEventListener("click", salva);
$("nascondi-controllati").addEventListener("change", disegnaPunti);
window.addEventListener("hashchange", instrada);

instrada();
aggiornaStato();
api("/api/ping").then((dati) => {
  if (dati && dati.sistema) sistema = dati.sistema;
  $("tasto-salva").textContent = tasto("S");
  if (sistema !== "mac" && vistaCorrente === "archivio") caricaArchivio();
}).catch(() => { /* resta l'aspetto macOS */ });
