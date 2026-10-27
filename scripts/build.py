#!/usr/bin/env python3
"""Build the pinned Rust targets and assemble browser assets."""
import argparse
import os
import re
from pathlib import Path
import shutil
import subprocess
import tomllib

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--desktop",action="store_true")
parser.add_argument("--site-path",type=Path,help="Optional isolated Flintglade source checkout to synchronize")
args=parser.parse_args()
version=tomllib.loads((root/"Cargo.toml").read_text())["package"]["version"]
for extra in [[],["--lib","--target","wasm32-unknown-unknown"]]:
    subprocess.run(["cargo","build","--release","--locked","-j","2",*extra],cwd=root,check=True)
shutil.copy2(root/"target/wasm32-unknown-unknown/release/flintglade_ripple.wasm",root/"web/ripple.wasm")
(root/"web/ripple.wasm").chmod(0o644)
# One workspace fragment supplies the standalone wrapper and the Labs wrapper.
workspace=(root/"web/workspace.html").read_text().rstrip()+"\n"
def replace_workspace(path):
    html=path.read_text()
    start=html.index("<main")
    end=html.index("</main>",start)+len("</main>")
    path.write_text(html[:start]+workspace+html[end:].lstrip("\r\n"))
replace_workspace(root/"web/index.html")
if args.site_path:
    labs=args.site_path.resolve()/"publisher/labs"
    page=labs/"ripple-tank.html"
    replace_workspace(page)
    html=page.read_text()
    if "'wasm-unsafe-eval'" not in html: html=html.replace("script-src 'self'", "script-src 'self' 'wasm-unsafe-eval'",1)
    if "worker-src 'self'" not in html: html=html.replace("manifest-src 'self'", "worker-src 'self'; manifest-src 'self'",1)
    html=re.sub(r'(?:ripple-tank|ripple-workbench)\.js(?:\?v=[^" ]+)?',f'ripple-workbench.js?v={version}',html)
    if 'href="ripple-workbench.css' not in html:html=html.replace('</head>',f'<link rel="stylesheet" href="ripple-workbench.css?v={version}">\n</head>')
    page.write_text(html)
    for src,dst in [("app.js","ripple-workbench.js"),("ripple-worker.js","ripple-worker.js"),("ripple-workbench.css","ripple-workbench.css"),("ripple.wasm","ripple.wasm")]:shutil.copy2(root/"web"/src,labs/dst)

if args.desktop:
    env=os.environ.copy()
    env["PYINSTALLER_CONFIG_DIR"]=str(root/"build/pyinstaller-cache")
    subprocess.run([str(root/".packaging/bin/python"),"-m","PyInstaller","--noconfirm","--onedir","--name","ripple-tank","--additional-hooks-dir","scripts/hooks","--exclude-module","PySide6.QtNetwork","--exclude-module","PySide6.QtDBus","--add-binary","target/release/libflintglade_ripple.so:.","desktop/ripple.py"],cwd=root,env=env,check=True)
