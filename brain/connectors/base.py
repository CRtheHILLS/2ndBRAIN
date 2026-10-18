"""Connector base types: Candidate, Doc, Connector protocol, URL normalization, HTTP helper."""
from __future__ import annotations

import ipaddress
import socket
import threading
from typing import Literal, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, Field

UA = "2ndBRAIN/0.1 (+https://github.com/CRtheHILLS/2ndBRAIN)"

Kind = Literal["official", "encyclopedia", "paper", "textbook", "video", "web", "forum", "book"]


class Candidate(BaseModel):
    url: str
    title: str
    kind: Kind
    snippet: str = ""
    year: int | None = None
    authority: float = 0.5
    connector: str
    lang: str = ""
    extra: dict = Field(default_factory=dict)


class Doc(BaseModel):
    url: str
    title: str
    text: str
    lang: str = ""
    kind: Kind = "web"
    connector: str = ""
    meta: dict = Field(default_factory=dict)


class Connector(Protocol):
    name: str

    def search(self, query: str, lang: str, limit: int) -> list[Candidate]: ...

    def fetch(self, c: Candidate) -> Doc | None: ...


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    for prefix in ("mobile.", "m.", "www."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    if parts.port:
        host = f"{host}:{parts.port}"
    query = urlencode([
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() != "fbclid"
    ])
    path = parts.path.rstrip("/")
    scheme = (parts.scheme or "https").lower()
    if scheme == "http":
        scheme = "https"
    return urlunsplit((scheme, host, path, query, ""))


PRIVATE_MSG = "비공개 주소는 가져오지 않아요"
_BLOCKED_HOSTS = ("localhost",)
_BLOCKED_SUFFIXES = (".localhost", ".internal")  # covers *.railway.internal


def _system_getaddrinfo(host: str, port: int):
    return socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)


_getaddrinfo = _system_getaddrinfo  # tests swap this; production resolves for real


def is_public_url(url: str) -> bool:
    """http(s) URL whose host resolves only to public addresses (SSRF guard).

    Rejects loopback, private (10/8, 172.16/12, 192.168/16), link-local (169.254/16),
    unique-local (fc00::/7), ``localhost`` and ``*.internal``; resolution failure -> False.
    """
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    if parts.scheme not in ("http", "https"):
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    if not host or host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_SUFFIXES):
        return False
    try:
        infos = _getaddrinfo(host, port or (443 if parts.scheme == "https" else 80))
    except (OSError, UnicodeError, ValueError):
        return False
    if not infos:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(str(info[4][0]).split("%", 1)[0])
        except ValueError:
            return False
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if (ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast
                or ip.is_reserved or ip.is_unspecified or not ip.is_global):
            return False
    return True


def _guard(url: str) -> None:
    if not is_public_url(url):
        raise ValueError(PRIVATE_MSG)


def _check_redirect(r: httpx.Response) -> None:
    """Event hook: every redirect hop must also point at a public address."""
    if r.is_redirect:
        _guard(str(r.url.join(r.headers.get("location", ""))))


_client: httpx.Client | None = None
_client_lock = threading.Lock()


def _get_client() -> httpx.Client:
    global _client
    with _client_lock:
        if _client is None:
            _client = httpx.Client(headers={"User-Agent": UA}, follow_redirects=True,
                                   event_hooks={"response": [_check_redirect]})
        return _client


def close_client() -> None:
    global _client
    with _client_lock:
        if _client is not None:
            _client.close()
            _client = None


def http_get(url: str, params: dict | None = None, timeout: float = 20,
             headers: dict | None = None) -> httpx.Response:
    _guard(url)
    r = _get_client().get(url, params=params, timeout=timeout, headers=headers)
    r.raise_for_status()
    return r


def http_download(url: str, max_bytes: int, timeout: float = 30) -> tuple[bytes, str]:
    """Stream a GET, never buffering more than max_bytes. Rejects oversized Content-Length."""
    _guard(url)
    with _get_client().stream("GET", url, timeout=timeout) as r:
        r.raise_for_status()
        declared = r.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > max_bytes:
            raise ValueError(f"content-length {declared} exceeds cap {max_bytes}")
        buf = bytearray()
        for chunk in r.iter_bytes():
            buf.extend(chunk)
            if len(buf) >= max_bytes:
                break
        return bytes(buf[:max_bytes]), r.headers.get("content-type", "").lower()
