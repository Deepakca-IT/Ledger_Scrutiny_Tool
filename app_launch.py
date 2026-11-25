"""
app_launch.py — desktop-style launcher for LS Tool.

Starts the Streamlit server on a FREE port (headless, no auto-opened browser),
opens it in a chromeless Edge/Chrome "app" window, then blocks. When the user
closes that window the launcher shuts the server down — so the whole thing opens
and closes like a single application.

Multiple independent instances are allowed: each launch grabs its own free port
and its own throwaway browser profile, so a second click just starts another one.

Launched hidden by LS_Tool.vbs -> run_app.bat, so no console window is visible.
Teardown uses taskkill /T to also stop any child processes Streamlit spawned.
"""
import os
import time
import socket
import shutil
import tempfile
import subprocess
import urllib.request
import urllib.parse
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)

CREATE_NO_WINDOW = 0x08000000
PY = os.path.join(HERE, "python", "python.exe")


def _free_port():
    """Ask the OS for an unused loopback port (supports multiple instances)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _find_browser():
    """First Chromium browser that supports --app mode, or None."""
    for p in (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ):
        if os.path.exists(p):
            return p
    for exe in ("msedge", "chrome"):
        w = shutil.which(exe)
        if w:
            return w
    return None


def _wait_healthy(port, timeout=90):
    """Poll Streamlit's health endpoint until it responds 'ok' (or timeout)."""
    deadline = time.time() + timeout
    paths = (f"http://127.0.0.1:{port}/_stcore/health",
             f"http://127.0.0.1:{port}/healthz")
    while time.time() < deadline:
        for url in paths:
            try:
                with urllib.request.urlopen(url, timeout=2) as r:
                    if r.status == 200 and r.read().strip() == b"ok":
                        return True
            except Exception:
                pass
        time.sleep(0.4)
    return False


def main():
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    profile = os.path.join(tempfile.gettempdir(), f"lstool_edge_{port}")

    server = subprocess.Popen(
        [PY, "-m", "streamlit", "run", "streamlit_app.py",
         "--server.port", str(port),
         "--server.address", "127.0.0.1",
         "--server.headless", "true",
         "--browser.gatherUsageStats", "false",
         "--client.toolbarMode", "minimal"],
        cwd=HERE, creationflags=CREATE_NO_WINDOW)

    try:
        browser = _find_browser()
        if browser:
            # Open the window INSTANTLY at splash.html (a spinner) — it polls the
            # server and redirects itself to the app the moment it's ready, so
            # there's no blank gap during the ~3-5s boot. The target URL rides in
            # the hash. A unique --user-data-dir forces a fresh, trackable browser
            # process (otherwise Edge hands off to an existing window and returns
            # immediately, breaking the close-detection).
            splash = (Path(HERE, "splash.html").as_uri()
                      + "#" + urllib.parse.quote(url, safe=""))
            win = subprocess.Popen(
                [browser, f"--app={splash}", f"--user-data-dir={profile}",
                 "--no-first-run", "--no-default-browser-check"])
            win.wait()                     # blocks until the app window closes
        else:
            # No Chromium browser found: degrade to the default browser (no
            # splash, no close-detection — server ends when the process is killed).
            _wait_healthy(port)
            import webbrowser
            webbrowser.open(url)
            server.wait()
    finally:
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(server.pid)],
                           creationflags=CREATE_NO_WINDOW,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    main()
