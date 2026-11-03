#!/bin/bash
# Trascrizione locale con WhisperX: lanciatore macOS di trascrivi.py (stesse opzioni).
# Aiuto completo: ./trascrivi.sh --help
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/.venv/bin/python" "$DIR/trascrivi.py" "$@"
