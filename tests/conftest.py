# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Общие настройки тестов: журнал трассировки не пишется в папку проекта."""

import pytest

from prizolov_os.config import settings


@pytest.fixture(autouse=True)
def _no_trace_files(monkeypatch):
    monkeypatch.setattr(settings, "trace", False)
