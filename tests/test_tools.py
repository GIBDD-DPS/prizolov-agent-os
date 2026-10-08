# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Тесты инструментов."""

import pytest

from prizolov_os.llm import ToolCall
from prizolov_os.tools import (
    Tool,
    ToolInputError,
    ToolRegistry,
    Workspace,
    calculate,
    current_datetime,
    default_tools,
    make_schema,
)
from prizolov_os.tools.base import validate_input


class TestCalculator:
    @pytest.mark.parametrize(
        "expression, expected",
        [("2+2*2", "6"), ("(10-4)/3", "2.0"), ("2^10", "1024"), ("-3 + abs(-5)", "2"),
         ("round(sqrt(2), 3)", "1.414"), ("max(1, 7, 3)", "7"), ("17 // 5", "3")],
    )
    def test_valid(self, expression, expected):
        assert calculate(expression) == expected

    @pytest.mark.parametrize(
        "expression",
        ["__import__('os')", "open('x')", "x + 1", "'a' * 3", "(1).__class__", "9**9**9",
         "(10**999)**999"],
    )
    def test_rejected(self, expression):
        with pytest.raises(ValueError):
            calculate(expression)

    def test_syntax_error(self):
        with pytest.raises(SyntaxError):
            calculate("2 +")


class TestDatetime:
    def test_known_timezone(self):
        assert "MSK" in current_datetime("Europe/Moscow")

    def test_unknown_timezone(self):
        with pytest.raises(ValueError, match="Неизвестный часовой пояс"):
            current_datetime("Mars/Olympus")


class TestValidateInput:
    schema = make_schema({
        "name": {"type": "string"},
        "count": {"type": "integer"},
        "mode": {"type": "string", "enum": ["a", "b"]},
    })

    def test_valid(self):
        validate_input(self.schema, {"name": "x", "count": 2, "mode": "a"})

    @pytest.mark.parametrize(
        "data, message",
        [
            ({"name": "x", "count": 2}, "обязательный"),
            ({"name": "x", "count": "2", "mode": "a"}, "integer"),
            ({"name": "x", "count": True, "mode": "a"}, "integer"),
            ({"name": "x", "count": 2, "mode": "c"}, "одним из"),
            ({"name": "x", "count": 2, "mode": "a", "extra": 1}, "Неизвестный"),
            ("not a dict", "объектом"),
        ],
    )
    def test_invalid(self, data, message):
        with pytest.raises(ToolInputError, match=message):
            validate_input(self.schema, data)


class TestRegistry:
    def echo_tool(self):
        return Tool("echo", "d", make_schema({"text": {"type": "string"}}), lambda text: text)

    def test_schemas_are_strict(self):
        schema = ToolRegistry([self.echo_tool()]).schemas()[0]
        assert schema["strict"] is True
        assert schema["input_schema"]["additionalProperties"] is False

    def test_duplicate_name(self):
        registry = ToolRegistry([self.echo_tool()])
        with pytest.raises(ValueError):
            registry.add(self.echo_tool())

    def test_execute_ok(self):
        result = ToolRegistry([self.echo_tool()]).execute(ToolCall("t1", "echo", {"text": "hi"}))
        assert (result.output, result.is_error) == ("hi", False)
        assert result.to_api() == {"type": "tool_result", "tool_use_id": "t1", "content": "hi"}

    def test_unknown_tool(self):
        result = ToolRegistry().execute(ToolCall("t1", "nope", {}))
        assert result.is_error
        assert result.to_api()["is_error"] is True

    def test_invalid_input_not_executed(self):
        calls = []
        tool = Tool("t", "d", make_schema({"n": {"type": "integer"}}), lambda n: calls.append(n))
        result = ToolRegistry([tool]).execute(ToolCall("t1", "t", {"n": "x"}))
        assert result.is_error
        assert calls == []

    def test_handler_exception(self):
        def boom():
            raise RuntimeError("сломалось")

        result = ToolRegistry([Tool("b", "d", make_schema({}), boom)]).execute(
            ToolCall("t1", "b", {})
        )
        assert result.is_error
        assert "сломалось" in result.output

    def test_non_string_output_serialized(self):
        tool = Tool("j", "d", make_schema({}), lambda: {"цена": 10})
        assert ToolRegistry([tool]).execute(ToolCall("t1", "j", {})).output == '{"цена": 10}'


class TestWorkspace:
    def test_write_read_list(self, tmp_path):
        ws = Workspace(tmp_path, sign_output=False)
        assert "Записано" in ws.write_file("notes/a.txt", "привет")
        assert ws.read_file("notes/a.txt") == "привет"
        assert "notes/" in ws.list_files(".")
        assert "notes/a.txt" in ws.list_files("notes")

    @pytest.mark.parametrize("path", ["../outside.txt", "/etc/passwd", "a/../../x"])
    def test_escape_blocked(self, tmp_path, path):
        with pytest.raises(PermissionError):
            Workspace(tmp_path / "ws").read_file(path)

    def test_symlink_escape_blocked(self, tmp_path):
        root = tmp_path / "ws"
        root.mkdir()
        (tmp_path / "secret.txt").write_text("s")
        (root / "link.txt").symlink_to(tmp_path / "secret.txt")
        with pytest.raises(PermissionError):
            Workspace(root).read_file("link.txt")

    def test_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            Workspace(tmp_path).read_file("nope.txt")

    def test_write_requires_approval(self, tmp_path):
        registry = ToolRegistry(default_tools(tmp_path))
        call = ToolCall("t1", "write_file", {"path": "a.csv", "content": "x"})
        assert registry.execute(call).is_error
        assert not (tmp_path / "a.csv").exists()
        assert not registry.execute(call, approver=lambda n, i: True).is_error
        assert (tmp_path / "a.csv").read_text() == "x"

    def test_default_tools(self, tmp_path):
        names = ToolRegistry(default_tools(tmp_path)).names()
        assert names == ["calculator", "current_datetime", "list_files", "read_file", "write_file"]


class TestServerTools:
    def test_spec_passed_through(self):
        from prizolov_os.tools import web_fetch_tool, web_search_tool

        registry = ToolRegistry([web_search_tool(max_uses=3), web_fetch_tool()])
        assert registry.schemas() == [
            {"type": "web_search_20260209", "name": "web_search", "max_uses": 3},
            {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 5},
        ]

    def test_not_executed_locally(self):
        from prizolov_os.tools import web_search_tool

        result = ToolRegistry([web_search_tool()]).execute(ToolCall("t1", "web_search", {}))
        assert result.is_error
