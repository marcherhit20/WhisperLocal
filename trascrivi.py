"""Trascrizione locale con WhisperX (italiano, CPU).

Uso:
  trascrivi.sh <file audio/video> [modello] [opzioni]        (macOS)
  trascrivi.bat <file audio/video> [modello] [opzioni]       (Windows)

Opzioni:
  --senza-verifica      salta il secondo modello e da_verificare.txt (più veloce, ma
                        allucinazioni e parti mancanti non vengono scoperte)
  --parole "Termini: a, b, c."  nomi e termini attesi; scriverli come frase con la
                        punteggiatura, altrimenti il testo esce senza punti e maiuscole
  --precisione int8     modello compresso: meno RAM; su Apple M4 più lento, su processori
                        Intel/AMD da provare; predefinita float32
  --online              consente internet, solo per scaricare un modello la prima volta
                        (meglio: prepara_modelli.py --online, che non apre registrazioni);
                        senza questa opzione la rete è sempre bloccata
  --diarize             distingue gli interlocutori (modello da preparare una volta)
  --speakers N          numero di interlocutori, se noto (con --diarize)

Esempi:
  trascrivi.sh input/riunione.mp3
  trascrivi.sh input/riunione.mp3 --parole "Termini: Rossi, ETF obbligazionario, due diligence."
  trascrivi.sh input/riunione.mp3 large-v2 --online   # primo uso di un modello nuovo

Predefiniti: large-v3-turbo in float32, con verifica tramite medium e da_verificare.txt.
I risultati vanno in output/<nomefile>_<modello>[_varianti]/ insieme a run.log
(log completo, tempo impiegato e memoria massima).
Blocco della rete: su macOS dal sistema (sandbox-exec) e dal programma; su Windows dal
programma (blocco_rete.py: copre tutto ciò che passa da Python, non il codice nativo).
Il token Hugging Face non va mai passato a questo script: si configura con `hf auth login`.
"""

import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

PROGETTO = Path(__file__).resolve().parent
WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"
# Profilo macOS che vieta le connessioni di rete verso l'esterno
PROFILO_SENZA_RETE = "(version 1)(allow default)(deny network-outbound (remote ip))"
FFMPEG_PORTATILE = PROGETTO / "strumenti" / "ffmpeg" / "bin"


def errore(messaggio, codice=1):
    print(messaggio, file=sys.stderr, flush=True)
    sys.exit(codice)


def uso():
    testo = __doc__
    return testo[testo.index("Uso:"):].rstrip() + "\n"


def prepara_ambiente():
    """PATH con l'FFmpeg portatile (strumenti/ffmpeg/bin) e output UTF-8 senza buffer."""
    if FFMPEG_PORTATILE.is_dir():
        os.environ["PATH"] = str(FFMPEG_PORTATILE) + os.pathsep + os.environ.get("PATH", "")
        if WINDOWS:
            try:
                os.add_dll_directory(str(FFMPEG_PORTATILE))
            except OSError:
                pass
    if MACOS:  # ffmpeg/ffprobe di Homebrew, anche se il Terminale non ha caricato il profilo
        os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + "/opt/homebrew/bin" + os.pathsep + "/usr/local/bin"
    # Telemetria di pyannote disattivata (è attiva di default)
    os.environ["PYANNOTE_METRICS_ENABLED"] = "0"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    # Output di Python senza buffer e in UTF-8 (su Windows il predefinito è cp1252)
    os.environ["PYTHONUNBUFFERED"] = "1"
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    for flusso in (sys.stdout, sys.stderr):
        try:
            flusso.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def leggi_argomenti(argv):
    opzioni = {"input": "", "modello": "large-v3-turbo", "online": False, "diarize": False,
               "speakers": "", "verifica": True, "parole": "", "precisione": "float32"}
    i = 0

    def valore(nome):
        if i + 1 >= len(argv):
            errore(f"Errore: {nome} richiede un valore")
        return argv[i + 1]

    while i < len(argv):
        a = argv[i]
        if a == "--online":
            opzioni["online"] = True
        elif a in ("--offline", "--verifica"):
            pass  # già il comportamento predefinito
        elif a == "--diarize":
            opzioni["diarize"] = True
        elif a == "--senza-verifica":
            opzioni["verifica"] = False
        elif a in ("--speakers", "--parole"):
            opzioni[a[2:]] = valore(a)
            i += 1
        elif a == "--precisione":
            v = valore(a)
            if v not in ("int8", "float32"):
                errore("Errore: --precisione accetta int8 o float32")
            opzioni["precisione"] = v
            i += 1
        elif a in ("-h", "--help"):
            print(uso(), end="")
            sys.exit(0)
        elif a.startswith("-"):
            print(f"Errore: opzione sconosciuta {a}", file=sys.stderr, flush=True)
            print(uso(), end="", flush=True)
            sys.exit(1)
        elif not opzioni["input"]:
            opzioni["input"] = a
        else:
            opzioni["modello"] = a
        i += 1
    return opzioni


def python_venv():
    return PROGETTO / ".venv" / ("Scripts/python.exe" if WINDOWS else "bin/python")


def contieni_processi_windows():
    """Windows: mette questo processo in un Job Object «kill on close» prima di avviare
    qualunque figlio. I figli e i nipoti nascono già dentro il job, quindi quando
    trascrivi.py termina (fine, Annulla, chiusura della finestra) Windows chiude anche loro.
    Restituisce l'handle (da tenere aperto); se non ci riesce, la trascrizione non parte."""
    if not WINDOWS:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class Base(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class IoCounters(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount",
                        "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class Estesa(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Base), ("IoInfo", IoCounters),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.restype = wintypes.HANDLE
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k.GetCurrentProcess.restype = wintypes.HANDLE
        k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        job = k.CreateJobObjectW(None, None)
        if not job:
            raise OSError(ctypes.get_last_error(), "CreateJobObject")
        info = Estesa()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError(ctypes.get_last_error(), "SetInformationJobObject")
        if not k.AssignProcessToJobObject(job, k.GetCurrentProcess()):
            raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject")
        return job
    except Exception as e:
        errore(f"Errore: impossibile raggruppare i processi della trascrizione ({e}). Senza questo, "
               "un'interruzione potrebbe lasciare processi attivi: trascrizione non avviata.")


def sorveglia_interfaccia():
    """Se lanciato dall'interfaccia (WHISPERLOCAL_INTERFACCIA_PID), si ferma quando il server
    non c'è più, anche nelle fasi senza output: su Windows il Job Object chiude i figli,
    su macOS si termina l'intero gruppo di processi (whisperx compreso)."""
    try:
        pid = int(os.environ.get("WHISPERLOCAL_INTERFACCIA_PID", ""))
    except ValueError:
        return
    import threading

    def fine():
        if WINDOWS:
            os._exit(1)  # alla chiusura dell'handle il job termina whisperx e ffmpeg
        import signal
        try:
            os.killpg(os.getpgrp(), signal.SIGTERM)
        finally:
            os._exit(1)

    if WINDOWS:
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        SYNCHRONIZE = 0x00100000
        handle = k.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            fine()

        def attendi():
            k.WaitForSingleObject(handle, 0xFFFFFFFF)
            fine()
    else:
        def attendi():
            while True:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    fine()
                except PermissionError:
                    pass
                time.sleep(2)

    threading.Thread(target=attendi, daemon=True).start()


class Esecutore:
    def __init__(self, online):
        self.online = online
        self.python = python_venv()

    def comando(self, argomenti_python):
        """Comando Python sotto blocco della rete (salvo --online)."""
        if self.online:
            return [str(self.python), *argomenti_python]
        comando = [str(self.python), str(PROGETTO / "blocco_rete.py"), *argomenti_python]
        if MACOS:
            comando = ["sandbox-exec", "-p", PROFILO_SENZA_RETE, *comando]
        return comando

    def esegui(self, argomenti_python, log=None, ram_file=None):
        """Esegue e inoltra l'output (anche a log, come tee). Restituisce il codice d'uscita.
        Se chi legge il nostro output sparisce (interfaccia chiusa), ferma il figlio ed esce."""
        env = os.environ.copy()
        if ram_file:
            env["WHISPERLOCAL_RAM_FILE"] = str(ram_file)
        comando = self.comando(argomenti_python)
        if ram_file and self.online:  # anche con la rete consentita misuro la memoria
            comando = [str(self.python), str(PROGETTO / "blocco_rete.py"), "--senza-blocco", *argomenti_python]
        processo = subprocess.Popen(comando, stdout=subprocess.PIPE if log else None,
                                    stderr=subprocess.STDOUT if log else None,
                                    stdin=subprocess.DEVNULL, env=env, cwd=PROGETTO)
        if log:
            with open(log, "ab") as f:
                while True:
                    blocco = os.read(processo.stdout.fileno(), 65536)
                    if not blocco:
                        break
                    f.write(blocco)
                    f.flush()
                    try:
                        sys.stdout.buffer.write(blocco)
                        sys.stdout.buffer.flush()
                    except OSError:
                        processo.kill()
                        processo.wait()
                        sys.exit(1)
        return processo.wait()


def durata_audio(file):
    try:
        uscita = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                 "-of", "csv=p=0", str(file)], capture_output=True, text=True)
        return float(uscita.stdout.strip() or 0)
    except (OSError, ValueError):
        return 0.0


def sveglia_windows(attiva):
    """Impedisce lo stop del PC durante la trascrizione (come caffeinate -i su macOS)."""
    if not WINDOWS:
        return
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        stato = ES_CONTINUOUS | ES_SYSTEM_REQUIRED if attiva else ES_CONTINUOUS
        ctypes.windll.kernel32.SetThreadExecutionState(stato)
    except Exception:
        pass


def cartella_parziale(out):
    return out.parent / f".{out.name}.parziale"


def pubblica(parziale, cartella):
    """Porta nella cartella definitiva (nuova o vuota) un insieme di risultati finito.

    I file vengono spostati uno alla volta con os.replace e il JSON per ultimo: l'interfaccia
    riconosce una trascrizione dal JSON, quindi quando c'è il resto è già al suo posto."""
    cartella.mkdir(parents=True, exist_ok=True)
    file = sorted(parziale.iterdir(), key=lambda f: (f.suffix == ".json" and f.name != "da_verificare.json", f.name))
    for f in file:
        os.replace(f, cartella / f.name)
    parziale.rmdir()


def formato_riepilogo(durata, trascorso, ram_mb):
    d, e = durata, trascorso
    testo = f"Audio: {int(d // 60)} min {int(math.fmod(d, 60)):02d} s | Tempo: {e // 60} min {e % 60:02d} s"
    if e > 0:
        testo += f" | Velocità: {d / e:.1f}x tempo reale"
    testo += f" | RAM massima: {'' if ram_mb is None else f'{ram_mb:.0f}'} MB"
    return testo


def trascrivi(o, esecutore, nome, suffisso, durata, modello, con_diarize):
    """Trascrive con un modello nella cartella parziale (nascosta), run.log compreso.
    Restituisce (cartella definitiva, cartella parziale). Esce in caso di errore."""
    out = PROGETTO / "output" / f"{nome}_{modello}{suffisso}{'_diar' if con_diarize else ''}"
    parziale = cartella_parziale(out)
    if parziale.exists():
        shutil.rmtree(parziale)
    parziale.mkdir(parents=True)
    log = parziale / "run.log"

    argomenti = [o["input"], "--model", modello, "--language", "it", "--device", "cpu",
                 "--compute_type", o["precisione"], "--batch_size", "2", "--vad_method", "silero",
                 "--output_dir", str(out), "--output_format", "all", "--print_progress", "True"]
    if not o["online"]:
        argomenti += ["--model_cache_only", "True"]
    if o["parole"]:
        argomenti += ["--hotwords", o["parole"]]
    if con_diarize:
        argomenti.append("--diarize")
        if o["speakers"]:
            argomenti += ["--min_speakers", o["speakers"], "--max_speakers", o["speakers"]]

    if o["online"]:
        rete = "consentita"
    else:
        rete = "bloccata" if MACOS else "bloccata dal programma (Python; non copre codice nativo)"
    righe = [
        f"Data:        {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"File:        {o['input']}",
        f"Modello:     {modello}",
        f"Precisione:  {o['precisione']}",
        f"Parole:      {o['parole'] or 'nessuna'}",
        f"Rete:        {rete}",
        f"Diarize:     {'sì' if con_diarize else 'no'}",
    ]
    if con_diarize:
        righe.append(f"Interlocutori: {o['speakers'] or 'automatico'}")
    righe += [f"Comando:     whisperx {' '.join(argomenti)}", "----"]
    log.write_text("\n".join(righe) + "\n", encoding="utf-8", newline="\n")

    # La cartella vera passata a whisperx è quella parziale; nel log resta quella definitiva
    argomenti[argomenti.index("--output_dir") + 1] = str(parziale)
    with tempfile.TemporaryDirectory() as tmp:
        ram_file = Path(tmp) / "ram"
        inizio = time.monotonic()
        codice = esecutore.esegui(["-m", "whisperx", *argomenti], log=log, ram_file=ram_file)
        trascorso = int(time.monotonic() - inizio)
        try:
            ram_mb = float(ram_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            ram_mb = None
    if codice != 0:
        print(f"ERRORE: trascrizione con {modello} non completata. Dettagli in {log}", file=sys.stderr)
        if not o["online"]:
            print("Se il modello non è ancora stato scaricato, riprova una volta con --online",
                  file=sys.stderr)
        sys.exit(1)

    riepilogo = f"----\n{formato_riepilogo(durata, trascorso, ram_mb)}\nOutput: {out}\n"
    with open(log, "a", encoding="utf-8", newline="\n") as f:
        f.write(riepilogo)
    sys.stdout.write(riepilogo)
    sys.stdout.flush()
    return out, parziale


def main(argv):
    prepara_ambiente()
    o = leggi_argomenti(argv)
    if not o["input"]:
        print(uso(), end="")
        return 1
    if o["speakers"]:
        if not re.fullmatch(r"[1-9][0-9]?", o["speakers"]):
            errore("Errore: --speakers richiede un numero intero da 1 a 99")
        if not o["diarize"]:
            errore("Errore: --speakers richiede --diarize")
    if not os.path.isfile(o["input"]):
        errore(f"Errore: file non trovato: {o['input']}")
    esecutore = Esecutore(o["online"])
    if not esecutore.python.exists():
        errore(f"Errore: ambiente Python non trovato in {esecutore.python} (vedi README: installazione)")
    # Percorso assoluto, così il run.log indica sempre dove sta l'audio (serve all'interfaccia)
    o["input"] = os.path.abspath(o["input"])

    nome = os.path.basename(o["input"])
    if "." in nome:
        nome = nome.rsplit(".", 1)[0]
    suffisso = ("_int8" if o["precisione"] == "int8" else "") + ("_parole" if o["parole"] else "")

    if not o["online"]:
        if MACOS and not shutil.which("sandbox-exec"):
            errore("Errore: sandbox-exec non disponibile, impossibile bloccare la rete")
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        errore("Errore: ffmpeg/ffprobe non trovati. Installali (vedi README) oppure mettili in "
               f"{FFMPEG_PORTATILE}")

    # Mai mescolare risultati nuovi con quelli di una trascrizione precedente con lo stesso nome
    modelli = [(o["modello"], o["diarize"])]
    if o["verifica"]:
        modelli.append(("large-v3-turbo" if o["modello"] == "medium" else "medium", False))
    for modello, con_diarize in modelli:
        out = PROGETTO / "output" / f"{nome}_{modello}{suffisso}{'_diar' if con_diarize else ''}"
        if out.is_dir() and any(out.iterdir()):
            errore(f"Errore: esistono già risultati in {out}. Rinomina il file audio (o sposta quella "
                   "cartella) e riprova: i risultati precedenti non vengono sovrascritti.")

    job = contieni_processi_windows()  # noqa: F841 (resta aperto fino all'uscita)
    sorveglia_interfaccia()
    sveglia_windows(True)
    try:
        if o["diarize"]:
            print("Controllo del modello interlocutori...", flush=True)
            codice = esecutore.esegui([str(PROGETTO / "prepara_speaker.py"), *(["--online"] if o["online"] else [])])
            if codice != 0:
                return codice

        durata = durata_audio(o["input"])
        principale, parziale = trascrivi(o, esecutore, nome, suffisso, durata, o["modello"], o["diarize"])
        if not o["verifica"]:
            pubblica(parziale, principale)
            return 0

        # medium sbaglia in modo diverso da turbo, quindi i disaccordi fanno emergere gli errori.
        # La trascrizione principale viene pubblicata solo insieme al suo da_verificare:
        # una verifica interrotta non lascia mai una trascrizione che sembra «senza verifica».
        secondo = "large-v3-turbo" if o["modello"] == "medium" else "medium"
        print(f"==== Secondo parere con {secondo} ====", flush=True)
        confronto, parziale_confronto = trascrivi(o, esecutore, nome, suffisso, durata, secondo, False)
        codice = esecutore.esegui([str(PROGETTO / "segnala.py"), str(principale / f"{nome}.json"),
                                   "--leggi-da", str(parziale / f"{nome}.json"), "--uscita", str(parziale),
                                   "--confronta", str(confronto / f"{nome}.json"),
                                   "--confronta-leggi-da", str(parziale_confronto / f"{nome}.json")])
        if codice != 0:
            print(f"ERRORE: controllo degli errori non completato; i risultati restano in {parziale} "
                  f"e {parziale_confronto}", file=sys.stderr)
            return codice
        # Il secondo parere per primo (resta nascosto dall'archivio appena c'è il principale,
        # che arriva subito dopo con il suo da_verificare)
        pubblica(parziale_confronto, confronto)
        pubblica(parziale, principale)
        return 0
    finally:
        sveglia_windows(False)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
