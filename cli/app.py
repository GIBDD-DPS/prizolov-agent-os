"""Интерактивный чат с Prizolov OS и команды управления."""

from typing import Callable, Dict

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from prizolov_os.core.kernel import Kernel
from prizolov_os.improvement import prompt_diff
from prizolov_os.llm import LLMError

from .render import (
    InputFn,
    agent_title,
    confirm,
    print_answer,
    print_code,
    print_usage,
    short,
)

HELP = """\
[bold]Диалог[/]
  /new                    начать новый диалог
  /sessions               сохранённые диалоги
  /resume ID              продолжить диалог
  /status                 состояние системы
  /log                    поручения специалистам в последнем ответе
[bold]Обучение[/]
  /good [комментарий]     хороший ответ
  /bad комментарий        плохой ответ: что не так (станет уроком)
  /lessons [агент]        уроки
  /unlearn N              удалить урок
  /facts                  что агент помнит о вас
  /forget N               удалить факт
[bold]Промпты[/]
  /improve [агент]        предложить улучшенный промпт по урокам
  /prompts [агент]        версии промптов
  /approve-prompt N       применить версию
  /reject-prompt N        отклонить версию
  /rollback агент         вернуть предыдущую версию
[bold]Инструменты, созданные агентом[/]
  /tools                  ожидающие проверки
  /approve-tool имя       показать код и подключить
  /reject-tool имя        отклонить
[bold]Прочее[/]
  /help                   эта справка
  /exit                   выход"""


class ChatApp:
    """Цикл чата: читает ввод, выполняет команды или передаёт сообщение ядру."""

    def __init__(self, kernel: Kernel, console: Console, ask: InputFn) -> None:
        self.kernel = kernel
        self.console = console
        self.ask = ask
        self.commands: Dict[str, Callable[[str], None]] = {
            "/help": lambda _: console.print(HELP),
            "/new": self.cmd_new,
            "/sessions": self.cmd_sessions,
            "/resume": self.cmd_resume,
            "/status": self.cmd_status,
            "/log": self.cmd_log,
            "/good": lambda arg: self.cmd_feedback(True, arg),
            "/bad": lambda arg: self.cmd_feedback(False, arg),
            "/lessons": self.cmd_lessons,
            "/unlearn": self.cmd_unlearn,
            "/facts": self.cmd_facts,
            "/forget": self.cmd_forget,
            "/improve": self.cmd_improve,
            "/prompts": self.cmd_prompts,
            "/approve-prompt": self.cmd_approve_prompt,
            "/reject-prompt": self.cmd_reject_prompt,
            "/rollback": self.cmd_rollback,
            "/tools": self.cmd_tools,
            "/approve-tool": self.cmd_approve_tool,
            "/reject-tool": self.cmd_reject_tool,
        }

    def loop(self) -> None:
        self.console.print(
            "[bold]Prizolov Agent OS[/] — пишите задачу. /help — команды, /exit — выход.\n"
        )
        while True:
            try:
                line = self.ask("> ").strip()
            except (EOFError, KeyboardInterrupt):
                self.console.print()
                return
            if not line:
                continue
            if line in ("/exit", "/quit"):
                return
            self.handle(line)

    def handle(self, line: str) -> None:
        if line.startswith("/"):
            name, _, arg = line.partition(" ")
            command = self.commands.get(name)
            if command is None:
                self.console.print(f"[red]Неизвестная команда {escape(name)}. /help — список[/]")
                return
            try:
                command(arg.strip())
            except (ValueError, RuntimeError, LLMError) as e:
                self.console.print(f"[red]{escape(str(e))}[/]")
            return
        self.send(line)

    def send(self, message: str) -> None:
        try:
            result = self.kernel.chat(message)
        except LLMError as e:
            self.console.print(f"[red]Ошибка модели: {escape(str(e))}[/]")
            return
        except KeyboardInterrupt:
            self.console.print("[yellow]Прервано[/]")
            return
        print_answer(self.console, result.text)
        print_usage(self.console, result.usage)
        candidates = self.kernel.improvement_candidates()
        if candidates:
            names = ", ".join(f"{agent_title(a)} ({n})" for a, n in candidates)
            self.console.print(
                f"[cyan]Накопились уроки: {escape(names)}. "
                "Можно улучшить промпт: /improve агент[/]"
            )
        if self.kernel.pending_tools():
            self.console.print("[cyan]Агент предложил новый инструмент: /tools[/]")

    # --- Диалог --------------------------------------------------------------

    def cmd_new(self, _: str) -> None:
        self.kernel.reset()
        self.console.print("Новый диалог.")

    def cmd_sessions(self, _: str) -> None:
        sessions = self.kernel.store.list_sessions()
        if not sessions:
            self.console.print("Сохранённых диалогов нет.")
            return
        table = Table("ID", "Тема", "Сообщений", "Обновлён")
        for s in sessions:
            table.add_row(s.id, escape(short(s.title, 50)), str(s.messages), s.updated_at[:16])
        self.console.print(table)

    def cmd_resume(self, arg: str) -> None:
        count = self.kernel.resume(_require(arg, "Укажите ID диалога: /resume ID"))
        self.console.print(f"Диалог продолжен ({count} сообщений).")

    def cmd_status(self, _: str) -> None:
        for key, value in self.kernel.get_status().items():
            self.console.print(f"{key}: {escape(str(value))}")

    def cmd_log(self, _: str) -> None:
        log = self.kernel.orchestrator.last_run_delegations
        if not log:
            self.console.print("В последнем ответе специалисты не привлекались.")
            return
        table = Table("Специалист", "Поручение", "Статус", "Токены")
        for d in log:
            tokens = d.usage.input_tokens + d.usage.output_tokens
            table.add_row(agent_title(d.agent), escape(short(d.task, 60)), d.status, str(tokens))
        self.console.print(table)

    # --- Обучение ------------------------------------------------------------

    def cmd_feedback(self, positive: bool, comment: str) -> None:
        if not positive and not comment:
            raise ValueError("Напишите, что не так: /bad комментарий")
        lesson = self.kernel.feedback(positive, comment)
        if lesson:
            self.console.print(
                f"Урок #{lesson.id} для {escape(agent_title(lesson.agent))}: {escape(lesson.text)}"
            )
        else:
            self.console.print("Спасибо за оценку.")

    def cmd_lessons(self, arg: str) -> None:
        lessons = self.kernel.store.list_lessons(arg or None)
        if not lessons:
            self.console.print("Уроков пока нет.")
            return
        table = Table("#", "Агент", "Урок", "Источник")
        for lesson in lessons:
            table.add_row(
                str(lesson.id), agent_title(lesson.agent), escape(lesson.text), lesson.source
            )
        self.console.print(table)

    def cmd_unlearn(self, arg: str) -> None:
        if not self.kernel.store.delete_lesson(_require_int(arg, "/unlearn N")):
            raise ValueError("Нет такого урока")
        self.console.print("Урок удалён.")

    def cmd_facts(self, _: str) -> None:
        facts = self.kernel.store.list_facts()
        if not facts:
            self.console.print("Фактов пока нет.")
            return
        for fact in facts:
            self.console.print(f"{fact.id}. {escape(fact.text)}")

    def cmd_forget(self, arg: str) -> None:
        if not self.kernel.store.delete_fact(_require_int(arg, "/forget N")):
            raise ValueError("Нет такого факта")
        self.console.print("Факт удалён.")

    # --- Промпты -------------------------------------------------------------

    def cmd_improve(self, arg: str) -> None:
        if not arg:
            candidates = self.kernel.improvement_candidates()
            if not candidates:
                raise ValueError("Укажите агента: /improve агент (уроки: /lessons)")
            arg = candidates[0][0]
        self.console.print(f"Готовлю новую версию промпта: {escape(agent_title(arg))}…")
        version, proposal = self.kernel.propose_prompt(arg)
        for change in proposal.changes:
            self.console.print(f"• {escape(change)}")
        self.console.print(escape(proposal.diff), highlight=False)
        self.console.print(
            f"Версия #{version.id}. Применить: /approve-prompt {version.id}, "
            f"отклонить: /reject-prompt {version.id}"
        )

    def cmd_prompts(self, arg: str) -> None:
        versions = self.kernel.store.list_prompt_versions(arg or None)
        if not versions:
            self.console.print("Все агенты работают на исходных промптах.")
            return
        table = Table("#", "Агент", "Статус", "Изменения", "Дата")
        for v in versions:
            table.add_row(
                str(v.id), agent_title(v.agent), v.status, escape(short(v.note, 60)),
                v.created_at[:16],
            )
        self.console.print(table)

    def cmd_approve_prompt(self, arg: str) -> None:
        version_id = _require_int(arg, "/approve-prompt N")
        version = self.kernel.store.get_prompt_version(version_id)
        if version is None:
            raise ValueError("Нет такой версии")
        current = self.kernel.agents[version.agent].system_prompt
        self.console.print(escape(prompt_diff(current, version.prompt)), highlight=False)
        if not confirm(self.ask, "Применить эту версию?"):
            self.console.print("Отменено.")
            return
        self.kernel.approve_prompt(version_id)
        self.console.print(f"Промпт агента {escape(agent_title(version.agent))} обновлён.")

    def cmd_reject_prompt(self, arg: str) -> None:
        self.kernel.reject_prompt(_require_int(arg, "/reject-prompt N"))
        self.console.print("Версия отклонена.")

    def cmd_rollback(self, arg: str) -> None:
        agent = _require(arg, "Укажите агента: /rollback агент")
        previous = self.kernel.rollback_prompt(agent)
        where = f"версия #{previous.id}" if previous else "исходный промпт"
        self.console.print(f"{escape(agent_title(agent))}: восстановлен {where}.")

    # --- Инструменты ---------------------------------------------------------

    def cmd_tools(self, _: str) -> None:
        tools = self.kernel.pending_tools()
        if not tools:
            self.console.print("Нет инструментов, ожидающих проверки.")
            return
        for tool in tools:
            self.console.print(f"[bold]{escape(tool.name)}[/] — {escape(tool.description)}")
        self.console.print("Проверить и подключить: /approve-tool имя")

    def cmd_approve_tool(self, arg: str) -> None:
        name = _require(arg, "Укажите имя: /approve-tool имя")
        record = self.kernel.store.get_custom_tool(name)
        if record is None:
            raise ValueError(f"Нет инструмента '{name}'")
        params = ", ".join(record.input_schema.get("properties", {}))
        self.console.print(f"[bold]{escape(name)}[/]: {escape(record.description)}")
        self.console.print(f"Параметры: {escape(params)}")
        print_code(self.console, record.code, f"Код инструмента {name}")
        self.console.print(
            "[yellow]Код выполняется в отдельном процессе без доступа к файлам и сети, "
            "но полной изоляции нет. Подключайте, только если понимаете, что он делает.[/]"
        )
        if not confirm(self.ask, "Подключить инструмент?"):
            self.console.print("Отменено.")
            return
        self.kernel.approve_tool(name)
        self.console.print("Инструмент подключён.")

    def cmd_reject_tool(self, arg: str) -> None:
        self.kernel.reject_tool(_require(arg, "Укажите имя: /reject-tool имя"))
        self.console.print("Инструмент отклонён.")


def run_once(kernel: Kernel, console: Console, task: str) -> int:
    """Выполняет одну задачу и возвращает код выхода."""
    try:
        result = kernel.run(task)
    except LLMError as e:
        console.print(f"[red]Ошибка модели: {escape(str(e))}[/]")
        return 1
    print_answer(console, result.text)
    print_usage(console, result.usage)
    return 0 if result.completed else 2


def _require(arg: str, message: str) -> str:
    if not arg:
        raise ValueError(message)
    return arg


def _require_int(arg: str, usage: str) -> int:
    try:
        return int(arg)
    except ValueError:
        raise ValueError(f"Нужен номер: {usage}") from None
