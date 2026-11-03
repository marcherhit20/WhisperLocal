#!/bin/bash
# Doppio clic: apre l'interfaccia di WhisperLocal nel browser (http://127.0.0.1:8765).
# Lascia aperta la finestra del Terminale mentre la usi: chiudendola si ferma tutto,
# compresa un'eventuale trascrizione in corso.

PROJECT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
# ffmpeg/ffprobe di Homebrew, anche se il Terminale non ha caricato il profilo
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$PROJECT_DIR" || exit 1
exec "$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/interfaccia.py" "$@"
