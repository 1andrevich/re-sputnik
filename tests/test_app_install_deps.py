# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 1andrevich. Licensed under the GNU GPLv3 — see LICENSE.
"""The local package file is installed, its dependencies are not (issue #1).

`luci-app-re-homeproxy` declares `Depends: … kmod-nft-tproxy, ucode-mod-digest`,
and `ucode-mod-digest` is absent from a stock 24.10 image. Installing the local
.ipk/.apk without a package index leaves that dependency unresolvable — and opkg
then blames the ARCHITECTURE ("Packages for … found, but incompatible with the
architectures configured"), because it sets `wrong_arch_found` whenever no
candidate survives, whatever the real reason.

These tests pin both halves of the fix: the index IS refreshed before a local opkg
install (apk refreshes itself and is deliberately left alone), and the failure
message names the missing dependency instead of parroting opkg's arch red herring.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, "src")
from re_sputnik.engine import install_app  # noqa: E402
from re_sputnik.engine.preinstall import TargetInfo  # noqa: E402
from re_sputnik.router.client import CommandResult, CommandTimeout  # noqa: E402

# Verbatim from issue #1 (Xiaomi AX6000, OpenWrt 24.10.4, opkg).
ISSUE_1_OUTPUT = """\
Unknown package 'luci-app-re-homeproxy'.
Collected errors:
 * pkg_hash_check_unresolved: cannot find dependency ucode-mod-digest for luci-app-re-homeproxy
 * pkg_hash_fetch_best_installation_candidate: Packages for luci-app-re-homeproxy found, \
but incompatible with the architectures configured
 * opkg_install_cmd: Cannot install package luci-app-re-homeproxy.
"""


class FakeClient:
    """Records every command in order; both run() and run_stream() succeed."""

    def __init__(self, stdout: str = "", exit_code: int = 0) -> None:
        self.commands: list[str] = []
        self._stdout = stdout
        self._exit = exit_code

    def _result(self, command: str) -> CommandResult:
        self.commands.append(command)
        return CommandResult(command, self._exit, self._stdout, "")

    def run(self, command: str, timeout: int | None = None) -> CommandResult:
        return self._result(command)

    def run_stream(self, command: str, *, on_line=None, timeout: int | None = None) -> CommandResult:
        return self._result(command)


@pytest.fixture(autouse=True)
def _rearm_latch():
    # Each test starts with the once-per-run refresh latch cleared.
    install_app.reset_feed_refresh()
    yield
    install_app.reset_feed_refresh()


# ----- refresh_feeds ----------------------------------------------------


def test_refresh_updates_the_opkg_lists() -> None:
    c = FakeClient()
    install_app.refresh_feeds(c, "opkg")
    assert any(cmd.startswith("opkg update") for cmd in c.commands)


def test_refresh_leaves_apk_alone() -> None:
    # `apk add` opens the db for write without APK_OPENF_NO_AUTOUPDATE, so apk-tools 3
    # treats an absent index cache as stale and fetches it itself. An explicit
    # `apk update` is pure duplication — and would charge apk failures the retry
    # budget above. Only opkg, which has no such autoupdate, needs the help.
    c = FakeClient()
    install_app.refresh_feeds(c, "apk")
    assert c.commands == []


def test_refresh_runs_once_per_install_run() -> None:
    # The app install and the LuCI i18n step both call it; only one index download.
    c = FakeClient()
    install_app.refresh_feeds(c, "opkg")
    install_app.refresh_feeds(c, "opkg")
    assert len(c.commands) == 1
    install_app.reset_feed_refresh()          # next install/update re-arms it
    install_app.refresh_feeds(c, "opkg")
    assert len(c.commands) == 2


def test_refresh_never_aborts_the_install() -> None:
    # A broken/slow feed must not raise — that was the reason the refresh was
    # skipped in the first place; it's now best-effort instead of absent.
    timing_out = MagicMock()
    timing_out.run.side_effect = CommandTimeout("too slow")
    install_app.refresh_feeds(timing_out, "opkg")

    install_app.reset_feed_refresh()
    broken = MagicMock()
    broken.run.side_effect = RuntimeError("channel closed")
    install_app.refresh_feeds(broken, "opkg")


# ----- failure reporting ------------------------------------------------


def test_error_names_the_dependency_not_the_architecture() -> None:
    msg = install_app._app_install_error(MagicMock(), "opkg", ISSUE_1_OUTPUT)
    assert msg.startswith("cannot find dependency ucode-mod-digest")
    # The old blind [-200:] tail reported opkg's LAST line, cut mid-word.
    assert not msg.startswith("_hash_fetch_best_installation_candidate")


def test_kmod_failure_gets_the_firmware_diagnosis(monkeypatch: pytest.MonkeyPatch) -> None:
    # The app hard-depends on kmod-nft-tproxy, so a firmware whose kernel can't
    # supply it now fails at the APP step — it must still explain why.
    from re_sputnik.engine import firmware

    monkeypatch.setattr(firmware, "diagnose_kmods", lambda client, pm: "прошивка несовместима")
    out = (" * pkg_hash_check_unresolved: cannot find dependency kmod-nft-tproxy "
           "for luci-app-re-homeproxy\n")
    msg = install_app._app_install_error(MagicMock(), "opkg", f"Collected errors:\n{out}")
    assert "kmod-nft-tproxy" in msg and "прошивка несовместима" in msg


def test_no_firmware_probe_when_no_kmod_involved() -> None:
    # diagnose_kmods() shells out repeatedly (opkg update + info per module) —
    # never pay that on a failure that has nothing to do with kernel modules.
    client = MagicMock()
    install_app._app_install_error(client, "opkg", ISSUE_1_OUTPUT)
    client.run.assert_not_called()


# ----- ordering in the real update path ---------------------------------


def test_update_refreshes_the_index_before_installing_the_local_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The legacy → new migration hits this hardest: the pre-rename package never
    depended on ucode-mod-digest, so the router won't have it."""
    ti = TargetInfo(version="24.10.4", board="mediatek/filogic",
                    arch="aarch64_cortex-a53", pkg_manager="opkg", is_snapshot=False)
    assets = install_app.AppAssets(app_url="https://example.invalid/app.ipk",
                                   pubkey_url=None, i18n_url=None, version="2026.06.29-r1")
    monkeypatch.setattr(install_app, "ensure_clock", lambda *a, **k: (True, ""))
    monkeypatch.setattr(install_app, "resolve_app_assets", lambda *a, **k: assets)
    monkeypatch.setattr(install_app, "_wget", lambda *a, **k: (True, ""))
    monkeypatch.setattr(install_app, "remove_legacy_app", lambda *a, **k: None)

    c = FakeClient()
    ok, _msg = install_app.update_app(c, ti)

    assert ok
    update_at = next(i for i, cmd in enumerate(c.commands) if cmd.startswith("opkg update"))
    install_at = next(i for i, cmd in enumerate(c.commands) if cmd.startswith("opkg install /tmp/"))
    assert update_at < install_at
