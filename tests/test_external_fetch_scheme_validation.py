"""TP-146 146-C: pins the http(s)-only allowlist that
`external_fetch._validate_url_scheme` enforces before any
`urllib.request.urlopen` call, and prevents regression to the bare
urlopen pattern ruff S310 caught.

Without this contract, the urlopen call accepts any scheme
`urllib.request` understands — `file://`, `ftp://`, `gopher://`,
`data:`, `javascript:` — and the `refresh-externals` workflow flows
external input through that path. A poisoned PR could read local
files or probe internal services via a crafted URL silently; the
scheme check is the moment-of-defense.

Also pins case-insensitive comparison per RFC 3986 §3.1: uppercase
and mixed-case good URLs must pass without a caller-side `.lower()`
shim. If the test ever needs to lowercase its input to pass, the
implementation has drifted.
"""
from __future__ import annotations

import pytest

from espalier import external_fetch


@pytest.mark.security
@pytest.mark.parametrize("bad_url", [
    "file:///etc/passwd",
    "ftp://example.com/file",
    "data:text/plain;base64,aGVsbG8=",
    "gopher://example.com",
    "javascript:alert(1)",
    "/etc/passwd",          # no scheme at all
    "",                     # empty
])
def test_non_http_schemes_rejected(bad_url):
    with pytest.raises(ValueError, match="http"):
        external_fetch._validate_url_scheme(bad_url)


@pytest.mark.security
@pytest.mark.parametrize("good_url", [
    "http://example.com/path",
    "https://example.com/path",
    "HTTPS://EXAMPLE.COM",       # uppercase scheme (RFC 3986 §3.1)
    "Http://Example.Com",        # mixed case
])
def test_http_schemes_accepted(good_url):
    # Pass the URL through directly. The validator must handle
    # case-insensitively without help from the caller.
    external_fetch._validate_url_scheme(good_url)


@pytest.mark.security
@pytest.mark.parametrize("bad_url", ["file:///etc/passwd", "ftp://x"])
def test_fetch_url_rejects_non_http_before_network(bad_url):
    """`fetch_url` itself must raise before doing any I/O — proves the
    scheme check guards the public entry point, not just the helper."""
    with pytest.raises(ValueError, match="http"):
        external_fetch.fetch_url(bad_url, timeout=0.1, retries=0)


@pytest.mark.security
def test_non_string_url_rejected():
    """Non-string inputs reach the validator (e.g., int from a bad
    config); reject rather than crash deeper in urllib."""
    with pytest.raises(ValueError, match="http"):
        external_fetch._validate_url_scheme(None)  # type: ignore[arg-type]
