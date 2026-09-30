"""Tests for ``espalier.config.load_config``.

Pins the loader's permissive contract: defaults are returned when no
``espalier.toml`` exists, valid toml parses cleanly, and an unknown key
loads (dropped) with a warning that names it and the nearest known key.
The load-not-crash half keeps schema additions forward-compatible (a new
``HarnessConfig`` field never breaks an existing adopter's first load);
the warn half ends the silence a typo used to enjoy (DEF-950).
"""
from __future__ import annotations

import warnings


from espalier.config import load_config
from espalier.models import HarnessConfig


class TestLoadConfig:
    def test_default_config_when_no_toml(self, tmp_path):
        """load_config returns a HarnessConfig with defaults when no toml exists."""
        config = load_config(tmp_path)
        assert isinstance(config, HarnessConfig)
        assert config.surface_mode == "core"
        assert config.lane_count == 3

    def test_parses_valid_toml(self, tmp_path):
        """load_config reads preferred_profiles from a valid espalier.toml."""
        (tmp_path / "espalier.toml").write_text(
            'preferred_profiles = ["python_api"]\n', encoding="utf-8"
        )
        config = load_config(tmp_path)
        assert config.preferred_profiles == ["python_api"]

    def test_unknown_keys_load_and_warn(self, tmp_path):
        """An unrecognised key is dropped, the load survives, AND the drop is
        said: one warning naming the file, the key and the known keys. Until
        2026-09-30 this pin asserted only the first half and its docstring called
        the silence a contract."""
        (tmp_path / "espalier.toml").write_text(
            'unknown_key = "value"\nlane_count = 5\n', encoding="utf-8"
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            config = load_config(tmp_path)
        assert config.lane_count == 5  # real key was parsed
        assert isinstance(config, HarnessConfig)  # no crash
        texts = [str(w.message) for w in caught]
        assert len(texts) == 1, texts
        assert "espalier.toml: unknown key `unknown_key` is ignored" in texts[0]
        assert "known keys: " in texts[0] and "lane_count" in texts[0]

    def test_unknown_key_warning_names_the_nearest_known_key(self, tmp_path):
        """The drive that filed DEF-950's second half: ``protcted_paths`` loaded
        with zero warnings."""
        (tmp_path / "espalier.toml").write_text(
            'protected_paths = ["src/core/"]\nprotcted_paths = ["typo/"]\n', encoding="utf-8"
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            config = load_config(tmp_path)
        assert config.protected_paths == ["src/core/"]
        texts = [str(w.message) for w in caught]
        assert len(texts) == 1, texts
        assert "unknown key `protcted_paths`" in texts[0]
        assert "did you mean `protected_paths`?" in texts[0]

    def test_unknown_table_warns_like_a_key(self, tmp_path):
        """A TOML table arrives as a dict-valued top-level key; same loop."""
        (tmp_path / "espalier.toml").write_text(
            'lane_count = 2\n[stack]\nsource_extensions = [".astro"]\n', encoding="utf-8"
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            load_config(tmp_path)
        texts = [str(w.message) for w in caught]
        assert len(texts) == 1 and "unknown key `stack`" in texts[0], texts

    def test_foreign_keys_another_reader_owns_do_not_warn(self, tmp_path):
        """A key declared in ``FOREIGN_KEYS`` belongs to a script outside the
        engine (the self-host ``record_snapshot.py`` refusal keys); warning on
        it would invite deleting the refusal."""
        from espalier.config import FOREIGN_KEYS

        assert FOREIGN_KEYS, "the census below needs at least one declared foreign key"
        body = "".join(f"{key} = true\n" for key in FOREIGN_KEYS) + "lane_count = 4\n"
        (tmp_path / "espalier.toml").write_text(body, encoding="utf-8")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            config = load_config(tmp_path)
        assert config.lane_count == 4
        assert [str(w.message) for w in caught] == []

    def test_custom_config_path(self, tmp_path):
        """load_config accepts an explicit config_path argument."""
        custom = tmp_path / "custom.toml"
        custom.write_text('lane_count = 7\n', encoding="utf-8")
        config = load_config(tmp_path, config_path=custom)
        assert config.lane_count == 7

    def test_explicit_missing_config_path_warns(self, tmp_path):
        """an EXPLICIT --config path that does not exist is an
        operator typo, not 'no config present'. It must warn (rather than
        silently run with defaults) so the operator knows their config was not
        applied."""
        missing = tmp_path / "typo.toml"  # never created
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = load_config(tmp_path, config_path=missing)
        assert isinstance(config, HarnessConfig)
        assert config.lane_count == 3  # defaults
        assert any("not found" in str(rec.message) for rec in w), (
            f"explicit missing --config did not warn; warnings={[str(r.message) for r in w]}"
        )

    def test_implicit_absent_config_stays_silent(self, tmp_path):
        """Must-NOT-trip (the friction false-positive guard): the IMPLICIT default
        (no config_path, repo lacks espalier.toml) is the common case and must
        stay silent — warning here would be the high-severity friction class."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            load_config(tmp_path)  # no config_path, no espalier.toml on disk
        assert not any("not found" in str(rec.message) for rec in w), (
            f"implicit-absent config spuriously warned; warnings={[str(r.message) for r in w]}"
        )

    def test_malformed_toml_degrades_to_defaults(self, tmp_path):
        """a syntactically malformed espalier.toml degrades to defaults
        with a warning rather than tracebacking through every caller (init /
        fingerprint / analyze / doctor). TOMLDecodeError is a ValueError subclass."""
        (tmp_path / "espalier.toml").write_text(
            'lane_count = = 5\n[unclosed\n', encoding="utf-8"
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = load_config(tmp_path)
        assert isinstance(config, HarnessConfig)
        assert config.lane_count == 3  # default, not a traceback
        assert any("could not read or parse" in str(rec.message) for rec in w)

    def test_wrong_type_list_field_dropped(self, tmp_path):
        """a bare string where a list is expected (`include_paths = "src"`)
        is dropped with a warning, not silently kept as a str that
        analyze._path_allowed would iterate character-by-character (dropping the
        whole intended tree). The default ([]) is used instead."""
        (tmp_path / "espalier.toml").write_text(
            'include_paths = "src"\nlane_count = 5\n', encoding="utf-8"
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = load_config(tmp_path)
        assert config.include_paths == []  # bad str dropped, default used
        assert config.lane_count == 5  # well-typed sibling still parsed
        assert any("include_paths" in str(rec.message) for rec in w)

    def test_an_extra_actions_entry_that_is_not_a_command_list_is_dropped(self, tmp_path):
        """The type guard checked that ``extra_actions`` is a table and never
        looked inside it. A top-level key written below the ``[extra_actions]``
        header belongs to that table, so ``lane_count = 5`` there reached the
        plan builder as an action whose commands are the number five (a
        ``TypeError`` with no file name, from ``init``, ``fingerprint``,
        ``doctor`` and ``upgrade`` alike), and a string became one command per
        character, written into the saved plan without a word. Dropped and
        named here, at the one loader every verb reads through; the
        well-formed entry beside them is kept."""
        (tmp_path / "espalier.toml").write_text(
            '[extra_actions]\nverify = ["npm test"]\nlane_count = 5\n'
            'default_profile = "workflow"\nmixed = ["ok", 3]\n',
            encoding="utf-8",
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = load_config(tmp_path)
        assert config.extra_actions == {"verify": ["npm test"]}
        said = " ".join(str(rec.message) for rec in w)
        for name in ("lane_count", "default_profile", "mixed"):
            assert name in said, (name, said)
        assert "espalier.toml" in said and "[extra_actions]" in said
        assert "above the" in said, "the remedy for the misplaced key is named"

    def test_a_well_formed_extra_actions_table_draws_no_warning(self, tmp_path):
        (tmp_path / "espalier.toml").write_text(
            '[extra_actions]\nverify = ["npm test", "npm run lint"]\nempty = []\n',
            encoding="utf-8",
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = load_config(tmp_path)
        assert config.extra_actions == {"verify": ["npm test", "npm run lint"], "empty": []}
        assert not w, [str(rec.message) for rec in w]

    def test_wrong_type_none_default_field_dropped(self, tmp_path):
        """earn-the-red: the config guard skipped None-default fields
        (`default is not None` short-circuit), so a mistyped `default_profile`
        (a `str | None` field) flowed through unchecked. A list value must now
        be dropped+warned and fall back to the default (None)."""
        (tmp_path / "espalier.toml").write_text(
            'default_profile = ["workflow", "minimal"]\nlane_count = 4\n',
            encoding="utf-8",
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = load_config(tmp_path)
        assert config.default_profile is None  # bad list dropped, default used
        assert config.lane_count == 4  # well-typed sibling still parsed
        assert any("default_profile" in str(rec.message) for rec in w)

    def test_bool_for_int_field_rejected(self, tmp_path):
        """bool subclasses int, so `lane_count = true` passes the
        ``isinstance(value, int)`` guard and would be kept as True (=1). The
        reverse (an int where a bool is expected) is already caught, since
        ``isinstance(1, bool)`` is False. Close the asymmetric hole: a bool
        where an int is expected must be dropped+warned, falling back to the
        default."""
        (tmp_path / "espalier.toml").write_text(
            'lane_count = true\nsurface_mode = "extended"\n', encoding="utf-8"
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = load_config(tmp_path)
        assert config.lane_count == 3  # bool dropped, default (3) used
        assert config.surface_mode == "extended"  # well-typed sibling still parsed
        assert any("lane_count" in str(rec.message) for rec in w)

    def test_int_value_unchanged(self, tmp_path):
        """Negative control: a genuine int `lane_count = 8` still validates —
        the bool-rejection guard drops a bool where an int is expected, never a
        well-typed int."""
        (tmp_path / "espalier.toml").write_text(
            "lane_count = 8\n", encoding="utf-8"
        )
        config = load_config(tmp_path)
        assert config.lane_count == 8

    def test_valid_none_default_field_preserved(self, tmp_path):
        """Regression guard: a correctly str-typed `default_profile` survives."""
        (tmp_path / "espalier.toml").write_text(
            'default_profile = "workflow"\n', encoding="utf-8"
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = load_config(tmp_path)
        assert config.default_profile == "workflow"
        assert not any("default_profile" in str(rec.message) for rec in w)

    def test_warns_when_no_toml_parser(self, tmp_path, monkeypatch):
        """When tomllib is None and a config file exists, returns default and warns."""
        (tmp_path / "espalier.toml").write_text('lane_count = 9\n', encoding="utf-8")
        import espalier.config as config_mod
        monkeypatch.setattr(config_mod, "tomllib", None)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = load_config(tmp_path)
        assert isinstance(config, HarnessConfig)
        assert config.lane_count == 3  # default, not 9
        assert len(w) == 1
        assert "no TOML parser" in str(w[0].message).lower() or \
               "tomli" in str(w[0].message).lower()
