# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Безопасность: защита от инструкций, спрятанных в данных."""

from .injection import DATA_RULE, Finding, scan, unwrap, wrap_untrusted

__all__ = ["DATA_RULE", "Finding", "scan", "unwrap", "wrap_untrusted"]
