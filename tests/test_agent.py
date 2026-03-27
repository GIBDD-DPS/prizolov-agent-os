"""Тесты для модуля Agent."""

import pytest
from prizolov_os.agent import Agent


class TestAgentInit:
    """Тесты инициализации агента."""
    
    def test_agent_create_with_role(self):
        """Создание агента с ролью."""
        agent = Agent(role="test")
        assert agent.role == "test"
        assert agent.constraints == {}
        assert agent.memory == []
    
    def test_agent_create_with_constraints(self):
        """Создание агента с ограничениями."""
        constraints = {"forbidden_tokens": ["bad", "evil"]}
        agent = Agent(role="secure", constraints=constraints)
        assert agent.constraints == constraints
    
    def test_agent_create_without_constraints(self):
        """Создание агента без ограничений (должно быть {})."""
        agent = Agent(role="test")
        assert agent.constraints == {}


class TestAgentApplyConstraints:
    """Тесты метода apply_constraints."""
    
    def test_apply_constraints_valid_input(self):
        """Валидный вход без запрещённых токенов."""
        agent = Agent(role="test")
        result = agent.apply_constraints("hello world")
        assert result == "hello world"
    
    def test_apply_constraints_none_input(self):
        """None должен вызывать TypeError."""
        agent = Agent(role="test")
        with pytest.raises(TypeError, match="Expected input_data to be str"):
            agent.apply_constraints(None)
    
    def test_apply_constraints_int_input(self):
        """Число должно вызывать TypeError."""
        agent = Agent(role="test")
        with pytest.raises(TypeError, match="Expected input_data to be str"):
            agent.apply_constraints(123)
    
    def test_apply_constraints_list_input(self):
        """Список должен вызывать TypeError."""
        agent = Agent(role="test")
        with pytest.raises(TypeError, match="Expected input_data to be str"):
            agent.apply_constraints(["hello"])
    
    def test_apply_constraints_forbidden_token(self):
        """Запрещённый токен должен вызывать ValueError."""
        agent = Agent(role="secure", constraints={"forbidden_tokens": ["bad"]})
        with pytest.raises(ValueError, match="Forbidden token 'bad'"):
            agent.apply_constraints("this is bad input")
    
    def test_apply_constraints_multiple_forbidden_tokens(self):
        """Несколько запрещённых токенов."""
        agent = Agent(
            role="secure",
            constraints={"forbidden_tokens": ["bad", "evil", "hate"]}
        )
        with pytest.raises(ValueError):
            agent.apply_constraints("evil and hate are bad")
    
    def test_apply_constraints_empty_string(self):
        """Пустая строка должна проходить (если нет ограничений)."""
        agent = Agent(role="test")
        result = agent.apply_constraints("")
        assert result == ""


class TestAgentExecute:
    """Тесты метода execute."""
    
    def test_execute_basic(self):
        """Базовое выполнение."""
        agent = Agent(role="test")
        result = agent.execute("hello")
        assert "[test]" in result
        assert "hello" in result
    
    def test_execute_adds_to_memory(self):
        """Выполнение должно добавлять запись в память."""
        agent = Agent(role="test")
        agent.execute("task1")
        assert len(agent.memory) == 1
        assert agent.memory[0][0] == "task1"
    
    def test_execute_multiple_times(self):
        """Несколько выполнений."""
        agent = Agent(role="test")
        agent.execute("task1")
        agent.execute("task2")
        agent.execute("task3")
        assert len(agent.memory) == 3
    
    def test_execute_with_forbidden_token(self):
        """Выполнение с запрещённым токеном должно падать."""
        agent = Agent(role="secure", constraints={"forbidden_tokens": ["bad"]})
        with pytest.raises(ValueError):
            agent.execute("this is bad")


class TestAgentMemory:
    """Тесты памяти агента."""
    
    def test_get_memory_empty(self):
        """Получение пустой памяти."""
        agent = Agent(role="test")
        assert agent.get_memory() == []
    
    def test_get_memory_returns_copy(self):
        """get_memory должен возвращать копию."""
        agent = Agent(role="test")
        agent.execute("task1")
        memory = agent.get_memory()
        memory.append(("fake", "fake"))
        assert len(agent.get_memory()) == 1  # Оригинал не изменился
    
    def test_clear_memory(self):
        """Очистка памяти."""
        agent = Agent(role="test")
        agent.execute("task1")
        agent.execute("task2")
        assert len(agent.memory) == 2
        
        agent.clear_memory()
        assert len(agent.memory) == 0
