from typing import List, Tuple


class Memory:
    """Простая память в виде списка кортежей (запрос, ответ)."""
    
    def __init__(self) -> None:
        self.data: List[Tuple[str, str]] = []
    
    def store(self, query: str, response: str) -> None:
        """Сохраняет пару запрос-ответ в память."""
        if not isinstance(query, str) or not isinstance(response, str):
            raise TypeError("Query and response must be strings")
        self.data.append((query.strip(), response.strip()))
    
    def retrieve(self, query: str) -> str:
        """
        Безопасный поиск по памяти.
        Возвращает пустую строку, если запрос некорректен или не найдено совпадений.
        """
        if not query or not isinstance(query, str):
            return ""
        
        keywords = query.strip().split()
        if not keywords:
            return ""
        
        first_keyword = keywords[0].lower()
        results = [
            response for stored_query, response in self.data 
            if first_keyword in stored_query.lower()
        ]
        
        return " ".join(results)
    
    def clear(self) -> None:
        """Очищает всю память."""
        self.data = []
    
    def __len__(self) -> int:
        """Возвращает количество записей в памяти."""
        return len(self.data)
