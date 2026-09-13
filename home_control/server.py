import json
import os
import socket
import urllib.error
import urllib.request

from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
HA = "http://supervisor/core/api"
WWW = "/www"

print("HOME CONTROL: starting v0.1.2", flush=True)
print(
    "HOME CONTROL: SUPERVISOR_TOKEN present:",
    bool(TOKEN),
    flush=True,
)

try:
    print(
        "HOME CONTROL: supervisor resolves to:",
        socket.gethostbyname("supervisor"),
        flush=True,
    )
except Exception as error:
    print(
        "HOME CONTROL: supervisor DNS ERROR:",
        repr(error),
        flush=True,
    )


def ha_get(path):
    url = HA + path

    request = urllib.request.Request(
        url,
        headers={
            "Authorization": "Bearer " + TOKEN,
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode())

    except urllib.error.HTTPError as error:
        print(
            "HOME CONTROL: HA HTTP ERROR:",
            error.code,
            error.reason,
            "URL:",
            url,
            flush=True,
        )
        raise

    except Exception as error:
        print(
            "HOME CONTROL: HA CONNECTION ERROR:",
            repr(error),
            "URL:",
            url,
            flush=True,
        )
        raise


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
                    {"ok": False, "error": repr(error)},
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
                print(
                    "HOME CONTROL: BOOTSTRAP ERROR:",
                    repr(error),
                    flush=True,
                )
                self.send_json(
                    502,
                    {"error": repr(error)},
                )
            return

        super().do_GET()


ThreadingHTTPServer(
    ("0.0.0.0", 8099),
    Handler,
).serve_forever()
