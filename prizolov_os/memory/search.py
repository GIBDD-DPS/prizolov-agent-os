"""Простой поиск по ключевым словам с грубым учётом русской морфологии."""

import re
from typing import Iterable, List, Set, Tuple, TypeVar

T = TypeVar("T")
_WORD = re.compile(r"[\w-]+", re.UNICODE)
STEM_LENGTH = 5


def stems(text: str) -> Set[str]:
    """Основы слов: первые 5 символов слов от 3 букв ('золото', 'золота' -> 'золот')."""
    return {w[:STEM_LENGTH] for w in _WORD.findall(text.lower()) if len(w) >= 3}


def keyword_score(query: str, text: str) -> int:
    """Сколько основ слов запроса встречается в тексте."""
    return len(stems(query) & stems(text))


def rank(query: str, items: Iterable[Tuple[T, str]], limit: int) -> List[T]:
    """Лучшие items по совпадению с запросом; при равенстве - более поздние."""
    scored = [(keyword_score(query, text), i, item) for i, (item, text) in enumerate(items)]
    scored = [s for s in scored if s[0] > 0]
    scored.sort(key=lambda s: (-s[0], -s[1]))
    return [item for _, _, item in scored[:limit]]
