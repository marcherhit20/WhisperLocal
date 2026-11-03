"""Scarica (solo con --online) o controlla offline il modello degli interlocutori.

Il login viene letto dalla configurazione Hugging Face, mai da argomenti o log.
Non apre registrazioni e non esegue inferenza.
"""

import argparse
import os
import sys

MODELLO = "pyannote/speaker-diarization-community-1"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--online", action="store_true", help="consente il download iniziale")
    args = parser.parse_args()
    os.environ["PYANNOTE_METRICS_ENABLED"] = "0"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    if not args.online:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

    try:
        from pyannote.audio import Pipeline

        pipeline = Pipeline.from_pretrained(MODELLO)
        if pipeline is None:
            raise RuntimeError("Modello non caricato")
    except Exception:
        if args.online:
            messaggio = (
                "Errore interlocutori: impossibile scaricare o caricare il modello. "
                "Controlla la connessione, accetta le condizioni su "
                f"https://huggingface.co/{MODELLO} e accedi con hf auth login dall'ambiente .venv "
                "(vedi ISTRUZIONI.md)."
            )
        else:
            messaggio = (
                "Errore interlocutori: modello non disponibile offline. "
                "Completa il login Hugging Face, poi esegui dalla cartella del progetto "
                "prepara_speaker.py --online con il Python di .venv (vedi ISTRUZIONI.md)."
            )
        print(messaggio, file=sys.stderr, flush=True)
        return 1
    print("Modello interlocutori pronto.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
