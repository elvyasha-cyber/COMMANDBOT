"""Короткий пайплайн: промпт → модель через proxyapi.ru."""

import os

from dotenv import load_dotenv
from haystack import Pipeline
from haystack.components.builders import ChatPromptBuilder
from haystack.components.generators.chat import OpenAIChatGenerator
from haystack.dataclasses import ChatMessage
from haystack.utils import Secret

load_dotenv()

prompt_builder = ChatPromptBuilder(
    template=[
        ChatMessage.from_system(
            "Ты отвечаешь по-русски, одним коротким предложением."
        ),
        ChatMessage.from_user("{{query}}"),
    ],
    required_variables=["query"],
)

generator = OpenAIChatGenerator(
    api_key=Secret.from_env_var("OPENAI_API_KEY"),
    model=os.environ["OPENAI_MODEL"],
    api_base_url=os.environ["OPENAI_BASE_URL"],
)

pipeline = Pipeline()
pipeline.add_component("prompt_builder", prompt_builder)
pipeline.add_component("llm", generator)
pipeline.connect("prompt_builder.prompt", "llm.messages")

result = pipeline.run(
    {
        "prompt_builder": {
            "query": "Ответь, что пайплайн Haystack до модели дошёл.",
        }
    }
)

reply = result["llm"]["replies"][0]
print(reply.text)
