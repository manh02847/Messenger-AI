"""Show API-provided web sources/search suggestions as plain Messenger text."""

from __future__ import annotations

import ipaddress
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit


def public_url(value: object) -> str | None:
    if (
        not isinstance(value, str)
        or len(value) > 2048
        or re.search(r'[\s<>"\\\x00-\x1f]', value)
    ):
        return None
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if (
            parsed.scheme not in ("http", "https")
            or not host
            or parsed.username
            or parsed.password
        ):
            return None
        if host == "localhost" or host.endswith((".localhost", ".local")):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            if "." not in host:
                return None
        _ = parsed.port
    except ValueError:
        return None
    return value


class SearchSuggestions(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items: list[tuple[str, str]] = []
        self.href: str | None = None
        self.label: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href = public_url(dict(attrs).get("href"))
            self.label = []

    def handle_data(self, data):
        if self.href:
            self.label.append(data)

    def handle_endtag(self, tag):
        if tag == "a":
            if self.href:
                label = " ".join(" ".join(self.label).split())
                if label:
                    self.items.append((label, self.href))
            self.href, self.label = None, []


def with_sources(data: dict, answer: str, char_limit: int) -> tuple[str, bool, int]:
    metadata = data["candidates"][0].get("groundingMetadata")
    if not isinstance(metadata, dict):
        return answer, False, 0
    chunks = metadata.get("groundingChunks", [])
    sources = []
    if isinstance(chunks, list):
        for chunk in chunks:
            web = chunk.get("web") if isinstance(chunk, dict) else None
            if not isinstance(web, dict):
                continue
            url = public_url(web.get("uri"))
            if url and url not in {item[1] for item in sources}:
                title = web.get("title")
                title = (
                    " ".join(title.split())
                    if isinstance(title, str)
                    else urlsplit(url).hostname
                )
                sources.append((title, url))
    suggestions = []
    entry = metadata.get("searchEntryPoint")
    if isinstance(entry, dict) and isinstance(entry.get("renderedContent"), str):
        parser = SearchSuggestions()
        parser.feed(entry["renderedContent"][:200000])
        suggestions = list(dict.fromkeys(parser.items))[:5]
    # Keep links intact, with room for an actual answer. No HTML, raw metadata,
    # search-query bodies or source text is logged/persisted separately.
    footer = ""
    allowance = max(0, char_limit - min(len(answer), 600) - 2)
    for heading, items in (("Google Search", suggestions), ("Nguồn", sources[:3])):
        lines = []
        for title, url in items:
            line = f"{title[:160]}: {url}"
            section = "\n\n" + heading + ":\n" + "\n".join([*lines, line])
            if len(footer) + len(section) <= allowance:
                lines.append(line)
        if lines:
            footer += "\n\n" + heading + ":\n" + "\n".join(lines)
    used = bool(sources or metadata.get("webSearchQueries"))
    if not footer:
        return answer[:char_limit], used, len(sources)
    return (
        answer[: max(0, char_limit - len(footer))].rstrip() + footer,
        used,
        len(sources),
    )
