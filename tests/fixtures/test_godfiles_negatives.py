"""Must-NOT-trip negatives corpus for the godfiles scanner.

This is a *negatives* corpus, not a test module: it holds clean-but-tempting
constructs the godfiles scanner must report ZERO findings on. It is
fixtures-only and contains NO real assertions. Inner functions OMIT the
``test_`` prefix so pytest skips collection (mirroring the positives
fixture's convention).

The godfiles scanner is fundamentally a LOC-threshold detector: a file
"trips" when ``outline_file(path)["loc"] >= DEFAULT_THRESHOLD`` (750).
The earn-the-gate test calls ``outline_file`` directly and asserts the
reported LOC exceeds the threshold.

The tempting bait here: this file is deliberately rich in the *structural*
signals a god-file candidate carries -- several top-level classes, dunder
methods, and multiple naming-prefix function clusters that the scanner's
``_cluster_functions`` would group and flag as extraction boundaries. A
naive "looks complex, must be a god-file" heuristic would be tempted. But
the godfiles contract is purely LOC-based, and this file sits comfortably
under 750 lines, so the scanner correctly stays silent.

Like the positives fixture, this lives under ``tests/fixtures/`` and is
therefore covered by the scanner's EXEMPT_PREFIXES, so live
``espalier scan godfiles`` runs never touch it. The negatives test reaches
it the SAME way the earn-the-gate test reaches the positives fixture: a
direct ``outline_file`` call on this path, immune to live-tree drift.
"""
from __future__ import annotations

from dataclasses import dataclass


# --- Cluster 1: a "handle_*" family. The scanner's _cluster_functions
# groups these by the "handle" prefix and would emit an extraction-hint
# cluster. Tempting structure, but it does not contribute to the LOC
# threshold by itself -- the file stays small.
def handle_create(payload: dict[str, object]) -> dict[str, object]:
    """Create a record from a payload."""
    return {"op": "create", "payload": payload}


def handle_update(payload: dict[str, object]) -> dict[str, object]:
    """Update a record from a payload."""
    return {"op": "update", "payload": payload}


def handle_delete(payload: dict[str, object]) -> dict[str, object]:
    """Delete a record identified by a payload."""
    return {"op": "delete", "payload": payload}


def handle_archive(payload: dict[str, object]) -> dict[str, object]:
    """Archive a record identified by a payload."""
    return {"op": "archive", "payload": payload}


# --- Cluster 2: a "render_*" family. Another grouped cluster the scanner
# would surface as a candidate extraction boundary.
def render_summary(rows: list[dict[str, object]]) -> str:
    """Render a one-line summary of rows."""
    return f"summary: {len(rows)} rows"


def render_table(rows: list[dict[str, object]]) -> str:
    """Render rows as a pipe-delimited table."""
    return "\n".join("|".join(str(v) for v in r.values()) for r in rows)


def render_detail(row: dict[str, object]) -> str:
    """Render a single row in detail form."""
    return "; ".join(f"{k}={v}" for k, v in row.items())


# --- Cluster 3: a "parse_*" family.
def parse_int(raw: str) -> int:
    """Parse an integer, returning 0 on empty input."""
    return int(raw) if raw else 0


def parse_float(raw: str) -> float:
    """Parse a float, returning 0.0 on empty input."""
    return float(raw) if raw else 0.0


def parse_bool(raw: str) -> bool:
    """Parse a truthy string into a bool."""
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# --- A handful of dunder-named module-level helpers feed the scanner's
# "__dunder__" group key. Still well under threshold.
def __probe_one__() -> int:
    return 1


def __probe_two__() -> int:
    return 2


@dataclass(frozen=True, slots=True)
class Account:
    """A small value object with several methods -- looks class-heavy,
    but the file as a whole stays well under the LOC threshold."""

    name: str
    balance: int

    def deposit(self, amount: int) -> "Account":
        """Return a new Account with the deposit applied."""
        return Account(self.name, self.balance + amount)

    def withdraw(self, amount: int) -> "Account":
        """Return a new Account with the withdrawal applied."""
        return Account(self.name, self.balance - amount)

    def is_overdrawn(self) -> bool:
        """True when the balance is negative."""
        return self.balance < 0

    def __repr__(self) -> str:
        return f"Account({self.name!r}, {self.balance})"


@dataclass(frozen=True, slots=True)
class Ledger:
    """A second class to make the file look multi-responsibility. The
    scanner's outline would report two top-level classes -- tempting for a
    'split this up' heuristic, but the LOC count is what governs."""

    accounts: tuple[Account, ...]

    def total(self) -> int:
        """Sum of all account balances."""
        return sum(a.balance for a in self.accounts)

    def overdrawn(self) -> tuple[Account, ...]:
        """Accounts currently overdrawn."""
        return tuple(a for a in self.accounts if a.is_overdrawn())

    def by_name(self, name: str) -> Account | None:
        """First account matching the given name, if any."""
        for a in self.accounts:
            if a.name == name:
                return a
        return None


class Pipeline:
    """A small orchestrator. Three classes plus three function clusters
    reads like a god-file candidate at a glance, yet the body is compact."""

    def __init__(self, steps: list[str]) -> None:
        self._steps = list(steps)

    def add_step(self, step: str) -> None:
        """Append a step to the pipeline."""
        self._steps.append(step)

    def run(self, value: object) -> list[object]:
        """Run each step, accumulating intermediate values."""
        out: list[object] = []
        acc = value
        for _step in self._steps:
            out.append(acc)
        return out

    def __len__(self) -> int:
        return len(self._steps)


# --- A "validate_*" cluster that demonstrates non-tautological logic.
def validate_name(name: str) -> bool:
    """A real predicate -- not a tautology. Returns True for non-empty,
    reasonably short names."""
    return 0 < len(name.strip()) <= 64


def validate_balance(balance: int) -> bool:
    """A real predicate over the balance range."""
    return -1_000_000 <= balance <= 1_000_000


def validate_account(account: Account) -> bool:
    """Compose the two validators above into an account-level check."""
    return validate_name(account.name) and validate_balance(account.balance)


# --- A "compute_*" cluster rounding out the structural bait.
def compute_fee(amount: int) -> int:
    """Flat 1% fee, floored to an integer."""
    return amount // 100


def compute_interest(balance: int, rate_bps: int) -> int:
    """Simple basis-point interest, integer-floored."""
    return balance * rate_bps // 10_000


def compute_net(balance: int, fee: int, interest: int) -> int:
    """Net balance after fee and interest."""
    return balance - fee + interest
