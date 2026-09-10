# Herdr Session Titles

A fast, zero-dependency [Herdr](https://herdr.dev) plugin that automatically discovers and syncs real session titles and task context for **Devin**, **Cursor**, **Antigravity (Agy)**, **Kiro**, and **Claude Code** into your Herdr sidebar and tabs.

---

## The Problem

By default, Herdr's sidebar often labels agents generically as `agent`, `devin`, `cursor`, or shows raw terminal commands (`agy --dangerously-skip-permissions...`). 

When running 5–10 agent sessions across multiple workspaces, it is impossible to know what each agent is actually doing without switching to its pane.

## The Solution

**Herdr Session Titles** automatically inspects each agent's local state to extract the real task:
- **Devin:** Reads the local SQLite database (`~/.local/share/devin/cli/sessions.db`) and lock files to resolve live session titles and `/rename-session` commands.
- **Antigravity (Agy):** Reads session annotations and transcripts, automatically cleaning prompts and stripping leading image/screenshot paths.
- **Kiro:** Resolves session IDs from lock files and JSON session stores.
- **Cursor & Claude:** Resolves terminal titles and conversation topics.
- **Non-agent panes:** Formats clean context labels (`<agent> · <project>`).

---

## Key Highlights

- ⚡ **Blazing Fast (Direct Unix Socket):** Speaks directly to Herdr's local Unix socket (`session.snapshot`) with **zero subprocess forks**. A full sync across 15+ panes completes in **~1.2 ms**.
- 🔋 **Zero Battery Drain:** Zero polling subprocesses; sleeps cleanly between checks.
- 📦 **Zero External Dependencies:** Built entirely with Python 3's standard library (`socket`, `json`, `sqlite3`, `re`). No compilation, no `pip install`, and no API keys required.
- 🗂️ **Sidebar & Optional Tab Sync:** Populates your `$session` and `$location` sidebar tokens, with optional support for renaming the bottom tab bar (`--sync-tabs`).

---

## Quick Start

### Installation

```bash
herdr plugin install wxomi/herdr-session-titles
```

*(Or link locally during development)*:
```bash
herdr plugin link /path/to/herdr-session-titles
```

### Herdr Configuration

In your `~/.config/herdr/config.toml`, configure your sidebar to show the `$session` and `$location` tokens:

```toml
[ui.sidebar.agents]
row_gap = 0
rows = [
  ["state_icon", { token = "$session", bold = true }],
  [{ token = "$location", dim = true }],
]
```

---

## Configuration Options

The plugin can be configured via environment variables or flags in `herdr-plugin.toml`:

| Environment Variable | Default | Description |
| :--- | :--- | :--- |
| `HERDR_SESSION_TITLES_INTERVAL` | `2` | Polling interval in seconds (default: 2s). |
| `HERDR_SESSION_TITLES_SYNC_TABS` | `false` | Set to `true` (or pass `--sync-tabs`) to also rename the bottom tab bar with the clean task title. |
| `HERDR_SOCKET_PATH` | `~/.config/herdr/herdr.sock` | Path to the Herdr Unix domain socket. |

---

## Testing

Run the included unit test suite:

```bash
python3 -m unittest test_sync_titles.py
```

---

## License

MIT
