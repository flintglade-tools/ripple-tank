"""The application selects Fusion explicitly and does not bundle system theme plugins."""
from pathlib import Path
from PyInstaller.utils.hooks.qt import pyside6_library_info
hiddenimports, binaries, datas = pyside6_library_info.collect_module("PySide6.QtWidgets")
binaries = [row for row in binaries if "plugins" not in Path(row[0]).parts]
