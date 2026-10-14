"""Поиск и ответ на упоминание. Сам пайплайн собран в PipelineManager."""

from pipelines.config import Settings
from pipelines.manager import PipelineManager


def ask(
    question: str,
    chat_id: int,
    settings: Settings | None = None,
    background: str | None = None,
) -> dict:
    return PipelineManager(settings).answer(question, chat_id, background=background)
