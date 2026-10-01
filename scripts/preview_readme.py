"""Loopback-only preview of README artwork; never serves the repository or .env."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit
import mimetypes

ROOT = Path(__file__).resolve().parents[1]
ASSETS = (ROOT / "docs/assets").resolve()
FILES = {
    "/brand-mark.png": ROOT / "frontend/public/brand-mark.png",
    "/fonts/manrope.ttf": ROOT / "frontend/src/app/fonts/manrope-variable.ttf",
    "/fonts/plex.ttf": ROOT / "frontend/src/app/fonts/ibm-plex-sans-variable.ttf",
}


class Preview(BaseHTTPRequestHandler):
    def do_GET(self):
        path = unquote(urlsplit(self.path).path)
        target = FILES.get(path)
        if target is None:
            target = (ASSETS / path.lstrip("/")).resolve()
            if not target.is_relative_to(ASSETS):
                self.send_error(404)
                return
        if not target.is_file():
            self.send_error(404)
            return
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(target)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args):
        pass


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 0), Preview)
    print(f"http://127.0.0.1:{server.server_port}/showcase.html", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
