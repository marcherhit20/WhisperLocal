"""Portabilità macOS/Windows: blocco della rete, comandi e processi per sistema, nomi, UTF-8."""

import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import blocco_rete
import interfaccia as ui
import trascrivi

PROGETTO = Path(__file__).resolve().parent


def esegui_bloccato(codice, env=None):
    """Esegue codice Python sotto blocco_rete.py e restituisce l'output."""
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "prova.py"
        script.write_text(textwrap.dedent(codice), encoding="utf-8")
        risultato = subprocess.run([sys.executable, str(PROGETTO / "blocco_rete.py"), str(script)],
                                   capture_output=True, text=True, encoding="utf-8", timeout=60, env=env)
    return risultato


class BloccoReteTest(unittest.TestCase):
    PROVA = """
        import socket, subprocess, sys, urllib.request

        def prova(nome, f):
            try:
                f()
                print(nome, "PASSATO")
            except Exception as e:
                print(nome, "BLOCCATO" if "WhisperLocal" in str(e) or "WhisperLocal" in repr(getattr(e, "reason", "")) else "ALTRO", type(e).__name__)

        def ipv6():
            s = socket.socket(socket.AF_INET6)
            try:
                s.connect(("2001:4860:4860::8888", 53))
            finally:
                s.close()

        def loopback():
            server = socket.socket()
            server.bind(("127.0.0.1", 0))
            server.listen()
            socket.create_connection(server.getsockname(), timeout=5).close()
            server.close()

        prova("dns", lambda: socket.getaddrinfo("example.com", 443))
        prova("ipv4", lambda: socket.socket().connect(("1.1.1.1", 443)))
        prova("ipv6", ipv6)
        prova("udp", lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"x", ("8.8.8.8", 53)))
        prova("urllib", lambda: urllib.request.urlopen("https://example.com", timeout=5))
        prova("loopback", loopback)
        prova("programma", lambda: subprocess.run([sys.executable, "-c", "print(1)"]))
        prova("ffmpeg_url", lambda: subprocess.run(["ffmpeg", "-i", "http://example.com/a.mp3"], capture_output=True))
    """

    def test_blocca_rete_e_programmi_ma_non_il_computer_locale(self):
        risultato = esegui_bloccato(self.PROVA)
        righe = dict(r.split(" ", 1) for r in risultato.stdout.splitlines() if " " in r)
        for nome in ("dns", "ipv4", "ipv6", "udp", "urllib", "programma", "ffmpeg_url"):
            self.assertTrue(righe.get(nome, "").startswith("BLOCCATO"), f"{nome}: {righe.get(nome)} {risultato.stderr}")
        self.assertEqual(righe.get("loopback"), "PASSATO")

    @unittest.skipUnless(shutil.which("ffprobe"), "ffprobe non installato")
    def test_ffprobe_locale_consentito(self):
        risultato = esegui_bloccato("""
            import subprocess
            subprocess.run(["ffprobe", "-version"], capture_output=True, check=True)
            print("OK")
        """)
        self.assertIn("OK", risultato.stdout, risultato.stderr)

    def test_ffmpeg_reale_come_whisperx_su_file_con_spazi(self):
        import os
        percorso = os.environ.get("PATH", "")
        portatile = PROGETTO / "strumenti" / "ffmpeg" / "bin"
        if portatile.is_dir():
            percorso = str(portatile) + os.pathsep + percorso
        ffmpeg = shutil.which("ffmpeg", path=percorso)
        if not ffmpeg:
            self.skipTest("ffmpeg non installato")
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "cartella con spazi" / "prova è.wav"
            audio.parent.mkdir()
            subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "sine=duration=0.2", str(audio)], check=True)
            risultato = esegui_bloccato(f"""
                import subprocess, sys
                cmd = ["ffmpeg", "-nostdin", "-threads", "0", "-i", {str(audio)!r}, "-f", "s16le",
                       "-ac", "1", "-acodec", "pcm_s16le", "-ar", "16000", "-"]
                out = subprocess.run(cmd, capture_output=True, check=True).stdout
                print("BYTE", len(out))
            """, env={**os.environ, "PATH": percorso})
        self.assertIn("BYTE", risultato.stdout, risultato.stderr)
        self.assertGreater(int(risultato.stdout.split("BYTE")[1]), 1000)

    def test_memoria_massima_scritta(self):
        with tempfile.TemporaryDirectory() as tmp:
            ram = Path(tmp) / "ram"
            subprocess.run([sys.executable, str(PROGETTO / "blocco_rete.py"), "-m", "json.tool", "--help"],
                           capture_output=True, env={**__import__("os").environ, "WHISPERLOCAL_RAM_FILE": str(ram)})
            self.assertGreater(float(ram.read_text(encoding="utf-8")), 1)


class ProgrammiAmmessiTest(unittest.TestCase):
    def test_ffmpeg_solo_su_file_locali(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "audio con spazi è.mp3"
            audio.write_bytes(b"x")
            a = str(audio)
            ammessi = [
                ["ffmpeg", "-nostdin", "-threads", "0", "-i", a, "-f", "s16le", "-ac", "1",
                 "-acodec", "pcm_s16le", "-ar", "16000", "-"],  # il comando di whisperx
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a],
                ["ffprobe", "-version"], ["uname", "-p"],
                ['"C:\\Program Files\\ffmpeg\\bin\\ffmpeg.exe"', "-i", a, "-"],
            ]
            vietati = [
                ["ffmpeg", "-i", "http://esempio.it/a.mp3", "-"], ["ffmpeg", "-i", "\\\\server\\c\\a.mp3", "-"],
                ["ffmpeg", "-i", "//server/c/a.mp3", "-"], ["ffmpeg", "-i", "tcp:1.2.3.4:80", "-"],
                ["ffmpeg", "-i", "concat:" + a, "-"], ["ffmpeg", "-i", a + ".manca", "-"],
                ["ffmpeg", "-f", "hls", "-i", a, "-"], ["ffmpeg", "-protocol_whitelist", "file,http", "-i", a, "-"],
                ["ffmpeg", "-i", a, "rtp:1.2.3.4:5"], ["ffprobe", "https://esempio.it/a.mp3"],
                ["ffprobe", "\\\\srv\\a.mp3"], ["curl", "x"], ["uname", "x"], ["python", "-c", "1"],
                ["ffmpeg", "-i", a, "-filter_script:a", a, "-f", "s16le", "-"],
                ["ffmpeg", "-i", a, "-af", "amovie=http", "-f", "s16le", "-"],
                ["ffmpeg", "-i", a, "-f", "s16le", "/tmp/uscita.raw"], ["ffprobe", "-i", a, "-show_format"],
            ]
            for argomenti in ammessi:
                self.assertTrue(blocco_rete.programma_ammesso(None, argomenti), argomenti)
            for argomenti in vietati:
                self.assertFalse(blocco_rete.programma_ammesso(None, argomenti), argomenti)

    def test_percorsi_estesi_di_windows(self):
        self.assertFalse(blocco_rete.percorso_di_rete("\\\\?\\D:\\a\\prova ci.wav"))
        self.assertFalse(blocco_rete.percorso_di_rete("\\\\.\\D:\\a"))
        self.assertFalse(blocco_rete.percorso_di_rete("D:\\a\\b.wav"))
        self.assertTrue(blocco_rete.percorso_di_rete("\\\\?\\UNC\\server\\c\\b.wav"))
        self.assertTrue(blocco_rete.percorso_di_rete("\\\\server\\c\\b.wav"))
        self.assertTrue(blocco_rete.percorso_di_rete("//server/c/b.wav"))

    def test_riga_di_comando_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "a.mp3"
            audio.write_bytes(b"x")
            ok = ("_winapi.CreateProcess", (None, f'"C:\\ff\\ffmpeg.exe" -i "{audio}" -f s16le -', None))
            blocco_rete.controllo(*ok)
            # Come arriva davvero su Windows: nome dell'applicazione vuoto, programma nella riga
            blocco_rete.controllo("_winapi.CreateProcess", ("", f'ffmpeg -i "{audio}" -f s16le -', None))
            with self.assertRaises(PermissionError):
                blocco_rete.controllo("_winapi.CreateProcess", ("", "curl http://x", None))
            # CreateProcess subito dopo un Popen già controllato (qualunque forma abbiano gli argomenti)
            blocco_rete.controllo("subprocess.Popen", (None, ["ffmpeg", "-i", str(audio), "-f", "s16le", "-"], None, None))
            blocco_rete.controllo("_winapi.CreateProcess", (None, None, None))
            # ...ma solo una volta: un CreateProcess diretto con argomenti illeggibili è bloccato
            with self.assertRaises(PermissionError):
                blocco_rete.controllo("_winapi.CreateProcess", (None, None, None))
            # e un Popen rifiutato non autorizza il CreateProcess successivo
            with self.assertRaises(PermissionError):
                blocco_rete.controllo("subprocess.Popen", (None, ["curl", "x"], None, None))
            with self.assertRaises(PermissionError):
                blocco_rete.controllo("_winapi.CreateProcess", (None, None, None))
            for riga in ('"C:\\ff\\ffmpeg.exe" -i http://x/a.mp3 -', "cmd.exe /c curl x"):
                with self.assertRaises(PermissionError):
                    blocco_rete.controllo("_winapi.CreateProcess", (None, riga, None))


class TrascriviTest(unittest.TestCase):
    def test_riepilogo_come_il_vecchio_script(self):
        # awk: printf "%d min %02d s" con durata decimale tronca, %.1f per la velocità
        self.assertEqual(trascrivi.formato_riepilogo(272.47, 93, 4570.4),
                         "Audio: 4 min 32 s | Tempo: 1 min 33 s | Velocità: 2.9x tempo reale | RAM massima: 4570 MB")

    def test_comando_con_blocco_per_sistema(self):
        with patch.object(trascrivi, "MACOS", True):
            comando = trascrivi.Esecutore(False).comando(["-m", "whisperx"])
            self.assertEqual(comando[:2], ["sandbox-exec", "-p"])
            self.assertIn(str(PROGETTO / "blocco_rete.py"), comando)
        with patch.object(trascrivi, "MACOS", False):
            comando = trascrivi.Esecutore(False).comando(["-m", "whisperx"])
            self.assertNotIn("sandbox-exec", comando)
            self.assertEqual(comando[1], str(PROGETTO / "blocco_rete.py"))
            self.assertNotIn(str(PROGETTO / "blocco_rete.py"), trascrivi.Esecutore(True).comando(["-m", "whisperx"]))

    def test_pubblica_insieme_completo_json_per_ultimo(self):
        with tempfile.TemporaryDirectory() as tmp:
            finale, parziale = Path(tmp) / "a_medium", Path(tmp) / ".a_medium.parziale"
            parziale.mkdir()
            for nome, testo in (("a.json", "nuovo è"), ("a.txt", "t"), ("da_verificare.json", "d"), ("run.log", "log")):
                (parziale / nome).write_text(testo, encoding="utf-8")
            ordine = []
            vero_replace = trascrivi.os.replace
            with patch.object(trascrivi.os, "replace", side_effect=lambda a, b: (ordine.append(Path(a).name), vero_replace(a, b))):
                trascrivi.pubblica(parziale, finale)
            self.assertFalse(parziale.exists())
            self.assertEqual(ordine[-1], "a.json")  # il JSON, che segna la trascrizione, per ultimo
            self.assertEqual((finale / "a.json").read_text(encoding="utf-8"), "nuovo è")

    def test_non_sovrascrive_risultati_esistenti(self):
        with tempfile.TemporaryDirectory() as tmp:
            progetto = Path(tmp)
            (progetto / "input").mkdir()
            audio = progetto / "input" / "a.mp3"
            audio.write_bytes(b"x")
            for cartella in ("a_medium", "a_large-v3-turbo"):
                (progetto / "output" / cartella).mkdir(parents=True)
                (progetto / "output" / cartella / "a.json").write_text("{}", encoding="utf-8")
                with patch.object(trascrivi, "PROGETTO", progetto), \
                        patch.object(trascrivi.Esecutore, "esegui") as esegui, \
                        patch.object(trascrivi, "python_venv", return_value=Path(sys.executable)), \
                        patch.object(trascrivi.shutil, "which", return_value="/bin/x"), \
                        patch("sys.stderr") as stderr, self.assertRaises(SystemExit) as uscita:
                    trascrivi.main([str(audio)])
                self.assertEqual(uscita.exception.code, 1)
                esegui.assert_not_called()
                scritto = "".join(c.args[0] for c in stderr.write.call_args_list)
                self.assertIn("esistono già risultati", scritto)
                self.assertIn(cartella, scritto)
                shutil.rmtree(progetto / "output")

    def esegui_cli(self, *argomenti, cwd=None):
        return subprocess.run([sys.executable, str(PROGETTO / "trascrivi.py"), *argomenti],
                              capture_output=True, text=True, encoding="utf-8", cwd=cwd)

    def test_aiuto_completo(self):
        r = self.esegui_cli("--help")
        self.assertEqual(r.returncode, 0)
        for testo in ("Uso:", "--senza-verifica", "--speakers N", "Predefiniti: large-v3-turbo",
                      "output/<nomefile>_<modello>", "run.log", "token Hugging Face"):
            self.assertIn(testo, r.stdout)

    def test_errori_della_riga_di_comando(self):
        r = self.esegui_cli()
        self.assertEqual((r.returncode, r.stdout.startswith("Uso:")), (1, True))
        r = self.esegui_cli("a.mp3", "--sconosciuta")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stderr, "Errore: opzione sconosciuta --sconosciuta\n")  # come trascrivi.sh:
        self.assertTrue(r.stdout.startswith("Uso:"))  # errore su stderr, aiuto su stdout
        r = self.esegui_cli("a.mp3", "--parole")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Errore: --parole richiede un valore", r.stderr)
        r = self.esegui_cli("a.mp3", "--precisione", "float16")
        self.assertIn("Errore: --precisione accetta int8 o float32", r.stderr)
        with tempfile.TemporaryDirectory() as tmp:  # da un'altra cartella, nome con spazi
            r = self.esegui_cli("non c'è.mp3", cwd=tmp)
        self.assertEqual(r.returncode, 1)
        self.assertIn("Errore: file non trovato: non c'è.mp3", r.stderr)


class InterfacciaPerSistemaTest(unittest.IsolatedAsyncioTestCase):
    def lavoro(self):
        return ui.Lavoro(Path("input/prova.mp3"), "", True, 10, False, None)

    def test_comando_mac_e_windows(self):
        with patch.object(ui, "MACOS", True), patch.object(ui, "WINDOWS", False):
            self.assertEqual(ui.comando_trascrizione(self.lavoro())[:2], ["caffeinate", "-i"])
        with patch.object(ui, "MACOS", False), patch.object(ui, "WINDOWS", True):
            comando = ui.comando_trascrizione(self.lavoro())
            self.assertEqual(comando[:2], [sys.executable, str(PROGETTO / "trascrivi.py")])
            self.assertNotIn("caffeinate", comando)
            self.assertNotIn("--online", comando)

    async def test_annulla_windows_usa_taskkill_e_attende(self):
        lavoro = self.lavoro()
        lavoro.stato = "in corso"
        lavoro.processo = SimpleNamespace(pid=1234, returncode=None)

        def taskkill(*a, **k):
            lavoro.processo.returncode = 1
            return SimpleNamespace(returncode=0)

        with patch.object(ui, "WINDOWS", True), patch.object(ui.subprocess, "run", side_effect=taskkill) as run:
            await ui.ferma(lavoro)
        self.assertEqual(run.call_args.args[0], ["taskkill", "/T", "/F", "/PID", "1234"])
        self.assertEqual(run.call_args.kwargs["timeout"], 10)
        self.assertEqual(lavoro.stato, "annullato")
        self.assertIsNone(lavoro.errore)

    async def test_annulla_windows_fallito_lo_dice(self):
        lavoro = self.lavoro()
        lavoro.stato = "in corso"
        lavoro.processo = SimpleNamespace(pid=1234, returncode=None)
        with patch.object(ui, "WINDOWS", True), \
                patch.object(ui.subprocess, "run", side_effect=subprocess.TimeoutExpired("taskkill", 10)), \
                patch.object(ui.asyncio, "sleep", AsyncMock()):
            await ui.ferma(lavoro)
        self.assertIn("Gestione attività", lavoro.errore)
        self.assertEqual(lavoro.stato, "errore")  # non «Annullata» se il processo è ancora vivo

    async def test_errore_di_lettura_ferma_il_processo(self):
        async def righe():
            yield b"x" * 10
            raise ValueError("riga troppo lunga")

        processo = SimpleNamespace(stdout=righe(), wait=AsyncMock(return_value=0), pid=4321, returncode=None)
        lavoro = self.lavoro()
        with patch.object(ui.asyncio, "create_subprocess_exec", AsyncMock(return_value=processo)), \
                patch.object(ui, "ferma_processo", AsyncMock()) as ferma:
            await ui.esegui(lavoro)
        ferma.assert_awaited_once_with(lavoro)
        self.assertEqual(lavoro.stato, "errore")


    def test_taskkill_con_tempo_massimo(self):
        lavoro = self.lavoro()
        lavoro.processo = SimpleNamespace(pid=1234, returncode=None)
        with patch.object(ui.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
            self.assertTrue(ui.termina_windows(lavoro))
        self.assertEqual(run.call_args.args[0], ["taskkill", "/T", "/F", "/PID", "1234"])


    async def test_mostra_nel_finder_o_in_esplora_risorse(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            (output / "a_large-v3-turbo").mkdir()
            json_file = output / "a_large-v3-turbo" / "a.json"
            json_file.write_text("{}", encoding="utf-8")
            request = SimpleNamespace(match_info={"cartella": "a_large-v3-turbo"})
            for windows, atteso in ((True, ["explorer", f"/select,{json_file}"]), (False, ["open", "-R", str(json_file)])):
                with patch.object(ui, "OUTPUT", output), patch.object(ui, "WINDOWS", windows), \
                        patch.object(ui.subprocess, "Popen") as popen:
                    await ui.mostra(request)
                self.assertEqual(popen.call_args.args[0], atteso)

    async def test_ping_indica_il_sistema(self):
        with patch.object(ui, "WINDOWS", True):
            risposta = await ui.ping(None)
        self.assertEqual(json.loads(risposta.body)["sistema"], "windows")

    def test_nome_libero_evita_trascrizioni_in_corso(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(ui, "INPUT", Path(tmp) / "input"), \
                patch.object(ui, "OUTPUT", Path(tmp) / "output"):
            (Path(tmp) / "output" / ".a_large-v3-turbo.parziale").mkdir(parents=True)
            self.assertEqual(ui.nome_libero("a.mp3").name, "a_2.mp3")

    def test_nomi_riservati_e_separatori(self):
        self.assertEqual(ui.nome_sicuro("CON.mp3"), "_CON.mp3")
        self.assertEqual(ui.nome_sicuro("nul"), "_nul")
        self.assertEqual(ui.nome_sicuro("..\\..\\com1.wav"), "_com1.wav")
        self.assertEqual(ui.nome_sicuro("console.mp3"), "console.mp3")
        with tempfile.TemporaryDirectory() as tmp, patch.object(ui, "OUTPUT", Path(tmp)):
            (Path(tmp) / "a").mkdir()
            for nome in ("..\\a", "a\\..\\..", ".a"):
                with self.assertRaises(ui.web.HTTPNotFound):
                    ui.cartella_richiesta(SimpleNamespace(match_info={"cartella": nome}))

    def test_scrittura_utf8_con_fine_riga_lf(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "prova_corretto.txt"
            ui.scrivi(file, "perché è così\nseconda riga\n")
            self.assertEqual(file.read_bytes(), "perché è così\nseconda riga\n".encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
