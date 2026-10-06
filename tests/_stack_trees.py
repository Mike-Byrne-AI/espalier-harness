"""One stack table: the file set of every synthetic project tree the suite builds.

Stdlib only, with no ``espalier`` import. The selfcheck mirror carries a byte
copy of this module (``scripts/sync_selfcheck_tests.py``), so ``espalier
selfcheck`` builds its fixtures from the same rows as the suite.

``STACKS`` maps a row name to ``{relative path: body}``. A path ending in ``/``
is an empty directory, and its body is ``""``. Rows come in two kinds.

* **Fixture rows** (``python``, ``ml``, ``node``, ``typescript``, ``go``,
  ``polyglot``) are the bodies the ``tests/conftest.py`` stack fixtures have
  always written, one fixture per row. Their users assert on exact content:
  the ``print`` and the ``_cache_*`` helpers in ``python`` feed the scanner
  tests. Change a byte here and you change what those tests read. ``rust`` is
  the body of the deleted ``rust_repo`` fixture, which nothing used; no
  fixture writes it, and it is kept for a Rust consumer.
* **Adopter rows** (``adopter-<stack>``) are what
  ``tests/_adopter_tree.py::build_adopter_tree`` writes before it runs ``git
  init`` and, at its default depth, ``espalier init``. ``adopter-python`` is the
  tree that builder has always produced. The others are the non-Python
  projects an adopter brings: a Node project with ``test``, ``lint`` and
  ``build`` scripts and an Astro page, the same under pnpm, and a Go and a Rust
  project.

``write_stack`` writes a row byte for byte (UTF-8, ``newline=""``), so a tree
is identical on every host: a text-mode write would put CRLF on Windows.
"""
from __future__ import annotations

from pathlib import Path

ADOPTER_PREFIX = "adopter-"

_ADOPTER_NODE: dict[str, str] = {
    "README.md": "# Demo Web\n",
    "package.json": (
        "{\n"
        '  "name": "demo-web",\n'
        '  "version": "0.1.0",\n'
        '  "private": true,\n'
        '  "type": "module",\n'
        '  "scripts": {\n'
        '    "test": "node --test",\n'
        '    "lint": "eslint .",\n'
        '    "build": "astro build"\n'
        "  },\n"
        '  "devDependencies": {\n'
        '    "astro": "^4.16.0",\n'
        '    "eslint": "^9.12.0"\n'
        "  }\n"
        "}\n"
    ),
    ".gitignore": "node_modules/\ndist/\n",
    "src/index.mjs": "export function main() {\n  return 0;\n}\n",
    "src/pages/index.astro": '---\nconst title = "Demo";\n---\n<h1>{title}</h1>\n',
    "test/index.test.mjs": (
        'import { test } from "node:test";\n'
        'import assert from "node:assert/strict";\n'
        'import { main } from "../src/index.mjs";\n'
        "\n"
        'test("main", () => {\n'
        "  assert.equal(main(), 0);\n"
        "});\n"
    ),
}

STACKS: dict[str, dict[str, str]] = {
    # -- fixture rows: the conftest stack fixtures' bodies, byte for byte ----
    "python": {
        "app.py": (
            'from fastapi import FastAPI\n'
            'app = FastAPI()\n'
            '@app.get("/health")\n'
            'def health():\n'
            '    return {"status": "ok"}\n'
            'def helper():\n'
            '    try:\n'
            '        x = open("/tmp/foo")\n'
            '    except:\n'
            '        pass\n'
            '    print("debug")\n'
        ),
        "src/utils.py": (
            'def _cache_load(): pass\n'
            'def _cache_save(): pass\n'
            'def _cache_invalidate(): pass\n'
            'def _cache_warm(): pass\n'
            'def unrelated(): pass\n'
        ),
        "tests/test_health.py": "def test_health(): assert True\n",
        "pyproject.toml": (
            '[project]\nname = "test-api"\n'
            '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'
            '[tool.ruff]\nline-length = 100\n'
        ),
        "README.md": "# Test API\nA FastAPI service.\n",
    },
    "ml": {
        "src/": "",
        "train.py": (
            'import torch\n'
            'model = torch.nn.Linear(10, 1)\n'
            'def train():\n'
            '    model.cuda()\n'
            '    print("training")\n'
        ),
        "pyproject.toml": (
            '[project]\nname = "ml-proj"\ndependencies = ["torch", "transformers"]\n'
            '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'
        ),
        "tests/test_train.py": "def test_train(): assert True\n",
        "README.md": "# ML Project\n",
    },
    "node": {
        "src/index.js": "console.log('hello');\n",
        "package.json": (
            '{"name":"test-app","scripts":{"test":"jest","build":"next build","dev":"next dev"}}\n'
        ),
        "README.md": "# Node App\n",
    },
    "typescript": {
        "src/index.ts": (
            "export function greet(name: string): string {\n"
            "  return `hello, ${name}`;\n"
            "}\n"
        ),
        "src/app.tsx": "export const App = () => null;\n",
        "tests/index.test.ts": (
            "import { greet } from '../src/index';\n"
            "test('greet', () => { expect(greet('w')).toBe('hello, w'); });\n"
        ),
        "package.json": '{"name":"ts-app","scripts":{"test":"jest","build":"tsc"}}\n',
        "tsconfig.json": (
            '{"compilerOptions":{"target":"ES2020","module":"commonjs","strict":true}}\n'
        ),
        "README.md": "# TS App\n",
    },
    "go": {
        "go.mod": "module example.com/demo\n\ngo 1.21\n",
        "cmd/main.go": 'package main\n\nimport "fmt"\n\nfunc main() { fmt.Println("hi") }\n',
        "internal/foo/foo.go": 'package foo\n\nfunc Greet() string { return "hello" }\n',
        "internal/foo/foo_test.go": (
            'package foo\n\nimport "testing"\n\n'
            'func TestGreet(t *testing.T) { if Greet() != "hello" { t.Fail() } }\n'
        ),
        "README.md": "# Go App\n",
    },
    "polyglot": {
        "pyproject.toml": (
            '[project]\nname = "poly"\n'
            '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'
        ),
        "src/a.py": "def a(): return 'a'\n",
        "src/b.py": "def b(): return 'b'\n",
        "src/c.py": "def c(): return 'c'\n",
        "src/d.py": "def d(): return 'd'\n",
        "src/e.py": "def e(): return 'e'\n",
        "tests/test_a.py": "from src.a import a\n\ndef test_a(): assert a() == 'a'\n",
        # TypeScript secondary: fewer files than Python so primary stays python.
        "web/index.ts": "export const v = 1;\n",
        "package.json": '{"name":"poly-web","scripts":{"build":"tsc"}}\n',
        "README.md": "# Polyglot\n",
    },
    "rust": {
        "src/main.rs": "fn main() {}\n",
        "Cargo.toml": '[package]\nname = "test-app"\nversion = "0.1.0"\nedition = "2021"\n',
    },
    # -- adopter rows: what build_adopter_tree writes, per stack --------------
    "adopter-python": {
        "README.md": "# Demo App\n",
        "pyproject.toml": '[project]\nname = "demo-app"\nversion = "0.1.0"\n',
        # A real project has one. Without it `init` takes its no-gitignore
        # warning branch instead of the ownership-checked append path.
        ".gitignore": "__pycache__/\n*.pyc\ndist/\n",
        "src/demo/__init__.py": "",
        "src/demo/app.py": "def main() -> int:\n    return 0\n",
        "tests/test_app.py": (
            "from demo.app import main\n\n\ndef test_main():\n    assert main() == 0\n"
        ),
    },
    "adopter-node": dict(_ADOPTER_NODE),
    # The probe tree for package-manager detection: the Node project with a
    # pnpm lockfile beside it.
    "adopter-node-pnpm": {
        **_ADOPTER_NODE,
        "pnpm-lock.yaml": (
            "lockfileVersion: '9.0'\n"
            "\n"
            "settings:\n"
            "  autoInstallPeers: true\n"
            "  excludeLinksFromLockfile: false\n"
            "\n"
            "importers:\n"
            "\n"
            "  .: {}\n"
        ),
    },
    "adopter-go": {
        "README.md": "# Demo Go\n",
        "go.mod": "module example.com/demo\n\ngo 1.22\n",
        ".gitignore": "/bin/\n",
        "main.go": 'package main\n\nimport "fmt"\n\nfunc main() {\n\tfmt.Println(Greet())\n}\n',
        "greet.go": 'package main\n\nfunc Greet() string { return "hello" }\n',
        "greet_test.go": (
            'package main\n\nimport "testing"\n\n'
            "func TestGreet(t *testing.T) {\n"
            '\tif Greet() != "hello" {\n'
            "\t\tt.Fail()\n"
            "\t}\n"
            "}\n"
        ),
    },
    "adopter-rust": {
        "README.md": "# Demo Rust\n",
        "Cargo.toml": '[package]\nname = "demo"\nversion = "0.1.0"\nedition = "2021"\n',
        ".gitignore": "/target\n",
        "src/main.rs": "fn main() {\n    println!(\"{}\", demo::answer());\n}\n",
        "src/lib.rs": "pub fn answer() -> i32 {\n    0\n}\n",
        "tests/answer.rs": "#[test]\nfn answer_is_zero() {\n    assert_eq!(demo::answer(), 0);\n}\n",
    },
}

#: The stacks ``build_adopter_tree(stack=...)`` accepts: each adopter row's name
#: without its prefix.
ADOPTER_STACKS: tuple[str, ...] = tuple(
    name[len(ADOPTER_PREFIX):] for name in STACKS if name.startswith(ADOPTER_PREFIX)
)


def write_stack(dest: Path, row: str) -> Path:
    """Write the files of ``STACKS[row]`` under ``dest`` and return ``dest``.

    UTF-8 with ``newline=""``, so the bytes on disk are the row's bytes on
    every host. A key ending in ``/`` makes an empty directory.
    """
    if row not in STACKS:
        raise ValueError(f"unknown stack row {row!r}; expected one of {sorted(STACKS)}")
    dest.mkdir(parents=True, exist_ok=True)
    for rel, body in STACKS[row].items():
        path = dest / rel
        if rel.endswith("/"):
            path.mkdir(parents=True, exist_ok=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(body)
    return dest
