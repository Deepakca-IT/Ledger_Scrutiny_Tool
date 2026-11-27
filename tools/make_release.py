"""Build the update ZIP and its SHA-256 for a GitHub release.

Run from the repository root with a clean, committed working tree:
    python\\python.exe tools\\make_release.py

Output goes to dist\\ (git-ignored). Upload both files to a GitHub release
tagged v<version>, together with the installer from installer_output\\.
"""

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import updater  # noqa: E402


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout


def main():
    if git("status", "--porcelain").strip():
        sys.exit("Commit or discard changes first: the release must match a commit.")
    version = (ROOT / "version.txt").read_text(encoding="utf-8-sig").strip()
    files = [f for f in git("ls-files").splitlines() if updater.ALLOWED.match(f)]
    for need in ("version.txt", "streamlit_app.py", "updater.py", "requirements.txt"):
        if need not in files:
            sys.exit(f"Missing from the release: {need}")
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    out = dist / f"LS_Tool_update_{version}.zip"
    manifest = {"version": version, "commit": git("rev-parse", "HEAD").strip(),
                "requirements_sha256": updater._requirements_hash()}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(ROOT / f, f)
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    out.with_name(out.name + ".sha256").write_text(f"{digest}  {out.name}\n", encoding="ascii")
    print(f"{out.name}: {len(files)} files, {out.stat().st_size // 1024} KB, sha256 {digest}")


if __name__ == "__main__":
    main()
