from setuptools import setup, find_packages

setup(
    name="prizolov-os",
    version="0.1.0",
    packages=find_packages(),  # ✅ Исправить find_packages (с 's')
    entry_points={
        'console_scripts': [
            'prizolov=cli.main:main',  # ✅ Убрать лишнюю запятую
        ],
    },
    python_requires=">=3.9",  # ✅ Указать версию Python
)