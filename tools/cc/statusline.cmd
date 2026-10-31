:; "${@:-python}" "${BASH_SOURCE%[/\\]*}/statusline.py" || echo 'espalier: statusline did not run -- see docs/TROUBLESHOOTING.md'; return 0 #
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
rem The statusLine puts a dot before this file's quoted path (ledger
rem DEF-3017): both shells Claude Code picks between have that operator, so
rem one line runs in either. Git Bash sources this file and PowerShell runs
rem it as a batch file. Line 1 is for bash alone: a colon is a no-op there,
rem then the script beside this file and the same fallback, and the return
rem ends the source on that line. To cmd.exe a line opening with a colon is a
rem label, which it skips and never echoes, even before the echo-off. The
rem hash at its end keeps a carriage return from a CRLF checkout out of the
rem command.
rem
rem No label search (no goto, no call to a label), on purpose: cmd.exe
rem misreads one in an LF-only file, and this file is pinned eol=lf with
rem the rest of tools/cc. The deployed copy carries a managed-marker line
rem after the echo-off line that cmd.exe reads as a label; that is a no-op
rem exactly because nothing here seeks one. The fallback text is
rem espalier/cli.py::STATUSLINE_FALLBACK_TEXT verbatim on both lines
rem (tests/test_hook_exec_form.py pins the three equal).
if "%~1"=="" (set "ESPALIER_PY=python") else (set "ESPALIER_PY=%*")
%ESPALIER_PY% "%~dp0statusline.py" || (echo espalier: statusline did not run -- see docs/TROUBLESHOOTING.md& exit /b 0)
