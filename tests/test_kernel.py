"""Тесты для модуля Kernel."""

import pytest
from prizolov_os.core.kernel import Kernel
from prizolov_os.core.orchestrator import Orchestrator
from prizolov_os.agent import Agent


class TestKernelInit:
    """Тесты инициализации ядра."""
    
    def test_kernel_create_with_orchestrator(self):
        """Создание ядра с оркестратором."""
        orchestrator = Orchestrator()
        kernel = Kernel(orchestrator)
        assert kernel.orchestrator is orchestrator
        assert kernel.mode == "standard"


class TestKernelRun:
    """Тесты метода run."""
    
    def test_run_valid_task(self):
        """Запуск валидной задачи."""
        orchestrator = Orchestrator()
        orchestrator.register_agent("test", Agent(role="test"))
        kernel = Kernel(orchestrator)
        
        result = kernel.run("test task")
        assert isinstance(result, list)
        assert len(result) >= 0
    
    def test_run_empty_task(self):
        """Пустая задача должна вызывать ValueError."""
        orchestrator = Orchestrator()
        kernel = Kernel(orchestrator)
        
        with pytest.raises(ValueError, match="Task must be a non-empty string"):
            kernel.run("")
    
    def test_run_none_task(self):
        """None задача должна вызывать ValueError."""
        orchestrator = Orchestrator()
        kernel = Kernel(orchestrator)
        
        with pytest.raises(ValueError, match="Task must be a non-empty string"):
            kernel.run(None)
    
    def test_run_int_task(self):
        """Число вместо задачи должно вызывать ValueError."""
        orchestrator = Orchestrator()
        kernel = Kernel(orchestrator)
        
        with pytest.raises(ValueError, match="Task must be a non-empty string"):
            kernel.run(123)


class TestKernelGetStatus:
    """Тесты метода get_status."""
    
    def test_get_status_returns_dict(self):
        """get_status должен возвращать dict."""
        orchestrator = Orchestrator()
        kernel = Kernel(orchestrator)
        
        status = kernel.get_status()
        assert isinstance(status, dict)
        assert "mode" in status
        assert "orchestrator_active" in status
    
    def test_get_status_mode(self):
        """Режим должен быть 'standard'."""
        orchestrator = Orchestrator()
        kernel = Kernel(orchestrator)
        
        status = kernel.get_status()
        assert status["mode"] == "standard"
    
    def test_get_status_orchestrator_active(self):
        """orchestrator_active должен быть True."""
        orchestrator = Orchestrator()
        kernel = Kernel(orchestrator)
        
        status = kernel.get_status()
        assert status["orchestrator_active"] is True
