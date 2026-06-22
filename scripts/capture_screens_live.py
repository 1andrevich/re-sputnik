# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Capture a PNG of every app screen against a LIVE router connection.

Unlike capture_screens.py (fake MagicMock client = empty pages), this connects
to a real router over SSH (app key, password fallback from the OS keychain),
detects real state, and lets each screen's async/threaded loaders actually
finish before grabbing — so the screenshots show real data, fully loaded.

Windows-only (ImageGrab grabs the desktop region). Each window flashes briefly.
Read-only: it only opens screens; destructive actions are all button-gated.

Run:  python scripts/capture_screens_live.py [host]
Out:  docs/design/screenshots_live/<name>.png
"""
from __future__ import annotations

import json
import os
import sys
import time

import customtkinter as ctk
from PIL import ImageGrab

sys.path.insert(0, "src")
from re_sputnik import secrets as app_secrets  # noqa: E402
from re_sputnik.profiles import _config_dir  # noqa: E402
from re_sputnik.router import RouterClient  # noqa: E402
from re_sputnik.router.state import detect_state  # noqa: E402
from re_sputnik.ui.theme import apply_theme  # noqa: E402

OUT = os.path.join("docs", "design", "screenshots_live")
W, H = 980, 720
P = None

# Per-screen settle seconds — heavy screens (many SSH round-trips / live probes)
# need longer to fully populate before the grab.
SETTLE = {
    "adv_overview": 32, "adv_diagnostics": 35, "adv_advanced": 32, "08_verify": 35,
    "03_internet": 14, "04_software": 14, "05_preinstall": 14, "adv_core": 14,
    "06_quick_nodes": 14, "07_wifi_ap": 14, "adv_nodes": 12, "adv_rules": 12,
    "adv_access": 14, "adv_byedpi": 14, "02_firstrun": 10, "10_security": 10,
}
DEFAULT_SETTLE = 8


def most_recent_host() -> str:
    try:
        with open(os.path.join(_config_dir(), "routers.json"), encoding="utf-8") as f:
            profs = json.load(f)
        profs.sort(key=lambda p: p.get("last_connected", 0), reverse=True)
        return profs[0]["host"], int(profs[0].get("port", 22)), profs[0].get("user", "root")
    except Exception:
        return "192.168.1.1", 22, "root"


def connect(host: str, port: int, user: str) -> RouterClient:
    ident = None
    try:
        ident = app_secrets.load_or_create_app_identity()
    except Exception as e:  # noqa: BLE001
        print(f"(no app key: {e})")
    pw = app_secrets.get_router_password(host)
    cl = RouterClient(host, port=port, username=user,
                      pkey=ident.pkey if ident else None, password=pw,
                      expected_fingerprint=None)
    cl.connect()
    return cl, (ident.public_line if ident else None)


def cases(cl, st, cb):
    from re_sputnik.ui.about_screen import AboutScreen
    from re_sputnik.ui.access_screen import AccessScreen
    from re_sputnik.ui.advanced_screen import AdvancedScreen
    from re_sputnik.ui.byedpi_screen import ByeDPIScreen
    from re_sputnik.ui.connect_screen import ConnectScreen
    from re_sputnik.ui.core_screen import CoreScreen
    from re_sputnik.ui.diagnostics_screen import DiagnosticsScreen
    from re_sputnik.ui.finalize_screen import FinalizeScreen
    from re_sputnik.ui.firstrun_screen import FirstRunScreen
    from re_sputnik.ui.internet_screen import InternetScreen
    from re_sputnik.ui.nodes_screen import NodesScreen
    from re_sputnik.ui.overview_screen import OverviewScreen
    from re_sputnik.ui.preinstall_screen import PreinstallScreen
    from re_sputnik.ui.quick_nodes_screen import QuickNodesScreen
    from re_sputnik.ui.rules_screen import RulesScreen
    from re_sputnik.ui.security_screen import SecurityScreen
    from re_sputnik.ui.software_screen import SoftwareScreen
    from re_sputnik.ui.verify_screen import VerifyScreen
    from re_sputnik.ui.wifi_ap_screen import WifiApScreen
    return [
        ("01_connect", lambda m: ConnectScreen(m, P, on_connected=cb, on_back=cb)),
        ("02_firstrun", lambda m: FirstRunScreen(m, P, cl, st, on_done=cb, on_back=cb)),
        ("03_internet", lambda m: InternetScreen(m, P, cl, on_done=cb)),
        ("04_software", lambda m: SoftwareScreen(m, P, cl, on_done=cb)),
        ("05_preinstall", lambda m: PreinstallScreen(m, P, cl, on_done=cb, on_continue=cb)),
        ("06_quick_nodes", lambda m: QuickNodesScreen(m, P, cl, on_done=cb)),
        ("07_wifi_ap", lambda m: WifiApScreen(m, P, cl, on_done=cb)),
        ("08_verify", lambda m: VerifyScreen(m, P, cl, on_done=cb)),
        ("09_finalize", lambda m: FinalizeScreen(m, P, cl, on_done=cb)),
        ("10_security", lambda m: SecurityScreen(m, P, cl, on_back=cb)),
        ("adv_overview", lambda m: OverviewScreen(m, P, cl)),
        ("adv_nodes", lambda m: NodesScreen(m, P, cl)),
        ("adv_rules", lambda m: RulesScreen(m, P, cl)),
        ("adv_access", lambda m: AccessScreen(m, P, cl)),
        ("adv_byedpi", lambda m: ByeDPIScreen(m, P, cl)),
        ("adv_core", lambda m: CoreScreen(m, P, cl, st)),
        ("adv_diagnostics", lambda m: DiagnosticsScreen(m, P, cl)),
        ("adv_advanced", lambda m: AdvancedScreen(m, P, cl)),
        ("11_about", lambda m: AboutScreen(m, P)),
    ]


def grab(name, build) -> bool:
    win = ctk.CTk()
    win.geometry(f"{W}x{H}")
    win.title(name)
    # CRITICAL: run_async delivers results via a queue drained by a pump loop that
    # the app installs once at startup. Without it, every screen hangs on
    # "loading" forever. Install it per window (each is its own Tk root).
    from re_sputnik.ui import kit, worker
    worker.install(win)
    # CTkImages are cached module-level bound to the root that created them; clear
    # so each window recreates its icons (else "pyimage … doesn't exist" on reuse).
    kit._icon_cache.clear()
    try:
        scr = build(win)
        scr.pack(fill="both", expand=True)
        win.update_idletasks()
        win.deiconify()
        win.lift()
        win.attributes("-topmost", True)
        end = time.time() + SETTLE.get(name, DEFAULT_SETTLE)
        while time.time() < end:
            win.update()
            time.sleep(0.03)
        x, y = win.winfo_rootx(), win.winfo_rooty()
        w, h = win.winfo_width(), win.winfo_height()
        ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(os.path.join(OUT, f"{name}.png"))
        print(f"OK   {name}.png")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"FAIL {name}: {type(e).__name__}: {e}")
        return False
    finally:
        win.destroy()


def main() -> int:
    global P
    os.makedirs(OUT, exist_ok=True)
    P = apply_theme("dark")
    host, port, user = (sys.argv[1], 22, "root") if len(sys.argv) > 1 else most_recent_host()
    print(f"Connecting to {user}@{host}:{port} …")
    try:
        cl, pub = connect(host, port, user)
    except Exception as e:  # noqa: BLE001
        print(f"CONNECT FAILED: {type(e).__name__}: {e}")
        return 2
    print("Connected. Detecting state…")
    st = detect_state(cl, our_public_key=pub)
    print(f"State: reachable={st.reachable} openwrt={st.is_openwrt}")
    only = {n for n in os.environ.get("CAP_ONLY", "").split(",") if n}
    items = [(n, b) for n, b in cases(cl, st, lambda *a, **k: None) if not only or n in only]
    ok = sum(grab(n, b) for n, b in items)
    total = len(items)
    cl.close()
    print(f"--- {ok}/{total} screenshots written to {OUT}")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
