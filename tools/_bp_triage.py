import collections
import json
import os
import sys

_bp_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/bp.json"
with open(_bp_path) as _fh:
    d = json.load(_fh)
diags = [x for x in d.get("generalDiagnostics", []) if x.get("severity") == "error"]
cwd = os.getcwd()


def rel(p):
    return os.path.relpath(p, cwd).replace(os.sep, "/")


print("TOTAL errors:", len(diags))
print("\n=== by rule (top 25) ===")
for r, c in collections.Counter(x.get("rule", "<none>") for x in diags).most_common(25):
    print(f"{c:5}  {r}")
print("\n=== by file (all, desc) ===")
byfile = collections.Counter(rel(x["file"]) for x in diags)
for f, c in byfile.most_common():
    print(f"{c:5}  {f}")
print("\nfiles with errors:", len(byfile))
