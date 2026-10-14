"""Настройки из .env. Секреты остаются в переменных окружения."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    openai_base_url: str
    openai_model: str
    embedding_model: str
    embedding_dim: int
    pinecone_index: str
    pinecone_namespace: str


def load_settings() -> Settings:
    load_dotenv()
    for name in (
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
        "EMBEDDING_MODEL",
        "EMBEDDING_DIM",
        "PINECONE_API_KEY",
        "PINECONE_INDEX_NAME",
        "PINECONE_NAMESPACE",
    ):
        if not os.getenv(name, "").strip():
            raise RuntimeError(f"В .env не заполнено поле {name}")

    return Settings(
        openai_base_url=os.environ["OPENAI_BASE_URL"],
        openai_model=os.environ["OPENAI_MODEL"],
        embedding_model=os.environ["EMBEDDING_MODEL"],
        embedding_dim=int(os.environ["EMBEDDING_DIM"]),
        pinecone_index=os.environ["PINECONE_INDEX_NAME"],
        pinecone_namespace=os.environ["PINECONE_NAMESPACE"],
    )
