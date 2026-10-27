"""Bundle only the desktop backends used by this raster Qt application."""
from pathlib import Path
from PyInstaller.utils.hooks.qt import pyside6_library_info
hiddenimports, binaries, datas = pyside6_library_info.collect_module("PySide6.QtGui")

def needed(row):
    source = Path(row[0])
    if "plugins" not in source.parts:
        return True
    category = source.parent.name
    if category == "platforms":
        return source.name in {"libqxcb.so", "libqwayland.so", "libqoffscreen.so", "libqminimal.so"}
    if category == "platforminputcontexts":
        return source.name == "libcomposeplatforminputcontextplugin.so"
    return category in {"xcbglintegrations", "wayland-shell-integration", "wayland-decoration-client", "wayland-graphics-integration-client"}

binaries = [row for row in binaries if needed(row)]
