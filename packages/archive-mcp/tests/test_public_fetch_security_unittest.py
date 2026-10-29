"""Security checks for public-link extraction without real network access."""
import io
import unittest
from unittest.mock import MagicMock, patch

from jobs import link_extract


class PublicFetchSecurityTests(unittest.TestCase):
    def test_mixed_public_and_private_dns_answers_fail_closed(self):
        answers = [(None, None, None, None, ("8.8.8.8", 443)),
                   (None, None, None, None, ("127.0.0.1", 443))]
        with patch.object(link_extract.socket, "getaddrinfo", return_value=answers), \
             patch.object(link_extract.http.client, "HTTPSConnection") as factory:
            with self.assertRaisesRegex(ValueError, "non-public"):
                link_extract.fetch_public_content("https://example.com/")
            factory.assert_not_called()

    def test_connection_is_pinned_to_validated_address(self):
        response = MagicMock(status=200)
        response.getheader.return_value = "text/plain"
        response.headers.get_content_charset.return_value = "utf-8"
        response.read.return_value = b"safe body"
        connection = MagicMock()
        connection.getresponse.return_value = response
        connection.request.side_effect = lambda *_a, **_kw: connection._create_connection(
            ("example.com", 443), 8, None
        )
        answers = [(None, None, None, None, ("8.8.8.8", 443))]
        with patch.object(link_extract.socket, "getaddrinfo", return_value=answers), \
             patch.object(link_extract.socket, "create_connection") as connect, \
             patch.object(link_extract.http.client, "HTTPSConnection", return_value=connection) as factory:
            self.assertEqual(link_extract.fetch_public_content("https://example.com/"), "safe body")
            factory.assert_called_once_with("example.com", port=443, timeout=8)
            connect.assert_called_once_with(("8.8.8.8", 443), 8, None)

    def test_real_http_client_connects_to_validated_ip(self):
        sock = MagicMock()
        sock.makefile.return_value = io.BytesIO(
            b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 9\r\n\r\nsafe body"
        )
        answers = [(None, None, None, None, ("8.8.8.8", 80))]
        with patch.object(link_extract.socket, "getaddrinfo", return_value=answers) as resolve, \
             patch.object(link_extract.socket, "create_connection", return_value=sock) as connect:
            self.assertEqual(link_extract.fetch_public_content("http://example.com/"), "safe body")
            self.assertEqual(resolve.call_count, 1)
            connect.assert_called_once_with(("8.8.8.8", 80), 8, None)
            self.assertIn(b"Host: example.com", sock.sendall.call_args.args[0])

    def test_redirect_is_not_followed(self):
        response = MagicMock(status=302)
        connection = MagicMock()
        connection.getresponse.return_value = response
        with patch.object(link_extract.socket, "getaddrinfo", return_value=[(None, None, None, None, ("8.8.8.8", 443))]), \
             patch.object(link_extract.http.client, "HTTPSConnection", return_value=connection):
            with self.assertRaisesRegex(ValueError, "redirected"):
                link_extract.fetch_public_content("https://example.com/")
            self.assertEqual(connection.request.call_count, 1)

    def test_public_html_extracts_content_without_scripts(self):
        response = MagicMock(status=200)
        response.getheader.return_value = "text/html"
        response.headers.get_content_charset.return_value = "utf-8"
        response.read.return_value = b"<title>Example</title><h1>Header</h1><p>Body</p><script>secret</script>"
        connection = MagicMock()
        connection.getresponse.return_value = response
        with patch.object(link_extract.socket, "getaddrinfo", return_value=[(None, None, None, None, ("8.8.8.8", 443))]), \
             patch.object(link_extract.http.client, "HTTPSConnection", return_value=connection):
            text = link_extract.fetch_public_content("https://example.com/")
        self.assertIn("Header", text)
        self.assertIn("Body", text)
        self.assertNotIn("secret", text)


if __name__ == "__main__":
    unittest.main()
