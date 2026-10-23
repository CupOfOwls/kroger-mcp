"""Read a wheel's declared dependencies, for the lowest-versions test job.

    python floors.py requirements WHEEL   print the wheel's Requires-Dist lines (extras left out), one per
                                          line, to pass to `uv pip install --resolution lowest-direct`
    python floors.py report WHEEL         print each dependency's declared range next to the version
                                          installed in this interpreter, as a Markdown table (also appended
                                          to $GITHUB_STEP_SUMMARY when set)

Passing the requirements as direct requirements is what makes `lowest-direct` apply to them: installing
the wheel alone makes them transitive, and uv then resolves them to the highest versions. When a declared
floor cannot be installed (it does not exist, or another dependency needs more), the resolver picks the
lowest version that works and the report shows the difference.

Runs on the oldest supported Python, so it uses only the standard library and Python 3.8 syntax.
"""

import email
import os
import re
import sys
import zipfile
from importlib.metadata import PackageNotFoundError, version


def requires_dist(wheel):
    with zipfile.ZipFile(wheel) as z:
        names = [n for n in z.namelist() if n.endswith(".dist-info/METADATA")]
        if len(names) != 1:
            sys.exit("{}: expected one .dist-info/METADATA, found {}".format(wheel, len(names)))
        meta = email.message_from_bytes(z.read(names[0]))
    reqs = [r.strip() for r in meta.get_all("Requires-Dist") or []]
    return [r for r in reqs if not re.search(r"\bextra\s*==", r)]


def same_version(a, b):
    """4.5 and 4.5.0 are the same release."""
    def norm(v):
        parts = v.split(".")
        while len(parts) > 1 and parts[-1] == "0":
            parts.pop()
        return parts
    return norm(a) == norm(b)


def main(argv):
    if len(argv) != 2 or argv[0] not in ("requirements", "report"):
        sys.exit(__doc__)
    cmd, wheel = argv
    reqs = requires_dist(wheel)
    if not reqs:
        sys.exit("{}: no Requires-Dist lines; nothing to test at the floors".format(wheel))
    if cmd == "requirements":
        print("\n".join(reqs))
        return
    rows = ["| dependency | declared | installed | at the floor |", "|---|---|---|---|"]
    for req in reqs:
        m = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*([^;]*)", req)
        if not m:
            sys.exit("cannot parse the requirement {!r}".format(req))
        name, spec = m.group(1), m.group(2).strip() or "(any)"
        try:
            installed = version(name)
        except PackageNotFoundError:
            installed = "not installed (environment marker)"
        floor = re.search(r">=\s*([^,\s]+)", spec)
        at_floor = "yes" if floor and same_version(floor.group(1), installed) else ("no" if floor else "no floor")
        rows.append("| {} | {} | {} | {} |".format(name, spec, installed, at_floor))
    table = "\n".join(rows)
    print(table)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("### Lowest dependency versions\n\n" + table + "\n\n")


if __name__ == "__main__":
    main(sys.argv[1:])
