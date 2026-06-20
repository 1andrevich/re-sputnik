# SPDX-License-Identifier: GPL-2.0-only
"""Construct every screen against a hidden Tk root to catch build-time errors
(bad kwargs, missing methods) that import / py_compile can't see.

Run: python scripts/smoke_screens.py   (with src on PYTHONPATH)
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import customtkinter as ctk

from re_sputnik.router.state import RouterState
from re_sputnik.ui.theme import apply_theme


def fake_client() -> MagicMock:
    c = MagicMock()
    c.host = "192.168.1.1"
    c.run.return_value = types.SimpleNamespace(ok=True, stdout="", stderr="")
    c.uci_get.return_value = ""
    c.uci_get_list.return_value = []
    return c


def main() -> int:
    root = ctk.CTk()
    root.withdraw()
    p = apply_theme("dark")
    cl = fake_client()
    st = RouterState(reachable=True, is_openwrt=True)
    cb = lambda *a, **k: None  # noqa: E731 — trivial stub callback

    cases: list[tuple[str, object]] = []

    from re_sputnik.ui.connect_screen import ConnectScreen
    cases.append(("connect", lambda: ConnectScreen(root, p, on_connected=cb, on_back=cb)))
    from re_sputnik.ui.firstrun_screen import FirstRunScreen
    cases.append(("firstrun", lambda: FirstRunScreen(root, p, cl, st, on_done=cb, on_back=cb)))
    from re_sputnik.ui.internet_screen import InternetScreen
    cases.append(("internet", lambda: InternetScreen(root, p, cl, on_done=cb)))
    cases.append(("internet_offline", lambda: InternetScreen(root, p, cl, on_done=cb, allow_skip=True)))
    from re_sputnik.ui.software_screen import SoftwareScreen
    cases.append(("software", lambda: SoftwareScreen(root, p, cl, on_done=cb)))
    from re_sputnik.ui.preinstall_screen import PreinstallScreen
    cases.append(("preinstall", lambda: PreinstallScreen(root, p, cl, on_done=cb, on_continue=cb)))
    from re_sputnik.ui.quick_nodes_screen import QuickNodesScreen
    cases.append(("quick_nodes", lambda: QuickNodesScreen(root, p, cl, on_done=cb)))
    cases.append(("quick_nodes_offline", lambda: QuickNodesScreen(root, p, cl, on_done=cb, offline=True)))
    from re_sputnik.ui.wifi_ap_screen import WifiApScreen
    cases.append(("wifi_ap", lambda: WifiApScreen(root, p, cl, on_done=cb)))
    from re_sputnik.ui.verify_screen import VerifyScreen
    cases.append(("verify", lambda: VerifyScreen(root, p, cl, on_done=cb)))
    from re_sputnik.ui.finalize_screen import FinalizeScreen
    cases.append(("finalize", lambda: FinalizeScreen(root, p, cl, on_done=cb)))
    from re_sputnik.ui.settings_shell import SettingsShell
    cases.append(("settings_shell", lambda: SettingsShell(root, p, cl, st, on_exit=cb)))
    from re_sputnik.ui.security_screen import SecurityScreen
    cases.append(("security", lambda: SecurityScreen(root, p, cl, on_back=cb)))

    # Advanced-mode sub-sections (built on nav click, not at shell init).
    from re_sputnik.ui.overview_screen import OverviewScreen
    cases.append(("adv:overview", lambda: OverviewScreen(root, p, cl)))
    from re_sputnik.ui.nodes_screen import NodesScreen
    cases.append(("adv:nodes", lambda: NodesScreen(root, p, cl)))
    from re_sputnik.ui.rules_screen import RulesScreen
    cases.append(("adv:rules", lambda: RulesScreen(root, p, cl)))
    from re_sputnik.ui.access_screen import AccessScreen
    cases.append(("adv:access", lambda: AccessScreen(root, p, cl)))
    from re_sputnik.ui.byedpi_screen import ByeDPIScreen
    cases.append(("adv:byedpi", lambda: ByeDPIScreen(root, p, cl)))
    from re_sputnik.ui.core_screen import CoreScreen
    cases.append(("adv:core", lambda: CoreScreen(root, p, cl, st)))
    from re_sputnik.ui.diagnostics_screen import DiagnosticsScreen
    cases.append(("adv:diagnostics", lambda: DiagnosticsScreen(root, p, cl)))
    from re_sputnik.ui.advanced_screen import AdvancedScreen
    cases.append(("adv:advanced", lambda: AdvancedScreen(root, p, cl)))

    failed = 0
    for name, fn in cases:
        try:
            w = fn()
            w.update_idletasks()
            w.destroy()
            print(f"OK   {name}")
        except Exception as e:  # noqa: BLE001 — report, keep going
            failed += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")
    root.destroy()
    print(f"--- {len(cases) - failed}/{len(cases)} screens OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
