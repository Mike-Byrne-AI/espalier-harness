### Changed

- **A multi-package Python tree built on `setup.py` now reads its packages as
  package roots, and a vendored copy of a project manifest no longer does.**
  The fingerprint marks a directory holding `setup.py` as a package root,
  beside `pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, `pom.xml`
  and `build.gradle`, so a tree of packages from before `pyproject.toml` reads
  as a monorepo, and the monorepo profile, its guardrail and the package scopes
  apply to it. Any of those manifests under a directory named `vendor` or
  `third_party`, at any depth, is no longer a package root. `setup.cfg`,
  `requirements.txt`, `Pipfile` and `Gemfile` still mark none. An adopter with
  either kind of tree sees `package_roots` and the monorepo flag move in the
  fingerprint drift report on the next `espalier analyze` or upgrade: the
  expected move, not a defect.
