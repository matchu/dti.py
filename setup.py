import contextlib

from setuptools import setup

import dti

version = dti.__version__

if version.endswith(("a", "b", "rc")):
    # append version identifier based on commit count
    with contextlib.suppress(Exception):
        import subprocess

        p = subprocess.Popen(
            ["git", "rev-list", "--count", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        out, err = p.communicate()
        if out:
            version += out.decode("utf-8").strip()
        p = subprocess.Popen(
            ["git", "rev-parse", "--short", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        out, err = p.communicate()
        if out:
            version += "+g" + out.decode("utf-8").strip()

with open("requirements.txt") as f:
    requirements = f.read().splitlines()

extras_require = {"test": ["pytest", "pytest-asyncio"]}

setup(
    name="dti.py",
    author="diceroll123",
    url="https://github.com/diceroll123/dti.py",
    version=version,
    license="MIT",
    description="A Python wrapper for the Dress To Impress API",
    python_requires=">=3.7",
    packages=["dti"],
    install_requires=requirements,
    extras_require=extras_require,
)
