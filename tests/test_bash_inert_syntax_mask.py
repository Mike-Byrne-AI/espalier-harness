"""The role map — prose ABOUT a command must stop being read as the command.

This file is the gate for `_bash_patterns.mask_inert_syntax` and its four wiring
points. It exists because the guards scanned a flat command string with no shell
quoting awareness at all, so every character that puts a verb at a command
position — ``` ` ( ) { } ; | & ``` and newline — did so just as readily inside a
quoted argument, a `#` comment or a `<<'EOF'` heredoc body. Measured 2026-08-24
by driving the live hooks: 6/6 inert redirect shapes denied as protected-zone
writes, and a quoted heredoc quoting a delete literal hard-denied on the one tier
maintenance mode cannot bypass. The last of those blocked a ledger edit inside
the commit that fixed the class it documents.

⚠ THE DISTINCTION THIS FILE MUST PROTECT is role map vs blanking mask. An earlier
attempt blanked quoted-span CONTENTS; it was driven and rejected because six
catastrophic-rm classes work by splicing quotes INSIDE a word (`rm -r"f" /`,
`"rm" -rf /`, `rm'' -rf /`, `\\rm -rf /`, `rm -rf "/"`, `'rm' -rf /`) which the
shell concatenates away, so blanking deletes the verb. The pass here substitutes
separator characters ONLY and never token content.
:class:`TestQuoteSpliceClassesStillDeny` is the arm that keeps that true; if it
ever goes green while :class:`TestMaskTouchesNoTokenContent` reds, someone has
turned the role map back into a blanking mask.

Four classes, each pinning a different property:

* :class:`TestGenuineCommandsStillDeny` — ANTI-REGRESSION, the fail-open half.
  Every row denies today and must keep denying. Includes the spans that LOOK
  quoted but genuinely execute: `eval "..."`, `bash -c '...'`, a backtick inside
  DOUBLE quotes, and an unquoted-delimiter heredoc body. Bash really does expand
  those — verified against a real shell, not assumed — so a row here flipping to
  ALLOW is a bypass, never a false-positive fix.
* :class:`TestInertProseIsAllowed` — the EARN-THE-RED half. Every row was denied
  against the unfixed tree, by design, and must now allow.
* :class:`TestQuoteSpliceClassesStillDeny` — the six classes a blanking mask
  destroyed, pinned from a hand-written roster so a regression names itself.
* :class:`TestMaskControlsAndFailClosed` — rows that must not move in EITHER
  direction, plus the fail-closed rule. Without them the suite cannot tell "the
  mask works" from "the mask neutralised everything": a guard that matches
  nothing also has zero false positives.

The hooks are driven as real subprocesses through the house helper. Matching the
regexes directly would witness the pattern body and never the wiring — this repo
has shipped an INERT regression test three times that way, most recently in the
commit this class descends from, where the test drove the classifier while the
records under test only fire through the dispatch.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from tests._hook_assertions import assert_hook_allowed, assert_hook_denied
from tests.test_write_guard import run_bash_guard

HOOKS_DIR = Path(__file__).resolve().parents[1] / "tools" / "cc" / "hooks"
PROTECTED_FILE = "tools/cc/hooks/write_guard.py"

# Assembled, never written as one literal: this file is scanned by the repo's own
# guards and census gates, and a bare copy of the spelling in a tracked test is
# exactly what the class under test is about.
RM_RF = "rm" + " " + "-rf"
ROOT_TARGET = "/"


def _load_bash_patterns():
    spec = importlib.util.spec_from_file_location(
        "_bash_patterns_masktest", HOOKS_DIR / "_bash_patterns.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ─────────────────────────── anti-regression ───────────────────────────

#: (label, command) — genuinely executes, must stay DENY.
GENUINE: list[tuple[str, str]] = [
    ("bare_root", f"{RM_RF} {ROOT_TARGET}"),
    ("bare_star", f"{RM_RF} *"),
    ("flag_order", f"rm -fr {ROOT_TARGET}"),
    ("home_tilde", f"{RM_RF} ~"),
    ("sudo", f"sudo {RM_RF} {ROOT_TARGET}"),
    ("after_semicolon", f"ls; {RM_RF} {ROOT_TARGET}"),
    ("subshell", f"({RM_RF} {ROOT_TARGET})"),
    ("command_substitution", f"echo `{RM_RF} {ROOT_TARGET}`"),
    ("if_then", f"if true; then {RM_RF} {ROOT_TARGET}; fi"),
    ("env_prefix", f"FOO=1 {RM_RF} {ROOT_TARGET}"),
    # ⚠ These four LOOK like quoted text and genuinely execute. Verified against
    # a real bash: a backtick expands inside DOUBLE quotes and inside an
    # unquoted-delimiter heredoc body; `eval`/`-c` execute their quoted argument.
    ("eval_double_quoted", f'eval "{RM_RF} {ROOT_TARGET}"'),
    ("eval_single_quoted", f"eval '{RM_RF} {ROOT_TARGET}'"),
    ("bash_c_double_quoted", f'bash -c "{RM_RF} {ROOT_TARGET}"'),
    ("bash_c_single_quoted", f"bash -c '{RM_RF} {ROOT_TARGET}'"),
    ("sh_c_single_quoted", f"sh -c '{RM_RF} {ROOT_TARGET}'"),
    # ⚠ THE ROWS THAT WERE MISSING, AND THEIR ABSENCE WAS THE WHOLE DEFECT.
    # Every exec-quote row above is a SINGLE statement, and a single statement has
    # no separator to lose. The first cut of this pass spaced out separators inside
    # any quoted span, which deleted the command position of every statement AFTER
    # the first — so `eval "true; <delete> /"` stopped being seen while
    # `eval "<delete> /"` kept working. Measured against a real-bash reachability
    # oracle (bash genuinely deleted a real victim): 63 of 140 wrapper × body
    # combinations flipped DENY → ALLOW, on the maintenance-unbypassable tier.
    # 80 tests here, 8 mutations, an 84-attempt corpus differential and the
    # 154/154 release benchmark were ALL green across it. Multi-statement bodies
    # are the discriminator; keep them.
    ("eval_dq_two_statements", f'eval "true; {RM_RF} {ROOT_TARGET}"'),
    ("eval_sq_two_statements", f"eval 'true; {RM_RF} {ROOT_TARGET}'"),
    ("bash_c_cd_then", f'bash -c "cd /tmp; {RM_RF} {ROOT_TARGET}"'),
    ("sh_c_andand", f"sh -c 'true && {RM_RF} {ROOT_TARGET}'"),
    ("eval_newline_separated", f"eval 'ls\n{RM_RF} {ROOT_TARGET}'"),
    ("eval_subshell_body", f'eval "(cd /tmp; {RM_RF} {ROOT_TARGET})"'),
    ("heredoc_into_shell_quoted", f"bash <<'EOF'\n{RM_RF} {ROOT_TARGET}\nEOF"),
    ("heredoc_into_shell_unquoted", f"bash <<EOF\n{RM_RF} {ROOT_TARGET}\nEOF"),
    ("heredoc_piped_to_shell",
     f"cat <<'EOF' | bash\n{RM_RF} {ROOT_TARGET}\nEOF"),
    ("herestring_into_shell", f"bash <<< 'true; {RM_RF} {ROOT_TARGET}'"),
    ("backtick_inside_double_quotes",
     f'git commit -m "the guard refuses `{RM_RF} {ROOT_TARGET}`"'),
    ("unquoted_heredoc_body_expands",
     f"cat <<EOF\n`{RM_RF} {ROOT_TARGET}`\nEOF"),
    # protected-zone writes
    ("redirect", f"echo hi > {PROTECTED_FILE}"),
    ("append", f"echo hi >> {PROTECTED_FILE}"),
    ("heredoc_write", f"cat > {PROTECTED_FILE} <<EOF\nhi\nEOF"),
    ("redirect_after_semicolon", f"ls; echo hi > {PROTECTED_FILE}"),
    ("eval_quoted_cp_into_zone", f"eval 'cp /tmp/x {PROTECTED_FILE}'"),
    # DEF-754: a grouping character glued INSIDE a head word re-arms the
    # capture, and the suffix read from there lands in the pipeline the
    # grouping branch just rebound -- which a later `|` extends to a heredoc's
    # owner set. Here `b` (off every roster) joins `cat`, so the body stays
    # raw and the delete on its second line is seen. A first cut of the
    # linear walker skipped that read and turned this row into a relief
    # (code review, traced); the walker now reproduces the read exactly.
    ("heredoc_behind_glued_closer_piped",
     f"a}}b | cat <<'EOF'\n{RM_RF} {ROOT_TARGET}\nEOF"),
    # 447-A step 2 (2026-09-11). A quoted span or a comment is scoped to ITS
    # OWN statement's pipeline, so these are the spans a per-statement rule
    # must still read as live: the span's own head re-parses it, a pipe in any
    # spelling carries it into a shell, a group or a subshell around it is
    # what gets piped, a substitution captures it for an enclosing `eval`, or
    # the live code sits on the line after the comment. Each denies at
    # 6b128c0 and must keep denying.
    ("eval_dq_then_interpreter",
     f'eval "true; {RM_RF} {ROOT_TARGET}"; python3 -c pass'),
    ("interpreter_then_eval_dq",
     f'python3 -c pass; eval "true; {RM_RF} {ROOT_TARGET}"'),
    ("echo_then_eval_dq", f'echo x; eval "true; {RM_RF} {ROOT_TARGET}"'),
    ("echo_dq_piped_to_shell", f'echo "true; {RM_RF} {ROOT_TARGET}" | sh'),
    ("echo_dq_pipe_amp_to_shell", f'echo "true; {RM_RF} {ROOT_TARGET}" |& sh'),
    ("echo_dq_stderr_dup_piped_to_shell",
     f'echo "true; {RM_RF} {ROOT_TARGET}" 2>&1 | sh'),
    ("echo_dq_procsub_shell", f'echo "true; {RM_RF} {ROOT_TARGET}" > >(sh)'),
    ("group_echo_dq_piped_to_shell",
     f'{{ echo "true; {RM_RF} {ROOT_TARGET}"; }} | sh'),
    ("subshell_echo_dq_piped_to_shell",
     f'( echo "true; {RM_RF} {ROOT_TARGET}" ) | sh'),
    ("backtick_capture_in_assignment_then_eval",
     f'x=`echo "true; {RM_RF} {ROOT_TARGET}"`; eval "$x"'),
    ("dollar_capture_in_assignment_then_eval",
     f'x=$(echo "true; {RM_RF} {ROOT_TARGET}"); eval "$x"'),
    ("comment_then_live_line_behind_interpreter",
     f"python3 -c pass # note\n{RM_RF} {ROOT_TARGET}"),
    # The heredoc twins of the two pipe spellings above. Both ALLOWED at
    # 6b128c0: the walker rebound the body's owner set at the ampersand of a
    # redirect-duplication operator, so `cat` alone vouched for a body that
    # flows into the shell. Driven live before the fix, maintenance mode
    # stripped. `bench/reachability_differential.py` carries the `2>&1 |`
    # spelling as an executing row; `|&` is bash-4 syntax that the self-host
    # box's /bin/bash 3.2 rejects, so its liveness is the language's word and
    # this guard pin is its only witness here (unverified on this host).
    ("heredoc_pipe_amp_to_shell",
     f"cat <<'EOF' |& bash\ntrue; {RM_RF} {ROOT_TARGET}\nEOF"),
    ("heredoc_stderr_dup_piped_to_shell",
     f"cat <<'EOF' 2>&1 | bash\ntrue; {RM_RF} {ROOT_TARGET}\nEOF"),
    # The review batch of 447-A step 2 (both reviewers; each shape driven
    # live before the batch with a marker file in place of the delete): a
    # pipe whose target sits on the next line, with a comment or a heredoc
    # body between; a substitution opened inside an assignment word with a
    # separator inside it; the must-deny twins of the newline and `&&`
    # separators; a delete target written after a redirect-duplication.
    ("echo_dq_pipe_newline_to_shell",
     f'echo "true; {RM_RF} {ROOT_TARGET}" |\nsh'),
    ("echo_dq_pipe_comment_newline_to_shell",
     f'echo "true; {RM_RF} {ROOT_TARGET}" | # note\nsh'),
    ("heredoc_pipe_newline_then_shell",
     f"cat <<'EOF' |\ntrue; {RM_RF} {ROOT_TARGET}\nEOF\nbash"),
    ("capture_with_separator_inside_assignment_then_eval",
     f'x=$(echo a; echo "true; {RM_RF} {ROOT_TARGET}"); eval "$x"'),
    ("interpreter_newline_eval_dq",
     f'python3 -c pass\neval "true; {RM_RF} {ROOT_TARGET}"'),
    ("interpreter_andand_eval_dq",
     f'python3 -c pass && eval "true; {RM_RF} {ROOT_TARGET}"'),
    ("echo_andand_eval_dq", f'echo x && eval "true; {RM_RF} {ROOT_TARGET}"'),
    ("delete_target_after_stderr_dup", f"{RM_RF} 2>&1 {ROOT_TARGET}"),
    # ⚠ THE SHELL-OUT SPELLINGS (447-A step 3, 2026-09-11). A program under an
    # interpreter head hands its text to a shell through a CALL, and the raw
    # scan behind an off-roster head refused the one-statement body only by
    # the accident of the program's syntax around the verb -- and mostly did
    # not (DEF-761: 34 reaching rows unrefused at c7b46b9 with the step-3
    # bench rows enrolled). Each row here is one such call on the
    # one-statement body: the string forms, the argv list, the split forms,
    # both arms of each interpreter, awk's stream and print-into-a-shell, GNU
    # sed's `e`, git's alias and exec-valued keys, a program on a shell's or
    # an interpreter's stdin by here-string or pipe, and the statement
    # position varied. The mention twin of every head sits in INERT below; a
    # relief there without its row here is the fail-open this class refuses.
    ("py_c_os_system", f"python3 -c 'import os; os.system(\"{RM_RF} {ROOT_TARGET}\")'"),
    ("py_c_os_popen", f"python3 -c 'import os; os.popen(\"{RM_RF} {ROOT_TARGET}\")'"),
    ("py_c_subprocess_shell_dq",
     f"python3 -c \"import subprocess; subprocess.run('{RM_RF} {ROOT_TARGET}', shell=True)\""),
    ("py_c_subprocess_argv_list",
     f"python3 -c 'import subprocess; subprocess.run([\"rm\", \"-rf\", \"{ROOT_TARGET}\"])'"),
    ("py_c_subprocess_list_sh_c",
     f"python3 -c 'import subprocess; subprocess.run([\"sh\", \"-c\", \"\"\"{RM_RF} {ROOT_TARGET}\"\"\"])'"),
    ("py_c_shlex_split",
     f"python3 -c 'import shlex, subprocess; subprocess.run(shlex.split(\"{RM_RF} {ROOT_TARGET}\"))'"),
    ("py_c_split_argv",
     f"python3 -c 'import subprocess; subprocess.run(\"{RM_RF} {ROOT_TARGET}\".split())'"),
    ("py_c_from_import_run",
     f"python3 -c 'from subprocess import run; run(\"{RM_RF} {ROOT_TARGET}\", shell=True)'"),
    ("py_heredoc_os_system",
     f"python3 - <<'PY'\nimport os\nos.system(\"{RM_RF} {ROOT_TARGET}\")\nPY"),
    ("py_heredoc_triple_quoted_system",
     f"python3 - <<'PY'\nimport os\nos.system(\"\"\"{RM_RF} {ROOT_TARGET}\"\"\")\nPY"),
    ("py_herestring_os_system",
     f"python3 - <<< 'import os; os.system(\"{RM_RF} {ROOT_TARGET}\")'"),
    ("perl_e_system_q", f'perl -e "system(q{{{RM_RF} {ROOT_TARGET}}})"'),
    ("perl_e_qx", f'perl -e "qx{{{RM_RF} {ROOT_TARGET}}}"'),
    ("perl_e_backticks", f"perl -e '`{RM_RF} {ROOT_TARGET}`'"),
    ("perl_e_system_list", f"perl -e 'system(\"rm\", \"-rf\", \"{ROOT_TARGET}\")'"),
    ("node_e_execsync_template",
     f"node -e 'require(\"child_process\").execSync(`{RM_RF} {ROOT_TARGET}`)'"),
    ("node_e_exec_escaped_dq",
     f'node -e "require(\'child_process\').exec(\\"{RM_RF} {ROOT_TARGET}\\")"'),
    ("node_e_spawnsync_sh_c",
     f"node -e 'require(\"child_process\").spawnSync(\"sh\", [\"-c\", \"{RM_RF} {ROOT_TARGET}\"])'"),
    ("ruby_e_system_percent_q", f'ruby -e "system(%q{{{RM_RF} {ROOT_TARGET}}})"'),
    ("ruby_e_percent_x", f'ruby -e "%x{{{RM_RF} {ROOT_TARGET}}}"'),
    ("ruby_e_backticks", f"ruby -e '`{RM_RF} {ROOT_TARGET}`'"),
    ("ruby_e_system_list", f"ruby -e 'system(\"rm\", \"-rf\", \"{ROOT_TARGET}\")'"),
    ("awk_system_literal", f"awk 'BEGIN{{system(\"{RM_RF} {ROOT_TARGET}\")}}'"),
    ("awk_system_var", f"awk -v c=\"{RM_RF} {ROOT_TARGET}\" 'BEGIN{{system(c)}}'"),
    ("awk_stream_system", f"awk '{{system($0)}}' <<'EOF'\n{RM_RF} {ROOT_TARGET}\nEOF"),
    ("awk_print_pipe_sh", f"awk 'BEGIN{{print \"{RM_RF} {ROOT_TARGET}\" | \"sh\"}}'"),
    ("awk_getline_pipe", f"awk 'BEGIN{{\"{RM_RF} {ROOT_TARGET}\" | getline}}'"),
    ("sed_e_command", f"sed 'e {RM_RF} {ROOT_TARGET}' <<< x"),
    ("sed_dash_e_e_command", f"sed -n -e 'e {RM_RF} {ROOT_TARGET}' <<< x"),
    ("sed_e_stream", f"sed 'e' <<'EOF'\n{RM_RF} {ROOT_TARGET}\nEOF"),
    ("sed_s_e_flag_stream", f"sed 's/^/ /e' <<'EOF'\n{RM_RF} {ROOT_TARGET}\nEOF"),
    ("git_alias_dash_c", f"git -c alias.zz='!{RM_RF} {ROOT_TARGET}' zz"),
    ("git_config_alias", f"git config alias.zz '!{RM_RF} {ROOT_TARGET}'"),
    ("git_config_global_alias", f"git config --global alias.zz '!{RM_RF} {ROOT_TARGET}'"),
    ("git_credential_helper_dash_c",
     f"git -c credential.helper='!{RM_RF} {ROOT_TARGET}' fetch"),
    ("git_core_pager_dash_c", f"git -c core.pager='{RM_RF} {ROOT_TARGET}' log"),
    ("herestring_sh", f"sh <<< '{RM_RF} {ROOT_TARGET}'"),
    ("herestring_dq_bash", f'bash <<< "{RM_RF} {ROOT_TARGET}"'),
    ("echo_dq_piped_to_sh", f'echo "{RM_RF} {ROOT_TARGET}" | sh'),
    ("printf_sq_piped_to_bash", f"printf '%s' '{RM_RF} {ROOT_TARGET}' | bash"),
    ("echo_sq_piped_to_python",
     f"echo 'import os; os.system(\"{RM_RF} {ROOT_TARGET}\")' | python3 -"),
    ("printf_dq_piped_to_python_no_dash",
     f"printf '%s' \"import os; os.system('{RM_RF} {ROOT_TARGET}')\" | python3"),
    ("heredoc_piped_to_python",
     f"cat <<'PY' | python3 -\nimport os\nos.system(\"{RM_RF} {ROOT_TARGET}\")\nPY"),
    ("echo_dq_pipe_newline_to_python",
     f"echo \"import os; os.system('{RM_RF} {ROOT_TARGET}')\" |\npython3 -"),
    ("echo_sq_piped_to_perl", f"echo 'system(q{{{RM_RF} {ROOT_TARGET}}})' | perl"),
    ("py_c_os_system_inside_bash_c",
     f"bash -c 'python3 -c \"import os; os.system(\\\"{RM_RF} {ROOT_TARGET}\\\")\"'"),
    ("cd_andand_py_c_os_system",
     f"cd /tmp && python3 -c 'import os; os.system(\"{RM_RF} {ROOT_TARGET}\")'"),
    ("ls_semicolon_py_c_os_system",
     f"ls; python3 -c 'import os; os.system(\"{RM_RF} {ROOT_TARGET}\")'"),
    ("ls_newline_py_c_os_system",
     f"ls\npython3 -c 'import os; os.system(\"{RM_RF} {ROOT_TARGET}\")'"),
    # ⚠ A QUOTED HEREDOC BODY LINE ENDING IN A BACKSLASH, then the terminator,
    # then a live delete, then the delimiter again. bash keeps the backslash
    # inside a quoted body (driven with a marker: the statement after the
    # terminator ran), so the delete RUNS; the splicer used to join that line
    # to its terminator, the walker closed the body on the LAST `EOF` and
    # masked the delete as body text -- allowed behind `cat` at c7b46b9 and,
    # once `python3` became a reader head, behind it too. The unquoted twin
    # is in INERT: bash splices the pair there, so nothing runs.
    ("quoted_heredoc_backslash_line_then_delete",
     f"cat <<'EOF'\nx\\\nEOF\n{RM_RF} {ROOT_TARGET}\nEOF"),
    ("quoted_heredoc_backslash_line_then_delete_under_reader",
     f"python3 <<'EOF'\nprint(1)\\\nEOF\n{RM_RF} {ROOT_TARGET}\nEOF"),
    # The must-deny twin of the INERT unquoted row: fed to a SHELL, the joined
    # body (`xEOF`, then the delete) runs as a script -- bash's own reading,
    # driven with a marker -- and the body behind a shell head stays raw.
    ("unquoted_heredoc_backslash_line_into_shell",
     f"bash <<EOF\nx\\\nEOF\n{RM_RF} {ROOT_TARGET}\nEOF"),
    # ⚠ THE REVIEW BATCH OF THE THIRD STEP (both reviewers, each row driven
    # with a marker before the fix). A heredoc operator MENTIONED inside a
    # multi-line quoted argument opened a body that never closed, so no
    # continuation after it was spliced; a redirect duplication or a command
    # substitution in the stage before a pipe cut the stage short; an even run
    # of backslashes before a newline is a literal backslash, so the next line
    # closes an unquoted body; git's subcommand doors and the wider exec-valued
    # keys, which the first git reader did not know while the head already
    # held rule (2)'s relief; the here-string operator glued to the head, or
    # behind a valued switch; a VARIABLE printed into a shell.
    ("dq_multiline_heredoc_mention_then_continued_delete",
     f"echo \"note\ncat <<'EOF'\nmore\"; {RM_RF} \\\n{ROOT_TARGET}"),
    ("echo_dq_stderr_dup_piped_to_sh", f'echo "{RM_RF} {ROOT_TARGET}" 2>&1 | sh'),
    ("printf_sq_redirect_piped_to_bash",
     f"printf '%s' '{RM_RF} {ROOT_TARGET}' 2>/dev/null | bash"),
    ("echo_dq_cmdsub_piped_to_sh", f'echo "{RM_RF} {ROOT_TARGET}" $(true) | sh'),
    ("echo_sq_stderr_dup_piped_to_python",
     f"echo 'import os; os.system(\"{RM_RF} {ROOT_TARGET}\")' 2>&1 | python3 -"),
    ("unquoted_heredoc_double_backslash_line_then_delete",
     f"cat <<EOF\nx\\\\\nEOF\n{RM_RF} {ROOT_TARGET}\nEOF"),
    ("git_submodule_foreach", f"git submodule foreach '{RM_RF} {ROOT_TARGET}'"),
    ("git_submodule_foreach_recursive_words",
     f"git submodule foreach --recursive {RM_RF} {ROOT_TARGET}"),
    ("git_filter_branch_tree_filter",
     f"git filter-branch -f --tree-filter '{RM_RF} {ROOT_TARGET}' HEAD"),
    ("git_filter_branch_index_filter_eq",
     f"git filter-branch --index-filter='{RM_RF} {ROOT_TARGET}' HEAD"),
    ("git_rebase_exec", f"git rebase --exec '{RM_RF} {ROOT_TARGET}' HEAD~1"),
    ("git_rebase_x", f"git rebase -x '{RM_RF} {ROOT_TARGET}' main"),
    ("git_rebase_exec_eq", f"git rebase --exec='{RM_RF} {ROOT_TARGET}' main"),
    ("git_bisect_run", f"git bisect run sh -c '{RM_RF} {ROOT_TARGET}'"),
    ("git_difftool_extcmd", f"git difftool --extcmd='{RM_RF} {ROOT_TARGET}'"),
    ("git_core_fsmonitor_dash_c", f"git -c core.fsmonitor='{RM_RF} {ROOT_TARGET}' status"),
    ("git_filter_clean_dash_c", f"git -c filter.x.clean='{RM_RF} {ROOT_TARGET}' add ."),
    ("git_credential_url_helper_dash_c",
     f"git -c credential.https://x.helper='!{RM_RF} {ROOT_TARGET}' fetch"),
    ("herestring_glued_sh", f"sh<<<'{RM_RF} {ROOT_TARGET}'"),
    ("herestring_valued_switch_bash", f"bash -o pipefail <<< '{RM_RF} {ROOT_TARGET}'"),
    ("awk_variable_print_pipe_sh",
     f"awk 'BEGIN{{x = \"{RM_RF} {ROOT_TARGET}\"; print x | \"sh\"}}'"),
]

#: (label, command) — inert text. Denied before the mask; must now ALLOW.
INERT: list[tuple[str, str]] = [
    ("grep_for_a_redirect_double_quoted",
     f'command grep -n "> {PROTECTED_FILE}" docs/'),
    ("grep_for_a_redirect_single_quoted",
     f"command grep -n '> {PROTECTED_FILE}' docs/"),
    ("prose_about_a_heredoc",
     f"echo 'write it with cat > {PROTECTED_FILE} <<EOF'"),
    ("quoted_delimiter_heredoc_body",
     f"cat > /tmp/x.md <<'EOF'\nRun: cat > {PROTECTED_FILE} <<EOF\nEOF"),
    ("shell_comment",
     f"# to refresh, run cat > {PROTECTED_FILE}\nls"),
    ("delete_literal_in_quoted_heredoc",
     f"cat > /tmp/x.md <<'EOF'\nsee `{RM_RF} {ROOT_TARGET}`\nEOF"),
    ("delete_literal_single_quoted",
     f"printf '%s' 'see `{RM_RF} {ROOT_TARGET}`'"),
    ("paren_inside_double_quotes",
     f'echo "call print({RM_RF} {ROOT_TARGET}) here"'),
    ("markdown_fence_in_quoted_heredoc",
     f"cat > /tmp/d.md <<'EOF'\n```\n{RM_RF} {ROOT_TARGET}\n```\nEOF"),
    # ⚠ THE TRIGGER IS THE COMMENT'S FIRST WORD. Every comment row above happens
    # to open with prose ("to refresh, run", "Run:", "see"), and that prose was
    # doing the work: the first cut of this pass blanked the `#` itself, leaving an
    # unbroken whitespace run from the `;` to the verb, so a comment that STARTED
    # with the literal was still hard-denied while one that started with a word was
    # not. 54 tests were green across that hole. Added after an adversarial pass
    # found it.
    ("comment_whose_first_word_is_the_trigger",
     f"true; # {RM_RF} {ROOT_TARGET}"),
    ("bare_comment_trigger", f"# {RM_RF} {ROOT_TARGET}"),
    ("comment_git_trigger_first",
     "git status; # git reset --hard is destructive"),
    ("comment_write_verb_first",
     f"true; # cp /tmp/x {PROTECTED_FILE}"),
    # A `#` glued to an opening backtick really does open a comment in bash
    # (driven: the commented line never ran). Without backtick in the opener set
    # the span stayed wholly unmasked, and the UNANCHORED redirect extractor read
    # its text as a genuine protected-zone write.
    ("backtick_glued_comment",
     f"echo `#note: use cat > {PROTECTED_FILE}`"),
    # DEF-754, the relief side of the glued-grouping-character shapes: the
    # suffix read after the glued `}` is `cat` here, a roster head, so the
    # quoted heredoc body it owns is masked; and a suffix that is a skip word
    # (`time`) steps over itself and leaves the capture armed for `cat`. Both
    # were reliefs at HEAD and must stay so (both reviews).
    ("quoted_heredoc_behind_glued_paramexp_head",
     f"${{X}}cat <<'EOF'\nsee {RM_RF} {ROOT_TARGET}\nEOF"),
    ("quoted_heredoc_behind_glued_skipword_head",
     f"a}}time cat <<'EOF'\nsee {RM_RF} {ROOT_TARGET}\nEOF"),
    # 447-A step 2 (2026-09-11): a quoted span or a comment is inert when ITS
    # OWN statement's pipeline is non-re-parsing, whatever the other
    # statements are headed by. Every row here was denied at 6b128c0 because
    # the head roster was read over the union of every statement's heads, so
    # one `python3` anywhere in the command turned the mask off for the whole
    # command (the differential's 18 cross-statement mention rows and the two
    # exec-quote bodies of `heredoc_to_file_then_run`). The separator between
    # the statements is varied on purpose -- `;`, newline, `&&` -- because a
    # row set that shares the separator cannot fail on it.
    ("dq_mention_then_interpreter",
     f'echo "true; {RM_RF} {ROOT_TARGET}"; python3 -c pass'),
    ("interpreter_then_dq_mention",
     f'python3 -c pass; echo "true; {RM_RF} {ROOT_TARGET}"'),
    ("dq_mention_newline_then_interpreter",
     f'echo "true; {RM_RF} {ROOT_TARGET}"\npython3 -c pass'),
    ("dq_mention_andand_then_interpreter",
     f'echo "true; {RM_RF} {ROOT_TARGET}" && python3 -c pass'),
    ("sq_mention_then_interpreter",
     f"printf '%s' 'true; {RM_RF} {ROOT_TARGET}'; python3 -c pass"),
    ("ansi_c_mention_then_interpreter",
     f"echo $'true; {RM_RF} {ROOT_TARGET}'; python3 -c pass"),
    ("dq_exec_mention_then_interpreter",
     f"echo \"eval '{RM_RF} {ROOT_TARGET}'\"; python3 -c pass"),
    ("quoted_heredoc_exec_mention_then_interpreter",
     f"cat > /tmp/x.md <<'EOF'\neval '{RM_RF} {ROOT_TARGET}'\nEOF\npython3 -c pass"),
    ("comment_mention_behind_interpreter",
     f"python3 -c pass # true; {RM_RF} {ROOT_TARGET}"),
    ("comment_line_between_interpreter_lines",
     f"python3 -c pass\n# true; {RM_RF} {ROOT_TARGET}\npython3 -c pass"),
    # An assignment-only line ends a pipe left open at the newline (driven:
    # the line after it did not receive the span), so the interpreter on the
    # third line owns nothing of the first.
    ("pipe_newline_assignment_then_interpreter",
     f'echo "true; {RM_RF} {ROOT_TARGET}" |\nX=1\npython3 -c pass'),
    # ⚠ THE INTERPRETER MENTIONS (447-A step 3, 2026-09-11). `python3`,
    # `perl`, `node`, `ruby`, `awk`, `sed` and `git` came off the raw-scan
    # side: a program under one of them is read for its shell-out CALLS (the
    # GENUINE rows above) and the rest of its text is data, so a string that
    # only quotes the idiom stops being refused. The first two rows lived in
    # GENUINE as "off the allowlist by design"; DEF-616's named user -- a
    # heredoc trim script carrying the harness's own relaunch line -- is the
    # third. Each carries a separator inside the mention so it was RED at
    # c7b46b9: the roster's cover on these heads came from the body's own
    # separators, never from the head.
    ("python_dash_c_mentions_it",
     f"python3 -c \"print('{RM_RF} {ROOT_TARGET}')\""),
    ("git_commit_redirect_mention",
     f'git commit -m "docs: stop writing > {PROTECTED_FILE} by hand"'),
    ("python_heredoc_relaunch_line",
     "python3 - <<'PY'\nnote = '''\nESPALIER_MAINTENANCE_MODE=1 claude --continue\n'''\nprint(note)\nPY"),
    ("python_c_triple_quoted_mention",
     f"python3 -c 'print(\"\"\"true; {RM_RF} {ROOT_TARGET}\"\"\")'"),
    ("python_c_paren_mention",
     f"python3 -c 'print(\"never (true; {RM_RF} {ROOT_TARGET})\")'"),
    ("python_heredoc_string_mention",
     f"python3 - <<'PY'\ntext = \"true; {RM_RF} {ROOT_TARGET}\"\nprint(len(text))\nPY"),
    ("perl_e_print_mention", f'perl -e "print q{{true; {RM_RF} {ROOT_TARGET}}}"'),
    ("node_e_log_mention", f"node -e 'console.log(`true; {RM_RF} {ROOT_TARGET}`)'"),
    ("ruby_e_puts_mention", f'ruby -e "puts %q{{true; {RM_RF} {ROOT_TARGET}}}"'),
    ("git_commit_stdin_mention",
     f"git commit -q -F - <<'EOF'\ndocs: why\n\ntrue; {RM_RF} {ROOT_TARGET} is refused\nEOF"),
    ("git_grep_quoted_separator", f'git grep -n "true; {RM_RF} {ROOT_TARGET}"'),
    ("git_log_grep_mention", f'git log --grep "true; {RM_RF} {ROOT_TARGET}"'),
    ("sed_stream_mention", f"sed -n '1,3p' <<'EOF'\ntrue; {RM_RF} {ROOT_TARGET}\nEOF"),
    ("sed_substitute_stream_mention",
     f"sed 's/x/y/' <<'EOF'\ntrue; {RM_RF} {ROOT_TARGET}\nEOF"),
    ("awk_print_var_mention",
     f"awk -v c=\"true; {RM_RF} {ROOT_TARGET}\" 'BEGIN{{print c}}'"),
    ("awk_print_literal_mention", f"awk 'BEGIN{{print \"true; {RM_RF} {ROOT_TARGET}\"}}'"),
    ("python_script_reads_stdin_data",
     f"python3 script.py <<'EOF'\ntrue; {RM_RF} {ROOT_TARGET}\nEOF"),
    ("interpreter_pipe_data_to_c_program",
     f"echo 'true; {RM_RF} {ROOT_TARGET}' | python3 -c 'import sys; print(len(sys.stdin.read()))'"),
    # The unquoted twin of the GENUINE backslash-line row: bash removes the
    # backslash-newline pair inside an UNQUOTED body, so the terminator on the
    # next line is swallowed, the delete is body text, and nothing runs
    # (driven with a marker: it did not appear).
    ("unquoted_heredoc_backslash_line_swallows_the_terminator",
     f"cat <<EOF\nx\\\nEOF\n{RM_RF} {ROOT_TARGET}\nEOF"),
]

#: The six classes a BLANKING mask destroyed. Hand-written, not derived from the
#: implementation, so a removal reds instead of shrinking the population.
QUOTE_SPLICE: list[tuple[str, str]] = [
    ("quoted_target", f'{RM_RF} "{ROOT_TARGET}"'),
    ("single_quoted_target", f"{RM_RF} '{ROOT_TARGET}'"),
    ("spliced_flag", f'rm -r"f" {ROOT_TARGET}'),
    ("quoted_verb", f'"rm" -rf {ROOT_TARGET}'),
    ("single_quoted_verb", f"'rm' -rf {ROOT_TARGET}"),
    ("empty_quote_splice", f"rm'' -rf {ROOT_TARGET}"),
    ("escaped_verb", f"\\rm -rf {ROOT_TARGET}"),
]


class TestHeadCaptureInsideAScannedWord:
    """DEF-754: the walker's head capture derives a read from inside an
    already-scanned word instead of scanning again. These pin the SETS that
    derivation must reproduce -- the level at which the identity is argued and
    at which the shell differential is blind (no wrapper there glues a
    grouping character inside a head word)."""

    def test_the_suffix_after_a_glued_opener_is_recorded_like_the_read_did(self):
        bp = _load_bash_patterns()
        _, heads, _ = bp._walk_shell_roles(f"(cd /tmp; {RM_RF} x)")
        assert heads == {"(cd", "cd", "rm"}

    def test_a_grouping_character_before_the_last_slash_keeps_the_basename(self):
        """`_read_head_word` records the basename, so `(/bin/echo` IS the
        roster word `echo`; the suffix after the paren rsplits to the same."""
        bp = _load_bash_patterns()
        _, heads, _ = bp._walk_shell_roles("(/bin/echo hi")
        assert heads == {"echo"}

    def test_the_suffix_after_a_glued_closer_joins_the_rebound_pipeline(self):
        bp = _load_bash_patterns()
        _, heads, _ = bp._walk_shell_roles("a}b | cat")
        assert heads == {"a}b", "b", "cat"}

    def test_a_suffix_longer_than_any_rostered_word_is_the_sentinel(self):
        bp = _load_bash_patterns()
        _, heads, _ = bp._walk_shell_roles("(" * 40 + "cmd")
        assert bp._UNROSTERED_HEAD in heads
        assert "(" * 40 + "cmd" in heads
        real = heads - {"(" * 40 + "cmd", bp._UNROSTERED_HEAD}
        assert real and all(len(h) <= bp._MAX_ROSTERED_HEAD_LEN for h in real)
        assert bp._UNROSTERED_HEAD not in bp._NON_REPARSING_HEADS

    def test_no_rostered_word_holds_a_grouping_character(self):
        """The property the derivation leans on: a suffix that still holds a
        grouping character can never be on the roster."""
        bp = _load_bash_patterns()
        assert not any(set(h) & set("(){}") for h in bp._NON_REPARSING_HEADS | bp._HEAD_SKIP_WORDS)


class TestStatementExtents:
    """The per-statement settle reads each span against ITS statement's extent,
    and the walker advances the extent at every rebind of the owner set and
    only there. A rebind site added later without the advance attributes
    spans to the wrong statement -- silently, toward friction -- so the
    extents are pinned here through the settle's own arguments (failure-mode
    review, 447-A step 2)."""

    @staticmethod
    def _extents(bp, cmd: str) -> list[tuple[int, int]]:
        seen: dict = {}
        real = bp._settle_statement_spans

        def spy(masked, candidates, statements, safe_spans):
            seen["statements"] = [tuple(r) for r in statements]
            real(masked, candidates, statements, safe_spans)

        bp._settle_statement_spans = spy
        try:
            bp._walk_shell_roles(cmd)
        finally:
            bp._settle_statement_spans = real
        return seen["statements"]

    def test_a_separator_and_a_bare_newline_advance_and_an_open_pipe_does_not(self):
        bp = _load_bash_patterns()
        cmd = "a; b\nc |\nd"
        assert self._extents(bp, cmd) == [(0, 2), (2, 5), (5, len(cmd))]

    def test_extents_are_contiguous_and_cover_the_command(self):
        bp = _load_bash_patterns()
        cmd = ("x=1 a && (b || c) | d\n{ e; } |& f 2>&1 | g\n"
               "cat <<'EOF'\nbody\nEOF\nh")
        ext = self._extents(bp, cmd)
        assert ext[0][0] == 0 and ext[-1][1] == len(cmd)
        assert all(ext[k][1] == ext[k + 1][0] for k in range(len(ext) - 1))
        assert all(a <= b for a, b in ext)


class TestGenuineCommandsStillDeny:
    """A row flipping to ALLOW is a bypass, not a false-positive fix."""

    @pytest.mark.parametrize("label,cmd", GENUINE, ids=[r[0] for r in GENUINE])
    def test_denies(self, label, cmd, tmp_path):
        assert_hook_denied(run_bash_guard(cmd, tmp_path))


class TestInertProseIsAllowed:
    """Every row here was RED against the unfixed tree, by design."""

    @pytest.mark.parametrize("label,cmd", INERT, ids=[r[0] for r in INERT])
    def test_allows(self, label, cmd, tmp_path):
        assert_hook_allowed(run_bash_guard(cmd, tmp_path))


class TestQuoteSpliceClassesStillDeny:
    """The arm that keeps the role map from decaying into a blanking mask."""

    @pytest.mark.parametrize("label,cmd", QUOTE_SPLICE,
                             ids=[r[0] for r in QUOTE_SPLICE])
    def test_denies(self, label, cmd, tmp_path):
        assert_hook_denied(run_bash_guard(cmd, tmp_path))


class TestMaskControlsAndFailClosed:
    """Controls: the mask must not be vacuous, and must fail toward the deny."""

    def test_mask_preserves_length_and_offsets(self):
        """Substitution, never deletion — downstream offsets stay meaningful."""
        bp = _load_bash_patterns()
        for _label, cmd in GENUINE + INERT + QUOTE_SPLICE:
            assert len(bp.mask_inert_syntax(cmd)) == len(cmd), cmd

    def test_an_interpreter_head_no_longer_turns_the_mask_off(self):
        """DEF-616's mechanism-level probe, flipped (447-A step 3): behind a
        head that has a shell-out READER the quoted argument is masked like
        any rostered head's; behind a shell head, which hands its argument to
        a shell whole, the command still comes back raw."""
        bp = _load_bash_patterns()
        assert bp.mask_inert_syntax('python3 -c "a;b"') != 'python3 -c "a;b"'
        assert bp.mask_inert_syntax('git commit -m "a;b"') != 'git commit -m "a;b"'
        assert bp.mask_inert_syntax('bash -c "a;b"') == 'bash -c "a;b"'

    @pytest.mark.parametrize("cmd, blank", [
        ("MSG='a; b'; make", True),       # stored by a statement with no head: data
        ("MSG='a; b'", True),
        ('MSG="a; b"; make', True),
        ("MSG=$'a; b'; make", True),
        ("MSG='a; b' echo x", True),      # prefixes a rostered head
        ("MSG='a; b' make", False),       # prefixes a head on no roster: its owner
        ("MSG='a; b' | sh", False),       # a pipe extends the owner set to a shell
        ("{ MSG='a; b'; } | sh", False),  # a group: no owner set can see the shell
        ('MSG="$(x) a; b"; make', False),  # a live substitution captures the statement
    ])
    def test_an_assignment_value_is_data_by_its_statement(self, cmd, blank):
        """DEF-848's settle rule on its own (the failure-mode review): a
        quoted piece of an assignment value is data when its statement has
        no head at all, and is judged by its owners -- like any quoted
        argument -- when it prefixes a head or a pipe extends the statement
        to one. Read as the separator INSIDE the value, blank or live."""
        bp = _load_bash_patterns()
        at = cmd.index(";")
        assert (bp.mask_inert_syntax(cmd)[at] == " ") is blank, cmd

    def test_every_reader_head_resolves_to_a_family_with_a_reader(self):
        """The enrolment contract's mechanical half: each spelling the family
        test admits names a family in `_READER_FAMILIES`, the set the readers
        handle (the module refuses to import otherwise); a near-miss spelling
        names none and keeps the raw scan."""
        bp = _load_bash_patterns()
        for head in bp._READER_HEAD_SPELLINGS:
            assert bp._reader_family(head) in bp._READER_FAMILIES, head
        for head in ("python3.13t", "pypy3", "perl5", "ruby3.2", "nodejs", "gawk", "gsed"):
            assert bp._reader_family(head) in bp._READER_FAMILIES, head
        for head in ("pythont", "pythonic", "nodemon", "perlbrew", "rubygems",
                     "bash", "sh", "env", "xargs", bp._UNROSTERED_HEAD):
            assert bp._reader_family(head) is None, head

    def test_mask_touches_no_token_content(self):
        """Only characters in the syntax set may change, and only to a space.

        This is the property that separates a role map from a blanking mask. If
        it reds, quote-splice coverage is already gone whether or not
        :class:`TestQuoteSpliceClassesStillDeny` has noticed yet.

        The ONE sanctioned exception is an exec opener (`eval`, `sh -c`) inside
        a span already proven inert -- `_EXEC_OPENER_RE`'s own note calls it
        the one place the pass touches token content, and 447-A step 2 applies
        it inside a per-statement safe span as well. A changed character
        outside the syntax set must therefore lie inside such a match AND
        where the pass may touch it: anywhere when every head is rostered,
        else only inside a safe span the walker reported (both reviews: an
        exception scoped to the whole command let a mask that erased a live
        opener pass this control). The verb of every quote-splice row is not
        an opener, so that coverage is intact.
        """
        bp = _load_bash_patterns()
        for _label, cmd in GENUINE + INERT + QUOTE_SPLICE:
            masked = bp.mask_inert_syntax(cmd)
            try:
                _, heads, spans = bp._walk_shell_roles(cmd)
            except (bp._UnresolvedShellSyntax, IndexError):
                heads, spans = set(), []
            all_rostered = bool(heads) and all(
                bp._head_hands_nothing_to_a_shell(h) for h in heads)
            touchable = {k for a, b in spans for k in range(a, b)}
            opener_positions = {k for m in bp._EXEC_OPENER_RE.finditer(cmd)
                                for k in range(m.start(), m.end())
                                if all_rostered or k in touchable}
            for k, (original, new) in enumerate(zip(cmd, masked)):
                if original == new:
                    continue
                assert original in bp._INERTABLE_SYNTAX or k in opener_positions, (
                    cmd, k, original)
                assert new == " ", (cmd, original, new)

    #: Inert rows whose relief comes from SUBSTITUTION — each carries a syntax
    #: character inside an inert span, so masking must visibly change them. Named
    #: explicitly rather than derived, so deleting the substitution for one of them
    #: reds here instead of quietly shrinking a count.
    MUST_CHANGE = (
        "grep_for_a_redirect_double_quoted",
        "grep_for_a_redirect_single_quoted",
        "prose_about_a_heredoc",
        "quoted_delimiter_heredoc_body",
        "delete_literal_in_quoted_heredoc",
        "delete_literal_single_quoted",
        "paren_inside_double_quotes",
        "markdown_fence_in_quoted_heredoc",
        "backtick_glued_comment",
        # 447-A step 2: the per-statement rule's three span kinds -- a quoted
        # argument, a comment, a quoted heredoc body carrying an exec opener
        # -- each beside an off-roster statement
        "dq_mention_then_interpreter",
        "comment_mention_behind_interpreter",
        "quoted_heredoc_exec_mention_then_interpreter",
        # 447-A step 3: a separator or opener inside a program under a reader
        # head, and inside a quoted argument beside one
        "python_dash_c_mentions_it",
        "python_c_triple_quoted_mention",
        "python_heredoc_string_mention",
        "perl_e_print_mention",
        "node_e_log_mention",
        "ruby_e_puts_mention",
        "git_commit_stdin_mention",
        "git_grep_quoted_separator",
        "sed_stream_mention",
        "awk_print_var_mention",
    )

    def test_mask_is_not_vacuous(self):
        """A mask that changed nothing would pass every anti-regression row.

        ⚠ NOT "every inert row changes" — that was the first version and it was
        the wrong property. Some rows are relieved by a character SURVIVING rather
        than being substituted: a comment whose body holds no syntax character is
        fixed because the `#` itself is left standing to break the command-position
        run, so the mask returns it byte-identical. Asserting universal change made
        the correct fix look like a regression.
        """
        bp = _load_bash_patterns()
        by_label = dict(INERT)
        for label in self.MUST_CHANGE:
            cmd = by_label[label]
            assert bp.mask_inert_syntax(cmd) != cmd, label

    def test_mask_is_not_universal(self):
        """The genuine rows must reach the guard essentially unmasked.

        The four exec-quote and expanding-heredoc rows are the ones a naive mask
        would neutralise; pin them explicitly.
        """
        bp = _load_bash_patterns()
        for label in ("eval_double_quoted", "eval_single_quoted",
                      "bash_c_double_quoted", "bash_c_single_quoted",
                      "backtick_inside_double_quotes",
                      "unquoted_heredoc_body_expands"):
            cmd = dict((k, v) for k, v in GENUINE)[label]
            masked = bp.mask_inert_syntax(cmd)
            assert RM_RF in masked, (label, masked)

    @pytest.mark.parametrize("cmd", [
        "echo 'unterminated single quote",
        'echo "unterminated double quote',
        "cat <<'EOF'\nno terminator here",
        'echo "unbalanced $(subshell"',
    ])
    def test_unparseable_input_falls_back_to_raw(self, cmd):
        """Fail CLOSED: an unresolvable parse returns today's behaviour.

        A parse failure must never be the thing that lets a delete through.
        """
        bp = _load_bash_patterns()
        assert bp.mask_inert_syntax(cmd) == cmd

    @pytest.mark.parametrize("cmd", [
        f"ls; {RM_RF} {ROOT_TARGET} 'unterminated",
        f'ls; {RM_RF} {ROOT_TARGET} "unterminated',
        f"ls; {RM_RF} {ROOT_TARGET} `unterminated",
        f"{RM_RF} {ROOT_TARGET} 'unterminated",
    ])
    def test_unterminated_quote_around_a_real_delete_still_denies(self, cmd,
                                                                  tmp_path):
        """The fail-closed rule, driven end to end rather than asserted.

        ⚠ The delete must sit at a REAL command position for this arm to mean
        anything. The first draft used ``echo 'oops <delete>`` and failed —
        correctly: that command was never denied, before or after this change,
        because the verb sits in an argument. The test was asserting a behaviour
        the guard never had, which would have read as a mask regression the first
        time anyone looked at it.
        """
        assert_hook_denied(run_bash_guard(cmd, tmp_path))

    def test_only_the_interpreter_sites_read_the_raw_command(self):
        """The raw/masked split inside `_candidate_paths_from_bash`, pinned.

        ⚠ A SOURCE-LEVEL contract, deliberately. The behavioural version of this
        went INERT the moment `python` came off `_NON_REPARSING_HEADS`: with the
        head allowlist in force those bodies are never masked anyway, so mutating
        the split changed nothing observable. The split still has to hold — it is
        one careless "tidy `command` and `scan` into one variable" away from
        fail-opening every BC-006 corpus attempt if the allowlist ever widens — so
        pin it where it actually lives. Derived from the function body, so a NEW
        extractor added outside the masked set names itself here rather than
        shrinking a count -- AND from the body of every helper this function
        hands both strings to: `_stdin_program_bodies` (DEF-698) reads the raw
        `command` for the heredoc body from OUTSIDE this slice, which the
        `.finditer(command)` scrape below cannot see, so its own two-string
        discipline is pinned separately at the bottom.
        """
        import re

        src = (HOOKS_DIR / "_bash_patterns.py").read_text(encoding="utf-8")
        start = src.index("def _candidate_paths_from_bash")
        # ⚠ END AT THE NEXT TOP-LEVEL `def`, NOT AT A NAMED SIBLING. This slice
        # used to run to `def _candidate_paths_from_powershell`, which is not the
        # end of this function -- it is merely the next one someone happened to
        # name. On 2026-08-26 the PowerShell symlink chain was relocated between
        # the two (it had to move below `_PS_CMD_POS` to be anchored), and
        # `powershell_symlink_linknames`'s own raw `.finditer(command)` silently
        # joined this population. The failure was loud in that direction, but the
        # same slice fails SILENTLY in the other: move `_candidate_paths_from_
        # powershell` above this function and the population becomes empty, and
        # an empty population satisfies nothing while looking like a pass. A
        # boundary defined by a NEIGHBOUR's name is not a boundary.
        end = src.index("\ndef ", start + 1)
        body = src[start:end]
        raw = sorted(set(re.findall(r"(\w+)\.finditer\(command\)", body)))
        assert raw == [], (
            "DEF-704 moved the last raw call sites into `_inline_program_bodies`; "
            f"a new extractor is reading the raw command directly: {raw}"
        )
        # EVERY program-body helper, derived by name shape rather than the two
        # named by hand: opener on the MASKED string, body from the RAW one by
        # offset. A third arm (`php -r`, `lua -e`) enrols here by construction.
        helpers = [m.group(1) for m in re.finditer(r"^def (_\w+_program_bodies)\(", src, re.M)]
        assert len(helpers) >= 2, helpers
        for name in helpers:
            h0 = src.index(f"def {name}(")
            h1 = src.index("\ndef ", h0 + 1)
            helper = src[h0:h1]
            assert ".finditer(scan)" in helper, (
                f"{name}: the opener must be matched on the MASKED string"
            )
            assert "command[" in helper, (
                f"{name}: the body must be sliced from the RAW command by offset"
            )
        # The stdin-program helper: opener on the MASKED string, body from the
        # RAW one. A behavioural pin cannot exist here for the same reason as
        # above (an interpreter head turns the mask off), so pin the source.
        h0 = src.index("def _stdin_program_bodies")
        h1 = src.index("\ndef ", h0 + 1)
        helper = src[h0:h1]
        assert "_INTERP_STDIN_RE.finditer(scan)" in helper, (
            "the stdin-program opener must be matched on the MASKED string"
        )
        assert "command[" in helper and "command.find(" in helper, (
            "the stdin-program body must be sliced from the RAW command"
        )
        assert "_stdin_program_bodies(command, scan)" in body, (
            "the call site must hand the helper BOTH strings, raw first"
        )
        # The population must not be able to go vacuous unnoticed: this function
        # reads the MASKED `scan` everywhere except those four sites, so a slice
        # that captured nothing at all would pass the assertion above.
        assert ".finditer(scan)" in body, (
            "the sliced body contains no masked call site at all -- the slice "
            "boundary is wrong, not the split."
        )

    def test_interpreter_bodies_are_not_masked(self, tmp_path):
        """BC-006: the inline-interpreter extractors read a QUOTED SCRIPT BODY.

        Masked input fail-opens all five corpus attempts, which is why
        `_candidate_paths_from_bash` keeps a raw string for exactly those sites.
        Driven here because the split is a one-line edit away from being lost.
        """
        for cmd in (
            'node -e \'require("fs").writeFileSync(".claude/settings.json", "x")\'',
            'ruby -e \'File.write(".claude/settings.json", "x")\'',
            'perl -e \'open(F, ">.claude/settings.json"); print F "x";\'',
            'pypy -c \'open(".claude/settings.json", "w").write("x")\'',
        ):
            assert_hook_denied(run_bash_guard(cmd, tmp_path))

    def test_parameter_expansion_survives_the_mask(self):
        """`${...}` is a live expansion and must reach the extractors intact.

        ⚠ A UNIT assertion on the mask, deliberately NOT a driven deny test. The
        first version of this drove `F=.claude/settings.json; echo x > "${F}"`
        and asserted it still denies — it does, but it also denies with the
        `${...}` branch deleted, because `_candidate_paths_from_bash` expands
        simple assignments BEFORE masking. Mutation proved that arm inert: it
        passed under the mutation it was written to catch. Pinning the mask's own
        output is the honest scope, and it is the property a future caller that
        masks before expanding would rely on.
        """
        bp = _load_bash_patterns()
        for cmd in ('echo x > "${F}"', 'echo "${HOME}/x"', 'cp a "${D}/b"'):
            assert bp.mask_inert_syntax(cmd) == cmd, cmd

    def test_speedbump_predicates_consume_masked_input(self, tmp_path):
        """The four speed-bump wirings, pinned.

        ⚠ Added because mutation caught their absence: reverting `_masked_command`
        to the raw string left this whole file GREEN. The guard-driven rows above
        never reach `_speedbump`, so nothing here saw that wiring at all.
        """
        spec = importlib.util.spec_from_file_location(
            "_speedbump_masktest", HOOKS_DIR / "_speedbump.py",
        )
        sb = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = sb
        spec.loader.exec_module(sb)

        inert = [
            ("forcepush_in_comment", sb._pred_forcepush,
             "# doc: `git push --force` rewrites history\nls"),
            ("forcepush_paren_in_dquotes", sb._pred_forcepush,
             'echo "call run(git push --force) here"'),
            ("discard_in_comment", sb._pred_discard,
             "# doc: `git stash drop` is destructive\nls"),
            ("gitclean_in_comment", sb._pred_gitclean,
             "# doc: `git clean -fd` deletes untracked files\nls"),
        ]
        for label, pred, cmd in inert:
            assert not pred("Bash", {"command": cmd}, tmp_path), label

        genuine = [
            ("forcepush", sb._pred_forcepush, "git push --force origin main"),
            ("discard", sb._pred_discard, "git reset --hard HEAD~1"),
            ("gitclean", sb._pred_gitclean, "git clean -fd"),
            ("release", sb._pred_release, "git push origin v1.2.3"),
        ]
        for label, pred, cmd in genuine:
            assert pred("Bash", {"command": cmd}, tmp_path), label


class TestExecOpenerMentionsAreRelievedInsideInertCommands:
    """Prose that quotes `eval` / `sh -c` is no longer refused — where it can be.

    ``_CMD_POS_EXEC_QUOTE`` is ``\\b``-anchored, so the bare WORD ``eval`` creates
    a command position wherever it appears (measured: it matches mid-prose at
    offset 11 of ``some prose eval 'x'``). Separator substitution alone cannot
    suppress that, because the trigger is token CONTENT.

    ⚠ THE OBVIOUS FIX WAS MEASURED AND REJECTED. Anchoring that arm loses four
    genuinely-executing shapes — ``find -exec sh -c``, ``ssh host '...'``, a
    flag-embedded ``--wrap='eval ...'`` and a ``git`` alias body — to relieve
    three inert ones. Instead the exec opener is blanked only inside a command
    whose head words are ALL on ``_NON_REPARSING_HEADS``: under that precondition
    the opener is necessarily argument text, so blanking it cannot hide a live
    invocation. ``bench/reachability_differential.py`` carries the nested-shell
    wrappers so any future narrowing of that arm has to answer to the shell.

    Population went 16 refused shapes → 4.
    """

    CONTAINERS = [
        ("quoted_heredoc", "cat > /tmp/x.md <<'EOF'\n%s\nEOF"),
        ("single_quotes", "printf '%%s' '%s'"),
        ("shell_comment", "# %s\nls"),
    ]
    PAYLOADS = [
        ("eval_quoted", f"eval '{RM_RF} {ROOT_TARGET}'"),
        ("bash_c", f"bash -c '{RM_RF} {ROOT_TARGET}'"),
        ("sh_c", f"sh -c '{RM_RF} {ROOT_TARGET}'"),
        ("eval_unquoted", f"eval {RM_RF} {ROOT_TARGET}"),
    ]

    @pytest.mark.parametrize(
        "cname,template", CONTAINERS, ids=[c[0] for c in CONTAINERS],
    )
    @pytest.mark.parametrize(
        "pname,payload", PAYLOADS, ids=[p[0] for p in PAYLOADS],
    )
    def test_exec_quote_mention_is_allowed(self, cname, template, pname,
                                           payload, tmp_path):
        assert_hook_allowed(run_bash_guard(template % payload, tmp_path))

    @pytest.mark.parametrize("payload", [p[1] for p in PAYLOADS],
                             ids=[p[0] for p in PAYLOADS])
    def test_the_same_payload_unwrapped_still_denies(self, payload, tmp_path):
        """The half that keeps the relief honest.

        Blanking an exec opener must not reach a command that really runs one. If
        this class ever goes green while these rows do too, the opener is being
        blanked outside the inert precondition.
        """
        assert_hook_denied(run_bash_guard(payload, tmp_path))

    def test_nested_shell_invocations_still_deny(self, tmp_path):
        """The four shapes anchoring would have lost. None may be relieved."""
        for cmd in (
            f"find . -maxdepth 0 -exec sh -c '{RM_RF} {ROOT_TARGET}' \\;",
            f"echo x | xargs sh -c '{RM_RF} {ROOT_TARGET}'",
            f"nice sh -c '{RM_RF} {ROOT_TARGET}'",
            f"env sh -c '{RM_RF} {ROOT_TARGET}'",
        ):
            assert_hook_denied(run_bash_guard(cmd, tmp_path))

    def test_the_git_residual_was_a_roster_choice_and_is_now_read(self, tmp_path):
        """What used to be refused here, and why it no longer is.

        `git` was deliberately absent from `_NON_REPARSING_HEADS` (`git
        submodule foreach` runs a shell), so a commit message quoting an exec
        form was not masked at all -- pinned as a roster choice, not a lexer
        limit. The trio's third step made the choice: `git` is a READER head,
        its alias, credential-helper and exec-valued config values are read
        as programs (the `git_*` rows in GENUINE), and the rest of a git
        command is data.
        """
        assert_hook_allowed(run_bash_guard(
            f'git commit -m "never run eval \'{RM_RF} {ROOT_TARGET}\'"',
            tmp_path,
        ))


class TestInlineInterpreterOpenersAreAnchored:
    """DEF-704: the `-c` / `-e` openers were the last extractors that were
    neither command-position-anchored nor matched on the masked string, so a
    `#` comment or a prose line spelling `python3 -c "open('<hook>','w')"` was
    read as an invocation and denied, and their `\\s+` joiners reached past a
    newline (`python3` + newline + `-c "..."` is two statements to bash and
    was one to the regex). Both failed toward friction; the rows below pin
    the relief AND, twin by twin, that the real invocations still deny.
    """

    WRITE = f"open('{PROTECTED_FILE}','w').write('x')"

    def test_a_comment_mention_is_not_an_invocation(self, tmp_path):
        assert_hook_allowed(run_bash_guard(f'ls # python3 -c "{self.WRITE}"', tmp_path))

    def test_the_split_spelling_is_two_statements(self, tmp_path):
        # `-c "..."` at the start of line two is its own (failing) command to
        # bash; nothing runs the program.
        assert_hook_allowed(run_bash_guard(f'python3\n-c "{self.WRITE}"', tmp_path))

    def test_a_quoted_mention_behind_a_roster_head_is_text(self, tmp_path):
        # Inside single quotes everything is literal to bash, so the `;` that
        # would otherwise open a command position is masked to text.
        # ⚠ This pins the ANCHOR, not the mask half: the inner `"` closes the
        # `-c` body before the path, so it is green on the unfixed source and
        # under a match-on-raw mutation alike. The mask half's only witness is
        # the source pin in `test_only_the_interpreter_sites_read_the_raw_command`
        # (an interpreter head turns the mask off, so no behavioural row can
        # see it); do not delete that pin because "the behaviour is covered".
        dq = '"'
        body = f"open({dq}{PROTECTED_FILE}{dq}, {dq}w{dq})"
        cmd = f"echo 'x; python3 -c {dq}{body}{dq}'"
        assert_hook_allowed(run_bash_guard(cmd, tmp_path))

    @pytest.mark.parametrize("shape", [
        'python3 -c "{w}"',
        'x; python3 -c "{w}"',
        'true && python3 -c "{w}"',
        '$(python3 -c "{w}")',
        '/usr/bin/python3 -B -c "{w}"',
        'python3.12 -c "{w}"',
        'pypy -c "{w}"',
        'python3 -c "a = 1\n{w}"',
        'sudo python3 -c "{w}"',
        'PYTHONWARNINGS=ignore python3 -c "{w}"',
        # a quoted Windows interpreter path (Git Bash): the closing quote after
        # the name and the backslash directory both have to be command position
        '"C:\\Python312\\python.exe" -c "{w}"',
        "\"C:\\Python312\\python.exe\" - <<'PY'\n{w}\nPY",
        # ...and the default all-users install location has a SPACE in it, as
        # do plenty of POSIX paths; escaped-space unquoted is a real spelling too
        '"C:\\Program Files\\Python312\\python.exe" -c "{w}"',
        '"C:/Program Files/Python312/python.exe" -c "{w}"',
        '"/opt/my tools/python3" -c "{w}"',
        'C:\\Program\\ Files\\Python312\\python.exe -c "{w}"',
        # the condition of a compound, and a negated pipeline, run the program
        'if python3 -c "{w}"; then :; fi',
        'while python3 -c "{w}"; do break; done',
        'until python3 -c "{w}"; do break; done',
        '! python3 -c "{w}"',
    ])
    def test_real_python_invocations_still_deny(self, tmp_path, shape):
        assert_hook_denied(run_bash_guard(shape.format(w=self.WRITE), tmp_path))

    @pytest.mark.parametrize("cmd", [
        f"node -e 'require(\"fs\").writeFileSync(\"{PROTECTED_FILE}\", \"x\")'",
        f"x; node -e 'require(\"fs\").writeFileSync(\"{PROTECTED_FILE}\", \"x\")'",
        f"ruby -e 'File.write(\"{PROTECTED_FILE}\", \"x\")'",
        f"perl -e 'open(F, \">{PROTECTED_FILE}\"); print F \"x\";'",
        f"ls && ruby -e 'File.write(\"{PROTECTED_FILE}\", \"x\")'",
        f"sudo perl -e 'open(F, \">{PROTECTED_FILE}\"); print F \"x\";'",
        # the `-e` legs' quoted-path witnesses: with and without a space in the
        # path, one per interpreter (three of four legs were green over a hole)
        f"\"C:\\nodejs\\node.exe\" -e 'require(\"fs\").writeFileSync(\"{PROTECTED_FILE}\", \"x\")'",
        f"\"C:\\Program Files\\nodejs\\node.exe\" -e 'require(\"fs\").writeFileSync(\"{PROTECTED_FILE}\", \"x\")'",
        f"\"C:\\Ruby33\\bin\\ruby.exe\" -e 'File.write(\"{PROTECTED_FILE}\", \"x\")'",
        f"\"C:\\Program Files\\Ruby33\\bin\\ruby.exe\" -e 'File.write(\"{PROTECTED_FILE}\", \"x\")'",
        f"\"C:\\Strawberry\\perl\\bin\\perl.exe\" -e 'open(F, \">{PROTECTED_FILE}\"); print F \"x\";'",
        f"\"C:\\Program Files\\Strawberry\\perl\\bin\\perl.exe\" -e 'open(F, \">{PROTECTED_FILE}\"); print F \"x\";'",
    ])
    def test_the_other_three_interpreters_still_deny(self, tmp_path, cmd):
        assert_hook_denied(run_bash_guard(cmd, tmp_path))

    @pytest.mark.parametrize("cmd", [
        f"ls # node -e 'require(\"fs\").writeFileSync(\"{PROTECTED_FILE}\", \"x\")'",
        f"ls # ruby -e 'File.write(\"{PROTECTED_FILE}\", \"x\")'",
        f"ls # perl -e 'open(F, \">{PROTECTED_FILE}\"); print F \"x\";'",
        f"node\n-e 'require(\"fs\").writeFileSync(\"{PROTECTED_FILE}\", \"x\")'",
    ])
    def test_the_other_three_interpreters_are_anchored_too(self, tmp_path, cmd):
        assert_hook_allowed(run_bash_guard(cmd, tmp_path))

    def test_joiners_stop_at_a_newline_but_the_body_may_span_lines(self):
        """The census allowlists the four for their quoted body; this is the
        pin the allowlist would otherwise let rot: a `-c` on line two is NOT
        this line's flag, while a newline INSIDE the quoted body still is
        part of the program."""
        import _bash_patterns

        for rx, name, flag in ((_bash_patterns._PYTHON_DASH_C_RE, "python3", "-c"),
                               (_bash_patterns._NODE_DASH_E_RE, "node", "-e"),
                               (_bash_patterns._RUBY_DASH_E_RE, "ruby", "-e"),
                               (_bash_patterns._PERL_DASH_E_RE, "perl", "-e")):
            assert rx.search(f"{name}\n{flag} \"open('x','w')\"") is None, name
            assert rx.search(f"{name} {flag} \"a=1\nopen('x','w')\"") is not None, name
