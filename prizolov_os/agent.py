from typing import Optional, Dict, Any, List


class Agent:
    """Базовый класс для ИИ-агента с поддержкой ограничений."""
    
    def __init__(
        self, 
        role: str, 
        constraints: Optional[Dict[str, Any]] = None
    ):
        self.role = role
        self.constraints = constraints or {}
        self.memory = []
    
    def apply_constraints(self, input_data: str) -> str:
        """
        Применяет ограничения к входным данным.
        
        Args:
            input_data: Входная строка для проверки
            
        Returns:
            Проверенную строку
            
        Raises:
            TypeError: Если input_data не строка
            ValueError: Если найдены запрещённые токены
        """
        # ✅ Валидация типа входных данных
        if not isinstance(input_data, str):
            raise TypeError(
                f"Expected input_data to be str, got {type(input_data).__name__}"
            )
        
        # Проверка на запрещённые токены
        if "forbidden_tokens" in self.constraints:
            for token in self.constraints["forbidden_tokens"]:
                if token in input_data:
                    raise ValueError(
                        f"Forbidden token '{token}' found in input data"
                    )
        
        return input_data
    
    def execute(self, input_data: str) -> str:
        """
        Выполняет задачу агента.
        
        Args:
            input_data: Входные данные для обработки
            
        Returns:
            Результат выполнения
        """
        # Применяем ограничения перед выполнением
        validated_input = self.apply_constraints(input_data)
        
        # Базовая логика выполнения (можно расширить)
        result = f"[{self.role}] Обработано: {validated_input}"
        
        # Сохраняем в память
        self.memory.append((validated_input, result))
        
        return result
    
    def get_memory(self) -> List[tuple]:
        """Возвращает историю выполненных задач."""
        return self.memory.copy()
    
    def clear_memory(self) -> None:
        """Очищает память агента."""
        self.memory = []