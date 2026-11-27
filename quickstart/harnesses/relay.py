import http.client
import json
import os
import pathlib
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ["RELAY_HOST"]
MODEL = os.environ["RELAY_MODEL"]
KEY = pathlib.Path(os.environ.get("RELAY_KEY_FILE", "/run/api.key")).read_text().strip()
assert KEY, "Empty API key"
EXTRA_JSON = json.loads(os.environ.get("RELAY_EXTRA_JSON", "{}"))
SLOTS = threading.BoundedSemaphore(int(os.environ.get("RELAY_SLOTS", "4")))
LOCK = threading.Lock()
STATS = {"requests": 0, "ok": 0, "err": 0, "rate_limits": 0}


def log(msg):
    sys.stderr.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} [relay:{MODEL}] {msg}\n")
    sys.stderr.flush()


class Relay(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def do_GET(self):
        if self.path == "/health":
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif self.path in ("/v1/models", "/models"):
            payload = json.dumps({"object": "list", "data": [{"id": MODEL, "object": "model"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        elif self.path == "/status":
            with LOCK:
                payload = json.dumps({"host": HOST, "model": MODEL, **STATS}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path not in ("/v1/chat/completions", "/chat/completions"):
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 80 * 1024 * 1024:
                self.send_error(413)
                return
            body = self.rfile.read(size)
            req_obj = json.loads(body)
            if not isinstance(req_obj, dict):
                self.send_error(400)
                return
            req_obj["model"] = MODEL
            for ek, ev in EXTRA_JSON.items():
                if isinstance(ev, dict) and isinstance(req_obj.get(ek), dict):
                    merged = dict(req_obj[ek])
                    merged.update(ev)
                    req_obj[ek] = merged
                else:
                    req_obj[ek] = ev
            body = json.dumps(req_obj, separators=(",", ":")).encode()
        except (ValueError, OSError):
            self.send_error(400)
            return

        SLOTS.acquire()
        with LOCK:
            STATS["requests"] += 1
            req_no = STATS["requests"]

        conn = http.client.HTTPSConnection(HOST, timeout=600)
        try:
            conn.request(
                "POST",
                "/v1/chat/completions",
                body,
                {
                    "Authorization": "Bearer " + KEY,
                    "Content-Type": "application/json",
                    "Accept": self.headers.get("Accept", "*/*"),
                    "Accept-Encoding": "identity",
                    "User-Agent": "mario-eval-relay/4.0",
                },
            )
            response = conn.getresponse()
        except (http.client.HTTPException, OSError) as exc:
            conn.close()
            SLOTS.release()
            with LOCK:
                STATS["err"] += 1
            log(f"req #{req_no} network error: {exc}")
            err_b = json.dumps({"error": {"message": f"Upstream network error: {exc}", "type": "server_error"}}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err_b)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(err_b)
            return

        try:
            if not (200 <= response.status < 300):
                with LOCK:
                    STATS["err"] += 1
                    if response.status == 429:
                        STATS["rate_limits"] += 1
                err_body = response.read(65536)
                log(f"req #{req_no} HTTP {response.status}: {err_body[:240]!r}")
                self.send_response(response.status)
                for name in ("Content-Type", "Retry-After"):
                    if value := response.getheader(name):
                        self.send_header(name, value)
                self.send_header("Content-Length", str(len(err_body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(err_body)
                return

            with LOCK:
                STATS["ok"] += 1
            if req_no == 1 or req_no % 25 == 0:
                log(f"req #{req_no} ok stats={STATS}")

            self.send_response(response.status)
            for name in ("Content-Type", "Retry-After"):
                if value := response.getheader(name):
                    self.send_header(name, value)
            clen = response.getheader("Content-Length")
            if clen and response.getheader("Transfer-Encoding", "").lower() != "chunked":
                self.send_header("Content-Length", clen)
            self.send_header("Connection", "close")
            self.end_headers()
            while chunk := response.read1(65536):
                self.wfile.write(chunk)
                self.wfile.flush()
        except (http.client.HTTPException, OSError):
            pass
        finally:
            conn.close()
            SLOTS.release()

    def log_message(self, fmt, *args):
        pass


log(f"Starting relay -> https://{HOST}/v1/chat/completions for {MODEL} (extra={EXTRA_JSON})")
ThreadingHTTPServer(("0.0.0.0", 8765), Relay).serve_forever()
