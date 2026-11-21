"""Vocal Remover: a desktop front end for mlx-audio-separator."""
import json
import mimetypes
import os
import secrets
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_NAME = "Vocal Remover"
AUDIO_EXTS = {".wav", ".flac", ".mp3", ".ogg", ".opus", ".m4a", ".aiff", ".aif", ".aac", ".mp4", ".mov", ".webm"}

FROZEN = getattr(sys, "frozen", False)
HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
WEB_DIR = HERE / "web"
SUPPORT_DIR = Path.home() / "Library" / "Application Support" / APP_NAME
# Models are downloaded on first run (Download all), not shipped in the app.
MODEL_DIR = Path(os.environ.get("VR_MODEL_DIR") or SUPPORT_DIR / "models")
LOG_DIR = Path.home() / "Library" / "Logs" / APP_NAME
SETTINGS_FILE = SUPPORT_DIR / "settings.json"


# ---------------------------------------------------------------- media server
class MediaServer:
    """Serves finished stems to the in-app player. Only paths we registered
    are reachable, each behind a random token. Supports Range requests, which
    WebKit needs to play and seek audio."""

    def __init__(self):
        self.files = {}
        registry = self.files

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                token = self.path.rsplit("/", 1)[-1].split("?")[0]
                path = registry.get(token)
                if not path or not os.path.isfile(path):
                    self.send_error(404)
                    return
                size = os.path.getsize(path)
                start, end = 0, size - 1
                rng = self.headers.get("Range")
                if rng and rng.startswith("bytes="):
                    a, _, b = rng[6:].partition("-")
                    start = int(a) if a else max(0, size - int(b))
                    end = int(b) if a and b else size - 1
                    end = min(end, size - 1)
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                else:
                    self.send_response(200)
                length = end - start + 1
                self.send_header("Content-Type", mimetypes.guess_type(path)[0] or "application/octet-stream")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(length))
                self.end_headers()
                try:
                    with open(path, "rb") as f:
                        f.seek(start)
                        remaining = length
                        while remaining > 0:
                            chunk = f.read(min(1 << 16, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def url_for(self, path):
        token = secrets.token_urlsafe(12)
        self.files[token] = path
        return f"http://127.0.0.1:{self.port}/m/{token}"


# ---------------------------------------------------------------- API for JS
class Api:
    def __init__(self):
        self._window = None
        self._proc = None
        self._lock = threading.Lock()
        self._media = MediaServer()

    # -- setup
    def bootstrap(self):
        from catalog import MODELS, TOOLS, is_installed

        def tag(m):
            return {**m, "installed": is_installed(MODEL_DIR, m)}

        return {
            "models": [tag(m) for m in MODELS],
            "tools": [tag(t) for t in TOOLS],
            "modelDir": str(MODEL_DIR),
            "settings": self._load_settings(),
            "defaultOutput": str(Path.home() / "Music" / APP_NAME),
        }

    def save_settings(self, settings):
        SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(settings, indent=2))

    def _load_settings(self):
        try:
            return json.loads(SETTINGS_FILE.read_text())
        except Exception:
            return {}

    # -- files
    def pick_files(self):
        import webview

        types = ("Audio files (*.wav;*.flac;*.mp3;*.m4a;*.aiff;*.aif;*.ogg;*.opus;*.aac)", "All files (*.*)")
        result = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True, file_types=types)
        return self._describe(result or [])

    def pick_folder(self):
        import webview

        result = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        return result[0] if result else None

    def _describe(self, paths):
        out = []
        for p in paths:
            p = Path(p)
            if p.is_dir():
                out += self._describe(sorted(c for c in p.rglob("*") if c.suffix.lower() in AUDIO_EXTS))
            elif p.suffix.lower() in AUDIO_EXTS and p.is_file():
                out.append({"path": str(p), "name": p.name, "size": p.stat().st_size})
        return out

    def _on_drop(self, event):
        files = event.get("dataTransfer", {}).get("files", [])
        paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
        described = self._describe(paths)
        self._push("onFilesDropped", described)

    def reveal(self, path):
        subprocess.run(["open", "-R", path])

    def open_folder(self, path):
        subprocess.run(["open", path])

    def media_url(self, path):
        return self._media.url_for(path)

    # -- jobs
    def download_models(self):
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        return self.start({"action": "download"})

    def start(self, job):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                return {"ok": False, "error": "A job is already running"}
            if "output_root" in job:
                out_root = Path(job["output_root"]).expanduser()
                out_root.mkdir(parents=True, exist_ok=True)
                job["output_root"] = str(out_root)
            MODEL_DIR.mkdir(parents=True, exist_ok=True)
            job["model_dir"] = str(MODEL_DIR)
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            log = open(LOG_DIR / "worker.log", "w")
            cmd = [sys.executable] if FROZEN else [sys.executable, str(Path(__file__).resolve())]
            env = dict(os.environ, PYTHONUNBUFFERED="1", AUDIO_SEPARATOR_MODEL_DIR=str(MODEL_DIR))
            self._proc = subprocess.Popen(
                cmd + ["--worker", json.dumps(job)],
                stdout=subprocess.PIPE, stderr=log, text=True, env=env,
            )
            threading.Thread(target=self._pump, args=(self._proc, log), daemon=True).start()
            return {"ok": True}

    def cancel(self):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()

    def _pump(self, proc, log):
        for line in proc.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._push("onWorker", event)
        code = proc.wait()
        log.close()
        if code != 0:
            tail = ""
            try:
                tail = "\n".join((LOG_DIR / "worker.log").read_text().strip().splitlines()[-6:])
            except Exception:
                pass
            self._push("onWorker", {"type": "exit", "code": code, "log": tail})

    def _push(self, fn, payload):
        if self._window:
            self._window.evaluate_js(f"window.{fn} && window.{fn}({json.dumps(payload)})")

    def shutdown(self):
        self.cancel()


def selftest(window):
    """Open the real window, check the UI rendered with models, then quit."""
    import time

    time.sleep(3)
    result = window.evaluate_js(
        "JSON.stringify({models: document.querySelectorAll('.model').length,"
        " stems: document.querySelectorAll('.chip').length,"
        " dropVisible: !document.getElementById('empty').hidden,"
        " output: document.getElementById('outPath').textContent})"
    )
    print("SELFTEST", result, flush=True)

    # Optional end-to-end run: VR_SELFTEST_FILE=/path/song.wav
    song = os.environ.get("VR_SELFTEST_FILE")
    if song:
        out = os.environ.get("VR_SELFTEST_OUT", str(Path.home() / "Music" / APP_NAME))
        window.evaluate_js(
            f"state.output = {json.dumps(out)};"
            f"addFiles([{{path: {json.dumps(song)}, name: 'test', size: 1}}]);"
            "document.getElementById('goBtn').click();"
        )
        for _ in range(240):
            time.sleep(0.5)
            if window.evaluate_js("state.running") is False and window.evaluate_js("state.queue[0].status") != "queued":
                break
        print("SELFTEST-RUN", window.evaluate_js(
            "JSON.stringify({status: state.queue[0].status, stems: state.queue[0].outputs.map(o => o.stem),"
            " error: state.queue[0].error, bar: document.getElementById('status').textContent})"
        ), flush=True)
    window.destroy()


def _window_bg():
    """Match the page background so the window doesn't flash while loading."""
    dark = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                          capture_output=True, text=True).stdout.strip() == "Dark"
    return "#161618" if dark else "#f5f5f7"


def run_gui():
    import webview
    from webview.dom import DOMEventHandler

    api = Api()
    window = webview.create_window(
        APP_NAME,
        url=str(WEB_DIR / "index.html"),
        js_api=api,
        width=920,
        height=820,
        min_size=(760, 600),
        background_color=_window_bg(),
    )
    api._window = window

    def on_loaded():
        window.dom.document.events.drop += DOMEventHandler(api._on_drop, True, True)
        if "--selftest" in sys.argv:
            threading.Thread(target=selftest, args=(window,), daemon=True).start()

    window.events.loaded += on_loaded
    window.events.closed += api.shutdown
    webview.start(debug=bool(os.environ.get("VR_DEBUG")))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        import worker

        worker.main(sys.argv[2:])
        return
    run_gui()


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
