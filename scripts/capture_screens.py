# SPDX-License-Identifier: GPL-2.0-only
"""Capture a PNG of every app screen for the design docs.

Builds each screen against a fake router client (same construction as
``smoke_screens.py``), shows it briefly in a 900x650 window, and grabs the
window region with Pillow's ImageGrab. Windows-only (ImageGrab on the desktop);
each window flashes on screen for a moment — that's expected.

Run:  python scripts/capture_screens.py
Out:  docs/design/screenshots/<name>.png
"""
from __future__ import annotations

import os
import sys
import time
import types
from unittest.mock import MagicMock

import customtkinter as ctk
from PIL import ImageGrab

sys.path.insert(0, "src")
from re_sputnik.router.state import RouterState  # noqa: E402
from re_sputnik.ui.theme import apply_theme  # noqa: E402

OUT = os.path.join("docs", "design", "screenshots")
W, H = 900, 650
SETTLE = 0.6  # seconds to let async/threaded content render before grabbing


def fake_client() -> MagicMock:
    c = MagicMock()
    c.host = "192.168.1.1"
    c.run.return_value = types.SimpleNamespace(ok=True, stdout="", stderr="")
    c.uci_get.return_value = ""
    c.uci_get_list.return_value = []
    return c


def cases(cl, st, cb):
    from re_sputnik.ui.connect_screen import ConnectScreen
    from re_sputnik.ui.firstrun_screen import FirstRunScreen
    from re_sputnik.ui.internet_screen import InternetScreen
    from re_sputnik.ui.software_screen import SoftwareScreen
    from re_sputnik.ui.preinstall_screen import PreinstallScreen
    from re_sputnik.ui.quick_nodes_screen import QuickNodesScreen
    from re_sputnik.ui.wifi_ap_screen import WifiApScreen
    from re_sputnik.ui.verify_screen import VerifyScreen
    from re_sputnik.ui.finalize_screen import FinalizeScreen
    from re_sputnik.ui.security_screen import SecurityScreen
    from re_sputnik.ui.overview_screen import OverviewScreen
    from re_sputnik.ui.nodes_screen import NodesScreen
    from re_sputnik.ui.rules_screen import RulesScreen
    from re_sputnik.ui.access_screen import AccessScreen
    from re_sputnik.ui.byedpi_screen import ByeDPIScreen
    from re_sputnik.ui.core_screen import CoreScreen
    from re_sputnik.ui.diagnostics_screen import DiagnosticsScreen
    from re_sputnik.ui.about_screen import AboutScreen
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
        ("11_about", lambda m: AboutScreen(m, P)),
    ]


def grab(name, build) -> bool:
    win = ctk.CTk()
    win.geometry(f"{W}x{H}")
    win.title(name)
    try:
        scr = build(win)
        scr.pack(fill="both", expand=True)
        win.update_idletasks()
        win.deiconify()
        win.lift()
        end = time.time() + SETTLE
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


P = None


def main() -> int:
    global P
    os.makedirs(OUT, exist_ok=True)
    P = apply_theme("dark")
    cl, st = fake_client(), RouterState(reachable=True, is_openwrt=True)
    cb = lambda *a, **k: None  # noqa: E731
    ok = sum(grab(n, b) for n, b in cases(cl, st, cb))
    total = len(cases(cl, st, cb))
    print(f"--- {ok}/{total} screenshots written to {OUT}")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
