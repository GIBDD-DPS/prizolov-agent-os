# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Открытая статистика точности прогнозов: сколько сбылось на самом деле.

Считается только по прогнозам, срок которых наступил и которые сверены с
фактической ценой. Страница - самодостаточный HTML без внешних ресурсов: её можно
выложить на сайт или отдать через HTTP API (/public/accuracy).
"""

import html
from datetime import datetime
from typing import Any, Dict, List, Optional

from .__about__ import HEADER, PROJECT_ID, SIGNATURE, __author__, __brand__
from .forecasting.classify import ASSET_CLASSES
from .memory import Store

TARGET_80 = 80.0


def _pct(part: float, total: float) -> Optional[float]:
    return round(part / total * 100, 1) if total else None


def _group(rows: List[Any]) -> Dict[str, Any]:
    n = len(rows)
    direction = [r["direction_ok"] for r in rows if r["direction_ok"] is not None]
    errors = [abs(r["error_pct"]) for r in rows if r["error_pct"] is not None]
    return {
        "forecasts": n,
        "interval_80_pct": _pct(sum(1 for r in rows if r["hit_80"]), n),
        "interval_95_pct": _pct(sum(1 for r in rows if r["hit_95"]), n),
        "direction_pct": _pct(sum(1 for d in direction if d), len(direction)),
        "mean_abs_error_pct": round(sum(errors) / len(errors), 2) if errors else None,
    }


def accuracy_data(store: Store, recent: int = 30) -> Dict[str, Any]:
    """Сводка по сверенным рыночным прогнозам."""
    rows = store.query(
        "SELECT * FROM forecasts WHERE kind = 'market' AND status = 'verified' "
        "ORDER BY target_date DESC, id DESC"
    ) if _has_table(store) else []
    pending = store.query(
        "SELECT COUNT(*) AS n FROM forecasts WHERE kind = 'market' AND status = 'pending'"
    )[0]["n"] if _has_table(store) else 0

    def grouped(key: str, names: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        groups: Dict[str, List[Any]] = {}
        for r in rows:
            groups.setdefault(r[key], []).append(r)
        result = [{"key": k, "name": (names or {}).get(k, k), **_group(v)}
                  for k, v in groups.items()]
        return sorted(result, key=lambda g: -g["forecasts"])

    return {
        "generated": datetime.now().isoformat(timespec="minutes"),
        "overall": _group(rows),
        "pending": pending,
        "by_asset_class": grouped("asset_class", ASSET_CLASSES),
        "by_horizon": grouped("bucket"),
        "by_symbol": grouped("symbol")[:20],
        "recent": [
            {"symbol": r["symbol"], "source": r["source"], "made": r["base_date"],
             "target_date": r["target_date"], "horizon_days": r["horizon_days"],
             "base": r["base_value"], "median": r["median"], "low_80": r["low_80"],
             "high_80": r["high_80"], "actual": r["actual"], "hit_80": bool(r["hit_80"]),
             "direction_ok": None if r["direction_ok"] is None else bool(r["direction_ok"])}
            for r in rows[:recent]
        ],
    }


def _has_table(store: Store) -> bool:
    return bool(store.query(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'forecasts'"
    ))


def _fmt(value: Optional[float], suffix: str = "") -> str:
    if value is None:
        return "—"
    text = f"{value:,.2f}".replace(",", " ").rstrip("0").rstrip(".")
    return text + suffix


def _bar(value: Optional[float]) -> str:
    if value is None:
        return "—"
    width = max(0.0, min(value, 100.0))
    cls = "good" if abs(value - TARGET_80) <= 7 else "off"
    return (f'<span class="bar"><span class="fill {cls}" style="width:{width:.0f}%"></span>'
            f'<span class="mark"></span></span> {_fmt(value, "%")}')


def _table(title: str, groups: List[Dict[str, Any]]) -> str:
    if not groups:
        return ""
    rows = "".join(
        f"<tr><td>{html.escape(str(g['name']))}</td><td>{g['forecasts']}</td>"
        f"<td>{_bar(g['interval_80_pct'])}</td><td>{_fmt(g['direction_pct'], '%')}</td>"
        f"<td>{_fmt(g['mean_abs_error_pct'], '%')}</td></tr>"
        for g in groups
    )
    return (f"<h2>{html.escape(title)}</h2><div class='wrap'><table><tr><th></th>"
            "<th>Сверено</th><th>В интервале 80%</th><th>Направление</th>"
            f"<th>Средняя ошибка</th></tr>{rows}</table></div>")


def render_html(data: Dict[str, Any], title: str = "Точность прогнозов") -> str:
    """Самодостаточная страница со статистикой (светлая и тёмная тема)."""
    o = data["overall"]
    recent = "".join(
        f"<tr><td>{html.escape(r['symbol'])}</td><td>{r['made']}</td><td>{r['target_date']}</td>"
        f"<td>{_fmt(r['median'])}</td><td>{_fmt(r['low_80'])} – {_fmt(r['high_80'])}</td>"
        f"<td><b>{_fmt(r['actual'])}</b></td>"
        f"<td class='{'yes' if r['hit_80'] else 'no'}'>{'да' if r['hit_80'] else 'нет'}</td></tr>"
        for r in data["recent"]
    )
    if o["forecasts"]:
        summary = (
            f"<div class='stats'><div><span>Сверено прогнозов</span><b>{o['forecasts']}</b></div>"
            f"<div><span>Факт в интервале 80%</span><b>{_fmt(o['interval_80_pct'], '%')}</b>"
            f"<small>цель - около 80%</small></div>"
            f"<div><span>Угадано направление</span><b>{_fmt(o['direction_pct'], '%')}</b>"
            f"<small>50% - случайный уровень</small></div>"
            f"<div><span>Средняя ошибка медианы</span>"
            f"<b>{_fmt(o['mean_abs_error_pct'], '%')}</b></div></div>"
        )
    else:
        summary = ("<p class='empty'>Пока нет прогнозов, срок которых наступил. Статистика "
                   "появится после первых сверок.</p>")
    recent_table = (
        "<h2>Последние сверки</h2><div class='wrap'><table><tr><th>Актив</th><th>Сделан</th>"
        "<th>На дату</th><th>Медиана</th><th>Интервал 80%</th><th>Факт</th>"
        f"<th>В интервале</th></tr>{recent}</table></div>" if recent else ""
    )
    return f"""<!doctype html>
<!-- {HEADER} | {PROJECT_ID} -->
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="author" content="{__author__} / {__brand__}">
<title>{html.escape(title)} · Prizolov Agent OS</title>
<style>
:root {{ --bg:#f6f7f9; --panel:#fff; --text:#1d2330; --muted:#667085; --line:#e3e6ec;
  --good:#12805c; --off:#b54708; --accent:#2f5bea; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#0f1218; --panel:#171b23; --text:#e6e8ec;
  --muted:#98a2b3; --line:#2a303b; --good:#47cd89; --off:#fdb022; --accent:#6d8cff; }} }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text);
  font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
main {{ max-width:960px; margin:0 auto; padding:24px 16px 40px; }}
h1 {{ font-size:24px; margin:0 0 4px; }} h2 {{ font-size:17px; margin:28px 0 8px; }}
.lead, small, span, .empty {{ color:var(--muted); }}
.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:12px;
  margin-top:16px; }}
.stats div {{ background:var(--panel); border:1px solid var(--line); border-radius:12px;
  padding:14px; }}
.stats b {{ display:block; font-size:26px; }} .stats small {{ font-size:12px; }}
.wrap {{ overflow-x:auto; background:var(--panel); border:1px solid var(--line);
  border-radius:12px; }}
table {{ border-collapse:collapse; width:100%; font-size:14px; }}
th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--line);
  white-space:nowrap; }}
th {{ color:var(--muted); font-weight:500; }}
.bar {{ display:inline-block; position:relative; width:90px; height:8px; border-radius:4px;
  background:var(--line); vertical-align:middle; }}
.fill {{ position:absolute; left:0; top:0; bottom:0; border-radius:4px; }}
.fill.good {{ background:var(--good); }} .fill.off {{ background:var(--off); }}
.mark {{ position:absolute; left:80%; top:-3px; bottom:-3px; width:2px; background:var(--text); }}
.yes {{ color:var(--good); }} .no {{ color:var(--off); }}
footer {{ color:var(--muted); font-size:12px; margin-top:32px; }}
</style></head><body><main>
<h1>{html.escape(title)}</h1>
<p class="lead">Честная статистика: только прогнозы, срок которых наступил и которые
сверены с фактической ценой. Ничего не удалено и не подобрано. Ожидают срока: {data['pending']}.
Обновлено {data['generated'].replace('T', ' ')}.</p>
{summary}
{_table("По классам активов", data["by_asset_class"])}
{_table("По горизонту прогноза", data["by_horizon"])}
{_table("По активам", data["by_symbol"])}
{recent_table}
<p class="lead">Как читать: хороший вероятностный прогноз попадает в свой 80%-й интервал
примерно в 80% случаев (вертикальная черта на шкале). Заметно меньше - интервалы слишком
узкие, заметно больше - слишком широкие; система сама подстраивает калибровку. Прогнозы -
статистическая оценка по истории цен, а не инвестиционная рекомендация.</p>
<footer>{html.escape(SIGNATURE)}</footer>
</main></body></html>
"""


__all__ = ["accuracy_data", "render_html"]
