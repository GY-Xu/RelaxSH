"""Legacy setuptools shim for older editable installs."""

from pathlib import Path

from setuptools import find_packages, setup


ROOT = Path(__file__).parent.resolve()


def read_version() -> str:
    namespace = {}
    version_file = ROOT / "src" / "relaxsh" / "__init__.py"
    exec(version_file.read_text(encoding="utf-8"), namespace)
    return namespace["__version__"]


setup(
    name="relaxsh",
    version=read_version(),
    description="A cross-platform terminal slacking companion focused on novel reading.",
    long_description=(ROOT / "README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    author="xgy",
    python_requires=">=3.8",
    package_dir={"": "src"},
    packages=find_packages("src"),
    package_data={"relaxsh": ["data/*.txt"]},
    include_package_data=True,
    install_requires=[],
    extras_require={
        "release": ["build>=1.2", "pyinstaller>=6.0"],
        "dev": ["build>=1.2", "pyinstaller>=6.0"],
    },
    entry_points={"console_scripts": ["relaxsh=relaxsh.cli:main"]},
)
