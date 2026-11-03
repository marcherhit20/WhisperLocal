# WhisperLocal

Trascrizione **locale** di registrazioni audio e video in italiano, con i tempi, su
macOS e Windows. Usa [WhisperX](https://github.com/m-bain/whisperX) sul processore
(non serve una scheda grafica): le registrazioni non lasciano mai il computer.

- Testo con i tempi in TXT, SRT, VTT, TSV e JSON (tempi di ogni parola).
- **Secondo parere automatico**: un secondo modello (`medium`) ritrascrive l'audio e
  `segnala.py` elenca i punti da riascoltare (`da_verificare.txt`): allucinazioni,
  parole inesistenti, disaccordi tra i modelli.
- **Interfaccia nel browser** (solo locale, 127.0.0.1): caricamento, avanzamento,
  ascolto dei punti dubbi con l'audio sincronizzato e correzione del testo.
- Facoltativo: distinzione di chi parla (pyannote; da preparare a parte, non ancora
  provata con il modello reale).

La guida d'uso completa è in [ISTRUZIONI.md](ISTRUZIONI.md).

## Privacy e blocco della rete

Durante la trascrizione la rete è bloccata e i modelli vengono letti solo dalla cache:

| Sistema | Come | Cosa copre |
|---|---|---|
| macOS | `sandbox-exec` (sistema operativo) + `blocco_rete.py` | tutti i processi della trascrizione |
| Windows | `blocco_rete.py` (nel programma) | tutto ciò che passa da Python: connessioni IPv4/IPv6, richieste DNS, avvio di programmi (ammessi solo ffmpeg/ffprobe su file locali) |

**Limite su Windows:** il blocco è a livello di programma, non di sistema. Codice
nativo (C/C++) di una libreria che aprisse connessioni da solo non verrebbe fermato;
oggi non risulta che le librerie usate (torch, ctranslate2, …) lo facciano. Il
`run.log` di ogni trascrizione lo dichiara (`Rete: bloccata dal programma (Python; non copre codice nativo)`).
Per un blocco di sistema servono i diritti di amministratore (una regola del Firewall
in uscita sull'eseguibile Python dell'ambiente). Possibile sviluppo futuro, non
realizzato: eseguire la trascrizione in un **AppContainer** di Windows senza permesso
di rete, che non richiede l'amministratore ma richiede permessi espliciti su ogni
cartella usata (progetto, Python, cache dei modelli, registrazioni).

La rete serve solo una volta, per scaricare i modelli (`prepara_modelli.py --online`),
e quel comando non apre nessuna registrazione. L'opzione `--online` di `trascrivi`
invece toglie il blocco per tutta quella trascrizione: serve solo per scaricare un modello
non predefinito e va evitata con registrazioni riservate.

## Requisiti

- Python **3.11** (64 bit; provato con 3.11. Le versioni 3.10–3.13 dovrebbero funzionare,
  la **3.14 no**: WhisperX 3.8.6 non la supporta. Più versioni di Python convivono senza
  problemi: se hai già la 3.14 aggiungi la 3.11 e usa `py -3.11`)
- FFmpeg (`ffmpeg` e `ffprobe`)
- circa 8 GB di RAM libera e 10 GB di disco (ambiente + modelli)

## Installazione su Windows (senza diritti di amministratore)

1. **Python 3.11**: da <https://www.python.org/downloads/windows/> scarica
   l'installer *Windows installer (64-bit)* di Python 3.11 (es. 3.11.9) e installalo
   per il solo utente ("Install for current user", lascia attivo "py launcher").
2. **Scarica WhisperLocal**: su GitHub, *Code → Download ZIP*, ed estrai la cartella
   dove vuoi tenerla (non spostarla più dopo l'installazione). In alternativa
   `git clone`.
3. **FFmpeg**: scarica `ffmpeg-n7.1-latest-win64-gpl-shared-7.1.zip` da
   <https://github.com/BtbN/FFmpeg-Builds/releases/tag/latest>, estrailo e rinomina
   la cartella in modo da avere `strumenti\ffmpeg\bin\ffmpeg.exe` dentro WhisperLocal.
   (Se `ffmpeg` è già installato e nel PATH, puoi saltare questo passo.)
4. Doppio clic su **`installa.bat`**: crea `.venv` e installa i pacchetti con le
   versioni di `requirements.txt` (alcuni GB, diversi minuti). Su una rete aziendale
   pip può richiedere il proxy: `set HTTPS_PROXY=http://indirizzo:porta` nella stessa
   finestra prima di lanciare `installa.bat`.
5. **Modelli**, una volta sola e con internet: apri il Prompt dei comandi nella
   cartella (scrivi `cmd` nella barra di Esplora risorse) ed esegui
   ```
   .venv\Scripts\python.exe prepara_modelli.py --online
   ```
6. Doppio clic su **`WhisperLocal.bat`**: si apre la pagina nel browser.

Riga di comando: `trascrivi.bat input\registrazione.mp3` (aiuto: `trascrivi.bat --help`).

### In alternativa, da Visual Studio Code

Al posto dei `.bat` si può fare tutto dal terminale integrato di VS Code
(*Terminal → New Terminal*), nella cartella del progetto:

```
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe prepara_modelli.py --online
```

Poi, ogni volta: `.\.venv\Scripts\python.exe interfaccia.py` (si apre la pagina nel
browser; Ctrl+C o la chiusura del terminale fermano tutto, anche una trascrizione in corso).
Non serve attivare l'ambiente con `Activate.ps1`, spesso bloccato sui PC aziendali.
FFmpeg va comunque messo in `strumenti\ffmpeg\bin` (passo 3) se non è installato.

## Installazione su macOS

```bash
brew install python@3.11 ffmpeg
cd WhisperLocal
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python prepara_modelli.py --online
```

Poi doppio clic su `WhisperLocal.command`, oppure `./trascrivi.sh input/registrazione.mp3`.

## File principali

| File | Ruolo |
|---|---|
| `trascrivi.py` | trascrizione (modello principale + secondo parere + `segnala.py`), con la rete bloccata |
| `blocco_rete.py` | blocco della rete nel programma e misura della memoria |
| `segnala.py` | elenco dei punti da riascoltare |
| `interfaccia.py`, `interfaccia/` | server locale e pagina nel browser |
| `prepara_modelli.py`, `prepara_speaker.py` | download (con `--online`) e controllo offline dei modelli |
| `trascrivi.sh`, `WhisperLocal.command` | lanciatori macOS |
| `trascrivi.bat`, `WhisperLocal.bat`, `installa.bat` | lanciatori e installazione Windows |
| `test_*.py` | test (`python -m unittest -v`) |
| `.github/workflows/windows.yml` | prova automatica su Windows: installazione, test e una trascrizione completa offline |

Le cartelle `input/` (registrazioni) e `output/` (trascrizioni) non sono mai
incluse nel repository.
