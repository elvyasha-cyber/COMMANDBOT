"""Документы командного чата и хранилище Pinecone."""

from datetime import datetime

from haystack import Document
from haystack.utils import Secret
from haystack_integrations.document_stores.pinecone import PineconeDocumentStore

from pipelines.config import Settings, load_settings


def build_document_store(settings: Settings | None = None) -> PineconeDocumentStore:
    settings = settings or load_settings()
    return PineconeDocumentStore(
        api_key=Secret.from_env_var("PINECONE_API_KEY"),
        index=settings.pinecone_index,
        namespace=settings.pinecone_namespace,
        dimension=settings.embedding_dim,
        metric="cosine",
        show_progress=False,
    )


def message_to_document(
    *,
    chat_id: int,
    message_id: int,
    user_id: int,
    username: str,
    text: str,
    sent_at: datetime,
    session_id: str | None = None,
) -> Document:
    """Сообщение чата с метаданными автора. Идентификаторы хранятся строками: у групп Telegram они отрицательные."""
    meta = {
        "chat_id": str(chat_id),
        "message_id": str(message_id),
        "user_id": str(user_id),
        "username": username,
        "sent_at": sent_at.isoformat(timespec="seconds"),
        "source": "team-chat",
    }
    if session_id:
        meta["session_id"] = session_id
    return Document(id=f"{chat_id}:{message_id}", content=f"{username}: {text}", meta=meta)


def index_messages(documents: list[Document], settings: Settings | None = None) -> int:
    from pipelines.manager import PipelineManager

    return PipelineManager(settings).index_documents(documents)
