# Third-party notices

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
