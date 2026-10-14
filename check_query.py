"""Проверка ответа по репликам одного чата. Тестовые сообщения удаляются."""

from datetime import datetime, timezone

from pipelines.config import load_settings
from pipelines.indexing import build_document_store, index_messages, message_to_document
from pipelines.query import ask

CHAT_ID = 9001
OTHER_CHAT_ID = 9002


def sample_messages() -> list:
    moment = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)
    rows = [
        (CHAT_ID, 1, 11, "Игорь", "Предлагаю перенести релиз на пятницу: на стенде падает оплата.", 0),
        (CHAT_ID, 2, 12, "Марина", "Согласна с Игорем. До пятницы починим оплату и выпустим.", 5),
        (CHAT_ID, 3, 13, "Павел", "Тогда в четверг обновлю инструкцию для поддержки.", 7),
        (OTHER_CHAT_ID, 1, 14, "Олег", "Я в отпуск в Сочи со следующей недели.", 10),
    ]
    documents = []
    for chat_id, message_id, user_id, username, text, minutes in rows:
        sent_at = moment.replace(minute=minutes)
        documents.append(
            message_to_document(
                chat_id=chat_id,
                message_id=message_id,
                user_id=user_id,
                username=username,
                text=text,
                sent_at=sent_at,
            )
        )
    return documents


def main() -> None:
    settings = load_settings()
    documents = sample_messages()
    store = build_document_store(settings)
    try:
        written = index_messages(documents, settings)
        result = ask("Что решили по релизу?", CHAT_ID, settings)
        authors = [item.meta.get("username") for item in result["documents"]]
        chat_ids = {item.meta.get("chat_id") for item in result["documents"]}
        print(f"written={written}")
        print(f"retrieved={authors}")
        print(f"chat_ids={sorted(chat_ids)}")
        print(result["answer"])
        if "Олег" in authors or str(OTHER_CHAT_ID) in chat_ids:
            raise SystemExit("В ответ попал чужой чат")
        if not {"Игорь", "Марина", "Павел"}.issubset(set(authors)):
            raise SystemExit("Не все реплики нужного чата нашлись")
    finally:
        store.delete_documents([item.id for item in documents])
        print(f"deleted_check=yes namespace_count={store.count_documents()}")


if __name__ == "__main__":
    main()
