# WhisperLocal — Istruzioni

## In breve

Trasforma un file audio o video (MP3, MP4, …) in testo italiano con i tempi,
tutto sul tuo computer (Mac o Windows): la registrazione non viene mai inviata su internet.
Ogni trascrizione viene ricontrollata da un secondo modello e produce un elenco
dei punti da riascoltare (`da_verificare.txt`).

Si usa in due modi: con l'**interfaccia** nel browser (consigliato: caricamento,
avanzamento, ascolto dei punti dubbi e correzione in un'unica pagina) oppure dalla
**riga di comando** con `trascrivi.sh` (Mac) o `trascrivi.bat` (Windows).

Installazione e primo download dei modelli: vedi `README.md`.


## Dove sta tutto

Tutti i percorsi sono relativi alla cartella del progetto (`WhisperLocal`).

| Cosa | Dove |
|---|---|
| **File da trascrivere** (li copi tu, o li carica l'interfaccia) | `input/` |
| **Risultati** | `output/NOMEFILE_large-v3-turbo/` |
| Secondo parere (serve solo alla verifica) | `output/NOMEFILE_medium/` |
| **Interfaccia (doppio clic)** | Mac: `WhisperLocal.command` · Windows: `WhisperLocal.bat` |
| Riga di comando | Mac: `trascrivi.sh` · Windows: `trascrivi.bat` (entrambi usano `trascrivi.py`) |
| Programma dell'interfaccia (non toccare) | `interfaccia.py` e la cartella `interfaccia/` |
| Script che crea l'elenco dei punti da verificare | `segnala.py` |
| Blocco della rete | `blocco_rete.py` (più `sandbox-exec` sul Mac) |
| Download e controllo dei modelli | `prepara_modelli.py`, `prepara_speaker.py` (interlocutori) |
| Ambiente Python (non toccare) | `.venv/` |
| FFmpeg portatile (solo Windows, facoltativo) | `strumenti/ffmpeg/bin/` |
| Modelli scaricati (large-v3-turbo, medium) | cartella utente: `.cache/huggingface/hub/` |
| Modelli per i tempi e per trovare il parlato | cartella utente: `.cache/torch/hub/` |

Se usi `--parole`, le cartelle dei risultati finiscono con `_parole`
(es. `output/NOMEFILE_large-v3-turbo_parole/`).

Dentro la cartella dei risultati trovi:

| File | Contenuto |
|---|---|
| `NOMEFILE.txt` | il testo, una frase per riga — **quello da leggere** |
| `NOMEFILE.srt` | testo con i tempi, formato sottotitoli |
| `NOMEFILE.vtt` | come .srt, formato per il web |
| `NOMEFILE.tsv` | testo con i tempi, apribile con Excel/Numbers |
| `NOMEFILE.json` | tutto, compresi i tempi di ogni parola (per programmi) |
| `da_verificare.txt` | **i punti da riascoltare** (vedi sotto) |
| `da_verificare.json` | gli stessi punti, letti dall'interfaccia |
| `run.log` | registro tecnico: impostazioni, rete, tempo impiegato, memoria |
| `NOMEFILE_corretto.txt` / `.srt` / `.json` | la versione corretta salvata dall'interfaccia (gli originali restano com'erano) |
| `ascolto.m4a` | solo per formati che il browser non legge: copia dell'audio usata dal lettore |

I file compaiono nella cartella tutti insieme, solo a trascrizione e verifica finite:
se la interrompi (Annulla, chiusura della finestra, stop del computer) non resta mai
un file a metà, e i risultati precedenti non vengono toccati. Il lavoro interrotto
resta in una cartella nascosta (`output/.NOMEFILE_….parziale`) che viene cancellata
al rilancio. Se dalla riga di comando trascrivi di nuovo un file con lo stesso nome,
il programma si ferma subito per non sovrascrivere né mescolare i risultati esistenti:
rinomina il file audio (o sposta la vecchia cartella) e riprova. L'interfaccia invece
sceglie da sola un nome libero (`_2`, `_3`, …).


## Come si usa con l'interfaccia (consigliato)

**1. Apri WhisperLocal** con un doppio clic su `WhisperLocal.command` (Mac) o
`WhisperLocal.bat` (Windows). Si apre una finestra del Terminale / Prompt dei
comandi (**lasciala aperta**: è il programma) e il browser sulla pagina
`http://127.0.0.1:8765`. Se è già aperto, si riapre solo la pagina.
Puoi trascinare il file nel Dock (Mac) o crearne un collegamento sul Desktop
(Windows: tasto destro → Mostra altre opzioni → Crea collegamento).

**2. Trascrivi.** Trascina uno o più file audio o video nel riquadro (oppure
cliccaci per sceglierli). Se conosci nomi o termini che compaiono, scrivili
separati da virgola: la pagina li trasforma da sola nella frase giusta. Premi
**Trascrivi**. I file vengono copiati in `input/` (se un nome esiste già, la
copia prende `_2`, `_3`, …) e trascritti uno alla volta.

Per separare gli interventi, seleziona **Distingui chi parla**. Il numero di
interlocutori parte da **2**; puoi cambiarlo (da 1 a 99) o lasciarlo vuoto per
farlo stimare automaticamente. Prima del primo utilizzo prepara il modello
come descritto in "Distinguere chi parla" qui sotto.

**3. Segui l'avanzamento.** Per ogni file vedi il passo (1 di 3 large-v3-turbo,
2 di 3 medium, 3 di 3 controllo errori), la fase con la percentuale, il tempo
trascorso e quello previsto (la stima è misurata su un Mac M4: su altri computer
può essere diversa). Puoi chiudere la scheda del browser: la trascrizione
continua finché la finestra resta aperta. Il computer non va in stop da solo
durante una trascrizione, ma non chiudere il coperchio del portatile.
**Annulla** ferma il lavoro.

**4. Verifica e correggi.** Apri la trascrizione (pulsante **Apri** alla fine,
oppure dall'**Archivio**). A sinistra c'è il testo, una frase per riga, con il
suo tempo; a destra i punti da verificare, divisi in Allucinazioni, Alta e Bassa.

| Cosa fai | Cosa succede |
|---|---|
| clic su un punto a destra | l'audio parte 2 secondi prima, la pagina va alla frase e seleziona la parola dubbia: scrivi per correggerla |
| casella accanto al punto | lo segni come controllato; quando tutti i punti di una frase sono controllati il bordo diventa verde |
| clic sul tempo di una frase | ascolti da lì |
| `Esc` | play/pausa (riprende un secondo prima, per non perdere parole) |
| **Copia** (nelle allucinazioni) | copia il testo del secondo modello, da incollare al posto della frase ripetuta |
| **Salva**, `⌘S` (Mac) o `Ctrl+S` (Windows) | scrive `NOMEFILE_corretto.txt`, `.srt` e `.json`; riaprendo la trascrizione riparti da lì |

Puoi cambiare la velocità di ascolto e disattivare "Segui l'audio" se non vuoi
che la pagina scorra da sola. Se esci con modifiche non salvate, la pagina chiede
conferma.

**5. Scarica i file** dall'**Archivio** (pulsante **Scarica**) oppure apri la
cartella con **Mostra nel Finder** (Mac) / **Mostra in Esplora risorse** (Windows).

**Per chiudere** chiudi la finestra del Terminale / Prompt dei comandi (sul Mac
conferma "Termina"): si ferma anche un'eventuale trascrizione in corso.

L'interfaccia usa sempre le impostazioni predefinite (large-v3-turbo con verifica
tramite medium). Per le altre opzioni usa la riga di comando come spiegato qui sotto.


## Come si usa dalla riga di comando

**1. Copia il file** da trascrivere nella cartella `input/`.

**2. Apri il terminale nella cartella del progetto:**
- Mac: Terminale (Spotlight: Cmd+Spazio, "Terminale"), poi `cd ` seguito dal
  percorso della cartella (puoi trascinare la cartella nella finestra);
- Windows: apri la cartella in Esplora risorse, scrivi `cmd` nella barra
  dell'indirizzo e premi Invio.

Poi:

```bash
./trascrivi.sh input/NOMEFILE.mp3        # Mac
trascrivi.bat input\NOMEFILE.mp3         # Windows
```

Sostituisci `NOMEFILE.mp3` con il nome vero del file. Va bene anche un video
(`.mp4`, `.mov`, …): non serve convertirlo. Negli esempi seguenti, su Windows
usa `trascrivi.bat` al posto di `./trascrivi.sh` e `\` al posto di `/`.

- **Il nome contiene spazi?** Mettilo tra virgolette:
  `./trascrivi.sh "input/Riunione 3 ottobre.mp4"`
- **Non sai il nome esatto?** Scrivi il comando con uno spazio finale e
  trascina il file nella finestra: il percorso si scrive da solo. Poi premi Invio.

**3. Se conosci nomi o termini** che compaiono (persone, aziende, sigle, termini
tecnici), aggiungili. Scrivili come una frase, con il punto finale, altrimenti
il testo esce senza punteggiatura:

```bash
./trascrivi.sh input/NOMEFILE.mp3 --parole "Termini: Mario Rossi, ETF obbligazionario, business case."
```

**4. Aspetta la fine.** Nella finestra scorre il testo man mano. Alla fine compare
un riepilogo come questo:

```
Audio: 54 min 19 s | Tempo: 8 min 20 s | ...
==== Secondo parere con medium ====
Audio: 54 min 19 s | Tempo: 12 min 19 s | ...
Punti segnalati: 1 possibili allucinazioni, 307 a priorità alta, 136 a priorità bassa
```

**5. Apri i risultati** con un doppio clic su `NOMEFILE.txt` e `da_verificare.txt`
nella cartella `output/NOMEFILE_large-v3-turbo/`.

Puoi correggere `NOMEFILE.txt` direttamente in un editor di testo, ma così le
correzioni non si riportano negli altri formati (.srt, .json, …). Con
l'interfaccia invece finiscono anche in `NOMEFILE_corretto.srt`.


## Come leggere da_verificare.txt

Ogni voce ha questo formato:

```
[03:41] «incartamente» — parola inesistente; l'altro modello scrive: «certamente»
        …va bene, ci sentiamo «incartamente» la prossima settimana per…
```

cioè: minuto, testo trascritto, motivo della segnalazione, e sotto il contesto.
Vai a quel minuto nell'audio, ascolta e correggi il `.txt` se serve.

Le sezioni, in ordine di importanza:

1. **⚠ POSSIBILI ALLUCINAZIONI** — il modello ha ripetuto una frase in loop
   (es. lo stesso nome 37 volte) al posto di quello che è stato detto davvero.
   Sotto c'è il testo scritto dal secondo modello per lo stesso tratto: di solito
   è quello giusto, copialo nella trascrizione. **Controllale sempre.**
2. **PRIORITÀ ALTA** — parole inesistenti o punti in cui i due modelli hanno
   capito cose diverse. Qui ci sono quasi tutti gli errori veri.
3. **PRIORITÀ BASSA** — parole rare o straniere su cui i modelli concordano,
   differenze di articoli, intercalari («diciamo», «eh») e ripetizioni.
   Da guardare solo se hai tempo.

Nessun controllo trova tutti gli errori: una parola sbagliata ma esistente,
scritta uguale da entrambi i modelli, non viene segnalata.


## Opzioni

| Opzione | A cosa serve |
|---|---|
| `--parole "Termini: a, b, c."` | nomi e termini attesi, per scriverli giusti (attenzione: possono causare allucinazioni, che però vengono segnalate) |
| `--senza-verifica` | salta il secondo modello: circa il doppio più veloce, ma non trova allucinazioni né parti mancanti |
| `--online` | consente internet, **solo** per scaricare un modello nuovo la prima volta (per i modelli predefiniti usa invece `prepara_modelli.py --online`) |
| `--precisione int8` | usa meno memoria; su Mac M4 è più lento, su processori Intel/AMD può essere più veloce: prova su un file breve |
| `--diarize` | distingue chi parla con etichette SPEAKER_00, SPEAKER_01, … (richiede la preparazione iniziale del modello) |
| `--speakers N` | con `--diarize`, imposta il numero noto di interlocutori (da 1 a 99); omettendolo, il modello lo stima |

Per vedere l'aiuto completo: `./trascrivi.sh --help` (Mac) o `trascrivi.bat --help` (Windows).

Modello usato: `large-v3-turbo` (scelto nelle prove del 2026-10-01: più preciso
di small e medium, e large-v3 non era migliore). Secondo parere: `medium`.


## Tempi indicativi

Misurati su un MacBook Air M4 il 2026-10-01 (su un PC Windows senza scheda
grafica dedicata possono essere anche molto più lunghi):

| Audio | Tempo totale (con verifica) |
|---|---|
| 4 minuti e mezzo | circa 2-3 minuti |
| 54 minuti | circa 20-25 minuti |

Con `--senza-verifica` il tempo si riduce a circa un terzo/metà.
La distinzione degli interlocutori richiede tempo aggiuntivo: quando è attiva,
la pagina mostra il tempo trascorso senza una stima del tempo totale.


## Privacy

- **La rete è bloccata** durante la trascrizione, in modo diverso sui due sistemi:
  - **Mac:** dal sistema operativo (`sandbox-exec`): nessun programma lanciato
    per la trascrizione può collegarsi a internet. Nel `run.log`: `Rete: bloccata`.
  - **Windows:** dal programma (`blocco_rete.py`): Python rifiuta ogni
    connessione e ogni richiesta DNS verso fuori dal computer, i modelli sono
    caricati solo dalla cache, e si possono avviare solo ffmpeg/ffprobe su file
    locali. **Limite:** codice nativo (C/C++) dentro una libreria che aprisse una
    connessione da solo non sarebbe fermato; oggi non risulta che le librerie usate
    lo facciano. Nel `run.log`: `Rete: bloccata dal programma (Python; non copre codice nativo)`.
    Per un blocco di sistema anche su Windows: chiedere all'IT una regola del
    Firewall che vieti le connessioni in uscita all'eseguibile Python di `.venv`
    (va verificato che copra anche il processo Python avviato da `.venv\Scripts\python.exe`);
    in futuro si potrebbe usare un AppContainer di Windows (vedi README).
- `--online` toglie il blocco della rete **per tutta quella trascrizione** (serve solo
  per un modello non predefinito mai scaricato). Per i modelli predefiniti usa invece
  `prepara_modelli.py --online`, che scarica e basta, senza aprire registrazioni.
- L'interfaccia è una pagina locale: risponde solo a questo computer (indirizzo
  127.0.0.1), non carica nulla da internet e non accetta comandi da altri siti
  aperti nel browser. I file caricati restano in `input/`.
- Il token Hugging Face per scaricare il modello degli interlocutori **non va mai** scritto in file del progetto,
  comandi o chat: si inserisce una volta con `hf auth login` dall'ambiente del
  progetto (Mac: `.venv/bin/hf auth login`, Windows: `.venv\Scripts\hf.exe auth login`).


## Attenzione

- **Non spostare e non rinominare la cartella del progetto** dopo l'installazione:
  l'ambiente Python `.venv` contiene il percorso della cartella scritto al suo
  interno. Se la sposti, cancella `.venv` e rifai l'installazione (README).
- All'avvio può comparire un lungo avviso «torchcodec is not installed correctly…»:
  è innocuo (WhisperX decodifica l'audio con ffmpeg), puoi ignorarlo.


## Problemi comuni

| Messaggio | Cosa fare |
|---|---|
| `Errore: esistono già risultati in …` | C'è già una trascrizione con quel nome: rinomina il file audio (es. `riunione_2.mp3`) o sposta la vecchia cartella da `output/`. |
| `Errore: file non trovato` | Controlla il nome (maiuscole, estensione) e che il file sia in `input/`. Se ci sono spazi, usa le virgolette o trascina il file nella finestra. |
| `Se il modello non è ancora stato scaricato, riprova una volta con --online` | Esegui una volta `prepara_modelli.py --online` (vedi README); per un modello non predefinito rilancia il comando con `--online`. |
| `Errore: ffmpeg/ffprobe non trovati` | Mac: `brew install ffmpeg`. Windows: vedi README, "FFmpeg". |
| `permission denied: ./trascrivi.sh` (Mac) | Esegui una volta `chmod +x trascrivi.sh` e riprova. |
| `command not found`, `no such file` o «non è riconosciuto come comando» | Probabilmente non sei nella cartella del progetto: spostati lì e riprova. |
| `WhisperLocal: ... bloccato senza --online` | Il blocco della rete ha fermato un tentativo di collegamento: di solito manca un modello. Esegui `prepara_modelli.py --online`. |
| Un tratto di testo è una frase ripetuta tante volte | È un'allucinazione: in cima a `da_verificare.txt` (o tra le Allucinazioni nell'interfaccia) trovi il testo corretto del secondo modello. |
| Nella pagina compare «Server chiuso: riapri WhisperLocal» | La finestra del programma è stata chiusa: riaprilo con un doppio clic. |
| Nella pagina: «Il modello non è ancora scaricato…» | Esegui una volta `prepara_modelli.py --online`; poi l'interfaccia funziona. |
| `Errore interlocutori: modello non disponibile offline` | Completa la preparazione nella sezione seguente. Il controllo avviene prima della trascrizione e non scarica nulla dalla pagina. |
| `Errore: la porta 8765 è occupata da un altro programma` | Un altro programma usa la stessa porta: chiudilo, oppure riavvia il computer. |


## Distinguere chi parla

Le etichette **SPEAKER_00, SPEAKER_01, …** distinguono le voci: non identificano
i nomi delle persone e valgono solo all'interno di quella registrazione.
Il riconoscimento può sbagliare, soprattutto quando le voci si sovrappongono:
riascolta i cambi di interlocutore. Le etichette compaiono nell'editor e nei
file TXT/SRT/JSON, anche dopo aver salvato le correzioni.
(Funzione facoltativa, non ancora provata con il modello reale.)

Serve, una volta sola:

1. creare un account gratuito su huggingface.co;
2. accettare le condizioni sulla [pagina del modello](https://huggingface.co/pyannote/speaker-diarization-community-1);
3. creare un token di tipo "Read" e inserirlo dalla cartella del progetto con
   `.venv/bin/hf auth login` (Mac) o `.venv\Scripts\hf.exe auth login` (Windows)
   (non aggiungerlo alle credenziali Git);
4. scaricare il modello con `.venv/bin/python prepara_speaker.py --online`
   (Windows: `.venv\Scripts\python.exe prepara_speaker.py --online`).

Il comando di preparazione non apre registrazioni: scarica e controlla solo
il modello. Dopo il download funzionerà offline come il resto.

Dalla pagina seleziona **Distingui chi parla** e avvia normalmente.
Dalla riga di comando, per una registrazione con due persone:

```bash
./trascrivi.sh input/registrazione.mp3 --diarize --speakers 2
```

I risultati vanno in una cartella con suffisso `_diar`, separata dalla
trascrizione senza interlocutori. Il secondo modello continua a controllare
il testo e non ripete la distinzione delle voci.
