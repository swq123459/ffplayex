import sys
import os


def get_exe_path(filename):
    if getattr(sys, 'frozen', False):  # running as a bundled app
        base_path = sys._MEIPASS
    else:
        base_path = ""
    return os.path.join(base_path, filename)
