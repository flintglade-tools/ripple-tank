#!/usr/bin/env python3
"""Install/uninstall the extracted desktop bundle without administrator access."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile
import uuid


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path):
    try:
        st = path.lstat()
        return st.st_dev, st.st_ino
    except FileNotFoundError:
        return None


def uninstall(prefix, menu, marker):
    record = json.loads(marker.read_text())
    if record.get("application") != "flintglade-ripple" or record.get("menu") != str(menu) or not isinstance(record.get("files"), dict):
        raise ValueError("Installation identity does not match; no files removed")
    entries = []
    # Validate every recorded path before removing any software file.
    for name, expected in record["files"].items():
        rel = PurePosixPath(name)
        if rel.is_absolute() or ".." in rel.parts or not rel.parts or not isinstance(expected, dict):
            raise ValueError("Invalid installed-file record; no files removed")
        entries.append((prefix.joinpath(*rel.parts), expected))
    if menu.is_file() and not menu.is_symlink() and digest(menu) == record.get("menu_sha256"):
        menu.unlink()
    for path, expected in entries:
        if not path.parent.resolve().is_relative_to(prefix):
            continue
        if expected.get("kind") == "symlink":
            if path.is_symlink() and os.readlink(path) == expected.get("target"):
                path.unlink()
        elif expected.get("kind") == "file" and path.is_file() and not path.is_symlink() and digest(path) == expected.get("sha256"):
            path.unlink()
    marker.unlink()
    for name in sorted(record.get("directories", []), key=lambda value: len(PurePosixPath(value).parts), reverse=True):
        rel = PurePosixPath(name)
        if rel.is_absolute() or ".." in rel.parts:
            continue
        path = prefix.joinpath(*rel.parts)
        if path.is_symlink() or not path.parent.resolve().is_relative_to(prefix):
            continue
        try:
            path.rmdir()
        except OSError:
            pass
    try:
        prefix.rmdir()
    except OSError:
        pass
    print(json.dumps({"ok": True, "uninstalled": str(prefix), "user_or_modified_files_preserved": True,
                      "prefix_retained": prefix.exists(), "menu_retained": menu.exists()}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, default=Path.home()/".local/opt/flintglade-ripple")
    parser.add_argument("--applications-dir", type=Path, default=Path.home()/".local/share/applications")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    prefix = args.prefix.absolute()
    apps = args.applications_dir.absolute()
    if prefix.is_symlink() or any(c in str(prefix)+str(apps) for c in "\n\r\t\x00"):
        raise ValueError("Invalid installation path")
    prefix = prefix.resolve()
    if any(c in str(prefix) for c in ['%', '"', "\\", '$', '`']):
        raise ValueError("Choose an installation path without %, double quotes, backslashes, $ or backticks")
    menu = apps/"flintglade-ripple.desktop"
    marker = prefix/".flintglade-ripple-install.json"
    if args.uninstall:
        uninstall(prefix, menu, marker)
        return
    if prefix.exists():
        raise ValueError("Installation path already exists; move retained files or choose another path")
    if prefix.is_relative_to(source) or source.is_relative_to(prefix):
        raise ValueError("Install outside the extracted bundle")
    if not (source/"ripple-tank/ripple-tank").is_file():
        raise ValueError("Run install.py from the extracted desktop release")
    if menu.exists():
        raise ValueError("Application entry already exists; no files changed")
    prefix.parent.mkdir(parents=True, exist_ok=True)
    apps.mkdir(parents=True, exist_ok=True)
    owned_prefix = None
    owned_menu = None
    temp_menu = None
    try:
        # Atomic ownership claim: a competing installer cannot be mistaken for this one.
        prefix.mkdir(exist_ok=False)
        owned_prefix = identity(prefix)
        shutil.copytree(source, prefix, symlinks=True, dirs_exist_ok=True)
        files = {}
        directories = []
        for path in sorted(prefix.rglob("*")):
            name = str(path.relative_to(prefix))
            if path.is_symlink():
                if not path.resolve().is_relative_to(prefix):
                    raise ValueError("External installation symlink")
                files[name] = {"kind": "symlink", "target": os.readlink(path)}
            elif path.is_file():
                files[name] = {"kind": "file", "sha256": digest(path)}
            elif path.is_dir():
                directories.append(name)
        install_id = uuid.uuid4().hex
        executable = str(prefix/"ripple-tank/ripple-tank").replace('%', '%%')
        quoted = executable.replace("\\", "\\\\").replace('"', '\\"').replace('`', '\\`').replace('$', '\\$')
        exe = ('"'+quoted+'"').replace("\\", "\\\\")
        icon = str(prefix/"ripple.svg").replace("\\", "\\\\")
        desktop = f'[Desktop Entry]\nType=Application\nName=Ripple Tank\nComment=Flintglade gravity-capillary wave workspace\nExec={exe}\nIcon={icon}\nTerminal=false\nCategories=Education;Science;Physics;\nX-Flintglade-Ripple-Install-ID={install_id}\n'
        record = {"application": "flintglade-ripple", "install_id": install_id, "menu": str(menu),
                  "menu_sha256": hashlib.sha256(desktop.encode()).hexdigest(), "files": files, "directories": directories}
        with marker.open("x") as f:
            json.dump(record, f)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf8", dir=apps, prefix=".ripple-menu-", delete=False) as f:
            temp_menu = Path(f.name)
            f.write(desktop)
            f.flush()
            os.fsync(f.fileno())
        temp_menu.chmod(0o644)
        # Publishing the complete menu entry fails atomically if another entry exists.
        os.link(temp_menu, menu)
        owned_menu = identity(menu)
    except Exception:
        if owned_menu is not None and identity(menu) == owned_menu:
            menu.unlink()
        if owned_prefix is not None and identity(prefix) == owned_prefix:
            shutil.rmtree(prefix)
        raise
    finally:
        if temp_menu is not None:
            temp_menu.unlink(missing_ok=True)
    print(json.dumps({"ok": True, "installed": str(prefix), "menu": str(menu)}))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=sys.stderr)
        sys.exit(1)
