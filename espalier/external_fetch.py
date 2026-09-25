"""Stdlib URL fetcher with retry/timeout.

Single function `fetch_url(url, ...)` returning a `FetchResult`. No
third-party deps; uses `urllib.request` so the refresh subsystem can
run on a vanilla Python install. Network calls happen here only — the
parser and diff modules are pure transforms over the result.

Conservative defaults: 30s timeout, 2 retries on connection errors and
5xx responses, honors `Retry-After` on 429. Rejects non-text content
types because espalier does not refresh binary pins.
"""
from __future__ import annotations

import http.client
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from espalier._text import os_error_text

DEFAULT_USER_AGENT = "espalier-refresh-externals/0.6"
TEXT_CONTENT_TYPES = (
    "text/",
    "application/json",
    "application/xml",
    "application/xhtml+xml",
)

# `urllib.request.urlopen` accepts file://, ftp://, gopher:// and other
# schemes that would let a poisoned URL read local disk or probe internal
# services. RFC 3986 §3.1 says schemes are case-insensitive, so we compare
# on the lowercased input.
_ALLOWED_URL_SCHEMES = ("http://", "https://")


def _validate_url_scheme(url: str) -> None:
    """Reject URLs whose scheme is not http(s). Raises ValueError on rejection."""
    if not isinstance(url, str) or not url.lower().startswith(_ALLOWED_URL_SCHEMES):
        raise ValueError(
            f"external_fetch only supports http(s) URLs; got {url!r}"
        )


@dataclass(frozen=True)
class FetchResult:
    """Result of a single URL fetch attempt."""

    url: str
    status_code: int
    content: str
    fetched_at: datetime
    final_url: str
    error: str | None

    @property
    def ok(self) -> bool:
        return self.error is None and 200 <= self.status_code < 300


def _is_text_content_type(content_type: str) -> bool:
    ct = content_type.lower().split(";", 1)[0].strip()
    return any(ct.startswith(prefix) for prefix in TEXT_CONTENT_TYPES)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def fetch_url(
    url: str,
    *,
    timeout: float = 30.0,
    retries: int = 2,
    user_agent: str = DEFAULT_USER_AGENT,
) -> FetchResult:
    """Fetch `url` as text. Retries on connection errors and 5xx (not 4xx).

    Honors `Retry-After` on 429. Returns a FetchResult; never raises
    for transport-layer errors. Raises ValueError if the URL scheme is
    not http(s) — caller bug, not network condition.
    """
    _validate_url_scheme(url)
    last_error: str | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(  # noqa: S310 -- scheme validated by _validate_url_scheme above
                url,
                headers={"User-Agent": user_agent, "Accept": "text/html, text/plain, */*"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 -- scheme validated by _validate_url_scheme above
                content_type = resp.headers.get("Content-Type", "")
                if not _is_text_content_type(content_type):
                    return FetchResult(
                        url=url,
                        status_code=resp.status,
                        content="",
                        fetched_at=_now(),
                        final_url=resp.url,
                        error=(
                            f"non-text content-type {content_type!r}; "
                            "espalier does not refresh binary pins"
                        ),
                    )
                charset = resp.headers.get_content_charset() or "utf-8"
                raw = resp.read()
                try:
                    content = raw.decode(charset, errors="replace")
                except LookupError:
                    # An unknown/bogus Content-Type charset label raises
                    # LookupError, which is NOT in this method's except clauses
                    # and would otherwise escape uncaught. Degrade to a utf-8
                    # best-effort decode (errors="replace").
                    content = raw.decode("utf-8", errors="replace")
                return FetchResult(
                    url=url,
                    status_code=resp.status,
                    content=content,
                    fetched_at=_now(),
                    final_url=resp.url,
                    error=None,
                )
        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code}: {e.reason}"
            # 4xx is a hard fail — no retry.
            if 400 <= e.code < 500 and e.code != 429:
                return FetchResult(
                    url=url,
                    status_code=e.code,
                    content="",
                    fetched_at=_now(),
                    final_url=getattr(e, "url", url) or url,
                    error=last_error,
                )
            # 429: honor Retry-After if present. Every backoff sleep is gated
            # on `attempt < retries` so the final attempt returns immediately
            # instead of wasting cycles waiting for a retry that will never
            # happen. Original behavior on a 429 *without* a Retry-After
            # (immediately-retry-no-sleep) is preserved.
            if e.code == 429:
                retry_after = e.headers.get("Retry-After") if e.headers else None
                if retry_after and attempt < retries:
                    try:
                        wait = float(retry_after)
                        time.sleep(min(wait, 60.0))
                    except ValueError:
                        time.sleep(2 ** attempt)
            elif attempt < retries:
                time.sleep(2 ** attempt)
        except urllib.error.URLError as e:
            last_error = f"URLError: {e.reason}"
            if attempt < retries:
                time.sleep(2 ** attempt)
        except (TimeoutError, OSError) as e:
            last_error = f"{type(e).__name__}: {os_error_text(e)}"
            if attempt < retries:
                time.sleep(2 ** attempt)
        except (http.client.InvalidURL, ValueError) as e:
            # A malformed URL (control char in host, bad IPv6 literal) raised
            # while Request()/urlopen() parse it. http.client.InvalidURL is an
            # HTTPException (NOT URLError/OSError) and the IPv6 case is a bare
            # ValueError — neither is caught above, so both would otherwise
            # escape this method's "never raises for transport errors" contract
            # (and cli.main() re-raises InvalidURL as a raw traceback). A bad
            # URL will not heal on retry: record it and stop.
            last_error = f"malformed URL: {e}"
            break
    return FetchResult(
        url=url,
        status_code=0,
        content="",
        fetched_at=_now(),
        final_url=url,
        error=last_error or "unknown fetch error",
    )
