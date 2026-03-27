from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="prizolov-os",
    version="0.1.0",
    author="Dm.Andreyanov",
    author_email="contact@prizolov.ru",
    description="Agentic AI Operating System for autonomous business orchestration",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/GIBDD-DPS/prizolov-agent-os",
    packages=find_packages(),  # ✅ Исправлено: было find_package()
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.9",  # ✅ Добавлено: минимальная версия Python
    entry_points={
        "console_scripts": [
            "prizolov=cli.main:main",  # ✅ Убрана лишняя запятая после элемента
        ],
    },
)
