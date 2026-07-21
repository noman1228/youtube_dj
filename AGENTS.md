# AGENTS.md — AI agent guidance for youtube_dj

Purpose: Provide concise, actionable instructions so AI coding agents can be productive in this repository.

Quick links
- Run script: [run_windows.bat](run_windows.bat)
- Project entry: [main.py](main.py)
- App package: [app/](app/)
- Dependencies: [requirements.txt](requirements.txt)
- Docs: [README.md](README.md)

Developer environment
- Preferred Python: 3.11+ (64-bit). Use a virtualenv in `.venv`.
- To recreate environment (Windows PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

What agents should know
- Entrypoint is `main.py` which constructs the Qt UI in `app/main_window.py`.
- UI and app logic live under `app/` — edit these files for UI/behavior changes.
- Heavy or network actions: `yt-dlp`, `ytmusicapi`, and media playback (`python-vlc`) are required by the app; do not run network downloads or play media without explicit user permission.
- There are no automated tests or CI configs in the repo; prefer small, local, non-destructive edits and request user approval for larger changes.
- Follow the "link, don't embed" principle: link to README or source files rather than copying large docs.

Recommended agent tasks
- To run the app locally, use `run_windows.bat` or the PowerShell steps above.
- For UI changes, run the app to verify behavior; ask the user before installing or running system-level dependencies.
- When modifying code, keep changes minimal and focused; preserve existing style and import patterns.

Files added/edited by agents
- Prefer `AGENTS.md` (this file) for repository-level agent instructions.
- For area-specific guidance, propose additional files like `.github/copilot-instructions.md` or `docs/AGENT-UI.md`.

Safety & privacy
- Never add secrets or credentials to the repo. If a task requires secrets, ask the user how to proceed.

Suggested next agent customizations
- Create a `.github/copilot-instructions.md` to enforce PR style and test expectations.
- Add a small `scripts/run-headless.md` or a `skill` that documents a headless smoke-test procedure.

If any section needs more detail, tell me which area to expand (runtime, UI, tests, CI, or packaging).
