EMS_Duty_Moduls — Modular bot setup

This directory contains a modular rework of the monolithic `EMS_Duty_NAS_251114.py` bot.

Structure:
- core.py — bot bootstrap, dynamic command loader, hotloader
- helpers.py — shared helpers, decorators
- state.py — shared runtime state (duty_log, EMS_PEOPLE, etc.)
- processing.py — duty log processing helpers
- commands/ — individual command modules
  - ping.py, sugo.py, frissites.py, jelen.py, pair_char.py, char_lista.py, heti_top.py, diagnosztika.py

How to run:
- Copy `.env` settings used by the original monolith.
- Start the modular bot: `python -m EMS_Duty_Moduls.core` (or run core.py directly).
- Watchdog: change BOT_FILE in `.env` to the modular entrypoint if you want watchdog to launch this modular bot.

Adding a new command module:
- Create a new file under `commands/` e.g. `mycommand.py`.
- Add a Cog or a @commands.command decorated function.
- At the bottom provide a `setup(bot=None, state=None, helpers=None)` function which registers the cog or command(s) with the bot (e.g., `bot.add_cog(MyCog(bot, state, helpers))`).

Hot-reload:
- The `core` includes a simplistic hotloader which watches `commands/` for file modifications and reloads changed modules.
- This hotloader is simple — if you need production-grade reloading, add watchdog-based implementations.

Watchdog events
----------------
You can trigger a watchdog-managed action (like restart) by writing a JSON event into the `events/` directory. Example payload stored as `events/watchdog_event.json`:

  {"action": "restart", "reason": "module hotfix"}

To help with this, two helper scripts are included:
- `send_watchdog_event.py` — Python script: `python EMS_Duty_Moduls/scripts/send_watchdog_event.py --action restart --reason "hotfix"`
- `send_watchdog_event.ps1` — PowerShell script for Windows.

The watchdog will read the event file and remove it after executing, so the event triggers only once.

Notes:
- The modules created here are a functional skeleton that replicate the main command behavior found in the monolith.
- Not all internal functions (embed parsing, mention mapping, detailed retry logic) were fully ported — they will be ported as needed.

