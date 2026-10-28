"""Runs without the WebUI: python selftest.py [folder] — checks all wildcards."""
import os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_yamlwc.core import WildcardStore, RandomChooser, Track

d = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "wildcards")
s = WildcardStore(d); s.refresh(force=True)
r = s.diagnose()
labels = {"errors": "LOAD ERROR", "missing": "MISSING REFERENCE", "empty_refs": "POINTS TO EMPTY",
          "empty": "EMPTY", "dup_keys": "DEFINED TWICE", "dup_names": "SAME FILE NAME"}
for k, lab in labels.items():
    for line, _ in r[k][:200]:
        print(f"{lab}: {line}")
bad = 0
for key in sorted(s.entries):
    out = s.resolve(f"__{key}__", RandomChooser(random.Random(1)), Track())
    if "{" in out.replace("${", ""):
        print(f"UNCLOSED BRACE in __{key}__"); bad += 1
print(f"{s.file_count()} files, {len(s.entries)} wildcards checked — "
      + ("all fine" if not (bad or r['errors'] or r['missing']) else "please review the messages above"))
