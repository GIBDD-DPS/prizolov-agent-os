#!/usr/bin/env bash
# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

# Подготовка Codespace: установка пакета и .env с ключом доступа к веб-интерфейсу.
set -euo pipefail

pip install --quiet --no-warn-script-location -e ".[all]"

if [ ! -f .env ]; then
  key=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
  {
    echo "# Создано .devcontainer/setup.sh. Все параметры: .env.example"
    echo "PRIZOLOV_API_KEYS=$key"
  } > .env
  chmod 600 .env
fi
