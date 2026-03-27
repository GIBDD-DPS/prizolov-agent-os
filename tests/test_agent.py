# tests/test_agent.py
"""Тесты для модуля Agent."""

import pytest
from prizolov_os.agent import Agent


class TestAgentBasic:
    """Базовые тесты агента."""
    
    def test_agent_creation(self):
        """Тест создания агента."""
        agent = Agent(role="test")
        assert agent.role == "test"
        assert agent.constraints == {}
        assert agent.memory == []
    
    def test_agent_with_constraints(self):
        """Тест создания агента с ограничениями."""
        constraints = {"forbidden_tokens": ["bad", "evil"]}
        agent = Agent(role="secure", constraints=constraints)
        assert agent.constraints == constraints
    
    def test_agent_execute_basic(self):
        """Тест базового выполнения задачи."""
        agent = Agent(role="test")
        result = agent.execute("hello")
        assert "[test]" in result
        assert "hello" in result
    
    def test_agent_memory_stores(self):
        """Тест сохранения в память."""
        agent = Agent(role="test")
        agent.execute("task 1")
        agent.execute("task 2")
        assert len(agent.get_memory()) == 2
    
    def test_agent_memory_clear(self):
        """Тест очистки памяти."""
        agent = Agent(role="test")
        agent.execute("task 1")
        agent.clear_memory()
        assert len(agent.get_memory()) == 0


class TestAgentConstraints:
    """Тесты ограничений агента."""
    
    def test_apply_constraints_valid_input(self):
        """Тест валидного ввода."""
        agent = Agent(role="test")
        result = agent.apply_constraints("normal text")
        assert result == "normal text"
    
    def test_apply_constraints_none_input(self):
        """Тест None ввода - должен вызвать TypeError."""
        agent = Agent(role="test")
        with pytest.raises(TypeError) as exc_info:
            agent.apply_constraints(None)
        assert "Expected input_data to be str" in str(exc_info.value)
    
    def test_apply_constraints_int_input(self):
        """Тест числового ввода - должен вызвать TypeError."""
        agent = Agent(role="test")
        with pytest.raises(TypeError) as exc_info:
            agent.apply_constraints(123)
        assert "Expected input_data to be str" in str(exc_info.value)
    
    def test_apply_constraints_dict_input(self):
        """Тест dict ввода - должен вызвать TypeError."""
        agent = Agent(role="test")
        with pytest.raises(TypeError) as exc_info:
            agent.apply_constraints({"key": "value"})
        assert "Expected input_data to be str" in str(exc_info.value)
    
    def test_apply_constraints_forbidden_token(self):
        """Тест запрещённого токена - должен вызвать ValueError."""
        agent = Agent(role="secure", constraints={"forbidden_tokens": ["bad"]})
        with pytest.raises(ValueError) as exc_info:
            agent.apply_constraints("this is bad input")
        assert "Forbidden token 'bad'" in str(exc_info.value)
    
    def test_apply_constraints_multiple_forbidden_tokens(self):
        """Тест нескольких запрещённых токенов."""
        agent = Agent(role="secure", constraints={"forbidden_tokens": ["bad", "evil"]})
        with pytest.raises(ValueError):
            agent.apply_constraints("this is evil")
    
    def test_apply_constraints_empty_string(self):
        """Тест пустой строки - должен пройти."""
        agent = Agent(role="test")
        result = agent.apply_constraints("")
        assert result == ""
    
    def test_execute_with_forbidden_token(self):
        """Тест execute с запрещённым токеном."""
        agent = Agent(role="secure", constraints={"forbidden_tokens": ["stop"]})
        with pytest.raises(ValueError):
            agent.execute("please stop")


class TestAgentEdgeCases:
    """Тесты краевых случаев."""
    
    def test_agent_role_special_characters(self):
       Отлично! Шаг 7 выполнен ✅

Переходим к **Шагу 8: Расширение тестового покрытия**.

---

## 🔹 ШАГ 8: Написание полноценных тестов для всех модулей

### ❓ Что нужно сделать?
Расширить тесты так, чтобы они покрывали:
- ✅ Все основные функции каждого модуля
- ✅ Граничные случаи (пустые строки, `None`, некорректные типы)
- ✅ Обработку исключений
- ✅ Интеграционные сценарии

Текущие тесты покрывают только базовый случай. Нужно добавить тесты на ошибки и граничные условия.

### 🔍 Где искать?
1. Файл: `tests/test_agent.py` (расширить)
2. Файл: `tests/test_memory.py` (создать новый)
3. Файл: `tests/test_kernel.py` (создать новый)
4. Файл: `tests/test_orchestrator.py` (создать новый)
5. Файл: `pytest.ini` (создать конфигурацию)

### 🛠 Как исправить?

---

#### Часть 1: Создайте `pytest.ini` в корне проекта

```ini
# pytest.ini
[pytest]
testpaths = tests
python_files = test_*.py
python_functions = test_*
python_classes = Test*
addopts = -v --tb=short --cov=prizolov_os --cov-report=term-missing
filterwarnings =
    ignore::DeprecationWarning
