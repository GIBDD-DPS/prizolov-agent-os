"""Самосовершенствование: самопроверка, уроки, улучшение промптов, новые инструменты."""

from .critic import Critic, Review, revision_request
from .custom_tools import (
    ALLOWED_MODULES,
    UnsafeCodeError,
    build_tool,
    check_code,
    propose_tool_tool,
    run_sandboxed,
)
from .lessons import ExtractedLesson, LessonExtractor, format_lessons
from .prompts import PromptImprover, PromptProposal, prompt_diff

__all__ = [
    "ALLOWED_MODULES",
    "Critic",
    "ExtractedLesson",
    "LessonExtractor",
    "PromptImprover",
    "PromptProposal",
    "Review",
    "UnsafeCodeError",
    "build_tool",
    "check_code",
    "format_lessons",
    "prompt_diff",
    "propose_tool_tool",
    "revision_request",
    "run_sandboxed",
]
