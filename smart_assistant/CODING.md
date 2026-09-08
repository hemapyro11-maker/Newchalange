# Nezuko coding workflow

This update turns Nezuko's existing tools into a project-oriented workflow. It
does not include a Claude model or claim Claude Code's model quality or sandbox.
No Codex plugins need to be installed.

## Run

Use Python 3.11 or newer. From `smart_assistant`:

```powershell
py cli.py --coding-only --project "C:\Projects\my-app"
```

`start_code.bat --project "C:\Projects\my-app"` is the Windows shortcut.
The coding-only client uses the built-in coding commands and the existing file
editing tools. Media, messaging and other optional integrations are not loaded
in this mode. For the desktop interface, run `py main_gui.py` with its existing
GUI dependencies installed.

Configure an existing provider using `brain_setup` in the full desktop app, or
run a local Ollama server. The selected model must actually be available. Coding
commands also work directly without a model. Remote providers receive supplied
project context; `brain_local on` in the full app restricts model routing and
speech synthesis to local engines. Local speech engines may still download a
voice model on first use.

## A coding session

```text
project "C:\Projects\my-app"
mode plan
list_files *.py
search "calculate_total" *.py
read_file src/cart.py 1 120
mode ask
Fix the total calculation and run its tests.
```

Nezuko proposes one tool at a time, displays edits including their SEARCH/REPLACE
content, asks for approval, and feeds the actual tool result back to the model.
`y` approves the displayed operation; `n` cancels it. Permanent approval with `a`
is refused for execution, editing and permission-changing commands. Previously
saved natural-language shortcuts retain their arguments and still ask before
execution. Legacy shortcuts that lost their arguments are ignored.

`test` runs `python -m pytest -q` using the current interpreter. Supply an explicit
executable for another environment, for example:

```text
test "C:\Projects\my-app\.venv\Scripts\python.exe" -m pytest -q
git_status
git_diff src/cart.py
```

Tests and shell commands run in the selected project, report their exit status,
and can execute project code. They are not sandboxed. `run` uses an argument
list, not a shell; shell syntax such as pipes requires an explicitly selected
shell executable. Tool output displayed by `test` is capped at 24,000 characters.
`git_diff` shows unstaged changes to tracked files; use `git_status` and `read_file`
to inspect new, untracked files.

## Interface commands

- Desktop: `/project` selects a folder; `/plan` and `/code` switch modes;
  `/cancel` invalidates pending work; `/new` opens a fresh session;
  `/resume` opens the saved-session picker.
- Terminal: `/plan`, `/code`, `/cancel`, `/new`, `/resume SESSION_ID`, `/help`,
  and `/exit`. `/paste` accepts a multiline command until a line containing `/end`.
- `project`, `mode`, `list_files`, `search`, `git_status`, `git_diff`, and `test`
  work in both clients. Project selection is saved with coding conversations.

Root `AGENTS.md` and `CLAUDE.md` are included as project guidance when present.
File search is literal, bounded, and skips common dependency directories,
hidden files and common private-key extensions. This is not a comprehensive
secret scanner. File reads/edits can address absolute paths outside the project;
review the displayed paths before approving them.

## Behavioral changes

- One worker serializes model replies and tool execution. The UI remains on its
  own thread. Long model calls delay other queued commands.
- Starting/resuming a session or cancelling invalidates previous queued requests
  and approvals. Cancellation does not kill an already-running command or HTTP
  call; its eventual model reply cannot enter the new session.
- Scheduled commands, macros and hooks use an automation path. They cannot answer
  interactive confirmations. Only explicitly allowed commands run in the
  background; blocked actions are logged for explicit execution.
- Telegram and Discord approvals are tied to channel and sender. Their capture
  waits for the model response, subject to the existing connector timeout.
- Specialized agents use the normal tool/approval loop and enforce their declared
  tool list. These runs currently share the main session's history; they are not
  isolated parallel workers.
- SQLite migration files run transactionally, including tracking records.
  Migrations cannot issue their own BEGIN/COMMIT/SAVEPOINT or attach databases.
- Generated plugins receive static syntax/entry-point checks only. They are not
  executed during validation. Explicitly approved plugins run with normal user
  permissions; static success is not a runtime or security guarantee.
- Windows file-permission inspection no longer treats POSIX bits as ACLs. It
  reports that ACL auditing is unsupported, instead of issuing a false verdict.

## Model default

The Gemini default is `gemini-3.6-flash`, the documented replacement for the
retired `gemini-2.0-flash`. Explicit model overrides are retained. Provider quotas
vary by account and model; update configured limits to match your account.
Source: [Google Gemini deprecations](https://ai.google.dev/gemini-api/docs/deprecations),
checked 2026-09-08. A live provider call and its free-tier availability were not
verified in this development environment.

## Verification

Run `python -m pytest tests -q`. Optional integration tests require their actual
dependencies (FFmpeg, Tcl/Tk, external scanners, and so on). POSIX permission-bit
tests skip on Windows. Parser packages may download their language grammar on
first use.

`tests/test_coding_workflow.py` exercises cancellation, approval isolation,
Windows paths, atomic edits, transactional migrations, quota reservations,
session restoration, plan mode and agent tool restrictions. Its coding scenario
starts with a failing real unittest, uses deterministic model replies to read
and edit the file with explicit approvals, and reruns the real test successfully.
It tests the orchestration, not a live model's ability to solve arbitrary tasks.

The Windows onefile build configuration includes the new modules, but an EXE
has not been built or validated in this environment. See the accompanying
development report for exact test totals and remaining environment limitations.
