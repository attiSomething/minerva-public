"""Entry point for running from source and for the PyInstaller build."""

import multiprocessing
import sys

from minerva.desktop import main

if __name__ == "__main__":
    # the packaged app starts its library process from this same exe
    multiprocessing.freeze_support()
    sys.exit(main())
