"""Regressioni degli interlocutori: upload, comando offline, correzioni e CLI."""

import asyncio
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import interfaccia as ui


class Parte:
    def __init__(self, name, value, filename=None):
        self.name, self.value, self.filename = name, value, filename

    async def text(self):
        return self.value

    async def read_chunk(self, size):
        value, self.value = self.value, b""
        return value


class SpeakerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for nome, valore in (("INPUT", self.root / "input"), ("OUTPUT", self.root / "output")):
            p = patch.object(ui, nome, valore)
            p.start()
            self.addCleanup(p.stop)
        self.app = {"lavori": [], "coda": asyncio.Queue()}

    async def carica(self, campi):
        async def parti():
            # Le opzioni possono arrivare anche dopo il file nel multipart.
            yield Parte("file", b"audio di prova", "prova.mp3")
            for nome, valore in campi.items():
                yield Parte(nome, valore)

        request = SimpleNamespace(multipart=AsyncMock(return_value=parti()), app=self.app)
        with patch.object(ui, "durata_audio", AsyncMock(return_value=10)):
            return await ui.carica(request)

    async def test_upload_con_due_interlocutori_e_automatico(self):
        for numero in ("2", ""):
            response = await self.carica({"diarize": "1", "speakers": numero})
            self.assertEqual(response.status, 200)
            dati = json.loads(response.body)
            self.assertTrue(dati["diarize"])
            self.assertEqual(dati["speakers"], int(numero) if numero else None)
            self.assertIsNone(dati["previsto"])
            self.assertTrue((await self.app["coda"].get()).diarize)

    async def test_upload_errato_non_avvia_lavori_e_rimuove_solo_il_nuovo_file(self):
        ui.INPUT.mkdir()
        originale = ui.INPUT / "prova.mp3"
        originale.write_bytes(b"originale")
        for campi in ({"diarize": "1", "speakers": "0"},
                      {"diarize": "1", "speakers": "2.5"},
                      {"diarize": "1", "speakers": "100"},
                      {"diarize": "0", "speakers": "2"}, {"diarize": "altro"}):
            response = await self.carica(campi)
            self.assertEqual(response.status, 400)
            self.assertTrue(self.app["coda"].empty())
            self.assertEqual(list(ui.INPUT.iterdir()), [originale])
            self.assertEqual(originale.read_bytes(), b"originale")

    async def test_upload_senza_speaker_resta_compatibile(self):
        response = await self.carica({})
        self.assertEqual(response.status, 200)
        lavoro = await self.app["coda"].get()
        self.assertFalse(lavoro.diarize)
        self.assertIsNotNone(lavoro.dati()["previsto"])

    async def test_comando_speaker_offline_e_messaggio_modello_assente(self):
        async def righe():
            yield b"Errore interlocutori: modello non disponibile offline.\n"

        processo = SimpleNamespace(stdout=righe(), wait=AsyncMock(return_value=1), pid=0)
        lavoro = ui.Lavoro(self.root / "prova.mp3", "", False, 10, True, 2)
        with patch.object(ui.asyncio, "create_subprocess_exec", AsyncMock(return_value=processo)) as avvio:
            await ui.esegui(lavoro)
        comando = avvio.call_args.args
        self.assertIn("--diarize", comando)
        self.assertEqual(comando[-2:], ("--speakers", "2"))
        self.assertNotIn("--online", comando)
        self.assertNotIn("--hf_token", comando)
        self.assertEqual(lavoro.stato, "errore")
        self.assertIn("modello non disponibile offline", lavoro.errore)

    async def test_correzione_conserva_speaker_in_json_txt_srt(self):
        cartella = ui.OUTPUT / "prova_large-v3-turbo_diar"
        cartella.mkdir(parents=True)
        originale = {"segments": [
            {"start": 0, "end": 1, "text": "Uno", "speaker": "SPEAKER_00"},
            {"start": 1, "end": 2, "text": "Due", "speaker": "SPEAKER_01"}]}
        file = cartella / "prova.json"
        file.write_text(json.dumps(originale), encoding="utf-8")
        segmenti = ui.segmenti_originali(file)
        segmenti[0]["testo"] = "Testo corretto"
        request = SimpleNamespace(match_info={"cartella": cartella.name},
                                  json=AsyncMock(return_value={"segmenti": segmenti}))
        self.assertEqual((await ui.correzione(request)).status, 200)
        salvati = json.loads((cartella / "prova_corretto.json").read_text(encoding="utf-8"))["segmenti"]
        self.assertEqual([s["speaker"] for s in salvati], ["SPEAKER_00", "SPEAKER_01"])
        for ext in ("txt", "srt"):
            testo = (cartella / f"prova_corretto.{ext}").read_text(encoding="utf-8")
            self.assertIn("[SPEAKER_00]: Testo corretto", testo)
            self.assertIn("[SPEAKER_01]: Due", testo)
        self.assertEqual(json.loads(file.read_text(encoding="utf-8")), originale)


class CliTest(unittest.TestCase):
    def test_numero_interlocutori_errato_rifiutato_prima_di_aprire_file(self):
        script = str(Path(ui.__file__).with_name("trascrivi.py"))
        for opzioni in (("--diarize", "--speakers", "0"),
                        ("--diarize", "--speakers", "-1"),
                        ("--diarize", "--speakers", "2.5"),
                        ("--speakers", "2")):
            result = subprocess.run([sys.executable, script, "inesistente.mp3", *opzioni],
                                    capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Errore: --speakers", result.stderr)
            self.assertNotIn("file non trovato", result.stderr)


if __name__ == "__main__":
    unittest.main()
