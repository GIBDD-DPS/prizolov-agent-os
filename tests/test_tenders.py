# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Госзакупки: разбор ленты ЕИС, новые закупки, специалист (без сети)."""

import argparse
import io
import json
import urllib.parse

import pytest
from rich.console import Console

from prizolov_os.agents.specialists import create_tender_analyst
from prizolov_os.config import settings
from prizolov_os.llm import FakeLLMClient, tool_use_response
from prizolov_os.memory import Store
from prizolov_os.tenders import TenderSearch, TenderSearchError, build_url, parse_rss

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>ЕИС</title>
<item>
  <title>Закупка № 0373100000126000123</title>
  <link>/epz/order/notice/ea20/view/common-info.html?regNumber=0373100000126000123</link>
  <description>&lt;strong&gt;Размещение выполняется по: &lt;/strong&gt;44-ФЗ&lt;br/&gt;
  &lt;strong&gt;Наименование Заказчика: &lt;/strong&gt;ГБУ &amp;quot;Школа № 1&amp;quot;&lt;br/&gt;
  &lt;strong&gt;Наименование объекта закупки: &lt;/strong&gt;Поставка офисной мебели&lt;br/&gt;
  &lt;strong&gt;Начальная цена контракта: &lt;/strong&gt;1 234 567,89&lt;br/&gt;
  &lt;strong&gt;Валюта: &lt;/strong&gt;Российский рубль&lt;br/&gt;
  &lt;strong&gt;Этап размещения: &lt;/strong&gt;Подача заявок&lt;br/&gt;
  &lt;strong&gt;Размещено: &lt;/strong&gt;05.10.2026&lt;br/&gt;
  &lt;strong&gt;Окончание подачи заявок: &lt;/strong&gt;15.10.2026&lt;br/&gt;</description>
  <pubDate>Mon, 05 Oct 2026 10:00:00 +0300</pubDate>
</item>
<item>
  <title>Закупка № 32615000001</title>
  <link>https://zakupki.gov.ru/epz/order/notice/notice223/common-info.html?regNumber=32615000001</link>
  <description>&lt;strong&gt;Размещение выполняется по: &lt;/strong&gt;223-ФЗ&lt;br/&gt;
  &lt;strong&gt;Наименование закупки: &lt;/strong&gt;Мебель для столовой&lt;br/&gt;</description>
</item>
</channel></rss>""".encode("utf-8")


def fetch_stub(urls):
    def fetch(url):
        urls.append(url)
        return RSS
    return fetch


def test_build_url():
    url = build_url("офисная мебель", laws=("44",), max_price=2_000_000)
    params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert params["searchString"] == ["офисная мебель"] and params["fz44"] == ["on"]
    assert "fz223" not in params and params["priceToGeneral"] == ["2000000"]
    assert params["af"] == ["on"]


def test_parse_rss_fields():
    first, second = parse_rss(RSS)
    assert first.number == "0373100000126000123"
    assert first.title == "Поставка офисной мебели"
    assert first.customer == 'ГБУ "Школа № 1"'
    assert first.price == pytest.approx(1234567.89)
    assert first.law == "44-ФЗ" and first.stage == "Подача заявок"
    assert first.deadline == "15.10.2026" and first.url.startswith("https://zakupki.gov.ru/")
    assert second.number == "32615000001" and second.title == "Мебель для столовой"
    assert second.price is None


def test_bad_feed():
    with pytest.raises(TenderSearchError):
        parse_rss(b"<html>captcha</html")


def test_only_new_and_validation():
    urls = []
    search = TenderSearch(Store(), fetch_stub(urls))
    assert all(t.new for t in search.search("мебель"))
    assert search.search("мебель", only_new=True) == []
    assert [t.new for t in search.search("мебель")] == [False, False]
    with pytest.raises(ValueError):
        search.search("ab")
    assert len(urls) == 3


def test_cli(tmp_path, monkeypatch):
    from cli.main import run_tenders

    monkeypatch.setattr(settings, "db_path", str(tmp_path / "db.sqlite"))
    out = io.StringIO()
    args = argparse.Namespace(query=["офисная", "мебель"], max_price=0, new=False)
    assert run_tenders(Console(file=out, width=220), args, fetch=fetch_stub([])) == 0
    assert "Поставка офисной мебели" in out.getvalue() and "1 234 568" in out.getvalue()

    def broken(url):
        raise TenderSearchError("Нет связи с zakupki.gov.ru")

    out = io.StringIO()
    assert run_tenders(Console(file=out), args, fetch=broken) == 1
    assert "Нет связи" in out.getvalue()


def test_tender_analyst_searches(tmp_path, monkeypatch):
    monkeypatch.setattr("prizolov_os.tenders._http_get", lambda url: RSS)
    llm = FakeLLMClient([
        tool_use_response("search_tenders", {"query": "офисная мебель", "max_price": 0,
                                             "only_new": True}),
        "Найдена закупка 0373100000126000123",
    ])
    agent = create_tender_analyst(llm=llm, workspace_dir=tmp_path, store=Store())
    assert "Найдена" in agent.run("Найди тендеры на мебель").text
    sent = json.dumps(llm.calls[1]["messages"], ensure_ascii=False)
    assert "untrusted_data" in sent and "0373100000126000123" in sent
    assert {"search_tenders", "compare_documents", "read_file"} <= set(agent.tools.names())
