import asyncio
import importlib, sys
from pathlib import Path
import logging

logger = logging.getLogger("EMS_DUTY_HOTLOADER")


def _reload_module_for_path(p: Path):
    mod_name = f"EMS_Duty_Moduls.commands.{p.stem}"
    try:
        if mod_name in sys.modules:
            importlib.reload(sys.modules[mod_name])
            logger.info(f"Reloaded: {mod_name}")
        else:
            importlib.import_module(mod_name)
            logger.info(f"Loaded: {mod_name}")
    except Exception as e:
        logger.exception(f"Hotloader failed for {mod_name}: {e}")


async def watch_and_reload(commands_dir: Path, interval: int = 5):
    """Prefer watchdog event-based watching, fallback to polling.

    If the `watchdog` package is installed the function returns quickly after
    creating an async task for the event observer; otherwise it uses polling.
    """
    try:
        from watchdog.observers import Observer
        from watchdog.events import PatternMatchingEventHandler

        class _Handler(PatternMatchingEventHandler):
            patterns = ["*.py"]

            def on_modified(self, event):
                try:
                    p = Path(event.src_path)
                    logger.info("[hotloader] File modified: %s", p)
                    _reload_module_for_path(p)
                except Exception:
                    logger.exception("Hotloader event error")

            def on_created(self, event):
                try:
                    p = Path(event.src_path)
                    logger.info("[hotloader] File created: %s", p)
                    _reload_module_for_path(p)
                except Exception:
                    logger.exception("Hotloader event error")

        observer = Observer()
        handler = _Handler()
        observer.schedule(handler, str(commands_dir), recursive=False)
        observer.daemon = True
        observer.start()

        # Keep running to let observer process events
        while True:
            await asyncio.sleep(interval)

    except Exception:
        # Fallback to old polling-based watcher
        logger.info("watchdog package not found or failed — falling back to polling hotloader")
        last_ts = {}
        while True:
            for p in commands_dir.glob("*.py"):
                if p.name.startswith("__"):
                    continue
                ts = p.stat().st_mtime
                key = str(p)
                if key not in last_ts:
                    last_ts[key] = ts
                    continue
                if last_ts.get(key) != ts:
                    _reload_module_for_path(p)
                    last_ts[key] = ts
            await asyncio.sleep(interval)
