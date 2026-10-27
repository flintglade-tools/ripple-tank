#!/usr/bin/env python3
"""Package verified native/browser builds, license texts, provenance and checksums."""
import ast
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tarfile
import tomllib
import zipfile

root=Path(__file__).resolve().parents[1]
out=root/"artifacts"
out.mkdir(exist_ok=True)
version=tomllib.loads((root/"Cargo.toml").read_text())["package"]["version"]
revision=subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip()
if subprocess.check_output(["git","status","--porcelain"],cwd=root,text=True).strip():
    raise SystemExit("Commit the reviewed source before packaging")
base=f"ripple-tank-{version}"
stage=out/"stage"
if stage.exists(): shutil.rmtree(stage)
stage.mkdir()
desktop=stage/(base+"-fedora44-x86_64-desktop")
desktop.mkdir()
shutil.copytree(root/"dist/ripple-tank",desktop/"ripple-tank",symlinks=True)
for name in ["README.md","LICENSE","VERIFICATION.md","install.py"]:
    shutil.copy2(root/name,desktop/name)
shutil.copytree(root/"docs",desktop/"docs")
shutil.copy2(root/"desktop/ripple.svg",desktop/"ripple.svg")
shutil.copy2(root/"target/release/flintglade-ripple",desktop/"ripple")
licenses=desktop/"licenses"
licenses.mkdir()

# Keep actual distribution license texts with every collected RPM runtime.
toc=ast.literal_eval((root/"build/ripple-tank/Analysis-00.toc").read_text())
paths=set()
for section in toc:
    if isinstance(section,list):
        for row in section:
            if isinstance(row,tuple) and len(row)>=3 and isinstance(row[1],str) and row[1].startswith(("/usr/","/lib")) and Path(row[1]).is_file():
                paths.add(str(Path(row[1]).resolve()))
query=subprocess.run(["rpm","-qf","--qf","%{NAME}|%{VERSION}|%{RELEASE}|%{LICENSE}|%{SOURCERPM}\n",*sorted(paths)],text=True,capture_output=True,check=False)
rows=sorted(set(line for line in query.stdout.splitlines() if "|" in line))
rpms=[]
for row in rows:
    name,ver,release,license_name,source=row.split("|",4)
    source_name,source_ver,source_release=source.removesuffix(".src.rpm").rsplit("-",2)
    url=f"https://kojipkgs.fedoraproject.org/packages/{source_name}/{source_ver}/{source_release}/src/{source}"
    rpms.append(dict(name=name,version=ver,release=release,license=license_name,source_rpm=source,corresponding_source=url))
    listed=subprocess.check_output(["rpm","-ql",name],text=True).splitlines()
    for filename in listed:
        p=Path(filename)
        if p.is_file() and (filename.startswith("/usr/share/licenses/") or ("/doc/" in filename and re.search(r"license|copying|copyright|notice",p.name,re.I))):
            target=licenses/"fedora"/name/p.name
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(p,target)

rust=[]
registry=Path.home()/".cargo/registry/src"
for package in tomllib.loads((root/"Cargo.lock").read_text())["package"]:
    if "source" not in package: continue
    crate=next(registry.glob(f"*/{package['name']}-{package['version']}"))
    meta=tomllib.loads((crate/"Cargo.toml").read_text())["package"]
    rust.append(dict(name=package["name"],version=package["version"],checksum=package.get("checksum"),license=meta.get("license"),source=f"https://crates.io/crates/{package['name']}/{package['version']}"))
    for p in crate.iterdir():
        if p.is_file() and re.match(r"license|copying|copyright|notice",p.name,re.I):
            target=licenses/"rust"/crate.name/p.name
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(p,target)
pyinstaller=importlib.metadata.distribution("pyinstaller")
for f in pyinstaller.files or []:
    if re.search(r"copying|license",f.name,re.I) and pyinstaller.locate_file(f).is_file():
        target=licenses/"pyinstaller"/f.name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(pyinstaller.locate_file(f),target)

notices="""# Third-party notices

Project code is MIT licensed. Dependencies retain their own licenses; copies of
the actual license texts accompany the desktop distribution in licenses/.
COMPONENTS.json identifies each bundled Fedora runtime package, exact version,
license expression and corresponding source RPM download URL. Rust component
versions, source checksums and licenses are also listed there.

The desktop uses dynamically linked Qt/PySide/Shiboken under their LGPL option,
Python under its distribution licenses, and the PyInstaller bootloader under
GPL with its bootloader exception. No Qt or other runtime libraries were
modified. The supplied source/build procedure and replaceable shared libraries
allow rebuilding or substituting compatible libraries. The .so files live in
ripple-tank/_internal/ and its Qt subdirectories. User modification and reverse
engineering for debugging those modifications are not restricted by this app.

Qt/PySide upstream source: https://code.qt.io/ and https://download.qt.io/official_releases/.
The exact Fedora patches/build sources are the source RPMs listed in COMPONENTS.json.
The CLI and WASM engine do not link Qt or Python; their Rust dependency licenses
are included in their respective archives. No commercial ROMs or third-party
datasets are bundled.
"""
(root/"THIRD-PARTY-NOTICES.md").write_text(notices)
# Notices are generated deterministically; require the reviewed copy to match.
if subprocess.check_output(["git","diff","--","THIRD-PARTY-NOTICES.md"],cwd=root,text=True).strip():
    raise SystemExit("Review/commit generated THIRD-PARTY-NOTICES.md, then package again")
shutil.copy2(root/"THIRD-PARTY-NOTICES.md",desktop/"THIRD-PARTY-NOTICES.md")
(desktop/"COMPONENTS.json").write_text(json.dumps(dict(rpm=rpms,rust=rust),indent=2)+"\n")
(desktop/"BUILD.json").write_text(json.dumps(dict(version=version,source_revision=revision,platform=platform.platform(),python=platform.python_version(),engine_sha256=hashlib.sha256((root/"target/release/libflintglade_ripple.so").read_bytes()).hexdigest(),wasm_sha256=hashlib.sha256((root/"web/ripple.wasm").read_bytes()).hexdigest()),indent=2)+"\n")

cli=stage/(base+"-fedora44-x86_64-cli")
cli.mkdir()
for name in ["ripple","README.md","LICENSE","VERIFICATION.md","THIRD-PARTY-NOTICES.md","BUILD.json"]: shutil.copy2(desktop/name,cli/name)
shutil.copytree(root/"docs",cli/"docs")
shutil.copytree(licenses/"rust",cli/"licenses/rust")
(cli/"COMPONENTS.json").write_text(json.dumps(dict(rust=rust),indent=2)+"\n")
for bundle in [desktop,cli]:
    sums=[]
    for p in sorted(bundle.rglob("*")):
        if p.is_symlink() and not p.resolve().is_relative_to(bundle.resolve()): raise ValueError("External archive symlink")
        if p.is_file(): sums.append(hashlib.sha256(p.read_bytes()).hexdigest()+"  "+str(p.relative_to(bundle)))
    (bundle/"SHA256SUMS").write_text("\n".join(sums)+"\n")
    with tarfile.open(out/(bundle.name+".tar.gz"),"w:gz") as archive: archive.add(bundle,arcname=bundle.name)
with zipfile.ZipFile(out/(base+"-web.zip"),"w",zipfile.ZIP_DEFLATED) as archive:
    for p in sorted((root/"web").iterdir()):
        if p.is_file() and p.name!="workspace.html":archive.write(p,"web/"+p.name)
    for name in ["README.md","LICENSE","VERIFICATION.md","THIRD-PARTY-NOTICES.md"]:archive.write(root/name,name)
    for p in (licenses/"rust").rglob("*"):
        if p.is_file():archive.write(p,"licenses/rust/"+str(p.relative_to(licenses/"rust")))
with zipfile.ZipFile(out/(base+"-source.zip"),"w",zipfile.ZIP_DEFLATED) as archive:
    for filename in subprocess.check_output(["git","ls-files"],cwd=root,text=True).splitlines():archive.write(root/filename,filename)
artifacts=sorted([*out.glob("*.tar.gz"),*out.glob("*.zip")])
(out/"SHA256SUMS").write_text("\n".join(hashlib.sha256(p.read_bytes()).hexdigest()+"  "+p.name for p in artifacts)+"\n")
print(json.dumps(dict(source_revision=revision,runtime_packages=len(rpms),artifacts=[dict(name=p.name,bytes=p.stat().st_size) for p in artifacts])))
