"""Background worker for translation pipeline."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, Signal

if TYPE_CHECKING:
    from src import (
        CancelCheck,
        LanguageFilePair,
        PipelineResult,
        ProgressCallback,
        ProgressStats,
    )

logger = logging.getLogger(__name__)


class TranslationWorker(QThread):
    """Background worker for running translation pipeline.

    Runs the translation pipeline in a separate thread with progress updates.
    """

    # Signals
    progressUpdate = Signal(str, int, int, dict)  # message, current, total, stats
    translationComplete = Signal(object)  # PipelineResult
    translationError = Signal(str)  # error message
    translationCancelled = Signal()

    def __init__(
        self,
        modpack_path: Path,
        output_path: Path,
        selected_files: list[LanguageFilePair],
        config: dict[str, object],
        previous_result: PipelineResult | None = None,
    ) -> None:
        """Initialize translation worker.

        Args:
            modpack_path: Path to modpack
            output_path: Output directory
            selected_files: Selected files to translate
            config: Pipeline configuration
            previous_result: Previous pipeline result for retry
        """
        super().__init__()
        self.modpack_path = modpack_path
        self.output_path = output_path
        self.selected_files = selected_files
        self.config = config
        self.previous_result = previous_result
        self._is_cancelled = False
        self._last_update_time = 0.0
        self._update_throttle = 0.0  # No throttle - always emit for batch progress

    def _config_str(self, key: str, default: str = "") -> str:
        value = self.config.get(key, default)
        return value if isinstance(value, str) else default

    def _config_optional_str(self, key: str) -> str | None:
        value = self.config.get(key)
        return value if isinstance(value, str) and value else None

    def _config_int(self, key: str, default: int) -> int:
        value = self.config.get(key, default)
        if isinstance(value, int | float | str):
            return int(value)
        return default

    def _config_float(self, key: str, default: float) -> float:
        value = self.config.get(key, default)
        if isinstance(value, int | float | str):
            return float(value)
        return default

    def run(self) -> None:
        """Run the translation pipeline."""
        try:
            from src import LLMProvider, PipelineConfig, TranslationPipeline

            logger.info("Starting translation: %d files", len(self.selected_files))

            # Create pipeline config
            rpm = self._config_int("requests_per_minute", 0)
            tpm = self._config_int("tokens_per_minute", 0)
            pipeline_config = PipelineConfig(
                source_locale=self._config_str("source_locale", "en_us"),
                target_locale=self._config_str("target_locale", "ko_kr"),
                llm_provider=LLMProvider[
                    self._config_str("llm_provider", "ollama").upper()
                ],
                llm_model=self._config_str("llm_model", "qwen2.5:14b"),
                llm_temperature=self._config_float("llm_temperature", 0.1),
                llm_base_url=self._config_optional_str("llm_base_url"),
                llm_api_key=self._config_optional_str("llm_api_key"),
                max_concurrent=self._config_int("max_concurrent", 15),
                batch_size=self._config_int("batch_size", 30),
                requests_per_minute=rpm if rpm > 0 else None,  # 0 = no limit
                tokens_per_minute=tpm if tpm > 0 else None,  # 0 = no limit
                skip_glossary=bool(self.config.get("skip_glossary", False)),
                skip_review=bool(self.config.get("skip_review", False)),
                save_glossary=bool(self.config.get("save_glossary", True)),
            )

            # Create pipeline with progress callback
            progress_callback: ProgressCallback = self._emit_progress_throttled

            def cancel_check() -> bool:
                return self._is_cancelled

            cancel_check_callback: CancelCheck = cancel_check

            pipeline = TranslationPipeline(
                pipeline_config,
                progress_callback=progress_callback,
                cancel_check=cancel_check_callback,
            )

            # Run pipeline in event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                if self.previous_result:
                    # Retry mode
                    logger.info("Retrying failed tasks from previous result")
                    # First retry failed
                    result = loop.run_until_complete(
                        pipeline.retry_failed(self.previous_result)
                    )
                    # Then regenerate outputs
                    result = loop.run_until_complete(
                        pipeline.regenerate_outputs(
                            result,
                            self.output_path,
                            self.modpack_path,
                        )
                    )
                else:
                    # Normal run mode
                    result = loop.run_until_complete(
                        pipeline.run(
                            self.modpack_path,
                            self.output_path,
                            selected_files=self.selected_files,
                        )
                    )

                if self._is_cancelled:
                    self.translationCancelled.emit()
                    return

                self.translationComplete.emit(result)
                logger.info(
                    "Translation complete: %d/%d successful",
                    result.translated_entries,
                    result.total_entries,
                )

            finally:
                loop.close()

        except Exception as e:
            logger.exception("Translation error: %s", e)
            self.translationError.emit(str(e))

    def _emit_progress_throttled(
        self,
        message: str,
        current: int,
        total: int,
        stats: ProgressStats | None = None,
    ) -> None:
        """Emit progress update with throttling.

        Args:
            message: Progress message
            current: Current progress
            total: Total items
            stats: Additional statistics
        """
        logger.debug(
            "Received progress: %s (%d/%d) stats=%s", message, current, total, stats
        )
        now = time.time()
        if now - self._last_update_time >= self._update_throttle:
            logger.info("Emitting progress: %s (%d/%d)", message, current, total)
            self.progressUpdate.emit(message, current, total, dict(stats or {}))
            self._last_update_time = now
        else:
            logger.debug("Throttled (%.2fs since last)", now - self._last_update_time)

    def cancel(self) -> None:
        """Cancel the translation operation."""
        self._is_cancelled = True
        logger.info("Translation worker cancelled")
