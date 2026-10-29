import contextlib
import importlib.util
import io
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/raycast/archive-public-clipboard.py"
spec = importlib.util.spec_from_file_location("archive_public_clipboard", SCRIPT)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class Receiver(BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.requests.append((self.path, self.headers.get("Authorization"), json.loads(body)))
        payload = b'{"ok":true,"item_id":"test-item"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        pass


class RaycastAdapterTests(unittest.TestCase):
    def test_local_capture_sends_authenticated_clipboard_url(self):
        Receiver.requests = []
        server = HTTPServer(("127.0.0.1", 0), Receiver)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        env = {"ARCHIVE_MCP_BASE_URL": f"http://127.0.0.1:{server.server_port}",
               "ARCHIVE_MCP_HTTP_TOKEN": "x" * 40}
        with patch.dict("os.environ", env), patch.object(adapter.subprocess, "run") as clipboard, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            clipboard.return_value.stdout = "메모 https://example.com/test"
            self.assertEqual(adapter.main(), 0)
        self.assertIn("test-item", output.getvalue())
        path, auth, payload = Receiver.requests[0]
        self.assertEqual(path, "/api/v1/captures")
        self.assertEqual(auth, "Bearer " + "x" * 40)
        self.assertEqual(payload["url"], "https://example.com/test")

    def test_remote_plain_http_is_rejected_before_clipboard_or_network(self):
        with patch.dict("os.environ", {"ARCHIVE_MCP_BASE_URL": "http://example.com", "ARCHIVE_MCP_HTTP_TOKEN": "x" * 40}), \
             patch.object(adapter.subprocess, "run") as clipboard, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(adapter.main(), 1)
            clipboard.assert_not_called()


if __name__ == "__main__":
    unittest.main()
