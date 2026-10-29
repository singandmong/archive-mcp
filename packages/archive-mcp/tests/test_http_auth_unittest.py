"""Security and compatibility tests for the optional HTTP server."""
import tempfile
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
import server


class HttpAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.client = TestClient(server.app)
        self.items = patch.object(server, "QWIKI_ITEMS", Path(self.temp.name) / "items")
        self.items.start()
        self.addCleanup(self.items.stop)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.client.close)

    def test_missing_or_weak_configuration_fails_closed(self):
        for token in ("", "short"):
            with self.subTest(token=token), patch.dict("os.environ", {"ARCHIVE_MCP_HTTP_TOKEN": token}):
                self.assertEqual(self.client.get("/health").status_code, 200)
                self.assertEqual(self.client.get("/tools").status_code, 503)
                self.assertEqual(self.client.post("/api/v1/captures", json={}).status_code, 503)

    def test_http_and_stdio_share_explicit_archive_data_directory(self):
        env = {**os.environ, "ARCHIVE_DATA_DIR": self.temp.name, "PYTHONDONTWRITEBYTECODE": "1"}
        env.pop("QWIKI_VAULT", None)
        result = subprocess.run(
            [sys.executable, "-c", "import server, mcp_server; assert server.QWIKI_ITEMS == mcp_server._items()"],
            env=env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        env["QWIKI_VAULT"] = str(Path(self.temp.name) / "different")
        result = subprocess.run([sys.executable, "-c", "import server"], env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must refer to the same directory", result.stderr)
        env.pop("ARCHIVE_DATA_DIR")
        result = subprocess.run(
            [sys.executable, "-c", "import server, mcp_server; assert server.QWIKI_ITEMS == mcp_server._items()"],
            env=env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        env.pop("QWIKI_VAULT")
        result = subprocess.run(
            [sys.executable, "-c", "import server, mcp_server; assert server.QWIKI_ITEMS == mcp_server._items()"],
            env=env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_requires_correct_token_across_routes(self):
        token = "x" * 40
        with patch.dict("os.environ", {"ARCHIVE_MCP_HTTP_TOKEN": token}):
            for path in ("/tools", "/wrappers", "/openapi.json"):
                self.assertEqual(self.client.get(path).status_code, 401)
            for path in ("/api/v1/ingest", "/api/v1/captures", "/api/v1/captures/content",
                         "/api/v1/ingest/file", "/api/v1/ingest/obsidian-web-clipper",
                         "/test/docling", "/test/crawl", "/test/cognee", "/test/notebooklm/quiz"):
                self.assertEqual(self.client.post(path, json={}).status_code, 401)
                self.assertEqual(self.client.post(path, json={}, headers={"Authorization": "Bearer wrong"}).status_code, 401)
            self.assertEqual(self.client.get("/tools", headers={"Authorization": "Bearer " + token}).status_code, 200)
            self.assertEqual(self.client.post("/test/docling", json={"file": "/etc/passwd"}, headers={"Authorization": "Bearer " + token}).status_code, 404)
            with patch.dict("os.environ", {"ARCHIVE_MCP_ENABLE_TEST_ENDPOINTS": "1"}):
                self.assertEqual(self.client.post("/test/crawl", json={"url": "http://127.0.0.1"}, headers={"Authorization": "Bearer " + token}).status_code, 404)
            payload = {"url": "https://example.com/test", "source": "raycast", "source_device": "mac", "client_request_id": "test", "dry_run": True}
            self.assertEqual(self.client.post("/api/v1/captures", json=payload, headers={"Authorization": "Bearer " + token}).status_code, 200)
            actual = {**payload, "source": "telegram", "client_request_id": "saved", "dry_run": False}
            self.assertEqual(self.client.post("/api/v1/captures", json=actual).status_code, 401)
            self.assertFalse((Path(self.temp.name) / "items").exists())
            result = self.client.post("/api/v1/captures", json=actual, headers={"Authorization": "Bearer " + token})
            self.assertEqual(result.status_code, 200)
            self.assertNotIn("qwiki_path", result.json())
            self.assertNotIn("capture_path", result.json())
            self.assertEqual(len(list((Path(self.temp.name) / "items").glob("*/*/*.md"))), 1)
            content = self.client.post("/api/v1/captures/content", json={"client_request_id": "saved", "content": "test"}, headers={"Authorization": "Bearer " + token})
            self.assertEqual(content.json(), {"ok": True})
            disabled = self.client.post("/api/v1/ingest/obsidian-web-clipper", json={}, headers={"Authorization": "Bearer " + token})
            self.assertEqual(disabled.status_code, 404)


if __name__ == "__main__":
    unittest.main()
