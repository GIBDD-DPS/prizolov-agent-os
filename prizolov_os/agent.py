from typing import Optional, Dict, Any, List, Tuple


class Agent:
    """Базовый класс для ИИ-агента с поддержкой ограничений."""
    
    def __init__(
        self, 
        role: str, 
        constraints: Optional[Dict[str, Any]] = None
    ) -> None:
        self.role: str = role
        self.constraints: Dict[str, Any] = constraints or {}
        self.memory: List[Tuple[str, str]] = []
    
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
        if not isinstance(input_data, str):
            raise TypeError(
                f"Expected input_data to be str, got {type(input_data).__name__}"
            )
        
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
        validated_input = self.apply_constraints(input_data)
        result = f"[{self.role}] Обработано: {validated_input}"
        self.memory.append((validated_input, result))
        return result
    
    def get_memory(self) -> List[Tuple[str, str]]:
        """Возвращает историю выполненных задач."""
        return self.memory.copy()
    
    def clear_memory(self) -> None:
        """Очищает память агента."""
        self.memory = []
