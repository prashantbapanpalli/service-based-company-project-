"""Sales training interface. Run:  python trainer.py   then open http://localhost:8000

Serves web/index.html, the playbook and call-scenario JSON, and the agent's live instructions.
Standard library only; no extra packages needed.
"""

import json
import sys
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.knowledge import build_instructions, check_playbook, load_playbook
from app.scenarios import check_scenarios, load_scenarios

ROOT = Path(__file__).resolve().parent
PORT = 8000


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.path = "/web/index.html"
        elif self.path == "/api/playbook":
            return self._json(load_playbook())
        elif self.path == "/api/scenarios":
            return self._json(load_scenarios())
        elif self.path == "/api/instructions":
            playbook, scenarios = load_playbook(), load_scenarios()
            return self._json({
                "text": build_instructions(playbook=playbook, scenarios=scenarios),
                "problems": check_playbook(playbook) + check_scenarios(scenarios),
            })
        elif not self.path.startswith("/web/"):
            return self.send_error(404)
        return super().do_GET()

    def _json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=str(ROOT)))
    url = f"http://localhost:{port}"
    print(f"Sales trainer running at {url}  (Ctrl+C to stop)")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
