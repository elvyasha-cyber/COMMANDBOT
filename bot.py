"""Бот командного чата: память в Pinecone, ответ на упоминание, итог сессии."""

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

import telebot

from pipelines.config import load_settings
from pipelines.indexing import message_to_document
from pipelines.manager import PipelineManager

SESSIONS_PATH = Path(__file__).with_name("sessions.json")
MAX_REPLY = 4000


class Sessions:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {}
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self._data = loaded

    def _save(self) -> None:
        self._path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def start(self, chat_id: int) -> str | None:
        key = str(chat_id)
        with self._lock:
            if key in self._data:
                return None
            session_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            self._data[key] = {"session_id": session_id, "count": 0}
            self._save()
            return session_id

    def current(self, chat_id: int) -> str | None:
        with self._lock:
            item = self._data.get(str(chat_id))
            return None if item is None else item["session_id"]

    def mark(self, chat_id: int) -> None:
        with self._lock:
            item = self._data.get(str(chat_id))
            if item is None:
                return
            item["count"] += 1
            self._save()

    def stop(self, chat_id: int) -> dict | None:
        with self._lock:
            item = self._data.pop(str(chat_id), None)
            self._save()
            return item


def author_name(user: telebot.types.User) -> str:
    if user.username:
        return user.username
    name = " ".join(part for part in (user.first_name, user.last_name) if part).strip()
    return name or str(user.id)


def is_ping(message: telebot.types.Message, bot_username: str, bot_id: int) -> bool:
    text = message.text or ""
    if re.search(rf"@{re.escape(bot_username)}\b", text, flags=re.IGNORECASE):
        return True
    reply = message.reply_to_message
    return bool(reply and reply.from_user and reply.from_user.id == bot_id)


def question_text(message: telebot.types.Message, bot_username: str) -> str:
    text = message.text or ""
    return re.sub(rf"@{re.escape(bot_username)}\b", "", text, flags=re.IGNORECASE).strip()


def needs_recent_context(question: str) -> bool:
    """Уточнение или вопрос без своей темы: к нему нужны последние реплики."""
    text = question.strip().lower()
    if text.startswith(("это ", "я про ", "имею в виду", "уточняю", "не про ", "именно ")):
        return True
    if re.search(r"по этому поводу|об этом|на этот сч[её]т", text):
        return True
    if re.match(
        r"^(как ты считаешь|что ты думаешь|что думаешь|как думаешь|а ты как|тво[её] мнение|как считаешь|что скажешь)\b[\s,?!.]*$",
        text,
    ):
        return True
    words = re.findall(r"[а-яёa-z0-9]+", text)
    return len(words) <= 2


def clip(text: str) -> str:
    if len(text) <= MAX_REPLY:
        return text
    return text[: MAX_REPLY - 1] + "…"


def main() -> None:
    load_settings()
    bot = telebot.TeleBot(os.environ["TELEGRAM_BOT_TOKEN"])
    me = bot.get_me()
    sessions = Sessions(SESSIONS_PATH)
    manager = PipelineManager()

    def guard(handler):
        def wrapped(message: telebot.types.Message) -> None:
            try:
                handler(message)
            except Exception as exc:
                print(f"error={type(exc).__name__} chat={message.chat.id}", flush=True)
                bot.reply_to(message, "Не получилось обработать сообщение. Попробуйте ещё раз.")

        return wrapped

    def remember(message: telebot.types.Message) -> None:
        if message.from_user is None or message.from_user.is_bot or not message.text:
            return
        session_id = sessions.current(message.chat.id)
        document = message_to_document(
            chat_id=message.chat.id,
            message_id=message.message_id,
            user_id=message.from_user.id,
            username=author_name(message.from_user),
            text=message.text,
            sent_at=datetime.fromtimestamp(message.date, tz=timezone.utc),
            session_id=session_id,
        )
        manager.index_documents([document])
        if session_id:
            sessions.mark(message.chat.id)
        print(f"indexed chat={message.chat.id} message={message.message_id}", flush=True)

    @bot.message_handler(commands=["start"])
    @guard
    def on_start(message: telebot.types.Message) -> None:
        bot.reply_to(
            message,
            "Я помощник командного чата.\n"
            "/start_listening — начать сессию обсуждения\n"
            "/stop_listening — итог сессии: резюме, а если был спор — ещё и мнение\n"
            "Упомяните меня и задайте вопрос — отвечу по истории этого чата.",
        )

    @bot.message_handler(commands=["start_listening"])
    @guard
    def on_start_listening(message: telebot.types.Message) -> None:
        session_id = sessions.start(message.chat.id)
        if session_id is None:
            bot.reply_to(message, "Сессия уже идёт. Остановить: /stop_listening.")
            return
        print(f"session_start chat={message.chat.id}", flush=True)
        bot.reply_to(
            message,
            "Слушаю этот чат. Сообщения до /stop_listening попадут в итог сессии.",
        )

    @bot.message_handler(commands=["stop_listening"])
    @guard
    def on_stop_listening(message: telebot.types.Message) -> None:
        session = sessions.stop(message.chat.id)
        if session is None:
            bot.reply_to(message, "Слушание не запущено. Начните с /start_listening.")
            return
        if session["count"] == 0:
            bot.reply_to(message, "В этой сессии не было сообщений.")
            return
        bot.send_chat_action(message.chat.id, "typing")
        result = manager.summarize_session(message.chat.id, session["session_id"])
        print(f"session_stop chat={message.chat.id} messages={len(result['documents'])}", flush=True)
        bot.reply_to(message, clip(result["summary"]))

    def should_answer(message: telebot.types.Message) -> bool:
        if is_ping(message, me.username, me.id):
            return True
        if message.chat.type != "private":
            return False
        text = question_text(message, me.username)
        return bool(text) and needs_recent_context(text)

    @bot.message_handler(func=should_answer, content_types=["text"])
    @guard
    def on_ping(message: telebot.types.Message) -> None:
        remember(message)
        question = question_text(message, me.username)
        if not question:
            bot.reply_to(message, "Напишите вопрос вместе с упоминанием.")
            return
        background = None
        session_id = sessions.current(message.chat.id)
        if needs_recent_context(question):
            if session_id:
                lines = manager.session_lines(
                    message.chat.id,
                    session_id,
                    exclude_message_id=message.message_id,
                )
            else:
                lines = manager.recent_topic(
                    message.chat.id,
                    exclude_message_id=message.message_id,
                )
            background = "\n".join(lines)
        bot.send_chat_action(message.chat.id, "typing")
        result = manager.answer(
            question,
            message.chat.id,
            background=background,
            session_id=session_id if needs_recent_context(question) else None,
        )
        print(f"answer chat={message.chat.id} found={len(result['documents'])}", flush=True)
        bot.reply_to(message, clip(result["answer"]))

    @bot.message_handler(content_types=["text"])
    @guard
    def on_text(message: telebot.types.Message) -> None:
        remember(message)

    print(f"bot=@{me.username}", flush=True)
    print("polling", flush=True)
    bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)


if __name__ == "__main__":
    main()
