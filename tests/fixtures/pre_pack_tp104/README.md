# A frozen calibration corpus: do not edit these files

The nine `*.py.txt` files here are the harness hooks as they stood at the
`pre-pack-TP-104` tag, before the pack that consolidated their nine copies of
`_project_root` into one helper. They are old, pre-fix source on purpose: the
sister-site probe's regression test feeds them to the probe and asserts it
still finds that 9-clique, which is how the probe proves it can see the class
it was built to catch.

So a repository-wide sweep that matches something here (a missing path
normalisation, an old idiom, a lint finding) has found the corpus, not a
defect. Leave them byte for byte: `tests/test_sister_site_probe_regression.py`
pins each file's sha256, and a `-text` row in `.gitattributes` keeps a
`core.autocrlf` checkout from rewriting them. The `.py.txt` suffix keeps ruff
and mypy from reading them.
