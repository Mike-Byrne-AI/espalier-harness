"""Tests for ``espalier.profiles`` — the ``classify_repo`` scorer
that turns a ``RepoFingerprint`` into the matched profile names
(``general``, ``python_library``, ``python_app``, ``ml_repo``, ...)
that drive ``HarnessConfig`` selection.

Pins each profile's recognition rules: Python-only language scores
``python_library``; Python + entrypoints scores ``python_app``;
ML stack signals score ``ml_repo``. Without this contract a
scoring-weight tweak could silently demote ``ml_repo`` below
``python_library`` for an ML codebase, regressing harness
configuration to a generic Python profile without any visible error.
"""
from __future__ import annotations


from espalier.models import HarnessConfig, RepoFingerprint
from espalier.profiles import ALL_PROFILES, classify_repo


def _make_fp(**kwargs) -> RepoFingerprint:
    defaults = dict(repo_name="test-repo", repo_root=".")
    defaults.update(kwargs)
    return RepoFingerprint(**defaults)


class TestAllProfiles:
    def test_all_profiles_is_non_empty(self):
        assert len(ALL_PROFILES) > 0

    def test_all_profiles_contains_general(self):
        assert "general" in ALL_PROFILES

    def test_all_profiles_contains_python_library(self):
        assert "python_library" in ALL_PROFILES

    def test_all_profiles_contains_ml_repo(self):
        assert "ml_repo" in ALL_PROFILES


class TestClassifyRepoPythonLibrary:
    def test_python_language_scores_python_library(self):
        fp = _make_fp(languages=["python"])
        profiles, scores = classify_repo(fp)
        assert "python_library" in profiles

    def test_python_with_entrypoints_scores_python_app(self):
        fp = _make_fp(languages=["python"], entrypoints=["main.py"])
        profiles, scores = classify_repo(fp)
        assert "python_app" in profiles

    def test_python_with_api_surface_scores_python_app(self):
        fp = _make_fp(languages=["python"], api_surface=True)
        profiles, scores = classify_repo(fp)
        assert "python_app" in profiles

    def test_python_library_score_boosted_without_ui_or_ml(self):
        fp = _make_fp(languages=["python"], ui_surface=False, ml_surface=False)
        profiles, scores = classify_repo(fp)
        assert scores.get("python_library", 0.0) >= 0.75


class TestClassifyRepoWebApp:
    def test_ui_surface_scores_web_app(self):
        fp = _make_fp(languages=[], ui_surface=True)
        profiles, scores = classify_repo(fp)
        assert "web_app" in profiles

    def test_node_package_system_scores_web_app(self):
        fp = _make_fp(languages=[], package_systems=["node"])
        profiles, scores = classify_repo(fp)
        assert "web_app" in scores

    def test_ui_surface_score_at_least_threshold(self):
        fp = _make_fp(languages=[], ui_surface=True)
        profiles, scores = classify_repo(fp)
        assert scores.get("web_app", 0.0) >= 0.45


class TestClassifyRepoMlRepo:
    def test_ml_surface_scores_ml_repo(self):
        fp = _make_fp(languages=["python"], ml_surface=True)
        profiles, scores = classify_repo(fp)
        assert "ml_repo" in profiles

    def test_ml_repo_score_high(self):
        fp = _make_fp(languages=["python"], ml_surface=True)
        profiles, scores = classify_repo(fp)
        assert scores.get("ml_repo", 0.0) >= 0.9


class TestClassifyRepoAiOpsChannel:
    def test_ops_surface_scores_ai_ops_channel(self):
        fp = _make_fp(languages=["python"], ops_surface=True)
        profiles, scores = classify_repo(fp)
        assert "ai_ops_channel" in profiles

    def test_ops_channel_score_high(self):
        fp = _make_fp(languages=["python"], ops_surface=True)
        profiles, scores = classify_repo(fp)
        assert scores.get("ai_ops_channel", 0.0) >= 0.9


class TestClassifyRepoMonorepo:
    def test_monorepo_flag_scores_mixed_monorepo(self):
        fp = _make_fp(languages=["python"], monorepo=True)
        profiles, scores = classify_repo(fp)
        assert "mixed_monorepo" in profiles

    def test_mixed_monorepo_score_high(self):
        fp = _make_fp(languages=[], monorepo=True)
        profiles, scores = classify_repo(fp)
        assert scores.get("mixed_monorepo", 0.0) >= 0.9


class TestClassifyRepoDocsHeavy:
    def test_three_docs_files_scores_docs_heavy(self):
        fp = _make_fp(languages=[], docs_surface=["README.md", "CONTRIBUTING.md", "CHANGELOG.md"])
        profiles, scores = classify_repo(fp)
        assert "docs_heavy" in scores

    def test_two_docs_files_does_not_score_docs_heavy(self):
        fp = _make_fp(languages=[], docs_surface=["README.md", "CONTRIBUTING.md"])
        profiles, scores = classify_repo(fp)
        assert scores.get("docs_heavy", 0.0) == 0.0


class TestClassifyRepoFallbacks:
    def test_empty_fingerprint_returns_docs_heavy(self):
        fp = _make_fp(languages=[])
        profiles, scores = classify_repo(fp)
        assert profiles == ["docs_heavy"]

    def test_python_with_no_signals_returns_python_library(self):
        fp = _make_fp(languages=["python"])
        profiles, scores = classify_repo(fp)
        assert "python_library" in profiles

    def test_non_python_language_returns_general_if_no_other_signal(self):
        fp = _make_fp(languages=["ruby"])
        profiles, scores = classify_repo(fp)
        assert profiles == ["general"]

    def test_profiles_list_is_non_empty(self):
        fp = _make_fp(languages=["python"])
        profiles, scores = classify_repo(fp)
        assert len(profiles) > 0


class TestClassifyRepoReturnStructure:
    def test_returns_tuple_of_two(self):
        fp = _make_fp(languages=["python"])
        result = classify_repo(fp)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_profiles_is_list(self):
        fp = _make_fp(languages=["python"])
        profiles, scores = classify_repo(fp)
        assert isinstance(profiles, list)

    def test_scores_is_dict(self):
        fp = _make_fp(languages=["python"])
        profiles, scores = classify_repo(fp)
        assert isinstance(scores, dict)

    def test_scores_only_contain_non_zero_values(self):
        fp = _make_fp(languages=["python"])
        profiles, scores = classify_repo(fp)
        assert all(v > 0 for v in scores.values())

    def test_scores_are_rounded_to_two_decimal_places(self):
        fp = _make_fp(languages=["python"])
        profiles, scores = classify_repo(fp)
        for v in scores.values():
            assert round(v, 2) == v


class TestClassifyRepoWithConfig:
    def test_preferred_profile_added_to_profiles(self):
        fp = _make_fp(languages=["python"])
        config = HarnessConfig(preferred_profiles=["web_app"])
        profiles, scores = classify_repo(fp, config)
        assert "web_app" in profiles

    def test_preferred_profile_score_set_to_at_least_one(self):
        fp = _make_fp(languages=["python"])
        config = HarnessConfig(preferred_profiles=["web_app"])
        profiles, scores = classify_repo(fp, config)
        assert scores.get("web_app", 0.0) >= 1.0

    def test_suppressed_profile_removed_from_profiles(self):
        fp = _make_fp(languages=["python"])
        config = HarnessConfig(suppress_profiles=["python_library"])
        profiles, scores = classify_repo(fp, config)
        assert "python_library" not in profiles

    def test_no_config_does_not_crash(self):
        fp = _make_fp(languages=["python"])
        profiles, scores = classify_repo(fp, config=None)
        assert isinstance(profiles, list)

    def test_suppressing_every_scoring_profile_is_never_empty(self):
        """classify_repo's docstring guarantees a non-empty result; suppression
        narrows but must not empty it (suppression once ran AFTER the fallback,
        so suppressing the only scorer returned [])."""
        fp = _make_fp(languages=["python"])
        config = HarnessConfig(suppress_profiles=["python_library", "python_app"])
        profiles, _ = classify_repo(fp, config)
        assert profiles, "suppression emptied the selection; contract is non-empty"
        assert "python_library" not in profiles and "python_app" not in profiles

    def test_suppressing_all_known_profiles_falls_to_irreducible_floor(self):
        """Even if an operator suppresses every profile, the contract floor holds."""
        fp = _make_fp(languages=[])
        config = HarnessConfig(suppress_profiles=list(ALL_PROFILES))
        profiles, _ = classify_repo(fp, config)
        assert profiles == ["general"]
