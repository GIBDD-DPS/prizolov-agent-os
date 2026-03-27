"""Тесты для модуля Orchestrator."""

import pytest
from prizolov_os.core.orchestrator import Orchestrator
from prizolov_os.agent import Agent


class TestOrchestratorInit:
    """Тесты инициализации оркестратора."""
    
    def test_orchestrator_create_empty(self):
        """Создание пустого оркестратора."""
        orch = Orchestrator()
        assert orch.agents == []
        assert orch.execution_log == []


class TestOrchestratorRegisterAgent:
    """Тесты метода register_agent."""
    
    def test_register_agent_single(self):
        """Регистрация одного агента."""
        orch = Orchestrator()
        agent = Agent(role="test")
        orch.register_agent("test_agent", agent)
        
        assert len(orch.agents) == 1
        assert orch.agents[0]["name"] == "test_agent"
    
    def test_register_agent_multiple(self):
        """Регистрация нескольких агентов."""
        orch = Orchestrator()
        orch.register_agent("agent1", Agent(role="1"))
        orch.register_agent("agent2", Agent(role="2"))
        
        assert len(orch.agents) == 2


class TestOrchestratorExecute:
    """Тесты метода execute."""
    
    def test_execute_no_agents(self):
        """Выполнение без агентов."""
        orch = Orchestrator()
        result = orch.execute("task")
        assert result == []
    
    def test_execute_one_agent(self):
        """Выполнение с одним агентом."""
        orch = Orchestrator()
        orch.register_agent("test", Agent(role="test"))
        
        result = orch.execute("hello")
        assert len(result) == 1
    
    def test_execute_empty_task(self):
        """Пустая задача должна вызывать ValueError."""
        orch = Orchestrator()
        
        with pytest.raises(ValueError, match="Task must be a non-empty string"):
            orch.execute("")
    
    def test_execute_none_task(self):
        """None задача должна вызывать ValueError."""
        orch = Orchestrator()
        
        with pytest.raises(ValueError, match="Task must be a non-empty string"):
            orch.execute(None)


class TestOrchestratorExecutionLog:
    """Тесты журнала выполнения."""
    
    def test_execution_log_empty(self):
        """Пустой журнал."""
        orch = Orchestrator()
        assert orch.get_execution_log() == []
    
    def test_execution_log_after_execute(self):
        """Журнал после выполнения."""
        orch = Orchestrator()
        orch.register_agent("test", Agent(role="test"))
        orch.execute("task")
        
        log = orch.get_execution_log()
        assert len(log) == 1
        assert log[0]["agent"] == "test"
