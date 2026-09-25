@echo off
setlocal
rem Espalier statusline shim for Windows (ledger DEF-729).
rem
rem .claude/settings.json's statusLine runs this file with the interpreter
rem name init detected as its first argument. It is the one surface that runs
rem WITHOUT that interpreter: batch has the or-operator neither Windows shell
rem agrees on (Windows PowerShell 5.1 has none; Git Bash rewrites a bare /c
rem switch into a drive path and cmd starts interactive), so the fallback
rem line lives here, and the shim exits 0 either way -- Claude Code blanks a
rem statusline whose command exits non-zero.
rem
rem No label search (no goto, no call to a label), on purpose: cmd.exe
rem misreads one in an LF-only file, and this file is pinned eol=lf with
rem the rest of tools/cc. The deployed copy carries a managed-marker line
rem after the echo-off line that cmd.exe reads as a label; that is a no-op
rem exactly because nothing here seeks one. The fallback text is
rem espalier/cli.py::STATUSLINE_FALLBACK_TEXT verbatim
rem (tests/test_hook_exec_form.py pins the two equal).
if "%~1"=="" (set "ESPALIER_PY=python") else (set "ESPALIER_PY=%*")
%ESPALIER_PY% "%~dp0statusline.py" || (echo espalier: statusline did not run -- see docs/TROUBLESHOOTING.md& exit /b 0)
