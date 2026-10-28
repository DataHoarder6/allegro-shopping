"""Allegro URL identity: canonical URLs, offer ids, product uuids, cache subjects.

Allegro serves the same offer under at least four shapes: canonical
`/oferta/<slug>-<id>`, product landing `/produkt/<slug>-<uuid>?offerId=<id>`,
sponsored redirects `/events/clicks?...&redirect=<encoded url>`, and
`/dss-proxy/clicks?...`. Identity is resolved mechanically from the URL, never
from the title.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

_OFFER_PATH_RE = re.compile(r"(?:-|/)(\d{6,})$")
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)
_REDIRECT_PARAMS = ("redirect", "url", "dest", "destination")
# Tracking/session parameters that must not fragment identity.
_NOISE_PARAMS = frozenset(
    {
        "slist",
        "bi_s",
        "bi_m",
        "bi_c",
        "bi_t",
        "bi_cs",
        "bi_p",
        "sig",
        "placement",
        "ts",
        "emission_id",
        "emission_unit_id",
        "type",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
        "utm_term",
    }
)
_ALLOWED_HOSTS = frozenset({"allegro.pl", "www.allegro.pl"})


@dataclass(frozen=True, order=True)
class Subject:
    """A cache subject: one kind of thing, keyed by its own id namespace."""

    kind: str
    key: str

    def __post_init__(self) -> None:
        if not self.kind or not self.key:
            raise ValueError("Subject needs kind and key")

    @property
    def store_id(self) -> str:
        """Stable id for the shared hoard's `subject_id` column."""
        return f"{self.kind}:{self.key}"


def unwrap_redirect(url: str) -> str:
    """Follow Allegro's own tracking redirect parameter, if present."""
    parts = urlsplit(url)
    for name, value in parse_qsl(parts.query, keep_blank_values=True):
        if name in _REDIRECT_PARAMS and value.startswith(("https://", "http://")):
            return unquote(value)
    return url


def canonical_url(url: str) -> str:
    """Return the canonical offer/product URL with tracking parameters stripped."""
    unwrapped = unwrap_redirect(url)
    parts = urlsplit(unwrapped)
    host = parts.netloc.lower()
    if host not in _ALLOWED_HOSTS:
        raise ValueError(f"not an allegro.pl URL: {url}")
    path = re.sub(r"/{2,}", "/", parts.path)
    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in _NOISE_PARAMS
    ]
    return urlunsplit(("https", "allegro.pl", path, urlencode(sorted(query)), ""))


def offer_id_from_url(url: str) -> str | None:
    """Numeric offer id from an offer URL or a product URL's `offerId`, or None."""
    canon = canonical_url(url)
    parts = urlsplit(canon)
    for name, value in parse_qsl(parts.query, keep_blank_values=True):
        if name == "offerId" and value.isdigit():
            return value
    if "/oferta/" not in parts.path:
        return None
    match = _OFFER_PATH_RE.search(parts.path.rstrip("/"))
    return match.group(1) if match else None


def product_id_from_url(url: str) -> str | None:
    """Catalog product uuid from a /produkt/ URL, or None."""
    canon = canonical_url(url)
    path = urlsplit(canon).path
    if "/produkt/" not in path:
        return None
    match = _UUID_RE.search(path)
    return match.group(0).lower() if match else None


def offer_subject(url_or_id: str) -> Subject:
    oid = url_or_id if url_or_id.isdigit() else offer_id_from_url(url_or_id)
    if oid is None:
        raise ValueError(f"cannot derive offer id from {url_or_id!r}")
    return Subject("offer", oid)


def product_subject(product_id: str) -> Subject:
    return Subject("product", product_id.lower())


def seller_subject(login: str) -> Subject:
    return Subject("seller", login.strip().lower())


def search_subject(query: str, order: str | None = None) -> Subject:
    """A saved search is a subject too, so its result pages are cacheable."""
    key = query.strip().lower()
    if order:
        key = f"{key}|{order}"
    digest = hashlib.sha256(key.encode()).hexdigest()[:16]
    return Subject("search", digest)


def listing_url(
    query: str, *, page: int = 1, order: str | None = None, extra: dict[str, str] | None = None
) -> str:
    """Build a canonical listing URL. `order` uses Allegro's own codes (p, pd, d, qd, ...)."""
    params: dict[str, str] = {"string": query}
    if order:
        params["order"] = order
    if extra:
        params.update(extra)
    if page > 1:
        params["p"] = str(page)
    return "https://allegro.pl/listing?" + urlencode(params)
