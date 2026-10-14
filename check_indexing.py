"""Проверка: одно сообщение пишется в namespace бота и затем удаляется."""

from datetime import datetime, timezone

from pipelines.config import load_settings
from pipelines.indexing import build_document_store, index_messages, message_to_document

CHECK_CHAT_ID = 0
CHECK_MESSAGE_ID = 1


def main() -> None:
    settings = load_settings()
    store = build_document_store(settings)
    before = store.count_documents()
    stats = store._index.describe_index_stats()
    dimension = stats.get("dimension")

    print(f"index={settings.pinecone_index}")
    print(f"namespace={settings.pinecone_namespace}")
    print(f"dimension={dimension}")
    print("namespaces:")
    for name, info in stats.get("namespaces", {}).items():
        print(f"  {name}: {info.get('vector_count')}")

    if dimension != settings.embedding_dim:
        raise SystemExit(
            f"Размерность индекса {dimension} не совпадает с EMBEDDING_DIM={settings.embedding_dim}"
        )

    document = message_to_document(
        chat_id=CHECK_CHAT_ID,
        message_id=CHECK_MESSAGE_ID,
        user_id=1,
        username="Анна",
        text="На стенде проверим, что сообщение команды сохраняется в памяти чата.",
        sent_at=datetime.now(timezone.utc),
    )
    written = index_messages([document], settings)
    found = store.filter_documents(
        filters={"field": "message_id", "operator": "==", "value": str(CHECK_MESSAGE_ID)}
    )
    matched = [item for item in found if item.id == document.id]

    print(f"written={written}")
    print(f"namespace_count={store.count_documents()} (before {before})")
    if not matched:
        raise SystemExit("Тестовое сообщение не найдено в namespace commandbot")

    print(f"stored={matched[0].content}")
    print(f"author={matched[0].meta.get('username')} sent_at={matched[0].meta.get('sent_at')}")

    store.delete_documents([document.id])
    print(f"deleted_check=yes namespace_count={store.count_documents()}")


if __name__ == "__main__":
    main()
