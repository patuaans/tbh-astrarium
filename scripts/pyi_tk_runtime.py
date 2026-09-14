"""PyInstaller runtime hook for the bundled Tcl/Tk data directories."""

import os
import sys


if getattr(sys, "frozen", False):
    root = sys._MEIPASS
    os.environ.setdefault("TCL_LIBRARY", os.path.join(root, "_tcl_data"))
    os.environ.setdefault("TK_LIBRARY", os.path.join(root, "_tk_data"))
