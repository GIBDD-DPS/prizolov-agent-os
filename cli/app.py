# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Интерактивный чат с Prizolov OS и команды управления."""

from typing import Callable, Dict

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from prizolov_os.__about__ import HEADER
from prizolov_os.core.kernel import Kernel
from prizolov_os.forecasting import ASSET_CLASSES, METHOD_NAMES
from prizolov_os.improvement import prompt_diff
from prizolov_os.llm import LLMError

from .render import (
    InputFn,
    agent_title,
    confirm,
    format_usd,
    print_answer,
    print_code,
    print_llm_error,
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
  /index [full]           обновить базу знаний по документам рабочей папки
  /cost                   расходы: последняя задача, сегодня, всего
  /budget [task|day N]    лимиты расходов (на эту сессию)
[bold]Обучение[/]
  /good [комментарий]     хороший ответ
  /bad комментарий        плохой ответ: что не так (станет уроком)
  /lessons [агент]        уроки
  /unlearn N              удалить урок
  /facts                  что агент помнит о вас
  /forget N               удалить факт
[bold]Точность прогнозов[/]
  /forecasts              журнал прогнозов, соревнование методов, точность
  /verify                 сверить наступившие прогнозы с фактом
  /quality                отказы источников, оценки критика и ваши оценки
  /calibration-reset [класс]  сбросить накопленную калибровку
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
            "/index": self.cmd_index,
            "/cost": self.cmd_cost,
            "/budget": self.cmd_budget,
            "/log": self.cmd_log,
            "/good": lambda arg: self.cmd_feedback(True, arg),
            "/bad": lambda arg: self.cmd_feedback(False, arg),
            "/lessons": self.cmd_lessons,
            "/unlearn": self.cmd_unlearn,
            "/facts": self.cmd_facts,
            "/forget": self.cmd_forget,
            "/improve": self.cmd_improve,
            "/prompts": self.cmd_prompts,
            "/forecasts": self.cmd_forecasts,
            "/verify": self.cmd_verify,
            "/quality": self.cmd_quality,
            "/calibration-reset": self.cmd_calibration_reset,
            "/approve-prompt": self.cmd_approve_prompt,
            "/reject-prompt": self.cmd_reject_prompt,
            "/rollback": self.cmd_rollback,
            "/tools": self.cmd_tools,
            "/approve-tool": self.cmd_approve_tool,
            "/reject-tool": self.cmd_reject_tool,
        }

    def loop(self) -> None:
        self.console.print(f"[bold]{escape(HEADER)}[/]", highlight=False)
        self.console.print("Пишите задачу. /help — команды, /exit — выход.\n")
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
            print_llm_error(self.console, e)
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

    def cmd_cost(self, _: str) -> None:
        budget = self._budget()
        self.console.print(
            f"Последняя задача: {format_usd(budget.task_spent_usd)}; сегодня: "
            f"{format_usd(budget.today_spent_usd())}; всего: {format_usd(budget.total_spent_usd())}"
        )
        history = budget.history(7)
        if history:
            table = Table("День", "Запросов", "Расход")
            for row in history:
                table.add_row(row["day"], str(row["requests"]), format_usd(row["usd"]))
            self.console.print(table)
        tracer = self.kernel.tracer
        if tracer is not None:
            self.console.print(f"[dim]Журнал трассировки: {tracer.path}[/]")

    def cmd_budget(self, arg: str) -> None:
        budget = self._budget()
        if arg:
            kind, _, value = arg.partition(" ")
            try:
                amount = float(value.replace(",", "."))
            except ValueError:
                raise ValueError("Формат: /budget task 2.5 или /budget day 20 (0 - без лимита)")
            if kind not in ("task", "day") or amount < 0:
                raise ValueError("Формат: /budget task 2.5 или /budget day 20 (0 - без лимита)")
            setattr(budget, f"{kind}_limit_usd", amount)

        def limit(value: float) -> str:
            return "без лимита" if not value else format_usd(value)

        self.console.print(
            f"Лимит на задачу: {limit(budget.task_limit_usd)}, на день: "
            f"{limit(budget.day_limit_usd)}. "
            f"Сегодня потрачено {format_usd(budget.today_spent_usd())}."
        )

    def _budget(self):
        if self.kernel.budget is None:
            raise ValueError("Учёт расходов не подключён")
        return self.kernel.budget

    def cmd_index(self, arg: str) -> None:
        knowledge = self.kernel.knowledge
        if knowledge is None:
            raise ValueError("База знаний не подключена")
        report = knowledge.index(force=arg == "full")
        self.print_index(report, quiet=False)
        stats = knowledge.stats()
        self.console.print(
            f"База знаний: файлов {stats['files']}, фрагментов {stats['chunks']}"
            + (f", не прочитано {stats['errors']}" if stats["errors"] else "")
            + f". Папка: {escape(str(knowledge.root))}"
        )

    def print_index(self, report, quiet: bool = True) -> None:
        if report.changed:
            parts = []
            if report.added:
                parts.append(f"новых {len(report.added)}")
            if report.updated:
                parts.append(f"изменённых {len(report.updated)}")
            if report.removed:
                parts.append(f"удалённых {len(report.removed)}")
            self.console.print(f"[cyan]База знаний обновлена: {', '.join(parts)} файлов[/]")
        elif not quiet:
            self.console.print("Изменений в документах нет.")
        for path, error in report.errors:
            self.console.print(f"[yellow]Не прочитан {escape(path)}: {escape(error)}[/]")

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

    # --- Точность прогнозов --------------------------------------------------

    def cmd_verify(self, _: str) -> None:
        self.console.print("Сверяю прогнозы с фактом…")
        report = self.kernel.verify_forecasts()
        self.print_verification(report, quiet=False)

    def print_verification(self, report, quiet: bool = True) -> None:
        for error in report.errors:
            self.console.print(f"[yellow]Не удалось получить факт: {escape(error)}[/]")
        if report.verified:
            hits = sum(1 for f in report.verified if f.hit_80)
            self.console.print(
                f"[cyan]Сверено прогнозов: {len(report.verified)}, "
                f"в 80%-й интервал попало {hits}. Подробнее: /forecasts[/]"
            )
            if not quiet:
                table = Table("#", "Актив", "Дата", "Прогноз", "Факт", "Ошибка", "В интервале")
                for f in report.verified:
                    table.add_row(
                        str(f.id), escape(f.symbol), f.target_date.isoformat(),
                        f"{f.median:.4g}", f"{f.actual:.4g}", f"{f.error_pct:+.1f}%",
                        "да" if f.hit_80 else "нет",
                    )
                self.console.print(table)
        elif not quiet:
            self.console.print("Нет прогнозов, срок которых уже наступил.")

    def cmd_forecasts(self, _: str) -> None:
        journal = self.kernel.forecasts
        counts = journal.counts()
        self.console.print(
            f"Прогнозов: ожидают сверки {counts.get('pending', 0)}, "
            f"сверено {counts.get('verified', 0)}, "
            f"не удалось сверить {counts.get('unverifiable', 0)}."
        )
        board = journal.leaderboard()
        if not board:
            self.console.print("Пока нет данных: попросите прогноз, например курса доллара.")
            return
        table = Table(
            "Класс", "Горизонт", "Метод", "Проверено\nна истории", "В 80%\nинтервале",
            "Направление", "Ошибка", "Сверено\nвживую", "В 80%\n(вживую)",
            title="Соревнование методов",
        )

        def pct(value):
            return "—" if value is None else f"{value * 100:.0f}%"

        for row in board:
            bt, live = row["backtest"], row["live"]
            table.add_row(
                ASSET_CLASSES.get(row["asset_class"], row["asset_class"]),
                row["bucket"],
                METHOD_NAMES.get(row["method"], row["method"]),
                str(bt.n), pct(bt.pass_rate_80), pct(bt.direction_rate),
                "—" if bt.mean_abs_error_pct is None else f"{bt.mean_abs_error_pct:.1f}%",
                str(live.n), pct(live.pass_rate_80),
            )
        self.console.print(table)
        live = journal.live_accuracy()
        if live.n:
            self.console.print(
                f"Все сверенные прогнозы: {live.n}, в 80%-й интервал {pct(live.pass_rate_80)}, "
                f"в 95%-й {pct(live.pass_rate_95)}, направление {pct(live.direction_rate)}, "
                f"средняя ошибка {live.mean_abs_error_pct:.1f}%."
            )

    def cmd_quality(self, _: str) -> None:
        report = self.kernel.quality.report()
        tools = report["tools"]
        if tools:
            table = Table("Инструмент", "Агент", "Вызовов", "Ошибок", "Доля ошибок",
                          title=f"Инструменты и источники за {report['days']} дней")
            for t in tools:
                table.add_row(escape(t.key), agent_title(t.agent), str(t.calls),
                              str(t.errors), f"{t.error_rate * 100:.0f}%")
            self.console.print(table)
        critic = report["critic"]
        if critic["checks"]:
            self.console.print(
                f"Самопроверка: {critic['checks']} проверок, средняя оценка "
                f"{critic['average_score']}/10, доработок {critic['revisions']}."
            )
        for agent, marks in report["feedback"].items():
            self.console.print(
                f"Ваши оценки ({escape(agent_title(agent))}): "
                f"хороших {marks['good']}, плохих {marks['bad']}."
            )
        for tool, count in report.get("injections", {}).items():
            self.console.print(
                f"[yellow]Подозрительный текст в данных ({escape(tool)}): {count} раз[/]"
            )
        if not (tools or critic["checks"] or report["feedback"] or report.get("injections")):
            self.console.print("Статистики пока нет.")

    def cmd_calibration_reset(self, arg: str) -> None:
        classes = {v: k for k, v in ASSET_CLASSES.items()}
        asset_class = classes.get(arg, arg) or None
        if asset_class and asset_class not in ASSET_CLASSES:
            raise ValueError(f"Неизвестный класс. Доступны: {', '.join(ASSET_CLASSES)}")
        if not confirm(self.ask, "Сбросить накопленную калибровку?"):
            self.console.print("Отменено.")
            return
        self.kernel.forecasts.reset(asset_class)
        self.console.print("Калибровка сброшена; журнал прогнозов сохранён.")

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
        print_llm_error(console, e)
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
