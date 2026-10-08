# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Готовые специалисты Prizolov OS."""

from .specialists import (
    create_assistant,
    create_cashflow_analyst,
    create_market_analyst,
    create_researcher,
    create_specialists,
    create_writer,
)

__all__ = [
    "create_assistant",
    "create_cashflow_analyst",
    "create_market_analyst",
    "create_researcher",
    "create_specialists",
    "create_writer",
]
