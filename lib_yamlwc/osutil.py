import os
import subprocess
import sys


def open_file(path, editor=""):
    editor = (editor or "").strip().strip('"')
    if editor:
        subprocess.Popen([editor, path])
    elif os.name == "nt":
        try:
            os.startfile(path)
        except OSError:  # no file association (e.g. .yaml)
            subprocess.Popen(["notepad.exe", path])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def show_in_explorer(path):
    path = os.path.normpath(path)
    if os.name == "nt":
        subprocess.Popen(f'explorer /select,"{path}"')
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])
