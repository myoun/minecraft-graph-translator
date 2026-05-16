# gui/ — PySide6 Desktop App

Fluent Design wizard wrapping `src/` translation pipeline. Multi-step `QStackedWidget` flow, `QThread` workers, JSON i18n.

## STRUCTURE

```
gui/
├── __main__.py          # `python -m gui` entry
├── main.py              # logging + theme setup, QApplication boot
├── app.py               # MainWindow: QStackedWidget nav + central state dict + signal routing
├── config.py            # AppConfig: persistent JSON via platformdirs
├── views/               # wizard steps — see views/AGENTS.md
├── widgets/             # ModpackTreeWidget (paginated), ProgressCard, ScanStatsCard, dialogs
├── workers/             # QThread + asyncio integration — see workers/AGENTS.md
├── i18n/                # Custom JSON translator (NOT QTranslator/gettext)
│   └── translations/{ko,en}.json
└── styles/app.qss       # Single QSS, loaded at startup
```

## NAVIGATION MODEL

- `MainWindow` owns `QStackedWidget` with all wizard views.
- `MainWindow.state: dict` is the **single source of truth** between views (modpack path, scan result, settings, translation result).
- Views emit Qt signals (`modpackSelected`, `settingsConfirmed`, `cancelled`, ...) → `MainWindow._on_*` slots mutate state and call `self._go_to_step(n)`.
- **No router library, no Redux-style store.** Plain dict + signals.

## THREADING

- **All blocking work runs in `QThread` workers** (see `workers/AGENTS.md`). Never `await` from a view slot — views are pure-sync GUI code.
- **`TranslationWorker` runs an asyncio event loop inside `QThread.run()`** to drive `TranslationPipeline.run(...)`. This is the sole bridge between Qt and `src/`'s async world.
- **Throttle progress updates** to ~100ms intervals to avoid repaint storms with hundreds of mods.

## I18N

- `gui.i18n.translator` is a **module-level singleton** with `t(key, **fmt)` and `set_language(lang_code)`.
- All user-facing strings: `from gui.i18n import translator; label.setText(translator.t("welcome.title"))`.
- Adding a string: add the key to **both** `ko.json` and `en.json`. Korean first (default), then English.
- On language change, `MainWindow._on_language_changed()` rebuilds all views in place — views must read text via `t()` in their constructor and again on `retranslate()` if they cache.

## CONFIG PERSISTENCE

`AppConfig` (in `config.py`) — dot-notation accessor (`cfg.get("llm.model")`, `cfg.set("llm.temperature", 0.3)`). Persists to:

- Linux/macOS: `~/.config/mcgt/minecraft-graph-translator/config.json`
- Windows: `%LOCALAPPDATA%\mcgt\minecraft-graph-translator\config.json`

Defaults are merged on load — adding a new key with a default in `AppConfig._DEFAULTS` is safe for existing users.

## ANTI-PATTERNS

- **Importing `src.*` deeply** (`from src.translator.batch_translator import ...`) — use `from src import ...` (the public API).
- **`asyncio.run(...)` from a view slot** — blocks the GUI thread. Always go through a `QThread` worker.
- **Hardcoded UI strings** in any language — must go through `translator.t("...")`. Caught easily in PR review.
- **Reading `AppConfig` from inside a worker** — pass values through the worker's `__init__`. Workers must be self-contained for thread safety.
- **Adding a state-management library** (Redux, MobX, etc.) — the dict-on-MainWindow pattern is intentional. 8 views don't need a store.
- **Touching Qt widgets from worker threads** — emit signals; let the main thread update the UI.
- **Console removal in PyInstaller spec** — `console=True` is intentional in `gui_build.spec` for visible logs in the built `.exe`.
