# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Версия и авторство Prizolov Agent OS (единственный источник этих данных)."""

__title__ = "Prizolov Agent OS"
__version__ = "0.3.0"
__author__ = "Dm.Andreyanov"
__brand__ = "Prizolov Lab"
__year__ = "2026"
__email__ = "contact@prizolov.ru"
__url__ = "https://prizolov.ru"
__license__ = "Apache-2.0"
__copyright__ = f"© {__year__} {__author__} / {__brand__}"

# Уникальный идентификатор проекта. Записывается в базу данных, заголовки запросов
# и подписи файлов: по нему можно опознать копию этого кода.
PROJECT_ID = "PZL-AOS-a370d8738cd146fa"

HEADER = (
    f"{__title__} {__version__} | Author: {__author__} | Brand: {__brand__} | © {__year__}"
)
SIGNATURE = f"Создано в {__title__} {__version__} · {__copyright__} · {__url__}"
USER_AGENT = f"Prizolov-Agent-OS/{__version__} ({__brand__}; {__author__}; {PROJECT_ID})"
