"""What each stack an adopter brings is, in one table.

It imports nothing but the standard library, so the same bytes run on both
sides of the no-import boundary: the hooks import this file, the engine
imports its byte copy espalier/_stack_table.py (mirror row ``stack-table``),
and ``python3 scripts/sync_vendor_cc.py`` writes both copies. Every other list
that spells a stack's extensions, manifests, lockfiles, dependency
directories or commands is a projection of this table, or carries a
``stack-table: ok purpose-scoped`` marker saying why it is not
(tests/test_stack_table.py holds both directions).

Commands are argv tuples, never shell strings. The settings renderer narrows
them through settings_profiles.narrowed_rules, so no row's command derives a
bare ``Bash(<binary> *)``, and an argv is the shape a committed stop-gate
command would need on Windows. The one place rule strings live is a row's
``static_allows``: rules rendered only when that stack is detected.

Rows are NamedTuples, not dataclasses: ``dataclasses`` imports ``inspect``,
and the hook layer imports its helpers on every tool call.
"""
from __future__ import annotations

from typing import NamedTuple


class PackageManager(NamedTuple):
    """A Node package manager: the binary, the lockfiles that name it, and
    the argv templates that run the manifest's scripts."""

    name: str                    # the binary on PATH: "pnpm"
    lockfiles: tuple[str, ...]   # the files whose presence names it
    test: tuple[str, ...]        # argv that runs the manifest's `test` script
    run: tuple[str, ...]         # argv prefix that runs a named script
    start: tuple[str, ...]       # argv that runs the manifest's `start` script


class Stack(NamedTuple):
    """One stack: its source suffixes and what a repository of it carries."""

    name: str
    languages: tuple[tuple[str, str], ...]              # (suffix, language)
    manifests: tuple[str, ...] = ()                     # go.mod, Gemfile, package.json
    lockfiles: tuple[str, ...] = ()                     # with no manager choice: go.sum, Cargo.lock
    package_managers: tuple[PackageManager, ...] = ()   # the first is the default
    test: tuple[str, ...] = ()                          # argv, for a stack with one runner
    dependency_dirs: tuple[str, ...] = ()               # third-party code, by name, at any depth
    output_dirs: tuple[str, ...] = ()                   # build output: rust's target
    lint_fallback: tuple[str, ...] = ()                 # argv /preflight runs when nothing is declared
    static_allows: tuple[str, ...] = ()                 # rules rendered only for this stack
    ast_scannable: bool = False                         # the scanners can read its source


NPM = PackageManager(
    "npm", ("package-lock.json", "npm-shrinkwrap.json"),
    ("npm", "test"), ("npm", "run"), ("npm", "start"),
)
PNPM = PackageManager(
    "pnpm", ("pnpm-lock.yaml",),
    ("pnpm", "test"), ("pnpm", "run"), ("pnpm", "start"),
)
YARN = PackageManager(
    "yarn", ("yarn.lock",),
    ("yarn", "test"), ("yarn", "run"), ("yarn", "start"),
)
# `bun test` is Bun's own test runner: a built-in wins over a script of the
# same name, so the manifest's scripts run as `bun run <script>` (bun docs,
# "bun run"). bun.lock is the default since Bun 1.2; bun.lockb before it.
BUN = PackageManager(
    "bun", ("bun.lock", "bun.lockb"),
    ("bun", "run", "test"), ("bun", "run"), ("bun", "run", "start"),
)

#: Row order is read: ``suffix_to_language`` keeps it, and the fingerprint's
#: language map is that projection.
STACKS: tuple[Stack, ...] = (
    Stack(
        name="python",
        languages=((".py", "python"),),
        manifests=("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg", "Pipfile"),
        test=("pytest", "-q"),
        lint_fallback=("ruff", "check", "--no-cache", "--extend-exclude", "tools/cc", "."),
        static_allows=(
            "Bash(pytest *)",
            "Bash(python -m pytest *)",
            "Bash(python3 -m pytest *)",
            "Bash(ruff *)",
            "Bash(black *)",
        ),
        ast_scannable=True,
    ),
    Stack(
        name="node",
        languages=(
            (".js", "javascript"), (".jsx", "javascript"),
            (".mjs", "javascript"), (".cjs", "javascript"),
            (".ts", "typescript"), (".tsx", "typescript"),
            (".mts", "typescript"), (".cts", "typescript"),
            (".astro", "astro"), (".vue", "vue"), (".svelte", "svelte"),
        ),
        manifests=("package.json",),
        package_managers=(NPM, PNPM, YARN, BUN),
        dependency_dirs=("node_modules", "bower_components", "jspm_packages", ".yarn", ".pnpm-store"),
        lint_fallback=("npx", "--no-install", "eslint", "."),
    ),
    Stack(
        name="go",
        languages=((".go", "go"),),
        manifests=("go.mod",),
        lockfiles=("go.sum",),
        test=("go", "test", "./..."),
        lint_fallback=("golangci-lint", "run", "./..."),
    ),
    Stack(
        name="rust",
        languages=((".rs", "rust"),),
        manifests=("Cargo.toml",),
        lockfiles=("Cargo.lock",),
        test=("cargo", "test"),
        output_dirs=("target",),
        lint_fallback=("cargo", "clippy", "--all-targets", "--", "-D", "warnings"),
    ),
    Stack(
        name="jvm",
        languages=((".java", "java"), (".kt", "kotlin"), (".scala", "scala")),
        manifests=("pom.xml", "build.gradle"),
    ),
    Stack(name="dotnet", languages=((".cs", "csharp"),)),
    Stack(name="c", languages=((".cpp", "cpp"), (".c", "c"), (".h", "c"))),
    Stack(name="php", languages=((".php", "php"),)),
    Stack(
        name="ruby",
        languages=((".rb", "ruby"),),
        manifests=("Gemfile",),
        lockfiles=("Gemfile.lock",),
    ),
    Stack(name="swift", languages=((".swift", "swift"),)),
)


def stack(name: str) -> Stack:
    """The row called ``name``. Raises ``KeyError`` on a typo rather than
    answering with nothing."""
    for row in STACKS:
        if row.name == name:
            return row
    raise KeyError(f"no stack row named {name!r}")


def source_extensions() -> frozenset[str]:
    """Every row's source suffixes."""
    return frozenset(suffix for row in STACKS for suffix, _ in row.languages)


def suffix_to_language() -> dict[str, str]:
    """Suffix to language, in row order."""
    return {suffix: language for row in STACKS for suffix, language in row.languages}


def manifest_names() -> tuple[str, ...]:
    """Every row's manifests, in row order, each once."""
    return tuple(dict.fromkeys(name for row in STACKS for name in row.manifests))


def package_managers() -> tuple[PackageManager, ...]:
    """Every row's package managers, in row order; a row's first is its default."""
    return tuple(pm for row in STACKS for pm in row.package_managers)


def package_manager(name: str) -> PackageManager | None:
    """The package manager whose binary is ``name``, or ``None``."""
    for pm in package_managers():
        if pm.name == name:
            return pm
    return None


def lockfile_owners() -> dict[str, str]:
    """Lockfile name to what it names: a package manager's binary for a
    manager's lockfile, the row's name for a stack with no manager choice."""
    owners: dict[str, str] = {}
    for row in STACKS:
        for lockfile in row.lockfiles:
            owners[lockfile] = row.name
        for pm in row.package_managers:
            for lockfile in pm.lockfiles:
                owners[lockfile] = pm.name
    return owners


def dependency_dirs() -> frozenset[str]:
    """Directory names holding third-party code, pruned at any depth."""
    return frozenset(name for row in STACKS for name in row.dependency_dirs)


def output_dirs() -> frozenset[str]:
    """Directory names holding build output."""
    return frozenset(name for row in STACKS for name in row.output_dirs)


def script_runners() -> frozenset[str]:
    """The binaries whose ``run`` verb runs one of the manifest's named
    scripts, so a rule derived from one keeps the script's name."""
    return frozenset(pm.name for pm in package_managers())
