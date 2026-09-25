"""Classify a repository into project profiles based on fingerprint signals."""
from __future__ import annotations

from espalier.models import HarnessConfig, RepoFingerprint


ALL_PROFILES = [
    "python_library",
    "python_app",
    "web_app",
    "ml_repo",
    "ai_ops_channel",
    "mixed_monorepo",
    "docs_heavy",
    "general",
]


def classify_repo(fingerprint: RepoFingerprint, config: HarnessConfig | None = None) -> tuple[list[str], dict[str, float]]:
    """Score the fingerprint against every profile and pick the matches.

    Returns ``(selected, all_scores)``: ``selected`` is the list of profile
    names scoring ``>= 0.45`` (the inclusion threshold), highest-first; if none
    clear it, the single top-scorer (or a language-based fallback) is used.
    ``selected`` is never empty — ``suppress_profiles`` narrows the selection
    but cannot empty it (irreducible floor: ``general``). ``all_scores`` maps
    every nonzero-scoring profile to its rounded score. ``config`` (if given)
    drops ``suppress_profiles`` and force-includes ``preferred_profiles`` (which
    win over suppression when an operator lists the same profile in both).
    """
    scores = {name: 0.0 for name in ALL_PROFILES}

    if "python" in fingerprint.languages:
        scores["python_library"] += 0.55
        scores["python_app"] += 0.25
        if fingerprint.entrypoints:
            scores["python_app"] += 0.35
        if fingerprint.api_surface:
            scores["python_app"] += 0.3
    if fingerprint.ui_surface:
        scores["web_app"] += 0.8
    if "node" in fingerprint.package_systems:
        scores["web_app"] += 0.35
    if fingerprint.ml_surface:
        scores["ml_repo"] += 0.95
    if fingerprint.ops_surface:
        scores["ai_ops_channel"] += 0.9
    if fingerprint.monorepo:
        scores["mixed_monorepo"] += 0.95
    if len(fingerprint.docs_surface) >= 3:
        scores["docs_heavy"] += 0.65
    if not fingerprint.ui_surface and not fingerprint.ml_surface and "python" in fingerprint.languages:
        scores["python_library"] += 0.2

    cleaned = {name: round(score, 2) for name, score in scores.items() if score > 0}
    ordered = sorted(cleaned.items(), key=lambda item: item[1], reverse=True)
    # Apply suppression to the scoring set BEFORE the fallback, so a suppressed
    # profile can never be the value the non-empty fallback restores. (Suppressing
    # last used to empty the selection, violating the non-empty contract.)
    suppressed = set(config.suppress_profiles) if config else set()
    eligible = [(name, score) for name, score in ordered if name not in suppressed]
    profiles = [name for name, score in eligible if score >= 0.45]

    if not profiles and eligible:
        profiles = [eligible[0][0]]
    if not profiles:
        if "python" in fingerprint.languages and "python_library" not in suppressed:
            profiles = ["python_library"]
        elif fingerprint.languages and "general" not in suppressed:
            profiles = ["general"]
        elif "docs_heavy" not in suppressed:
            profiles = ["docs_heavy"]
        else:
            profiles = ["general"]  # irreducible floor: the contract guarantees non-empty

    if config:
        for profile in config.preferred_profiles:
            cleaned[profile] = max(cleaned.get(profile, 0.0), 1.0)
            if profile not in profiles:
                profiles.append(profile)
    return profiles, cleaned
