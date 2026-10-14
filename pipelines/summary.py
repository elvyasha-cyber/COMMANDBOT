"""Итог сессии. Пайплайн резюмирования собран в PipelineManager."""

from pipelines.config import Settings
from pipelines.manager import PipelineManager


def summarize(chat_id: int, session_id: str, settings: Settings | None = None) -> dict:
    return PipelineManager(settings).summarize_session(chat_id, session_id)
