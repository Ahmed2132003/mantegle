"""mt.common - moved from montage.py by tools/mt_move.py"""
import os


def clean_path(s):
    s = s.strip()
    if s.startswith("& "):
        s = s[2:].strip()
    return os.path.abspath(os.path.expanduser(s.strip('"').strip("'").strip()))
