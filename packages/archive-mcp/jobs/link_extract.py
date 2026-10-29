"""Small best-effort public web extractor; never follows redirects or private IPs."""
from __future__ import annotations

import http.client
import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit

from jobs.readable_html import _ReadableHTMLParser, _compact_text


def fetch_public_content(url: str) -> str:
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in {'http', 'https'} or not parts.hostname or parts.username or parts.password:
        raise ValueError('public http(s) URL required')
    port = parts.port or (443 if scheme == 'https' else 80)
    if port != (443 if scheme == 'https' else 80):
        raise ValueError('nonstandard port is not supported')
    addresses = {item[4][0] for item in socket.getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)}
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError('non-public address')
    address = sorted(addresses)[0]
    cls = http.client.HTTPSConnection if scheme == 'https' else http.client.HTTPConnection
    conn = cls(parts.hostname, port=port, timeout=8)
    conn._create_connection = lambda _address, timeout, source_address: socket.create_connection(
        (address, port), timeout, source_address
    )
    try:
        target = urlunsplit(('', '', parts.path or '/', parts.query, ''))
        conn.request('GET', target, headers={'User-Agent': 'ArchiveRuntime/1.0', 'Accept': 'text/html,text/plain', 'Accept-Encoding': 'identity'})
        response = conn.getresponse()
        if response.status != 200:
            raise ValueError('page unavailable or redirected')
        content_type = response.getheader('Content-Type', '').split(';', 1)[0].strip().lower()
        if content_type not in {'text/html', 'text/plain'}:
            raise ValueError('unsupported content type')
        raw = response.read(1000001)
        if len(raw) > 1000000:
            raise ValueError('page exceeds extraction limit')
        text = raw.decode(response.headers.get_content_charset() or 'utf-8', errors='replace')
        if content_type == 'text/plain':
            return text.strip()
        parser = _ReadableHTMLParser()
        parser.feed(text)
        body = _compact_text('\n'.join(parser.blocks)) or _compact_text(parser.text)
        return (f'# {parser.title.strip()}\n\n{body}' if parser.title.strip() else body).strip()
    finally:
        conn.close()
