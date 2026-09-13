import json
import os
import urllib.request

from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
HA = "http://supervisor/core/api"
WWW = "/www"


def ha_get(path):
    request = urllib.request.Request(
        HA + path,
        headers={
            "Authorization": "Bearer " + TOKEN,
            "Content-Type": "application/json",
        },
    )

    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode())


class Handler(SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WWW, **kwargs)

    def send_json(self, status, obj):
        body = json.dumps(obj).encode()

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()

        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path

        if path.endswith("/api/health"):
            try:
                config = ha_get("/config")

                self.send_json(
                    200,
                    {
                        "ok": True,
                        "location_name": config.get("location_name"),
                        "version": config.get("version"),
                    },
                )

            except Exception as error:
                self.send_json(
                    502,
                    {"ok": False, "error": str(error)},
                )

            return

        if path.endswith("/api/bootstrap"):
            try:
                self.send_json(
                    200,
                    {
                        "config": ha_get("/config"),
                        "states": ha_get("/states"),
                    },
                )

            except Exception as error:
                self.send_json(
                    502,
                    {"error": str(error)},
                )

            return

        super().do_GET()


ThreadingHTTPServer(
    ("0.0.0.0", 8099),
    Handler,
).serve_forever()
