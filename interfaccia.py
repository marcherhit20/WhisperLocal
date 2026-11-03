"""Interfaccia grafica di WhisperLocal: una pagina nel browser per caricare i file,
seguire le trascrizioni, verificare i punti segnalati ascoltando l'audio e correggere il testo.

Uso:
  macOS:   .venv/bin/python interfaccia.py        (oppure doppio clic su WhisperLocal.command)
  Windows: .venv\\Scripts\\python.exe interfaccia.py (oppure doppio clic su WhisperLocal.bat)

Il server ascolta solo su 127.0.0.1:8765 e non si collega a internet. Le trascrizioni le fa
trascrivi.py, che continua a bloccare la rete (macOS: sandbox-exec + programma; Windows:
blocco nel programma, vedi blocco_rete.py). Nessun file viene cancellato
o sovrascritto: i caricamenti vanno in input/ con un nome libero, le correzioni in
NOME_corretto.json/.txt/.srt accanto agli originali.
"""

import asyncio
import collections
import glob
import itertools
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from aiohttp import web

PROGETTO = Path(__file__).resolve().parent
WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"
FFMPEG_PORTATILE = PROGETTO / "strumenti" / "ffmpeg" / "bin"
INPUT = PROGETTO / "input"
OUTPUT = PROGETTO / "output"
PAGINA = PROGETTO / "interfaccia"
INDIRIZZO, PORTA = "127.0.0.1", 8765
URL = f"http://{INDIRIZZO}:{PORTA}/"
# Solo richieste rivolte a questo computer (protegge dal DNS rebinding) e, per le modifiche,
# provenienti da questa pagina (protegge da altri siti aperti nel browser)
HOST_AMMESSI = {f"127.0.0.1:{PORTA}", f"localhost:{PORTA}"}
ORIGINI_AMMESSE = {f"http://{h}" for h in HOST_AMMESSI}

MODELLO, SECONDO = "large-v3-turbo", "medium"  # i predefiniti di trascrivi.py
ESTENSIONI = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".wma", ".aif", ".aiff",
              ".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".mpeg", ".mpg", ".3gp"}
# Formati che Safari e Chrome riproducono direttamente; gli altri vengono convertiti una volta
TIPI_AUDIO = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac", ".wav": "audio/wav",
              ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime"}
# Secondi di elaborazione per secondo di audio, misurati il 2026-10-01 (turbo + medium, solo turbo)
RAPPORTO_CON_VERIFICA, RAPPORTO_SENZA_VERIFICA = 0.47, 0.19

# Righe di whisperx che segnano l'inizio di una fase
FASI = [
    ("Performing voice activity detection", "Ricerca del parlato"),
    ("Performing transcription", "Trascrizione"),
    ("Performing alignment", "Allineamento dei tempi"),
    ("Performing diarization", "Distinzione di chi parla"),
]


def prepara_ambiente():
    """ffmpeg/ffprobe (portatile in strumenti/ o di Homebrew) nel PATH; testo in UTF-8."""
    if FFMPEG_PORTATILE.is_dir():
        os.environ["PATH"] = str(FFMPEG_PORTATILE) + os.pathsep + os.environ.get("PATH", "")
    if MACOS:
        os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + "/opt/homebrew/bin" + os.pathsep + "/usr/local/bin"
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    for flusso in (sys.stdout, sys.stderr):
        try:
            flusso.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def avvisa(testo):
    """Scrive nella finestra del Terminale; se è già stata chiusa non importa."""
    try:
        print(testo, flush=True)
    except OSError:
        pass


# ---------------------------------------------------------------- lavori in coda

class Lavoro:
    _contatore = itertools.count(1)

    def __init__(self, file, parole, verifica, durata, diarize=False, speakers=None):
        self.id = next(self._contatore)
        self.file = file
        self.parole = parole
        self.verifica = verifica
        self.durata = durata
        self.diarize = diarize
        self.speakers = speakers
        self.stato = "in coda"  # in coda, in corso, finito, errore, annullato
        self.passo = 0
        self.fase = "In attesa"
        self.percentuale = None
        self.inizio = self.fine = None
        self.cartella = None
        self.riepilogo = None
        self.errore = None
        self.righe = collections.deque(maxlen=60)
        self.processo = None
        self.uscite = 0  # righe "Output:" di trascrivi.sh viste finora

    @property
    def passi(self):
        return 3 if self.verifica else 1

    def complessivo(self):
        """Avanzamento totale stimato in percentuale."""
        if self.stato == "finito":
            return 100.0
        if self.passo == 0:
            return 0.0
        # medium impiega più di turbo; il controllo errori dura pochi secondi
        pesi = [0.40, 0.57, 0.03] if self.verifica else [1.0]
        p = (self.percentuale or 0) / 100
        if self.diarize and self.passo == 1:
            frazioni = {"Trascrizione": 0.03 + 0.52 * p,
                        "Allineamento dei tempi": 0.55 + 0.15 * p,
                        "Distinzione di chi parla": 0.70 + 0.30 * p}
        else:
            frazioni = {"Trascrizione": 0.03 + 0.72 * p, "Allineamento dei tempi": 0.75 + 0.25 * p}
        frazione = frazioni.get(self.fase, 0)
        return round(100 * (sum(pesi[:self.passo - 1]) + pesi[self.passo - 1] * frazione), 1)

    def dati(self):
        nomi_passi = [MODELLO, SECONDO, "controllo errori"]
        return {
            "id": self.id,
            "nome": self.file.name,
            "stato": self.stato,
            "passo": self.passo,
            "passi": self.passi,
            "passo_nome": nomi_passi[self.passo - 1] if self.passo else "",
            "fase": self.fase,
            "percentuale": self.percentuale,
            "complessivo": self.complessivo(),
            "durata": self.durata,
            "previsto": round(self.durata * (RAPPORTO_CON_VERIFICA if self.verifica else RAPPORTO_SENZA_VERIFICA))
            if self.durata and not self.diarize else None,
            "trascorso": round((self.fine or time.time()) - self.inizio) if self.inizio else None,
            "cartella": self.cartella,
            "punti": conteggi_punti(self.riepilogo),
            "verifica": self.verifica,
            "diarize": self.diarize,
            "speakers": self.speakers,
            "errore": self.errore,
            "righe": list(self.righe),
        }


def conteggi_punti(riepilogo):
    """Dalla riga "Punti segnalati: …" di segnala.py ai tre numeri."""
    m = riepilogo and re.search(r"(\d+) possibili allucinazioni, (\d+) a priorità alta, (\d+) a priorità bassa", riepilogo)
    return {"allucinazioni": int(m[1]), "alta": int(m[2]), "bassa": int(m[3])} if m else None


def interpreta(lavoro, riga):
    """Aggiorna fase e avanzamento leggendo una riga di trascrivi.sh."""
    for chiave, fase in FASI:
        if chiave in riga:
            lavoro.fase, lavoro.percentuale = fase, None
            return
    if m := re.match(r"Progress: ([\d.]+)%", riga):
        lavoro.percentuale = min(100.0, float(m[1]))
    elif riga.startswith("==== Secondo parere"):
        lavoro.passo, lavoro.fase, lavoro.percentuale = 2, "Caricamento del modello", None
    elif riga.startswith("Output: "):
        lavoro.uscite += 1
        if lavoro.uscite == 1:
            lavoro.cartella = Path(riga[len("Output: "):].strip()).name
        if lavoro.verifica and lavoro.uscite == 2:
            lavoro.passo, lavoro.fase, lavoro.percentuale = 3, "Controllo degli errori", None
    elif riga.startswith("Punti segnalati:"):
        lavoro.riepilogo = riga
    elif "riprova una volta con --online" in riga:
        lavoro.errore = ("Il modello non è ancora scaricato: esegui una volta "
                         "prepara_modelli.py --online (vedi ISTRUZIONI.md, «Primo avvio»).")
    elif riga.startswith("Errore interlocutori:"):
        lavoro.errore = riga


def comando_trascrizione(lavoro):
    comando = [sys.executable, str(PROGETTO / "trascrivi.py"), str(lavoro.file)]
    if MACOS:
        comando = ["caffeinate", "-i", *comando]  # su Windows lo stop lo impedisce trascrivi.py
    if lavoro.parole:
        comando += ["--parole", lavoro.parole]
    if not lavoro.verifica:
        comando.append("--senza-verifica")
    if lavoro.diarize:
        comando.append("--diarize")
        if lavoro.speakers is not None:
            comando += ["--speakers", str(lavoro.speakers)]
    return comando


async def esegui(lavoro):
    comando = comando_trascrizione(lavoro)
    lavoro.stato, lavoro.passo, lavoro.fase, lavoro.inizio = "in corso", 1, "Caricamento del modello", time.time()
    avvisa(f"Trascrizione avviata: {lavoro.file.name}")
    codice = None
    try:
        # Gruppo di processi separato (macOS) o nuovo gruppo + Job Object creato da trascrivi.py
        # stesso prima dei suoi figli (Windows): Annulla ferma insieme trascrivi.py, whisperx e ffmpeg
        lavoro.processo = await asyncio.create_subprocess_exec(
            *comando, cwd=PROGETTO, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, limit=1 << 20, **opzioni_processo(),
            # trascrivi.py si ferma da solo se questo server sparisce (anche senza output)
            env={**os.environ, "WHISPERLOCAL_INTERFACCIA_PID": str(os.getpid())})
        async for grezza in lavoro.processo.stdout:
            # Le barre di avanzamento riscrivono la riga con \r: conta solo l'ultima versione
            riga = grezza.decode("utf-8", "replace").rstrip("\n").split("\r")[-1].rstrip()
            if not riga:
                continue
            interpreta(lavoro, riga)
            if not riga.startswith("Progress:"):
                lavoro.righe.append(riga)
        codice = await lavoro.processo.wait()
    except Exception as e:  # es. riga troppo lunga o processo non avviabile
        lavoro.errore = f"Errore interno dell'interfaccia: {e}"
        # La trascrizione non deve continuare senza controllo: la fermo e la aspetto
        if lavoro.processo and lavoro.processo.returncode is None:
            await ferma_processo(lavoro)
    lavoro.fine = time.time()
    if lavoro.stato == "annullato":
        avvisa(f"Trascrizione annullata: {lavoro.file.name}")
    elif codice == 0:
        lavoro.stato, lavoro.fase, lavoro.percentuale = "finito", "Completata", None
        avvisa(f"Trascrizione completata: {lavoro.file.name}")
    else:
        lavoro.stato = "errore"
        lavoro.errore = lavoro.errore or "La trascrizione si è interrotta: vedi i dettagli qui sotto."
        avvisa(f"Trascrizione non riuscita: {lavoro.file.name}")


# ---------------------------------------------------------------- processi (macOS / Windows)

def opzioni_processo():
    if WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def termina_windows(lavoro):
    """Ferma l'albero dei processi della trascrizione (Windows). trascrivi.py tiene i suoi
    figli in un Job Object «kill on close», quindi alla sua fine si chiudono anche loro."""
    try:
        risultato = subprocess.run(["taskkill", "/T", "/F", "/PID", str(lavoro.processo.pid)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        return risultato.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def gruppo_attivo(pid):
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


async def ferma(lavoro):
    if lavoro.stato == "in coda":
        lavoro.stato, lavoro.fase, lavoro.fine = "annullato", "Annullata", time.time()
        return
    if lavoro.stato != "in corso" or not lavoro.processo:
        return
    lavoro.stato, lavoro.fase = "annullato", "Annullata"
    await ferma_processo(lavoro)


async def ferma_processo(lavoro):
    """Ferma il processo della trascrizione e i suoi discendenti, con tempi massimi."""
    if WINDOWS:
        # Su Windows non c'è SIGTERM: si termina subito l'albero. I risultati restano
        # integri perché trascrivi.py e segnala.py pubblicano solo insiemi completi.
        await asyncio.to_thread(termina_windows, lavoro)
        for _ in range(50):
            if lavoro.processo.returncode is not None:
                return
            await asyncio.sleep(0.1)
        # Ancora vivo: non lo mostro come «Annullata»
        lavoro.stato, lavoro.fase = "errore", "Arresto non riuscito"
        lavoro.errore = ("Non sono riuscito a fermare la trascrizione: controlla in Gestione "
                         "attività che non resti un python.exe di WhisperLocal.")
        avvisa(lavoro.errore)
        return
    pid = lavoro.processo.pid
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(50):  # fino a 5 s per chiudersi da soli, poi SIGKILL
        if not gruppo_attivo(pid):
            return
        await asyncio.sleep(0.1)
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):  # gruppo già chiuso (resta solo un processo da raccogliere)
        pass


async def esegui_coda(app):
    while True:
        lavoro = await app["coda"].get()
        if lavoro.stato == "in coda":
            await esegui(lavoro)


async def gestione_coda(app):
    app["lavori"] = []
    app["coda"] = asyncio.Queue()
    compito = asyncio.create_task(esegui_coda(app))
    yield
    await ferma_tutto(app)
    compito.cancel()


async def ferma_tutto(app):
    for lavoro in app["lavori"]:
        await ferma(lavoro)


# ---------------------------------------------------------------- caricamento

# Nomi che Windows riserva ai dispositivi (anche con estensione: "con.mp3" non si può creare)
NOMI_RISERVATI = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def nome_sicuro(nome):
    nome = Path(nome.replace("\\", "/")).name
    nome = re.sub(r"[^\w .,()+&'-]", "_", nome).strip(" .")
    nome = nome[-150:] or "registrazione"
    if nome.split(".")[0].strip().upper() in NOMI_RISERVATI:
        nome = f"_{nome}"
    return nome


def nome_libero(nome):
    """Un nome in input/ che non si scontra con file né con cartelle di risultati già esistenti."""
    radice, estensione = os.path.splitext(nome)
    for n in itertools.count(1):
        candidato = f"{radice}{'' if n == 1 else f'_{n}'}{estensione}"
        base = glob.escape(Path(candidato).stem)
        occupato = (
            any(INPUT.glob(f"{base}.*"))
            or (INPUT / f".{candidato}.caricamento").exists()
            or any(OUTPUT.glob(f".{base}_*.parziale"))  # trascrizione in corso o interrotta
            or any(OUTPUT.glob(f"{base}_{MODELLO}*"))
            or any(OUTPUT.glob(f"{base}_{SECONDO}*"))
        )
        if not occupato:
            return INPUT / candidato


def frase_parole(testo):
    """Elenco di termini -> "Termini: a, b, c." (come elenco nudo il testo perde punteggiatura)."""
    testo = re.sub(r"^\s*termini\s*:\s*", "", testo, flags=re.I)
    voci = [v.strip(" .") for v in re.split(r"[,;\n]+", testo)]
    voci = [" ".join(v.split()) for v in voci if v.strip(" .")]
    return f"Termini: {', '.join(voci)}." if voci else ""


async def durata_audio(file):
    processo = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(file),
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    uscita, _ = await processo.communicate()
    try:
        return float(uscita)
    except ValueError:
        return None


def errore(stato, messaggio):
    return web.json_response({"errore": messaggio}, status=stato)


async def carica(request):
    campi = {}
    destinazione = None
    async for parte in await request.multipart():
        if parte.name in ("parole", "senza_verifica", "diarize", "speakers"):
            campi[parte.name] = await parte.text()
        elif parte.name == "file" and parte.filename and destinazione is None:
            nome = nome_sicuro(parte.filename)
            if Path(nome).suffix.lower() not in ESTENSIONI:
                return errore(400, f"«{nome}» non sembra un file audio o video.")
            INPUT.mkdir(exist_ok=True)
            destinazione = nome_libero(nome)
            temporaneo = destinazione.with_name(f".{destinazione.name}.caricamento")
            try:
                with open(temporaneo, "wb") as f:
                    while blocco := await parte.read_chunk(1 << 20):
                        f.write(blocco)
                temporaneo.rename(destinazione)
            except BaseException:
                temporaneo.unlink(missing_ok=True)
                raise
    if destinazione is None:
        return errore(400, "Nessun file ricevuto.")
    diarize = campi.get("diarize", "0")
    numero = campi.get("speakers", "").strip()
    if diarize not in ("0", "1") or (numero and (
            diarize != "1" or not re.fullmatch(r"[1-9][0-9]?", numero))):
        destinazione.unlink()  # solo il file appena creato da questa richiesta
        return errore(400, "Scegli Distingui chi parla e un numero di interlocutori da 1 a 99, oppure lascia il numero vuoto.")
    durata = await durata_audio(destinazione)
    if not durata:
        destinazione.unlink()  # appena creato da questa richiesta
        return errore(400, f"«{destinazione.name}» non contiene audio leggibile.")
    lavoro = Lavoro(destinazione, frase_parole(campi.get("parole", "")),
                    campi.get("senza_verifica") != "1", durata,
                    diarize == "1", int(numero) if numero else None)
    request.app["lavori"].append(lavoro)
    await request.app["coda"].put(lavoro)
    avvisa(f"In coda: {destinazione.name}")
    return web.json_response(lavoro.dati())


async def stato(request):
    return web.json_response({"lavori": [l.dati() for l in request.app["lavori"][-30:]]})


async def annulla(request):
    for lavoro in request.app["lavori"]:
        if str(lavoro.id) == request.match_info["id"]:
            await ferma(lavoro)
            return web.json_response(lavoro.dati())
    return errore(404, "Lavoro non trovato.")


# ---------------------------------------------------------------- archivio

def leggi_log(cartella):
    """Intestazione e riepilogo del run.log."""
    info = {}
    try:
        testo = (cartella / "run.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return info
    for riga in testo.splitlines()[:12]:
        if m := re.match(r"(Data|File|Modello|Precisione|Parole|Rete|Diarize):\s+(.*)", riga):
            info[m[1].lower()] = m[2].strip()
    if m := re.search(r"^Audio: (\d+) min (\d+) s \| Tempo: (\d+) min (\d+) s", testo, re.M):
        info["durata"] = int(m[1]) * 60 + int(m[2])
        info["tempo"] = int(m[3]) * 60 + int(m[4])
    return info


def json_trascrizione(cartella):
    candidati = [f for f in cartella.glob("*.json")
                 if f.name != "da_verificare.json" and not f.stem.endswith("_corretto")]
    return candidati[0] if len(candidati) == 1 else None


def leggi_verifica(cartella):
    try:
        return json.loads((cartella / "da_verificare.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def riepilogo_txt(cartella):
    """Righe "Confronto con:" e "Punti segnalati:" di un da_verificare.txt (anche senza .json)."""
    try:
        righe = (cartella / "da_verificare.txt").read_text(encoding="utf-8").splitlines()[:3]
    except OSError:
        return None, None
    confronto = next((r[len("Confronto con: "):] for r in righe if r.startswith("Confronto con: ")), None)
    punti = conteggi_punti(next((r for r in righe if r.startswith("Punti segnalati:")), None))
    return confronto, punti


def info_cartella(cartella, trascrizione):
    log = leggi_log(cartella)
    verifica = leggi_verifica(cartella)
    _, punti_txt = riepilogo_txt(cartella)
    return {
        "cartella": cartella.name,
        "nome": trascrizione.stem,
        "data": log.get("data"),
        "modello": log.get("modello"),
        "parole": log.get("parole", "nessuna") != "nessuna",
        "rete": log.get("rete"),
        "durata": log.get("durata"),
        "tempo": log.get("tempo"),
        "punti": verifica["riepilogo"] if verifica else punti_txt,
        "corretto": (cartella / f"{trascrizione.stem}_corretto.json").exists(),
        "file": file_scaricabili(cartella),
    }


async def trascrizioni(request):
    cartelle = [c for c in OUTPUT.iterdir() if c.is_dir() and not c.name.startswith(".")] if OUTPUT.is_dir() else []
    # Le cartelle del secondo parere (medium) servono solo alla verifica: non le elenco
    secondi = set()
    for c in cartelle:
        verifica = leggi_verifica(c)
        confronto = verifica.get("confronto") if verifica else riepilogo_txt(c)[0]
        if confronto:
            secondi.add(Path(confronto).parent.name)
    elenco = []
    for c in cartelle:
        trascrizione = json_trascrizione(c)
        if c.name not in secondi and trascrizione:
            elenco.append(info_cartella(c, trascrizione))
    elenco.sort(key=lambda t: t["data"] or "", reverse=True)
    return web.json_response({"trascrizioni": elenco})


def cartella_richiesta(request):
    nome = request.match_info["cartella"]
    cartella = OUTPUT / nome
    if "/" in nome or "\\" in nome or nome.startswith(".") or cartella.parent != OUTPUT or not cartella.is_dir():
        raise web.HTTPNotFound(text="Trascrizione non trovata.")
    trascrizione = json_trascrizione(cartella)
    if not trascrizione:
        raise web.HTTPNotFound(text="Trascrizione non trovata.")
    return cartella, trascrizione


def segmenti_originali(trascrizione):
    dati = json.loads(trascrizione.read_text(encoding="utf-8"))
    segmenti, ultimo = [], 0.0
    for s in dati.get("segments", []):
        inizio = s.get("start", ultimo)
        fine = ultimo = s.get("end", inizio)
        segmento = {"inizio": inizio, "fine": fine, "testo": s.get("text", "").strip()}
        if s.get("speaker"):
            segmento["speaker"] = s["speaker"]
        segmenti.append(segmento)
    return segmenti


def file_scaricabili(cartella):
    return sorted(f.name for f in cartella.iterdir()
                  if f.is_file() and not f.name.startswith(".") and f.name != "ascolto.m4a")


def sorgente_audio(cartella):
    file = leggi_log(cartella).get("file")
    if not file:
        return None
    percorso = Path(file) if Path(file).is_absolute() else PROGETTO / file  # i log vecchi sono relativi
    return percorso if percorso.is_file() else None


async def dettaglio(request):
    cartella, trascrizione = cartella_richiesta(request)
    corretto = cartella / f"{trascrizione.stem}_corretto.json"
    if corretto.exists():
        salvato = json.loads(corretto.read_text(encoding="utf-8"))
        segmenti, controllati, data = salvato["segmenti"], salvato.get("controllati", []), salvato.get("salvato")
    else:
        segmenti, controllati, data = segmenti_originali(trascrizione), [], None
    return web.json_response({
        **info_cartella(cartella, trascrizione),
        "segmenti": segmenti,
        "verifica": leggi_verifica(cartella),
        "controllati": controllati,
        "salvato": data,
        "audio": sorgente_audio(cartella) is not None,
    })


def tempo_srt(secondi):
    ms = round(secondi * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def scrivi(percorso, testo):
    """Scrittura atomica: un salvataggio interrotto non lascia un file a metà."""
    temporaneo = percorso.with_name(f".{percorso.name}.tmp")
    temporaneo.write_text(testo, encoding="utf-8", newline="\n")
    temporaneo.replace(percorso)


async def correzione(request):
    cartella, trascrizione = cartella_richiesta(request)
    try:
        dati = await request.json()
        segmenti = [
            {"inizio": float(s["inizio"]), "fine": float(s["fine"]), "testo": str(s["testo"]),
             **({"speaker": str(s["speaker"])} if s.get("speaker") else {})}
            for s in dati["segmenti"]
        ]
        controllati = [str(c) for c in dati.get("controllati", [])]
    except (ValueError, KeyError, TypeError):
        return errore(400, "Dati della correzione non validi.")
    salvato = datetime.now().isoformat(timespec="seconds")
    base = f"{trascrizione.stem}_corretto"
    scrivi(cartella / f"{base}.json", json.dumps(
        {"origine": trascrizione.name, "salvato": salvato, "segmenti": segmenti, "controllati": controllati},
        ensure_ascii=False, indent=1) + "\n")
    # Stesso formato dei file di whisperx: [SPEAKER_xx]: davanti al testo quando c'è
    testi = [(s, (f"[{s['speaker']}]: " if "speaker" in s else "") + " ".join(s["testo"].split()))
             for s in segmenti if s["testo"].strip()]
    scrivi(cartella / f"{base}.txt", "".join(t + "\n" for _, t in testi))
    scrivi(cartella / f"{base}.srt", "\n".join(
        f"{n}\n{tempo_srt(s['inizio'])} --> {tempo_srt(s['fine'])}\n{t}\n" for n, (s, t) in enumerate(testi, 1)))
    return web.json_response({"salvato": salvato, "file": file_scaricabili(cartella)})


CONVERSIONI = collections.defaultdict(asyncio.Lock)


async def audio(request):
    cartella, _ = cartella_richiesta(request)
    sorgente = sorgente_audio(cartella)
    if not sorgente:
        return errore(404, "File audio originale non trovato: è stato spostato o cancellato?")
    tipo = TIPI_AUDIO.get(sorgente.suffix.lower())
    if tipo and request.query.get("converti") != "1":
        return web.FileResponse(sorgente, headers={"Content-Type": tipo})
    # Formato che il browser non legge: una copia m4a solo per l'ascolto, creata una volta
    ascolto = cartella / "ascolto.m4a"
    async with CONVERSIONI[cartella.name]:
        if not ascolto.exists():
            temporaneo = cartella / ".ascolto-parziale.m4a"
            processo = await asyncio.create_subprocess_exec(
                "ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(sorgente), "-vn",
                "-c:a", "aac", "-b:a", "96k", str(temporaneo),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if await processo.wait() != 0:
                temporaneo.unlink(missing_ok=True)
                return errore(500, "Conversione dell'audio per il browser non riuscita.")
            temporaneo.rename(ascolto)
    return web.FileResponse(ascolto, headers={"Content-Type": "audio/mp4"})


async def scarica(request):
    cartella, _ = cartella_richiesta(request)
    nome = request.match_info["nome"]
    if nome not in file_scaricabili(cartella):
        return errore(404, "File non trovato.")
    return web.FileResponse(cartella / nome, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(nome)}"})


async def mostra(request):
    _, trascrizione = cartella_richiesta(request)
    if WINDOWS:
        subprocess.Popen(["explorer", f"/select,{trascrizione}"])
    else:
        subprocess.Popen(["open", "-R", str(trascrizione)])
    return web.json_response({"ok": True})


# ---------------------------------------------------------------- server

@web.middleware
async def protezione(request, handler):
    if request.headers.get("Host") not in HOST_AMMESSI:
        return web.Response(status=403, text="Accesso consentito solo da questo computer.")
    if request.method not in ("GET", "HEAD") and request.headers.get("Origin") not in ORIGINI_AMMESSE:
        return web.Response(status=403, text="Richiesta non ammessa.")
    return await handler(request)


async def intestazioni(request, risposta):
    # La pagina non può caricare nulla da fuori, nemmeno per errore
    risposta.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
    risposta.headers["X-Content-Type-Options"] = "nosniff"
    risposta.headers["Referrer-Policy"] = "no-referrer"
    risposta.headers.setdefault("Cache-Control", "no-cache")


async def pagina(request):
    return web.FileResponse(PAGINA / "index.html")


async def ping(request):
    return web.json_response({"app": "WhisperLocal", "sistema": "windows" if WINDOWS else "mac" if MACOS else "altro"})


def crea_app():
    app = web.Application(middlewares=[protezione], client_max_size=50 * 1024 * 1024)
    app.cleanup_ctx.append(gestione_coda)
    app.on_response_prepare.append(intestazioni)
    app.router.add_get("/", pagina)
    app.router.add_static("/static/", PAGINA)
    app.router.add_get("/api/ping", ping)
    app.router.add_get("/api/stato", stato)
    app.router.add_post("/api/carica", carica)
    app.router.add_post("/api/annulla/{id}", annulla)
    app.router.add_get("/api/trascrizioni", trascrizioni)
    app.router.add_get("/api/trascrizioni/{cartella}", dettaglio)
    app.router.add_get("/api/trascrizioni/{cartella}/audio", audio)
    app.router.add_get("/api/trascrizioni/{cartella}/file/{nome}", scarica)
    app.router.add_post("/api/trascrizioni/{cartella}/correzione", correzione)
    app.router.add_post("/api/trascrizioni/{cartella}/mostra", mostra)
    return app


def gia_attivo():
    try:
        with urllib.request.urlopen(URL + "api/ping", timeout=2) as risposta:
            return json.load(risposta).get("app") == "WhisperLocal"
    except Exception:
        return False


def apri_pagina():
    if MACOS:
        subprocess.Popen(["open", URL])
    else:
        webbrowser.open(URL)


async def avvia(apri):
    app = crea_app()
    runner = web.AppRunner(app, access_log=None, shutdown_timeout=2.0)
    await runner.setup()
    try:
        await web.TCPSite(runner, INDIRIZZO, PORTA).start()
    except OSError:
        await runner.cleanup()
        if await asyncio.to_thread(gia_attivo):
            avvisa("WhisperLocal è già aperto: riapro la pagina. Puoi chiudere questa finestra.")
            if apri:
                apri_pagina()
            return 0
        avvisa(f"Errore: la porta {PORTA} è occupata da un altro programma.")
        return 1
    avvisa(f"WhisperLocal è aperto nel browser: {URL}")
    avvisa("Lascia aperta questa finestra mentre usi la pagina.")
    avvisa("Per chiudere: chiudi la finestra o premi Ctrl+C (una trascrizione in corso viene fermata).")
    if apri:
        apri_pagina()
    chiusura = asyncio.Event()
    loop = asyncio.get_running_loop()
    if WINDOWS:
        ascolta_chiusura_windows(app, loop, chiusura)
    else:
        for segnale in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):  # SIGHUP: finestra chiusa
            loop.add_signal_handler(segnale, chiusura.set)
    await chiusura.wait()
    # Prima fermo la trascrizione, poi il server (che aspetta le richieste in corso)
    await ferma_tutto(app)
    await runner.cleanup()
    return 0


def ascolta_chiusura_windows(app, loop, chiusura):
    """Ctrl+C, Ctrl+Break e chiusura della finestra della console.

    Alla chiusura della finestra Windows concede circa 5 secondi: qui si terminano subito
    i processi della trascrizione (in questo thread, senza aspettare il ciclo asyncio), poi
    si avvisa il ciclo. Se anche questo non bastasse: i processi collegati alla stessa console
    ricevono anch'essi la chiusura, trascrivi.py si ferma appena non può più scrivere al server
    e il suo Job Object chiude whisperx e ffmpeg."""
    import ctypes
    from ctypes import wintypes

    def gestore(tipo):
        for lavoro in app["lavori"]:
            if lavoro.stato == "in corso" and lavoro.processo:
                lavoro.stato, lavoro.fase = "annullato", "Annullata"
                try:
                    termina_windows(lavoro)
                except Exception:
                    pass
        loop.call_soon_threadsafe(chiusura.set)
        if tipo in (0, 1):  # Ctrl+C / Ctrl+Break: il programma si chiude da solo
            return True
        time.sleep(3)  # chiusura finestra/logoff: lascia al ciclo il tempo di chiudere il server
        return True

    TipoGestore = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
    ascolta_chiusura_windows.gestore = TipoGestore(gestore)  # riferimento da non perdere
    ctypes.windll.kernel32.SetConsoleCtrlHandler(ascolta_chiusura_windows.gestore, True)


if __name__ == "__main__":
    prepara_ambiente()
    if WINDOWS:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    sys.exit(asyncio.run(avvia(apri="--senza-browser" not in sys.argv)))
