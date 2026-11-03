"""Scarica (solo con --online) o controlla offline i modelli della trascrizione.

Uso:
  python prepara_modelli.py --online    primo avvio su un computer nuovo (serve internet)
  python prepara_modelli.py             controllo offline: i modelli ci sono tutti?

Modelli: large-v3-turbo e medium (faster-whisper), VAD silero, allineamento italiano
(torchaudio VOXPOPULI) e il divisore di frasi di nltk (punkt_tab). Nessuna registrazione
viene aperta: durante il download non esce nessun audio dal computer.
Il modello degli interlocutori (facoltativo) si prepara a parte con prepara_speaker.py.
"""

import argparse
import gc
import os
import sys

MODELLI = ("large-v3-turbo", "medium")


def passo(testo):
    print(testo, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--online", action="store_true", help="consente il download iniziale")
    args = parser.parse_args()
    os.environ["PYANNOTE_METRICS_ENABLED"] = "0"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    if not args.online:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

    try:
        import nltk
        import whisperx

        for modello in MODELLI:
            passo(f"Modello {modello} e VAD silero...")
            m = whisperx.load_model(modello, "cpu", compute_type="float32", language="it",
                                    vad_method="silero", local_files_only=not args.online)
            del m
            gc.collect()
        passo("Modello di allineamento italiano...")
        allineamento, _ = whisperx.load_align_model(language_code="it", device="cpu",
                                                     model_cache_only=not args.online)
        del allineamento
        passo("Divisore di frasi (nltk punkt_tab)...")
        try:
            nltk.data.find("tokenizers/punkt_tab")
        except LookupError:
            if not args.online or not nltk.download("punkt_tab", quiet=True):
                raise
    except Exception as e:
        if args.online:
            messaggio = ("Errore modelli: download non riuscito. Controlla la connessione "
                         f"(proxy aziendale?) e riprova. Dettaglio: {type(e).__name__}: {e}")
        else:
            messaggio = ("Errore modelli: non tutti i modelli sono disponibili offline. "
                         "Esegui una volta: python prepara_modelli.py --online. "
                         f"Dettaglio: {type(e).__name__}: {e}")
        print(messaggio, file=sys.stderr, flush=True)
        return 1
    passo("Modelli pronti: da ora la trascrizione funziona senza internet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
