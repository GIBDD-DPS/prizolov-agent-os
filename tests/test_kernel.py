"""Тесты ядра."""

import pytest

from prizolov_os.core.kernel import Kernel
from prizolov_os.core.orchestrator import Orchestrator
from prizolov_os.llm import FakeLLMClient, tool_use_response


class TestKernel:
    def test_create_with_orchestrator(self):
        orchestrator = Orchestrator(llm=FakeLLMClient())
        kernel = Kernel(orchestrator)
        assert kernel.orchestrator is orchestrator
        assert kernel.mode == "standard"

    def test_create_builds_full_team(self, tmp_path):
        kernel = Kernel.create(llm=FakeLLMClient(), workspace_dir=tmp_path)
        assert kernel.get_status()["specialists"] == [
            "assistant", "researcher", "writer", "cashflow_analyst", "market_analyst"
        ]

    def test_run_delegates(self, tmp_path):
        # Один фейковый клиент на всех: сначала отвечает Директор, потом ассистент.
        llm = FakeLLMClient([
            tool_use_response("delegate", {"agent": "assistant", "task": "Посчитай 2+2"}),
            "4",
            "Ответ: 4",
        ])
        kernel = Kernel.create(llm=llm, workspace_dir=tmp_path)
        result = kernel.run("Сколько будет 2+2?")
        assert result.text == "Ответ: 4"
        assert kernel.get_status()["delegations"] == 1

    def test_chat_and_reset(self, tmp_path):
        kernel = Kernel.create(llm=FakeLLMClient(["a", "b"]), workspace_dir=tmp_path)
        kernel.chat("1")
        kernel.chat("2")
        assert len(kernel.orchestrator.director.history) == 4
        kernel.reset()
        assert kernel.orchestrator.director.history == []

    @pytest.mark.parametrize("task", ["", None])
    def test_invalid_task(self, task):
        with pytest.raises(ValueError, match="Task must be a non-empty string"):
            Kernel(Orchestrator(llm=FakeLLMClient())).run(task)
