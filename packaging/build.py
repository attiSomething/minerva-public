"""Build the Minerva desktop app with PyInstaller.

    python packaging/build.py

Produces, with the server, the page and the help docs inside:
- Windows: dist/Minerva.exe, a single file
- macOS: dist/Minerva.app
- Linux: dist/Minerva, a single file (its window uses Qt's web view)
"""

import os
import sys

import PyInstaller.__main__

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def data(rel):
    src = os.path.join(ROOT, rel)
    return f"{src}{os.pathsep}{rel}"


def main():
    args = [
        os.path.join(ROOT, "run_minerva.py"),
        "--name", "Minerva",
        "--windowed",
        "--noconfirm",
        "--clean",
        "--add-data", data("minerva/templates"),
        "--add-data", data("minerva/static"),
        "--add-data", data("minerva/docs"),
        "--collect-submodules", "keyring",
        "--collect-submodules", "webview",
        "--collect-submodules", "anthropic",
        "--collect-all", "pypdfium2",
        "--collect-all", "pypdfium2_raw",
        "--collect-data", "docx",
        "--collect-data", "reportlab",
        "--collect-submodules", "reportlab",
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", os.path.join(ROOT, "build"),
        "--specpath", os.path.join(ROOT, "build"),
    ]
    if sys.platform == "darwin":
        # a one-file .app unpacks itself on every launch and macOS frowns
        # on it, so the Mac build is a normal app folder
        args += ["--onedir", "--icon", os.path.join(HERE, "owl-512.png"),
                 "--osx-bundle-identifier", "io.github.attisomething.minerva"]
    else:
        args += ["--onefile", "--icon", os.path.join(HERE, "minerva.ico")]
    if sys.platform.startswith("linux"):
        args += ["--hidden-import", "qtpy",
                 "--hidden-import", "PyQt6.QtWebEngineWidgets",
                 "--hidden-import", "PyQt6.QtWebEngineCore",
                 "--hidden-import", "PyQt6.QtWebChannel",
                 "--hidden-import", "PyQt6.QtNetwork",
                 "--hidden-import", "PyQt6.QtPrintSupport"]
    if sys.platform == "win32":
        args += ["--version-file", os.path.join(HERE, "version_info.txt")]
        # shown while the one-file app unpacks, before Python starts; the
        # launch screen in the window takes over from it
        args += ["--splash", os.path.join(HERE, "splash.png")]
    PyInstaller.__main__.run(args)


if __name__ == "__main__":
    main()
