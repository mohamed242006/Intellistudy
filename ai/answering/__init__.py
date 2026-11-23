"""Answer layer: grounded, cited, refusable answers on top of retrieval.

    from ai.answering import AnswerService, OpenAICompatibleClient
    service = AnswerService(retrieval_service, OpenAICompatibleClient("gpt-4o-mini"))
    answer = service.answer("What is a pointcut?", user_id=..., course_id=...)
"""

from ai.answering.context import ContextBuilder
from ai.answering.grounding import GroundingPolicy
from ai.answering.llm import ExtractiveLLM, LLMClient, LLMError, OpenAICompatibleClient, ScriptedLLM
from ai.answering.models import Answer, Citation, ContextBundle, SourceRef
from ai.answering.prompt import PROMPT_VERSION
from ai.answering.refusal import RefusalPolicy
from ai.answering.service import AnswerService

__all__ = [
    "PROMPT_VERSION",
    "Answer",
    "AnswerService",
    "Citation",
    "ContextBuilder",
    "ContextBundle",
    "ExtractiveLLM",
    "GroundingPolicy",
    "LLMClient",
    "LLMError",
    "OpenAICompatibleClient",
    "RefusalPolicy",
    "ScriptedLLM",
    "SourceRef",
]
