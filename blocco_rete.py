"""Esegue uno script o un modulo Python senza accesso a internet.

Uso:
  python blocco_rete.py -m whisperx <argomenti>
  python blocco_rete.py segnala.py <argomenti>

Blocco a livello di programma (audit hook di Python, non rimovibile una volta installato):
  - connessioni e invii verso indirizzi che non siano questo computer (IPv4 e IPv6);
  - risoluzione di nomi diversi da localhost (nessuna richiesta DNS esce);
  - avvio di programmi esterni, salvo ffmpeg/ffprobe con le sole opzioni usate da WhisperX su
    file locali esistenti (niente URL, cartelle di rete \\\\server, protocolli come "tcp:",
    script di filtri o playlist) e uname.

Limite dichiarato: il codice nativo (librerie C/C++) che aprisse connessioni senza passare
da Python non è coperto. Su macOS trascrivi.py aggiunge sopra il blocco del sistema
(sandbox-exec), che copre anche quello. Su Windows un blocco di sistema richiederebbe
una regola del Firewall (amministratore) o un AppContainer (possibile sviluppo futuro).

Con la variabile WHISPERLOCAL_RAM_FILE, all'uscita scrive lì la memoria massima usata (MB).
Con --senza-blocco come primo argomento misura solo la memoria (usato da trascrivi.py --online).
"""

import atexit
import errno
import ipaddress
import os
import re
import runpy
import socket
import sys

NOMI_LOCALI = {"localhost", "localhost.localdomain", "ip6-localhost", ""}
PROGRAMMI_AMMESSI = {"ffmpeg", "ffprobe", "uname"}  # uname: platform.processor() su macOS/Linux


class ReteBloccata(PermissionError):
    pass


def indirizzo_locale(host):
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    host = str(host).strip().lower().strip("[]").split("%")[0]  # IPv6 con zona: fe80::1%en0
    if host in NOMI_LOCALI:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def destinazione_locale(indirizzo):
    # AF_UNIX (percorso su disco) è comunicazione locale tra processi
    if isinstance(indirizzo, (str, bytes)):
        return True
    if isinstance(indirizzo, tuple) and indirizzo:
        return indirizzo_locale(indirizzo[0])
    return False


def nome_programma(eseguibile, argomenti):
    voce = eseguibile
    if voce is None and argomenti:
        voce = argomenti[0] if isinstance(argomenti, (list, tuple)) else str(argomenti).split()[0]
    nome = os.fsdecode(voce or "").strip().strip('"').replace("\\", "/").rsplit("/", 1)[-1].lower()
    return nome[:-4] if nome.endswith(".exe") else nome


# ffmpeg/ffprobe possono leggere da URL, cartelle di rete (\\\\server\\...) e protocolli
# ("tcp:", "concat:", ...): sono ammessi solo su file locali esistenti, con formati d'uscita
# semplici e senza opzioni sui protocolli.
PROTOCOLLO = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]+:")  # "C:\\..." (una lettera) è un disco, non un protocollo
FORMATI_AMMESSI = {"s16le", "f32le", "wav"}


def _testo(a):
    return os.fsdecode(a).strip().strip('"') if isinstance(a, (str, bytes, os.PathLike)) else str(a)


def file_locale(percorso):
    if percorso.startswith(("\\\\", "//")):  # UNC: \\server\cartella
        return False
    return os.path.isfile(percorso) and not os.path.realpath(percorso).startswith(("\\\\", "//"))


# Solo le opzioni che servono davvero (whisperx: decodifica in s16le su stdout; ffprobe: durata).
# Ogni altra opzione è rifiutata: niente -filter_script, filtri con file, playlist, protocolli.
OPZIONI_FFMPEG = {"-nostdin": 0, "-hide_banner": 0, "-y": 0, "-vn": 0, "-threads": 1, "-v": 1,
                  "-loglevel": 1, "-i": 1, "-f": 1, "-ac": 1, "-acodec": 1, "-ar": 1}
OPZIONI_FFPROBE = {"-version": 0, "-hide_banner": 0, "-v": 1, "-loglevel": 1, "-show_entries": 1,
                   "-of": 1, "-print_format": 1, "-select_streams": 1}
VALORE_SEMPLICE = re.compile(r"^[A-Za-z0-9_.=,:-]+$")  # es. "error", "format=duration", "csv=p=0", "16000"


def argomenti_locali(nome, elenco):
    opzioni = OPZIONI_FFMPEG if nome == "ffmpeg" else OPZIONI_FFPROBE
    resto = elenco[1:]
    i = 0
    liberi = []
    while i < len(resto):
        a = resto[i]
        if "://" in a or a.startswith(("\\\\", "//")) or PROTOCOLLO.match(a):
            return False
        if a.startswith("-") and a != "-":
            if a not in opzioni:
                return False
            if opzioni[a]:
                if i + 1 >= len(resto):
                    return False
                valore = resto[i + 1]
                if a == "-i":
                    if not file_locale(valore):
                        return False
                elif a == "-f":
                    if valore not in FORMATI_AMMESSI:
                        return False
                elif not VALORE_SEMPLICE.match(valore) or PROTOCOLLO.match(valore):
                    return False
                i += 2
                continue
        else:
            liberi.append(a)
        i += 1
    if nome == "ffmpeg":
        return all(a == "-" for a in liberi)  # unica uscita ammessa: lo stdout
    return all(file_locale(a) for a in liberi)  # ffprobe: solo file locali


def programma_ammesso(eseguibile, argomenti):
    nome = nome_programma(eseguibile, argomenti)
    if nome not in PROGRAMMI_AMMESSI:
        return False
    elenco = [_testo(a) for a in (argomenti if isinstance(argomenti, (list, tuple)) else [argomenti])]
    if nome == "uname":
        return all(a.startswith("-") for a in elenco[1:])
    return argomenti_locali(nome, elenco)


def blocca(evento, motivo):
    raise ReteBloccata(errno.EPERM, f"WhisperLocal: {motivo} bloccato senza --online ({evento})")


def controllo(evento, argomenti):
    if evento in ("socket.connect", "socket.sendto", "socket.sendmsg"):
        if len(argomenti) > 1 and argomenti[1] is not None and not destinazione_locale(argomenti[1]):
            blocca(evento, "accesso alla rete")
    elif evento in ("socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyname_ex",
                    "socket.gethostbyaddr", "socket.getnameinfo"):
        host = argomenti[0] if argomenti else None
        if evento == "socket.getnameinfo" and isinstance(host, tuple):
            host = host[0]
        if not indirizzo_locale(host):
            raise socket.gaierror(socket.EAI_NONAME, f"WhisperLocal: risoluzione di nomi bloccata senza --online ({evento})")
    elif evento == "subprocess.Popen":
        if not programma_ammesso(argomenti[0], argomenti[1]):
            blocca(evento, f"avvio di «{nome_programma(argomenti[0], argomenti[1])}»")
    elif evento == "_winapi.CreateProcess":  # Windows: (nome applicazione, riga di comando, cartella)
        riga = argomenti[1] if len(argomenti) > 1 else None
        parti = _dividi_riga_windows(riga) if riga else []
        if not programma_ammesso(argomenti[0], parti or [argomenti[0]]):
            blocca(evento, "avvio di un programma esterno")
    elif evento in ("os.exec", "os.posix_spawn"):  # (percorso, argomenti, ambiente)
        if not programma_ammesso(argomenti[0], argomenti[1]):
            blocca(evento, "avvio di un programma esterno")
    elif evento == "os.spawn":  # (modo, percorso, argomenti, ambiente)
        if not programma_ammesso(argomenti[1], argomenti[2]):
            blocca(evento, "avvio di un programma esterno")
    elif evento in ("os.system", "os.startfile", "os.forkpty"):
        blocca(evento, "avvio di un programma esterno")


def _dividi_riga_windows(riga):
    """Primo elemento e argomenti di una riga di comando Windows (virgolette semplici)."""
    import shlex
    try:
        return shlex.split(riga, posix=False)
    except ValueError:
        return riga.split()


def memoria_massima_mb():
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class Contatori(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

            c = Contatori()
            c.cb = ctypes.sizeof(c)
            kernel32 = ctypes.WinDLL("kernel32")
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi = ctypes.WinDLL("psapi")
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
            if psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb):
                return c.PeakWorkingSetSize / 1048576
            return None
        import resource
        massimo = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return massimo / 1048576 if sys.platform == "darwin" else massimo / 1024  # byte su macOS, KB su Linux
    except Exception:
        return None


def scrivi_memoria():
    destinazione = os.environ.get("WHISPERLOCAL_RAM_FILE")
    mb = memoria_massima_mb()
    if destinazione and mb is not None:
        try:
            with open(destinazione, "w", encoding="utf-8") as f:
                f.write(f"{mb}\n")
        except OSError:
            pass


def installa():
    sys.addaudithook(controllo)


def main():
    argomenti = sys.argv[1:]
    if not argomenti or argomenti[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argomenti else 2
    atexit.register(scrivi_memoria)
    # Windows: le DLL di FFmpeg portatile (strumenti/ffmpeg/bin) per chi le carica (TorchCodec)
    ffmpeg_portatile = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strumenti", "ffmpeg", "bin")
    if sys.platform == "win32" and os.path.isdir(ffmpeg_portatile):
        try:
            os.add_dll_directory(ffmpeg_portatile)
        except OSError:
            pass
    if argomenti[0] == "--senza-blocco":  # solo misura della memoria (trascrivi.py --online)
        argomenti = argomenti[1:]
    else:
        installa()
    if argomenti[0] == "-m":
        if len(argomenti) < 2:
            print("Errore: -m richiede il nome di un modulo", file=sys.stderr)
            return 2
        sys.argv = [argomenti[1], *argomenti[2:]]
        runpy.run_module(argomenti[1], run_name="__main__", alter_sys=True)
    else:
        script = os.path.abspath(argomenti[0])
        sys.argv = [script, *argomenti[1:]]
        sys.path[0] = os.path.dirname(script)
        runpy.run_path(script, run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
