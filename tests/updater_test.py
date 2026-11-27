"""Offline test of the release build, the updater and the launch-time install.

Run: python\\python.exe -B tests\\updater_test.py
A local web server stands in for GitHub. Everything happens in a temp folder.
"""
import hashlib, http.server, io, json, os, shutil, subprocess, sys, tempfile, threading, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="lstool_upd_"))
APP = TMP / "app"
APP.mkdir()
for f in ("updater.py", "requirements.txt", "run_app.bat"):
    shutil.copy(ROOT / f, APP / f)
(APP / "version.txt").write_text("1.1.0\n")
(APP / "streamlit_app.py").write_text("OLD\n")
WEB = TMP / "web"
WEB.mkdir()
os.environ["LSTOOL_UPDATE_API"] = "http://127.0.0.1:8765/latest.json"
sys.path.insert(0, str(APP))
import updater  # noqa: E402  (the temp copy)


def make_release(version, files, req_hash=None, name=None, tamper=False):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, t in files.items():
            z.writestr(n, t)
        z.writestr("manifest.json", json.dumps({
            "version": version, "requirements_sha256": req_hash or updater._requirements_hash()}))
    data = buf.getvalue()
    name = name or f"LS_Tool_update_{version}.zip"
    (WEB / name).write_bytes(data)
    digest = hashlib.sha256(b"x" if tamper else data).hexdigest()
    (WEB / (name + ".sha256")).write_text(f"{digest}  {name}\n")
    base = "http://127.0.0.1:8765/"
    (WEB / "latest.json").write_text(json.dumps({"tag_name": f"v{version}", "body": "notes", "assets": [
        {"name": name, "browser_download_url": base + name},
        {"name": name + ".sha256", "browser_download_url": base + name + ".sha256"}]}))


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(WEB), **k)

    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8765), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
ok = True


def check(cond, msg):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + msg)


check(updater.is_newer("1.10.0", "1.9.9") and not updater.is_newer("1.1.0", "1.1.0"), "version compare")
make_release("1.1.0", {"version.txt": "1.1.0\n"})
check(updater.check_for_update(force=True)["status"] == "up_to_date", "same version is up to date")

make_release("1.2.0", {"version.txt": "1.2.0\n", "streamlit_app.py": "NEW\n"}, tamper=True)
r = updater.check_for_update(force=True)
check(r["status"] == "update_available", "newer release found")
check(updater.stage_update(r)["status"] == "error" and not updater.READY_FLAG.exists(), "bad checksum refused")

make_release("1.2.0", {"version.txt": "1.2.0\n", "../evil.py": "x"})
check(updater.stage_update(updater.check_for_update(force=True))["status"] == "error", "unsafe path refused")

make_release("1.2.0", {"version.txt": "1.2.0\n", "run_app.bat": "x"})
check(updater.stage_update(updater.check_for_update(force=True))["status"] == "error", "launcher change refused")

make_release("1.2.0", {"version.txt": "1.2.0\n"}, req_hash="different")
check(updater.stage_update(updater.check_for_update(force=True))["status"] == "installer_required",
      "new packages need the installer")

make_release("1.2.0", {"version.txt": "1.2.0\n", "streamlit_app.py": "NEW\n", "engines/x.py": "E\n"})
r = updater.stage_update(updater.check_for_update(force=True))
check(r["status"] == "staged" and updater.staged_version() == "1.2.0", "valid update staged")
check(updater.check_for_update()["status"] == "skipped", "checks only once a day")

# Launch-time install: run only the install block of run_app.bat.
bat = (APP / "run_app.bat").read_text(encoding="utf-8")
block = bat[bat.index("if exist update_ready.txt"):bat.index("rem === LS Tool")]
(APP / "apply_only.bat").write_text("@echo off\r\ncd /d \"%~dp0\"\r\n" + block.replace("\n", "\r\n"))
subprocess.run(["cmd", "/c", str(APP / "apply_only.bat")], check=True)
check((APP / "streamlit_app.py").read_text() == "NEW\n" and (APP / "version.txt").read_text() == "1.2.0\n"
      and (APP / "engines" / "x.py").exists(), "update installed at launch")
check(not updater.STAGING_DIR.exists() and not updater.READY_FLAG.exists(), "staging cleaned up")

(APP / ".git").mkdir()
check(updater.check_for_update(force=True)["status"] == "dev", "development copy never updates")

srv.shutdown()
shutil.rmtree(TMP, ignore_errors=True)
print("ALL PASSED" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
