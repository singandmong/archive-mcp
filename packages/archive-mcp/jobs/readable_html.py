"""Small HTML-to-text helper shared by the public link extractor."""
import re
from html.parser import HTMLParser


def _compact_text(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n\n".join(line for line in lines if line)


class _ReadableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.links: list[str] = []
        self.blocks: list[str] = []
        self.text = ""
        self._title_parts: list[str] = []
        self._block_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False
        self._block_tag: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = True
        if tag == "a":
            href = dict(attrs).get("href")
            if href and href.startswith(("http://", "https://")) and href not in self.links:
                self.links.append(href)
        if tag in {"h1", "h2", "h3", "p", "li", "blockquote"}:
            self._block_tag = tag
            self._block_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = False
            self.title = _compact_text(" ".join(self._title_parts))
        if self._block_tag == tag:
            block = _compact_text(" ".join(self._block_parts))
            if block:
                if tag in {"h1", "h2", "h3"}:
                    level = {"h1": "#", "h2": "##", "h3": "###"}[tag]
                    block = f"{level} {block}"
                elif tag == "li":
                    block = f"- {block}"
                elif tag == "blockquote":
                    block = f"> {block}"
                self.blocks.append(block)
            self._block_tag = None
            self._block_parts = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if not text:
            return
        self.text += f" {text}"
        if self._in_title:
            self._title_parts.append(text)
        if self._block_tag:
            self._block_parts.append(text)
