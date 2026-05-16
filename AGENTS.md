# PROJECT KNOWLEDGE BASE

**Generated:** 2026-04-19 15:20 KST
**Commit:** `8122ade`
**Branch:** `main`
**Version:** 2.5.1

## OVERVIEW

`auto-translate` = Minecraft modpack translator. Async Python 3.13+ pipeline + PySide6 GUI. Multi-provider LLM (OpenAI/Anthropic/Google/Ollama/Grok/DeepSeek) via LangChain. Ships Windows `.exe` (PyInstaller).

## STRUCTURE

```
.
├── src/                       # Core translation engine — see src/AGENTS.md
│   ├── pipeline.py            # Orchestrator: TranslationPipeline, PipelineConfig, PipelineResult
│   ├── prompts.py             # LLM prompt templates (KR/JP/CN style rules embedded)
│   ├── handlers/              # Mod-aware extractors — see src/handlers/AGENTS.md
│   ├── parsers/               # File-format parsers — see src/parsers/AGENTS.md
│   ├── llm/, translator/, scanner/, glossary/, validator/, reviewer/, output/, models/, utils/
│   └── assets/vanilla_minecraft_assets/versions/1.21.5/  # ~1MB JSON ref data, NOT code
├── gui/                       # PySide6+qfluentwidgets app — see gui/AGENTS.md
├── tools/                     # bump_version.py, build_vanilla_glossary.py
├── test/modpack/              # KubeJS fixture (NOT a test runner — manual integration)
├── main.py                    # CLI/example entry, NOT prod entrypoint
├── gui_build.spec             # PyInstaller spec → AutoTranslate.exe
└── Makefile                   # `make release v=vX.Y.Z` only
```

## WHERE TO LOOK

| Task | Location |
|------|----------|
| Add new mod handler | `src/handlers/AGENTS.md` |
| Add new file format parser | `src/parsers/AGENTS.md` |
| Change prompts / language rules | `src/prompts.py` |
| Tune batching / concurrency | `src/pipeline.py` (`PipelineConfig`), `src/translator/batch_translator.py` |
| Add LLM provider | `src/llm/client.py` (`LLMProvider` enum + `_create_chat_model`) |
| Fix placeholder corruption (`§`, `%s`, `{x}`, `<tag>`) | `src/translator/placeholder.py` |
| Change validation severity | `src/validator/translation_validator.py` |
| Add GUI screen / step | `gui/views/AGENTS.md` |
| Add background job | `gui/workers/AGENTS.md` |
| Add UI string | `gui/i18n/translations/{ko,en}.json` + `translator.t("key")` |
| Bump version | `make release v=vX.Y.Z` (NEVER hand-edit the 3 version strings) |
| Build Windows exe | `uv run pyinstaller --clean --noconfirm gui_build.spec` |

## PIPELINE

```
ModpackScanner → GlossaryBuilder → handlers.extract() → BatchTranslator
  → PlaceholderProtector(protect→LLM→restore) → Validator → LLMReviewer
  → ResourcePackGenerator / JarModGenerator
```

## CONVENTIONS

- **Python 3.13+ only.** `from __future__ import annotations` everywhere. Full types. Google docstrings.
- **Package manager: `uv`.** Never `pip install` / `python -m venv`. Use `uv sync`, `uv run python ...`, `uv add`.
- **Async-first.** All I/O (file, LLM, HTTP) is `async`. Handlers/parsers expose `async def extract/apply/parse/dump`.
- **Pydantic v2** for data shapes (translation, glossary, validation, config). No raw dicts across module boundaries.
- **Logging: `colorlog`** with module `logger = logging.getLogger(__name__)`. No `print()` in `src/` (CLI-only `print` in `main.py`).
- **Locale code format: `xx_yy` lowercase** (`en_us`, `ko_kr`, `ja_jp`, `zh_cn`, `zh_tw`). Used in paths, glossary filenames, config.
- **Version sync (3 files MUST match):** `pyproject.toml` `version`, `src/__init__.py` `__version__`, `gui/__init__.py` `__version__`. Use `tools/bump_version.py` — do NOT hand-edit.
- **Commit prefixes:** `feat: / fix: / docs: / style: / refactor: / test: / chore:` (per README).
- **Vanilla glossary filename:** `vanilla_glossary_{source_locale}_{target_locale}.json` in `src/glossary/vanilla_glossaries/`. Auto-load by locale pair.
- **Config persistence:** `platformdirs.user_config_dir("minecraft-graph-translator", "mcgt")` — never write near source.

## ANTI-PATTERNS (THIS PROJECT)

- **NEVER** modify `⟦PH1⟧`-style placeholders. They wrap `§` color codes, `%s`/`%1$s` formats, `{name}`, `<tag>`, `\n` during LLM calls. Mismatch → `PlaceholderError` → reject entry.
- **NEVER** translate Korean output with English parens (`경험치 (Experience)`) or square brackets (`[철] [검]`). Hard violations in `src/prompts.py:178-180`.
- **NEVER** deviate from glossary. If glossary maps `Enchanting Table → 마법 부여대`, every occurrence MUST use it. Glossary overrides LLM.
- **NEVER** add test framework, linter, formatter without asking. None intentional — `pyproject.toml` has runtime + `pyinstaller`+`ty`. `pytest` in PyInstaller `excludes`.
- **NEVER** use `pip` or hand-edit `uv.lock`. Use `uv add <pkg>`.
- **NEVER** hand-edit `src/glossary/vanilla_glossaries/*.json` (57k+ lines, generated). Regenerate with `tools/build_vanilla_glossary.py`.
- **NEVER** suppress `PlaceholderError` to "make it pass" — corrupt placeholders silently break game.
- **NEVER** commit `DEPLOYMENT.md`, `RELEASE_GUIDE.md`, `tools/MIGRATION_GUIDE.md` (in `.gitignore` — internal docs).
- **NEVER** `pip install pytest` to "run tests" — `test/modpack/` is **manual fixture**, not unit-test suite. Run `uv run python main.py` against it.
- **No docstring/comment emojis in code files.** README/docs only.

## UNIQUE STYLES

- **Two registry systems** with different conventions (do not unify):
  - `src/handlers/` — manual `registry.register()` ordered by `priority` ClassVar (higher first).
  - `src/parsers/` — auto-registers via `__init_subclass__`, looked up by file extension.
- **Pipeline result mutable across stages.** `regenerate_outputs(result, ...)` and `retry_failed(result)` mutate same `PipelineResult`. Don't copy/freeze mid-pipeline.
- **Separate `__version__` in `src/` and `gui/`** despite one project — both change together via `tools/bump_version.py`.
- **GUI navigation = `QStackedWidget` + central state dict on `MainWindow`**, not router/state lib. Views emit signals, `MainWindow._on_*` slots route.

## COMMANDS

```bash
uv sync                                    # Install deps (Python 3.13 required)
uv run python -m gui                       # Run GUI (preferred entrypoint)
uv run python main.py                      # CLI demo against ./test/modpack
uv run python tools/build_vanilla_glossary.py --source en_us.json --target ko_kr.json
uv run pyinstaller --clean --noconfirm gui_build.spec   # Build Windows exe
make release v=v2.5.2                      # Bump version + tag + push (triggers GH Action)
```

No `make test`, `make lint`, `make fmt` — none configured. CI = `.github/workflows/release.yml` only (build on `v*.*.*` tag).

## NOTES

- **No tests.** None. `test/` is fixture for manual `main.py` runs. Don't pretend.
- **No linter/formatter.** Don't add ruff/black/isort without asking.
- **Windows-first.** `gui_build.spec` produces `.exe`. macOS/Linux dev works (`uv run python -m gui`) but no release artifact.
- **Console window stays open** in built exe (`console=True` in `gui_build.spec`) — intentional for logs.
- **All user-facing strings in GUI** must use `gui/i18n/translator.t("key")`. Do not hard-code KR/EN.