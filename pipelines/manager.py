"""Три пайплайна Haystack из урока. Компоненты между пайплайнами не общие."""

import re

from haystack import Document, Pipeline
from haystack.components.builders import ChatPromptBuilder
from haystack.components.embedders import OpenAIDocumentEmbedder, OpenAITextEmbedder
from haystack.components.generators.chat import OpenAIChatGenerator
from haystack.dataclasses import ChatMessage
from haystack.document_stores.types import DuplicatePolicy
from haystack.utils import Secret
from haystack_integrations.components.retrievers.pinecone import PineconeEmbeddingRetriever

from pipelines.config import Settings, load_settings
from pipelines.indexing import build_document_store

SUMMARY_TEMPLATE = [
    ChatMessage.from_system(
        "Ты участник рабочего чата компании и отвечаешь по-русски, живым языком. "
        "Тема берётся из найденных реплик. Не перескакивай на другую тему. "
        "Если вопрос участника вроде «что думаешь?» или «по этому поводу», "
        "не перечисляй протокол и не пиши, что реплик нет: обсуди эту тему, "
        "скажи своё мнение и предложи несколько конкретных вариантов или рекомендаций, "
        "даже если их не было в переписке дословно. В конце можно задать короткий вопрос. "
        "Если вопрос просит итог сессии, опиши тему и ключевые тезисы. "
        "Если был спор, добавь абзац «Мнение:». "
        "Если договорились о действиях, добавь блок «Итог:» — кто что делает. "
        "В любом итоге добавь рекомендации, как продолжить обсуждение. "
        "Не выдумывай чужие реплики и решения, которых не было."
    ),
    ChatMessage.from_user(
        "Вопрос: {{ question }}\n\n"
        "Найденные реплики:\n"
        "{% for doc in documents %}"
        "- {{ doc.meta['sent_at'] }} — {{ doc.content }}\n"
        "{% endfor %}"
    ),
]


class PipelineManager:
    """Менеджер пайплайнов: индексация, поиск и резюме диалога."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        self.document_store = build_document_store(self.settings)
        self._indexing = self._create_indexing_pipeline()
        self.query_pipeline = self._create_query_pipeline()
        self._summarization = self._create_summarization_pipeline()

    def _text_embedder(self) -> OpenAITextEmbedder:
        return OpenAITextEmbedder(
            api_key=Secret.from_env_var("OPENAI_API_KEY"),
            model=self.settings.embedding_model,
            dimensions=self.settings.embedding_dim,
            api_base_url=self.settings.openai_base_url,
        )

    def _retriever(self, top_k: int) -> PineconeEmbeddingRetriever:
        return PineconeEmbeddingRetriever(document_store=self.document_store, top_k=top_k)

    def _create_indexing_pipeline(self) -> Pipeline:
        """Только эмбеддинг. Запись в Pinecone делает сам менеджер, не пайплайн."""
        pipeline = Pipeline()
        pipeline.add_component(
            "embedder",
            OpenAIDocumentEmbedder(
                api_key=Secret.from_env_var("OPENAI_API_KEY"),
                model=self.settings.embedding_model,
                dimensions=self.settings.embedding_dim,
                api_base_url=self.settings.openai_base_url,
                progress_bar=False,
            ),
        )
        return pipeline

    def _create_query_pipeline(self) -> Pipeline:
        """Query_pipeline: текст становится вектором, ретривер ищет документы."""
        pipeline = Pipeline()
        pipeline.add_component("text_embedder", self._text_embedder())
        pipeline.add_component("retriever", self._retriever(top_k=4))
        pipeline.connect("text_embedder.embedding", "retriever.query_embedding")
        return pipeline

    def _create_summarization_pipeline(self) -> Pipeline:
        """Резюме и ответ на упоминание: поиск, промпт, модель."""
        pipeline = Pipeline()
        pipeline.add_component("text_embedder", self._text_embedder())
        pipeline.add_component("retriever", self._retriever(top_k=4))
        pipeline.add_component(
            "prompt_builder",
            ChatPromptBuilder(template=SUMMARY_TEMPLATE, required_variables=["question", "documents"]),
        )
        pipeline.add_component(
            "llm",
            OpenAIChatGenerator(
                api_key=Secret.from_env_var("OPENAI_API_KEY"),
                model=self.settings.openai_model,
                api_base_url=self.settings.openai_base_url,
            ),
        )
        pipeline.connect("text_embedder.embedding", "retriever.query_embedding")
        pipeline.connect("retriever.documents", "prompt_builder.documents")
        pipeline.connect("prompt_builder.prompt", "llm.messages")
        return pipeline

    def index_documents(self, documents: list[Document]) -> int:
        if not documents:
            return 0
        result = self._indexing.run({"embedder": {"documents": documents}})
        embedded = result["embedder"]["documents"]
        return self.document_store.write_documents(embedded, policy=DuplicatePolicy.OVERWRITE)

    def search(self, text: str, chat_id: int, session_id: str | None = None, top_k: int = 4) -> list[Document]:
        result = self.query_pipeline.run(
            {
                "text_embedder": {"text": text},
                "retriever": {"filters": self._filters(chat_id, session_id), "top_k": top_k},
            }
        )
        return result["retriever"]["documents"]

    def recent_topic(
        self,
        chat_id: int,
        exclude_message_id: int | None = None,
        limit: int = 4,
    ) -> list[str]:
        """Реплики сразу перед вопросом, без предыдущего обращения к боту."""
        documents = self.document_store.filter_documents(filters=self._filters(chat_id))
        documents.sort(key=lambda document: document.meta.get("sent_at", ""))
        if exclude_message_id is not None:
            skip = f"{chat_id}:{exclude_message_id}"
            documents = [document for document in documents if document.id != skip]
        chosen: list[str] = []
        for document in reversed(documents):
            content = document.content or ""
            if re.search(r"@\w+", content):
                break
            chosen.append(content)
            if len(chosen) >= limit:
                break
        chosen.reverse()
        return chosen

    def session_lines(
        self,
        chat_id: int,
        session_id: str,
        exclude_message_id: int | None = None,
    ) -> list[str]:
        """Все реплики сессии слушания, кроме текущего вопроса."""
        documents = self.document_store.filter_documents(filters=self._filters(chat_id, session_id))
        documents.sort(key=lambda document: document.meta.get("sent_at", ""))
        if exclude_message_id is not None:
            skip = f"{chat_id}:{exclude_message_id}"
            documents = [document for document in documents if document.id != skip]
        return [document.content for document in documents if document.content]

    def answer(
        self,
        question: str,
        chat_id: int,
        background: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        search_text = question if not background else f"{background}\nВопрос: {question}"
        top_k = 15 if session_id else 4
        return self._speak(search_text, question, self._filters(chat_id, session_id), top_k=top_k)

    def summarize_session(self, chat_id: int, session_id: str) -> dict:
        found = self._speak(
            "итог обсуждения, спор, решения и действия участников",
            "Подведи итог этой сессии обсуждения.",
            self._filters(chat_id, session_id),
            top_k=20,
        )
        return {"summary": found["answer"], "documents": found["documents"]}

    def _speak(self, search_text: str, question: str, filters: dict, top_k: int) -> dict:
        result = self._summarization.run(
            {
                "text_embedder": {"text": search_text},
                "retriever": {"filters": filters, "top_k": top_k},
                "prompt_builder": {"question": question},
            },
            include_outputs_from={"retriever"},
        )
        return {
            "answer": result["llm"]["replies"][0].text,
            "documents": result["retriever"]["documents"],
        }

    @staticmethod
    def _filters(chat_id: int, session_id: str | None = None) -> dict:
        chat_filter = {"field": "chat_id", "operator": "==", "value": str(chat_id)}
        if not session_id:
            return chat_filter
        return {
            "operator": "AND",
            "conditions": [
                chat_filter,
                {"field": "session_id", "operator": "==", "value": session_id},
            ],
        }
