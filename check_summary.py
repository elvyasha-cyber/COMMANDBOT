"""Проверка итога двух сессий одного чата. Тестовые сообщения удаляются."""

from datetime import datetime, timezone

from pipelines.config import load_settings
from pipelines.indexing import build_document_store, index_messages, message_to_document
from pipelines.summary import summarize

CHAT_ID = 9003


def sample_messages() -> list:
    moment = datetime(2026, 10, 14, 11, 0, tzinfo=timezone.utc)
    rows = [
        ("dispute", 1, 21, "Игорь", "Давайте по пятницам работать из дома.", 0),
        ("dispute", 2, 22, "Марина", "Нет. По пятницам все должны быть в офисе, иначе стенд никто не смотрит.", 3),
        ("dispute", 3, 23, "Игорь", "Стенд можно смотреть удалённо. Дома в пятницу спокойнее закрывать задачи.", 6),
        ("decision", 4, 24, "Павел", "Релиз переносим на пятницу, я обновляю инструкцию в четверг.", 20),
        ("decision", 5, 25, "Света", "Беру на себя починку оплаты до четверга.", 23),
    ]
    documents = []
    for session_id, message_id, user_id, username, text, minutes in rows:
        documents.append(
            message_to_document(
                chat_id=CHAT_ID,
                message_id=message_id,
                user_id=user_id,
                username=username,
                text=text,
                sent_at=moment.replace(minute=minutes),
                session_id=session_id,
            )
        )
    return documents


def main() -> None:
    settings = load_settings()
    documents = sample_messages()
    store = build_document_store(settings)
    try:
        written = index_messages(documents, settings)
        dispute = summarize(CHAT_ID, "dispute", settings)
        decision = summarize(CHAT_ID, "decision", settings)
        dispute_authors = [item.meta.get("username") for item in dispute["documents"]]
        decision_authors = [item.meta.get("username") for item in decision["documents"]]

        print(f"written={written}")
        print(f"dispute_authors={dispute_authors}")
        print(dispute["summary"])
        print("---")
        print(f"decision_authors={decision_authors}")
        print(decision["summary"])

        if sorted(dispute_authors) != ["Игорь", "Игорь", "Марина"]:
            raise SystemExit("В спор попали не те реплики")
        if sorted(decision_authors) != ["Павел", "Света"]:
            raise SystemExit("В решение попали не те реплики")
        if "Мнение:" not in dispute["summary"]:
            raise SystemExit("В итоге спора нет мнения бота")
        if "Итог:" not in decision["summary"]:
            raise SystemExit("В итоге решений нет финального результата")
    finally:
        store.delete_documents([item.id for item in documents])
        print(f"deleted_check=yes namespace_count={store.count_documents()}")


if __name__ == "__main__":
    main()
