#!/usr/bin/env python3
# @raycast.schemaVersion 1
# @raycast.title Archive Clipboard URL
# @raycast.mode fullOutput
# @raycast.icon 📑
# @raycast.description Save the first clipboard URL to an Archive MCP HTTP endpoint
"""Minimal Raycast adapter; endpoint and token come from the process environment."""
import ipaddress
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from urllib.parse import urlsplit


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main() -> int:
    endpoint = os.environ.get("ARCHIVE_MCP_BASE_URL", "http://127.0.0.1:8765").rstrip("/")
    token = os.environ.get("ARCHIVE_MCP_HTTP_TOKEN", "")
    if len(token.encode("utf-8")) < 32:
        print("Archive MCP 인증 토큰이 설정되지 않았습니다.", file=sys.stderr)
        return 1
    try:
        parts = urlsplit(endpoint)
        host = parts.hostname or ""
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host.lower() == "localhost"
        if parts.username or parts.password or parts.query or parts.fragment or not (
            parts.scheme == "https" or (parts.scheme == "http" and loopback)
        ):
            raise ValueError("invalid endpoint")
        clipboard = subprocess.run(["pbpaste"], check=True, capture_output=True, text=True).stdout
        match = re.search(r"https?://[^\s<>\"']+", clipboard, flags=re.IGNORECASE)
        if not match:
            print("클립보드에서 링크를 찾지 못했습니다.", file=sys.stderr)
            return 1
        url = match.group(0).rstrip(".,;:!?")
        payload = {"url": url, "source": "raycast", "source_device": "mac",
                   "client_request_id": f"raycast:{uuid.uuid4()}"}
        request = urllib.request.Request(
            endpoint + "/api/v1/captures", data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
            method="POST",
        )
        with urllib.request.build_opener(NoRedirect).open(request, timeout=15) as response:
            result = json.load(response)
        if not result.get("ok"):
            raise ValueError("capture failed")
        print("저장 완료: " + str(result.get("item_id", "")))
        return 0
    except (OSError, subprocess.SubprocessError, ValueError, urllib.error.URLError, json.JSONDecodeError):
        print("저장하지 못했습니다. 인증 토큰과 HTTPS 서버 연결을 확인해 주세요.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
