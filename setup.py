from setuptools import setup, find_packages

setup(
    name="prizolov-os",
    version="0.1.0",
    packages=find_packages(),
    entry_points={
        'console_scripts': [
            'prizolov=cli.main:main',
        ],
    },
)
