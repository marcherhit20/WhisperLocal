"""Segnala le parole da ricontrollare in una trascrizione WhisperX.

Uso:
  python segnala.py <trascrizione.json> [--confronta <altra_trascrizione.json>] [--soglia 2.5]

Esempi:
  python segnala.py output/prova1_large-v3/prova1.json
  python segnala.py output/prova1_large-v3/prova1.json \
      --confronta output/prova1_large-v3-turbo/prova1.json

Criteri:
  1. frasi ripetute in loop (allucinazioni: il parlato reale lì può mancare);
  2. parole sconosciute o rare in italiano (frequenze di wordfreq, funziona offline);
  3. con --confronta: punti in cui un secondo modello ha trascritto in modo diverso.

Scrive da_verificare.txt nella cartella della trascrizione, e da_verificare.json con gli
stessi punti per l'interfaccia.
Nessun criterio trova tutti gli errori: una parola sbagliata ma esistente,
scritta uguale da entrambi i modelli, non viene segnalata.
"""

import argparse
import difflib
import json
import os
import re
from pathlib import Path

from wordfreq import zipf_frequency

CONTESTO = 5  # parole mostrate prima e dopo il punto segnalato

# Articoli, preposizioni e congiunzioni: un disaccordo solo su queste è un controllo minore.
# "non" è escluso di proposito perché cambia il significato.
FUNZIONALI = {
    "", "i", "il", "lo", "la", "le", "l'", "gli", "un", "uno", "una", "un'",
    "a", "ad", "al", "allo", "alla", "ai", "agli", "alle", "e", "ed", "o",
    "di", "del", "dello", "della", "dei", "degli", "delle", "dell'",
    "da", "dal", "dallo", "dalla", "dai", "dagli", "dalle",
    "in", "nel", "nello", "nella", "nei", "negli", "nelle",
    "su", "sul", "sullo", "sulla", "sui", "sugli", "sulle", "per", "con", "tra", "fra", "che",
}

# Intercalari del parlato: un disaccordo solo su questi (più FUNZIONALI) è un controllo minore
RIEMPITIVI = {
    "eh", "ehm", "ehh", "mh", "mhm", "uhm", "ah", "oh", "beh", "boh", "diciamo", "magari", "cioè",
    "insomma", "ecco", "allora", "quindi", "comunque", "ok", "okay", "però", "poi", "anche",
    "proprio", "appunto", "praticamente", "sostanzialmente", "niente", "tipo", "così", "senso",
    "realtà", "vabbè", "va", "bene", "sì", "esatto", "certo", "perfetto", "io",
}

# Numeri in lettere -> cifre, così "cinque" e "5" non risultano in disaccordo
NUMERI = {
    "zero": "0", "uno": "1", "due": "2", "tre": "3", "quattro": "4", "cinque": "5", "sei": "6",
    "sette": "7", "otto": "8", "nove": "9", "dieci": "10", "undici": "11", "dodici": "12",
    "tredici": "13", "quattordici": "14", "quindici": "15", "sedici": "16", "diciassette": "17",
    "diciotto": "18", "diciannove": "19", "venti": "20", "trenta": "30", "quaranta": "40",
    "cinquanta": "50", "sessanta": "60", "settanta": "70", "ottanta": "80", "novanta": "90",
    "cento": "100",
}


def carica_parole(percorso):
    with open(percorso, encoding="utf-8") as f:
        dati = json.load(f)
    parole = dati["word_segments"]
    # Le parole non allineabili (es. numeri) non hanno "start": uso l'ultimo tempo noto
    ultimo = 0.0
    for p in parole:
        ultimo = p.get("start", ultimo)
        p["t"] = ultimo
    return parole


def normalizza(parola):
    parola = parola.lower().replace("’", "'")
    return re.sub(r"^[^\w']+|[^\w']+$", "", parola)


def per_confronto(parola):
    parola = normalizza(parola)
    return NUMERI.get(parola, parola)


def disaccordo_minore(a, b, i1, i2, j1, j2):
    """Vero se il disaccordo riguarda solo articoli/intercalari, o se le parole
    presenti in un solo modello ripetono parole vicine (es. "magari magari")."""
    if set(a[i1:i2] + b[j1:j2]) <= FUNZIONALI | RIEMPITIVI:
        return True
    if i1 == i2:
        return set(b[j1:j2]) <= set(a[max(0, i1 - 3):i1 + 3])
    if j1 == j2:
        return set(a[i1:i2]) <= set(b[max(0, j1 - 3):j1 + 3])
    return False


def frequenza(parola):
    """Frequenza in scala Zipf: 0 = sconosciuta, 3 = rara, 5+ = comune.
    None se la parola non va valutata (numeri, vuota)."""
    # Per le forme elise ("dell'escalation") valuto la parola dopo l'apostrofo
    base = normalizza(parola).split("'")[-1]
    if not base or any(c.isdigit() for c in base):
        return None
    return zipf_frequency(base, "it")


MIN_RIPETIZIONI = 6  # una frase ripetuta almeno 6 volte di fila è un probabile loop


def trova_loop(seq):
    """Frasi di 1-4 parole ripetute almeno MIN_RIPETIZIONI volte di fila: è il modo
    tipico in cui Whisper "allucina" al posto del parlato reale.
    Restituisce (inizio, fine, frase, ripetizioni) in indici di parola."""
    trovati = []
    i = 0
    while i < len(seq):
        migliore = None
        for n in range(1, 5):
            k = 1
            while i + (k + 1) * n <= len(seq) and seq[i + k * n:i + (k + 1) * n] == seq[i:i + n]:
                k += 1
            if k >= MIN_RIPETIZIONI and (migliore is None or k * n > migliore[0] * migliore[1]):
                migliore = (k, n)
        if migliore:
            k, n = migliore
            trovati.append((i, i + k * n, " ".join(seq[i:i + n]), k))
            i += k * n
        else:
            i += 1
    return trovati


def accorcia(testo, massimo=150):
    return testo if len(testo) <= massimo else testo[:massimo] + "…"


def formatta_tempo(secondi):
    secondi = int(secondi)
    h, resto = divmod(secondi, 3600)
    m, s = divmod(resto, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def scrivi_atomico(percorso, testo):
    """Un'interruzione a metà non lascia mai un file incompleto al posto di quello finale."""
    temporaneo = percorso.with_name(f".{percorso.name}.tmp")
    with open(temporaneo, "w", encoding="utf-8", newline="\n") as f:
        f.write(testo)
    os.replace(temporaneo, percorso)


def main():
    parser = argparse.ArgumentParser(description="Segnala le parole da ricontrollare.")
    parser.add_argument("trascrizione", type=Path)
    parser.add_argument("--confronta", type=Path, help="JSON dello stesso audio prodotto da un altro modello")
    # Usati da trascrivi.py: legge il JSON ancora nella cartella parziale e scrive lì l'elenco,
    # che viene pubblicato insieme alla trascrizione; nei file resta il percorso definitivo.
    parser.add_argument("--leggi-da", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--uscita", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--confronta-leggi-da", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--soglia", type=float, default=2.5,
                        help="sotto questa frequenza una parola è considerata rara (default 2.5)")
    args = parser.parse_args()

    parole = carica_parole(args.leggi_da or args.trascrizione)
    a = [per_confronto(p["word"]) for p in parole]
    loop_principale = trova_loop(a)
    altre = carica_parole(args.confronta_leggi_da or args.confronta) if args.confronta else []

    # Punti segnalati: (inizio, fine) indici di parola -> {"motivi": [...], "alta": priorità alta?}
    segnalati = {}

    if args.confronta:
        b = [per_confronto(p["word"]) for p in altre]
        loop_altro = trova_loop(b)
        confronto = difflib.SequenceMatcher(None, a, b, autojunk=False)
        for op, i1, i2, j1, j2 in confronto.get_opcodes():
            if op == "equal":
                continue
            alternativa = accorcia(" ".join(p["word"] for p in altre[j1:j2]) or "(niente)")
            motivo = f"l'altro modello scrive: «{alternativa}»"
            # Se il disaccordo nasce da un loop del secondo modello, è lui a sbagliare
            errore_altro = any(l1 < max(j2, j1 + 1) and j1 < l2 for l1, l2, _, _ in loop_altro)
            if errore_altro:
                motivo += " (lì il secondo modello ripete in loop: probabilmente sbaglia lui)"
            segnalati[(i1, i2)] = {
                "motivi": [motivo],
                "alta": not errore_altro and not disaccordo_minore(a, b, i1, i2, j1, j2),
                "alternativa": " ".join(p["word"] for p in altre[j1:j2]),
            }

    for i, p in enumerate(parole):
        f = frequenza(p["word"])
        if f is None or f >= args.soglia:
            continue
        # Se la parola è già dentro un disaccordo, aggiungo il motivo a quel punto
        chiave = next(((i1, i2) for (i1, i2) in segnalati if i1 <= i < i2), (i, i + 1))
        punto = segnalati.setdefault(chiave, {"motivi": [], "alta": False})
        punto["motivi"].insert(0, "parola sconosciuta" if f == 0 else "parola rara o straniera")
        if f == 0:
            punto["alta"] = True

    # I punti dentro un loop della trascrizione principale sono già coperti dalla sezione allucinazioni
    for (i1, i2) in list(segnalati):
        if any(l1 < max(i2, i1 + 1) and i1 < l2 for l1, l2, _, _ in loop_principale):
            del segnalati[(i1, i2)]

    # Ogni punto diventa una voce: da qui si scrivono sia da_verificare.txt sia da_verificare.json
    # (usato dall'interfaccia). L'id dipende solo dalle posizioni, quindi resta uguale rigenerando.
    loop = []
    for l1, l2, frase, k in loop_principale:
        inizio, fine = parole[l1]["t"], parole[l2 - 1].get("end", parole[l2 - 1]["t"])
        stesso_tratto = " ".join(p["word"] for p in altre if inizio - 1 <= p["t"] <= fine + 1) if altre else None
        loop.append({
            "id": f"loop-{l1}-{l2}", "sezione": "allucinazione", "inizio": inizio, "fine": fine,
            "testo": frase, "ripetizioni": k, "alternativa": stesso_tratto,
        })

    def voce(i1, i2):
        indice_tempo = min(i1, len(parole) - 1)
        punto = segnalati[(i1, i2)]
        ultima = parole[i2 - 1] if i2 > i1 else parole[indice_tempo]
        return {
            "id": f"{i1}-{i2}",
            "sezione": "alta" if punto["alta"] else "bassa",
            "inizio": parole[indice_tempo]["t"],
            "fine": ultima.get("end", ultima["t"]),
            "testo": " ".join(p["word"] for p in parole[i1:i2]),
            "motivi": punto["motivi"],
            "alternativa": punto.get("alternativa"),
            "prima": " ".join(p["word"] for p in parole[max(0, i1 - CONTESTO):i1]),
            "dopo": " ".join(p["word"] for p in parole[i2:i2 + CONTESTO]),
        }

    alta = [voce(*k) for k in sorted(segnalati) if segnalati[k]["alta"]]
    bassa = [voce(*k) for k in sorted(segnalati) if not segnalati[k]["alta"]]
    riepilogo = (f"Punti segnalati: {len(loop)} possibili allucinazioni, "
                 f"{len(alta)} a priorità alta, {len(bassa)} a priorità bassa")

    righe_loop = []
    for v in loop:
        righe_loop.append(f"[{formatta_tempo(v['inizio'])} → {formatta_tempo(v['fine'])}] «{v['testo']}» "
                          f"ripetuto {v['ripetizioni']} volte: il parlato reale in questo tratto potrebbe mancare, riascoltare")
        if v["alternativa"] is not None:
            righe_loop.append(f"        l'altro modello qui scrive: «{accorcia(v['alternativa'] or '(niente)', 400)}»")

    def descrivi(v):
        testo = accorcia(v["testo"] or "(niente)")
        return [
            f"[{formatta_tempo(v['inizio'])}] «{testo}» — {'; '.join(v['motivi'])}",
            f"        …{v['prima']} «{testo}» {v['dopo']}…",
        ]

    righe = [
        f"DA VERIFICARE — {args.trascrizione}",
        f"Confronto con: {args.confronta}" if args.confronta else "Confronto con un altro modello: no",
        riepilogo,
        "Formato: [tempo] «testo trascritto» — motivo, poi il contesto.",
        "",
        "=== ⚠ POSSIBILI ALLUCINAZIONI: frasi ripetute in loop al posto del parlato ===",
        "",
    ]
    righe += righe_loop or ["Nessuna."]
    righe += [
        "",
        "=== PRIORITÀ ALTA: probabili errori (parole inesistenti o modelli in disaccordo) ===",
        "",
    ]
    for v in alta:
        righe += descrivi(v)
    righe += [
        "",
        "=== PRIORITÀ BASSA: parole rare o straniere, articoli, intercalari, ripetizioni ===",
        "",
    ]
    for v in bassa:
        righe += descrivi(v)

    uscita = (args.uscita or args.trascrizione.parent) / "da_verificare.txt"
    scrivi_atomico(uscita, "\n".join(righe) + "\n")
    dati = {
        "trascrizione": str(args.trascrizione),
        "confronto": str(args.confronta) if args.confronta else None,
        "riepilogo": {"allucinazioni": len(loop), "alta": len(alta), "bassa": len(bassa)},
        "voci": loop + alta + bassa,
    }
    scrivi_atomico(uscita.parent / "da_verificare.json", json.dumps(dati, ensure_ascii=False, indent=1) + "\n")
    print(riepilogo)
    print(f"Elenco scritto in: {args.trascrizione.parent / 'da_verificare.txt'}")


if __name__ == "__main__":
    main()
