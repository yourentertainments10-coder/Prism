"""Bounded public-web retrieval with URL checks and freshness metadata."""

import hashlib
import html
import ipaddress
import json
import re
import socket
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

from prism_superagent.engine.attachments import request_text
from prism_superagent.engine.errors import FallbackToModel
from prism_superagent.tracing import record_trace

_URL = re.compile(r"https://[^\s<>()\]]+", re.IGNORECASE)


def classify_web_request(content, web_mode=False):
    if not isinstance(content, str):
        return None
    request = request_text(content).strip()
    lower = request.lower()
    urls = _URL.findall(request)
    if len(urls) > 1 and re.search(r"\b(verify|check|validate)\b.*\b(source|sources|urls?|links?)\b", lower):
        return "source_verify", {"urls": [url.rstrip(".,;:!?") for url in urls[:5]]}
    if urls and re.search(r"\b(fetch|retrieve|get|open|read|check|verify)\b", lower):
        return "web_api_get", {"url": urls[0].rstrip(".,;:!?" )}
    if web_mode or re.search(r"\b(search the web|web search|search online|search the internet)\b", lower):
        query = request
        query = re.sub(r"^(?:please\s+)?(?:search (?:the web|online|the internet)(?: for)?|web search for)\s*",
                       "", query, flags=re.IGNORECASE).strip()
        if query:
            return "web_search", {"query": query}
    return None


def execute_web(operation, inputs):
    if operation == "web_api_get":
        return _get_json_or_text(inputs["url"])
    if operation == "web_search":
        return _search(inputs["query"])
    if operation == "source_verify":
        sources = []
        for url in inputs["urls"]:
            status, content_type, raw = _request(url)
            sources.append({"url": url, "status": status, "content_type": content_type,
                            "sha256": hashlib.sha256(raw).hexdigest(),
                            "verified": status == 200})
        return {"sources": sources, "verified": bool(sources) and all(s["verified"] for s in sources),
                "retrieved_at": datetime.now(timezone.utc).isoformat()}
    raise ValueError(f"Unsupported web retrieval operation: {operation}")


def _validate_public_https(url):
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("Web retrieval accepts public HTTPS URLs only.")
    host = parsed.hostname.rstrip(".").lower()
    if host in ("localhost", "localhost.localdomain"):
        raise ValueError("Local and private network URLs are blocked.")
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(item[4][0])
                         for item in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)]
        except OSError as exc:
            raise ValueError(f"Could not resolve public host '{host}': {exc}") from None
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("Local and private network URLs are blocked.")
    return parsed


def _request(url, params=None):
    _validate_public_https(url)
    try:
        record_trace("external_api_request", url=url)
        with httpx.Client(timeout=httpx.Timeout(15, connect=5), follow_redirects=False,
                          headers={"User-Agent": "Prism/2.0"}) as client:
            with client.stream("GET", url, params=params) as response:
                if response.is_redirect:
                    raise ValueError("Redirects are not followed by Prism's verified fetcher.")
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 2_000_000:
                        raise ValueError("Response exceeded Prism's 2 MB retrieval limit.")
                return response.status_code, response.headers.get("content-type", ""), bytes(body)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429 or exc.response.status_code >= 500:
            raise FallbackToModel(
                f"The specialized web source returned HTTP {exc.response.status_code}.") from None
        raise ValueError(f"The source returned HTTP {exc.response.status_code}.") from None
    except httpx.RequestError as exc:
        raise FallbackToModel(
            f"The specialized web request could not connect ({type(exc).__name__}).") from None


def _get_json_or_text(url):
    status, content_type, raw = _request(url)
    digest = hashlib.sha256(raw).hexdigest()
    retrieved_at = datetime.now(timezone.utc).isoformat()
    charset_match = re.search(r"charset=([^;\s]+)", content_type, re.IGNORECASE)
    encoding = charset_match.group(1) if charset_match else "utf-8"
    body = raw.decode(encoding, errors="replace")
    if "json" in content_type.lower() or body.lstrip().startswith(("{", "[")):
        try:
            body = json.loads(body)
            formatted = json.dumps(body, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            formatted = body[:12_000]
    else:
        formatted = _strip_html(body)[:12_000] if "html" in content_type.lower() else body[:12_000]
    return {"url": url, "status": status, "content_type": content_type,
            "retrieved_at": retrieved_at, "sha256": digest, "body": formatted,
            "verification": ["public HTTPS host", "HTTP 200", "content SHA-256"],
            "verified": status == 200 and bool(digest)}


class _SearchParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self.current = None
        self.capture = None
        self.result_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        if tag == "div":
            if self.current is None and "result" in classes:
                self.current = {"title": "", "url": "", "snippet": ""}
                self.results.append(self.current)
                self.result_depth = 1
            elif self.current is not None:
                self.result_depth += 1
        if self.current is not None and tag == "a" and "result__a" in classes:
            self.current["url"] = attrs.get("href", "")
            self.capture = "title"
        elif self.current is not None and "result__snippet" in classes:
            self.capture = "snippet"

    def handle_endtag(self, tag):
        if tag == "a":
            self.capture = None
        if tag == "div" and self.current is not None:
            self.result_depth -= 1
            if self.result_depth <= 0:
                self.current = None

    def handle_data(self, data):
        if self.current is not None and self.capture:
            self.current[self.capture] += data


def _search(query):
    status, _content_type, raw = _request("https://html.duckduckgo.com/html/",
                                          params={"q": query})
    parser = _SearchParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    results = [item for item in parser.results if item.get("title") and item.get("url")][:6]
    return {"query": query, "status": status,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "results": results, "verified": status == 200 and bool(results)}


def _strip_html(source):
    class TextOnly(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []
            self.hidden = 0

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style", "noscript", "svg"):
                self.hidden += 1
            elif tag in ("p", "div", "br", "li", "tr", "h1", "h2", "h3") and self.parts:
                self.parts.append("\n")

        def handle_endtag(self, tag):
            if tag in ("script", "style", "noscript", "svg") and self.hidden:
                self.hidden -= 1

        def handle_data(self, data):
            if not self.hidden:
                self.parts.append(data)

    parser = TextOnly()
    parser.feed(source)
    return re.sub(r"\n[ \t]+", "\n", html.unescape(" ".join(parser.parts))).strip()

