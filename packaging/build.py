"""Build the Minerva desktop app with PyInstaller.

    python packaging/build.py

Produces dist/Minerva.exe on Windows (dist/Minerva elsewhere): a single file
with the server, the page, and the help docs inside it.
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
        "--onefile",
        "--windowed",
        "--noconfirm",
        "--clean",
        "--icon", os.path.join(HERE, "minerva.ico"),
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
    if sys.platform == "win32":
        args += ["--version-file", os.path.join(HERE, "version_info.txt")]
        # shown while the one-file app unpacks, before Python starts; the
        # launch screen in the window takes over from it
        args += ["--splash", os.path.join(HERE, "splash.png")]
    PyInstaller.__main__.run(args)


if __name__ == "__main__":
    main()
