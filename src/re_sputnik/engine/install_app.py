# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Quick-Setup phase 2 — install Re:HomeProxy on a clean router (ONLINE).

Unlike Option 3 (offline staging, where the PC fetches everything and pushes it),
this runs against a router that already has internet (the Internet phase ran
first). So it uses the project's own *blessed* installers rather than
reimplementing them:

  A. install the LuCI app (+ language pack) — the only step done by hand, since
     the app's rpcd/scripts don't exist on a clean router yet;
  B. restart rpcd so ``luci.homeproxy`` registers;
  C. install the core via ``core_mgmt.uc`` (prepare → download → install) — it
     size-gates and auto-picks a build that fits the device;
  D. install the kernel modules via ``core_mgmt.uc install_kmods``;
  E. optionally install ByeDPI (its rpcd installer) + curl (apk/opkg resolves
     curl's deps online — no PC-side closure needed here);
  F. select the core and enable + start the service.

URL resolution (which release/asset) is done on the PC for robustness; the
download itself happens on the router (it has the internet, and core_mgmt's
download/kmod steps need it anyway).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..router import RouterClient, CommandResult
from ._net import http_get
from .preinstall import TargetInfo, get_target_info
from ..i18n import _

HP_REPO = "1andrevich/homeproxy-hiddify"
PUBKEY_NAME = "homeproxy-hiddify.pub"
CORE_MGMT = "/usr/share/homeproxy/scripts/core_mgmt.uc"
APP_PKG = "luci-app-re-homeproxy"

# ⚠️ TEMPORARY pins for ongoing testing — install the LuCI package from THESE exact
# tags instead of scanning for the newest.
# END STATE (once real STABLE releases resume): set BOTH to None so that BOTH fresh
# install AND update pull the LATEST STABLE release — never a prerelease/dev tag:
#   • non-legacy → GitHub `releases/latest` (newest non-prerelease);
#   • legacy (23.05) → the newest `*-legacy` release (latest legacy, kept current).
# (See the matching TODO in the version-ranking block below.)
PINNED_TAG: Optional[str] = "2026.06.22-r1-dev"            # 24.10+ / non-legacy
PINNED_TAG_LEGACY: Optional[str] = "2026.06.22-r1-legacy"  # OpenWrt 23.05 (legacy .ipk)

Progress = Callable[[str], None]


@dataclass(slots=True)
class InstallResult:
    ok: bool = False
    steps: list[str] = field(default_factory=list)   # human-readable, completed
    error: Optional[str] = None


@dataclass(slots=True)
class SoftwareStatus:
    """What's already on the router, so the install screen can skip re-installing."""
    app: bool = False        # /usr/share/homeproxy present (LuCI app + rpcd scripts)
    hiddify: bool = False    # /usr/bin/hiddify-core
    singbox: bool = False    # /usr/bin/sing-box
    kmods: bool = False      # kmod-nft-tproxy + kmod-tun
    byedpi: bool = False     # ciadpi binary / init script
    zapret: bool = False     # /opt/zapret2/nfq2/nfqws2 present
    # Authoritative: HomeProxy's own get_active_core() resolved a usable core binary
    # (diag_core_check.binary) — the SAME signal the Verify step uses. File presence
    # (hiddify/singbox) alone can disagree with it (e.g. a failed/rolled-back core
    # install), which let the wizard "skip" a core that Verify then can't find.
    core_usable: bool = False

    @property
    def core(self) -> Optional[str]:
        if self.hiddify:
            return "hiddify"
        if self.singbox:
            return "singbox"
        return None

    @property
    def ready(self) -> bool:
        """App + a really-usable core (authoritative check) + kmods — enough to move
        on without installing. Uses ``core_usable`` (HomeProxy's own get_active_core)
        rather than file presence so the skip gate can't disagree with Verify."""
        return self.app and self.core_usable and self.kmods


def software_status(client: RouterClient) -> SoftwareStatus:
    """Detect already-installed pieces. File presence works without rpcd (clean
    router); once the app IS present we additionally ask HomeProxy's own
    diag_core_check whether a core binary actually resolves — the authoritative
    'core usable' signal the Verify step relies on, so the two can't disagree."""
    from .preinstall import kmods_installed
    out = client.run(
        "printf '%s' "
        "\"$([ -d /usr/share/homeproxy ] && echo a)"
        "$([ -x /usr/bin/hiddify-core ] && echo h)"
        "$([ -x /usr/bin/sing-box ] && echo s)"
        "$({ [ -x /usr/bin/ciadpi ] || [ -f /etc/init.d/ciadpi ]; } && echo b)"
        "$([ -x /opt/zapret2/nfq2/nfqws2 ] && echo z)\""
    ).stdout
    app = "a" in out
    core_usable = False
    if app:
        # rpcd is present with the app — trust get_active_core() over file presence.
        try:
            ci = client.ubus_homeproxy("diag_core_check", timeout=15)
            core_usable = isinstance(ci, dict) and bool(ci.get("binary"))
        except Exception:  # noqa: BLE001 — fall back to file presence below
            core_usable = "h" in out or "s" in out
    return SoftwareStatus(app=app, hiddify="h" in out, singbox="s" in out,
                          byedpi="b" in out, zapret="z" in out,
                          kmods=kmods_installed(client), core_usable=core_usable)


# ----- PC-side release/asset resolution ---------------------------------


def _gh(url: str) -> object:
    # TLS trust (certifi) + dead-proxy bypass live in _net.http_get.
    return json.loads(http_get(
        url, headers={"User-Agent": "re-companion", "Accept": "application/vnd.github+json"}))


@dataclass(slots=True)
class AppAssets:
    app_url: str
    pubkey_url: Optional[str]       # publisher key (apk trust); None → --allow-untrusted
    i18n_url: Optional[str]
    version: str = ""               # version parsed from the app asset filename


def _pick(assets: dict[str, str], prefix: str, ext: str,
          legacy_ok: bool) -> Optional[tuple[str, str]]:
    # Legacy builds are named ``<pkg>_<ver>_all-legacy.ipk``; normal builds
    # ``<pkg>_<ver>_all.ipk`` / ``.apk``. Match the suffix for the target —
    # ``_all.ipk`` deliberately does NOT match ``_all-legacy.ipk`` and vice-versa.
    suffix = f"_all-legacy{ext}" if legacy_ok else f"_all{ext}"
    for name, url in assets.items():
        if name.startswith(prefix + "_") and name.endswith(suffix):
            return name, url
    return None


_VER_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:-r(\d+))?")


def _ver_key(version: str) -> tuple:
    """Order key for a ``YYYY.MM.DD-rN`` release version (missing -rN = r0).
    Unparseable strings sort lowest so they never masquerade as 'newer'."""
    m = _VER_RE.search(version or "")
    return tuple(int(g or 0) for g in m.groups()) if m else (0, 0, 0, 0)


def is_newer(candidate: str, installed: str) -> bool:
    """True only if release version ``candidate`` is *strictly* newer than
    ``installed`` — so a same/older 'latest' (e.g. while we run a pinned dev build
    ahead of the public release) never offers a downgrade as an 'update'."""
    if not candidate or not installed:
        return False
    return _ver_key(candidate) > _ver_key(installed)


def resolve_app_assets(ti: TargetInfo, language: str, *, use_latest: bool = False) -> AppAssets:
    """Find the newest release carrying the LuCI app, and take its sibling
    publisher key + language pack from that SAME release.

    The app/i18n packages are pure Lua/JS = noarch, so any release's build works.
    Taking the ``.pub`` from the app's own release matters: the key must be the
    one the package was signed with, and the GitHub ``latest`` may not even carry
    a ``.pub`` (see workaround note below).

    TODO(temporary workaround): we scan ALL releases, INCLUDING prereleases,
    because the current GitHub ``latest`` is a legacy-only ``.ipk`` release while
    the new-name ``luci-app-re-homeproxy`` ``.apk`` lives in a prerelease. Once a
    STABLE release ships the ``.apk``/new-name assets, prefer ``releases/latest``
    (it'll be first in this newest-first scan anyway, so this stays correct —
    just drop the prerelease tolerance). See memory: project_companion_app_architecture.
    """
    ext = ti.ext
    legacy_ok = ti.version.startswith("23.")
    # use_latest (the Advanced "update" path) ignores the testing pin and scans the
    # newest releases first, so it tracks real published updates.
    pin = None if use_latest else (PINNED_TAG_LEGACY if legacy_ok else PINNED_TAG)
    suffix = f"_all-legacy{ext}" if legacy_ok else f"_all{ext}"
    if pin:  # install from this exact release
        pinned = _gh(f"https://api.github.com/repos/{HP_REPO}/releases/tags/{pin}")
        releases = [pinned] if isinstance(pinned, dict) else list(pinned)
    else:
        releases = _gh(f"https://api.github.com/repos/{HP_REPO}/releases")  # newest first

    # GitHub lists by created_at, which can disagree with the version (a higher
    # version may have an OLDER release-object date), so we don't take the first
    # match — we rank by parsed version and prefer a stable release, falling back
    # to the newest prerelease only while no stable carries the asset. A pinned
    # lookup returns its one release as-is. Once the pin is dropped (real "latest"),
    # this picks the genuine newest stable and its sibling links automatically.
    best_any: Optional[tuple] = None      # (ver_key, AppAssets)
    best_stable: Optional[tuple] = None
    for rel in releases:
        assets = {a.get("name", ""): a.get("browser_download_url", "")
                  for a in rel.get("assets", [])}
        app = _pick(assets, APP_PKG, ext, legacy_ok)
        if not app:
            continue
        app_name, app_url = app
        version = app_name[len(APP_PKG) + 1:-len(suffix)]  # <pkg>_<VER>_all.apk → VER
        i18n = (_pick(assets, f"luci-i18n-homeproxy-{language}", ext, legacy_ok)
                if language and language != "en" else None)
        cand = AppAssets(app_url=app_url, pubkey_url=assets.get(PUBKEY_NAME),
                         i18n_url=(i18n[1] if i18n else None), version=version)
        if pin:
            return cand  # exact pinned release — take its assets verbatim
        key = _ver_key(version)
        if best_any is None or key > best_any[0]:
            best_any = (key, cand)
        if not rel.get("prerelease"):
            if best_stable is None or key > best_stable[0]:
                best_stable = (key, cand)
    # ⚠️ TEMPORARY (since 2026-06) — track the newest release in ANY status,
    # including PRERELEASES. The project currently ships only dev prereleases, which
    # ARE the genuine latest; preferring stable would pin the update check to an old
    # stable (e.g. 2026.06.16) and hide a newer prerelease (2026.06.22-dev), so the
    # app would wrongly report "you're up to date". Stable is preferred only to break
    # a tie at the SAME version.
    # TODO (end state, once real STABLE releases resume): BOTH install AND update
    # must use the LATEST STABLE release, never a prerelease/dev tag —
    #   • non-legacy → newest NON-prerelease (revert to `chosen = best_stable or
    #     best_any`, i.e. stable-preferred);
    #   • legacy (23.05) → newest `*-legacy` release regardless of status.
    # Also drop PINNED_TAG/PINNED_TAG_LEGACY (set to None) so install stops targeting
    # a hand-picked tag and follows the same latest-stable resolution as update.
    if best_any and best_stable:
        chosen = best_any if best_any[0] > best_stable[0] else best_stable
    else:
        chosen = best_stable or best_any
    if chosen:
        return chosen[1]
    where = f"релизе {pin}" if pin else f"релизах {HP_REPO}"
    raise RuntimeError(f"в {where} нет пакета {APP_PKG}{ext}")


# ----- router-side helpers ----------------------------------------------


def _run_retry(client: RouterClient, command: str, *, timeout: int, attempts: int = 3,
               say: Optional["Progress"] = None, what: str = "") -> CommandResult:
    """Run a network command, retrying on TimeoutError.

    A slow uplink can blow a single timeout without the operation being truly
    stuck (the observed failure: ``apk update`` over a poor link). Every package
    comes from the same feed, so the right answer is to *complete* the fetch on a
    retry, not to skip the step. Re-raises the final TimeoutError if all attempts
    time out; a non-zero exit is returned to the caller unchanged (not retried —
    that's a real error, e.g. a missing package, not a slow link)."""
    for n in range(1, attempts + 1):
        try:
            return client.run(command, timeout=timeout)
        except TimeoutError:
            if n >= attempts:
                raise
            if say:
                say(f"Медленный интернет — повтор {n + 1}/{attempts}: {what or command[:40]}…")
    raise AssertionError("unreachable")  # loop body either returns or raises


def _core_mgmt(client: RouterClient, *args: str, timeout: int = 300, attempts: int = 1,
               say: Optional["Progress"] = None, what: str = "операции с ядром") -> dict:
    """Run a core_mgmt.uc action and parse its JSON reply. Network-bound actions
    (download/install over the same feed) pass ``attempts`` > 1 so a transient
    slow moment retries the fetch instead of aborting the whole install."""
    quoted = " ".join(f"'{a}'" for a in args)
    out = _run_retry(client, f"ucode {CORE_MGMT} {quoted}", timeout=timeout,
                     attempts=attempts, say=say, what=what)
    text = out.stdout.strip()
    try:
        return json.loads(text) if text else {"error": "no output"}
    except json.JSONDecodeError:
        return {"error": f"non-JSON: {text[:160] or out.stderr.strip()[:160]}"}


def _wget(client: RouterClient, url: str, dest: str, *, timeout: int = 300) -> bool:
    return client.run(f"wget -qO {dest} '{url}'", timeout=timeout).ok


# ----- LuCI interface language ------------------------------------------

# Feed i18n packs that localize the rest of the UI a user actually touches. Two
# names are tried for the software page (apk = package-manager, opkg/23.05 = opkg);
# the missing one is simply skipped.
def luci_i18n_components(client: RouterClient) -> list[str]:
    """LuCI i18n component names derived from the router's INSTALLED luci-app/mod
    set — so EVERY localizable page gets its pack, not a hardcoded subset (which
    left pages like Attended Sysupgrade in English). ``base`` is always included;
    ``luci-app-firewall`` -> ``firewall``. A luci-mod-* whose strings live inside
    luci-i18n-base has no own pack and is harmlessly skipped downstream (the
    per-pack install/stage is tolerant of a missing pack)."""
    out = client.run("(apk info 2>/dev/null || opkg list-installed 2>/dev/null) "
                     "| grep -oE 'luci-(app|mod)-[a-z0-9-]+'").stdout
    comps = {"base"}
    for tok in out.split():
        m = re.match(r"luci-(?:app|mod)-(.+)", tok.strip())
        if m:
            comps.add(m.group(1))
    return sorted(comps)


def _install_luci_i18n(client: RouterClient, pm: str, language: str,
                       say: "Progress") -> bool:
    """Install the LuCI feed language packs and set the UI to that language.
    Best-effort: a pack missing from the feed is skipped, the whole step never
    aborts install; ``luci.main.lang`` is then pinned to ``language`` so the web
    interface is actually localized. Returns True if packs were tried."""
    if not language or language == "en":
        return False
    say(f"Устанавливаю язык интерфейса LuCI ({language})…")
    # 180s caps + retry: on a slow uplink the repo refresh alone can run past 90s
    # without ever stalling, and the index download is all-or-nothing — so give it
    # ~3 min and retry a couple of times before giving up (rather than aborting the
    # whole install on a single slow fetch).
    if pm == "apk":
        _run_retry(client, "apk update 2>/dev/null", timeout=180, say=say,
                   what=_("обновление репозитория"))
        add = "apk add"
    else:
        _run_retry(client, "opkg update 2>/dev/null", timeout=180, say=say,
                   what=_("обновление репозитория"))
        add = "opkg install"
    for comp in luci_i18n_components(client):
        # Per-package so one missing pack can't abort the rest; failures ignored.
        _run_retry(client, f"{add} luci-i18n-{comp}-{language} 2>/dev/null", timeout=180,
                   say=say, what=f"luci-i18n-{comp}")
    # Force the LuCI UI to this language (rather than leaving 'auto'/browser-locale),
    # so the web interface is actually localized for the user's audience.
    client.run(f"uci set luci.main.lang={language}; uci commit luci 2>/dev/null; true", timeout=15)
    return True


# Packages this one supersedes (the pre-rename lineage). Removed before installing
# the new package so an upgrade from the old name is a CLEAN replacement — no file
# conflict, no orphaned package left registered. The shared /etc/config/homeproxy is
# a conffile and survives the removal. Mirrors the package's own Provides/Replaces.
LEGACY_APP_PKGS = ("luci-app-homeproxy-hiddify", "luci-app-homeproxy")

# Sentinel returned by app_installed_version() when ONLY a pre-rename package is
# installed (new name absent): the UI shows it as "old version → migration available".
LEGACY_INSTALLED = "legacy"


def legacy_app_installed(client: RouterClient, pm: str) -> str:
    """Name of a REAL (not merely 'provided') pre-rename package installed on the
    router, or '' if none. apk `info -e` matches PROVIDED names (the new pkg provides
    the old ones), so detect via the real installed-name list instead."""
    for old in LEGACY_APP_PKGS:
        if pm == "apk":
            real = bool(client.run(f"apk info 2>/dev/null | grep -xF {old}").stdout.strip())
        else:
            real = bool(client.run(
                f"opkg list-installed 2>/dev/null | grep '^{old} '").stdout.strip())
        if real:
            return old
    return ""


def remove_legacy_app(client: RouterClient, pm: str, say: "Optional[Progress]" = None) -> None:
    """Remove any pre-rename homeproxy package before the new one is installed.
    No-op when none is present; best-effort (never aborts the install)."""
    for old in LEGACY_APP_PKGS:
        if pm == "apk":
            # CAUTION: `apk info -e <name>` ALSO matches PROVIDED names — the new
            # package `provides` the old ones, so `-e` returns true even when no real
            # old package is installed, and `apk del <provided-name>` would remove the
            # PROVIDER (the new app!). Match only a REAL installed package by its name
            # in the installed-package list.
            present = bool(client.run(f"apk info 2>/dev/null | grep -xF {old}").stdout.strip())
            cmd = f"apk del {old}"
        else:
            present = bool(client.run(
                f"opkg list-installed 2>/dev/null | grep '^{old} '").stdout.strip())
            # --force-depends: the OLD luci-i18n-homeproxy-* packages depend on the OLD
            # app name and would otherwise BLOCK removal ("depended upon by …"). It
            # removes ONLY the app (not the dependents); the i18n keeps working (its
            # .lmo files stay) and its broken dependency is repaired when run()/
            # update_app()/preinstall reinstall the NEW i18n right after.
            cmd = f"opkg remove --force-depends {old}"
        if present:
            if say:
                say(f"Удаляю старый пакет {old}…")
            client.run(f"{cmd} 2>/dev/null; true", timeout=90)


# ----- orchestration ----------------------------------------------------


def run(client: RouterClient, core: str, *, with_byedpi: bool = False,
        with_zapret: bool = False,
        language: str = "ru", progress: Optional[Progress] = None,
        start_service: bool = True) -> InstallResult:
    res = InstallResult()

    def say(m: str) -> None:
        if progress:
            progress(m)

    def say_line(line: str) -> None:
        # Stream a raw command's output line into the same progress log, so a slow
        # package install shows live activity instead of a frozen status line.
        if line.strip():
            say(line.rstrip())

    ti = get_target_info(client)
    if ti.is_snapshot:
        res.error = (_("На устройстве SNAPSHOT-сборка OpenWrt — kmod из релизного "
                     "репозитория недоступны. Используйте релизную прошивку."))
        return res
    pm = ti.pkg_manager

    try:
        # --- A. LuCI app (+ language pack) -----------------------------
        say(f"Роутер: {ti.version} · {ti.arch} ({pm}). Определяю пакеты приложения…")
        assets = resolve_app_assets(ti, language)

        say(_("Устанавливаю приложение Re:HomeProxy…"))
        trusted = False
        if pm == "apk" and assets.pubkey_url:
            # Install the publisher key from the app's own release so apk trusts
            # the package (and future updates) without --allow-untrusted. Falls
            # back to untrusted (PC fetched over https) if the key is missing.
            trusted = client.run(
                f"wget -qO /tmp/hp.pub '{assets.pubkey_url}' && "
                f"cp /tmp/hp.pub /etc/apk/keys/ 2>/dev/null && echo OK; rm -f /tmp/hp.pub"
            ).stdout.strip().endswith("OK")
        if not _wget(client, assets.app_url, f"/tmp/{APP_PKG}{ti.ext}"):
            res.error = _("не удалось скачать пакет приложения на роутер")
            return res
        # Clean replacement if the router still has the pre-rename package.
        remove_legacy_app(client, pm, say)
        # A local-file install doesn't need a repo refresh — skipping `apk update`
        # avoids a flaky feed index aborting the app install.
        # Streamed so the (slow over Wi-Fi) dependency pulls show live in the log.
        # The 180s here is a STALL timeout — it only trips after 180s with no output,
        # so a slow-but-progressing install isn't killed, but a wedged one is.
        if pm == "apk":
            flag = "" if trusted else "--allow-untrusted "
            inst = client.run_stream(f"apk add {flag}/tmp/{APP_PKG}{ti.ext} 2>&1",
                                     on_line=say_line, timeout=180)
        else:
            inst = client.run_stream(f"opkg install /tmp/{APP_PKG}{ti.ext} 2>&1",
                                     on_line=say_line, timeout=180)
        client.run(f"rm -f /tmp/{APP_PKG}{ti.ext}")
        if not inst.ok:
            res.error = f"установка приложения не удалась: {inst.stdout.strip()[-200:]}"
            return res
        res.steps.append(_("Приложение установлено"))

        if assets.i18n_url:
            say(f"Устанавливаю языковой пакет HomeProxy ({language})…")
            if _wget(client, assets.i18n_url, f"/tmp/i18n{ti.ext}"):
                flag = "--allow-untrusted " if (pm == "apk" and not trusted) else ""
                add = f"apk add {flag}" if pm == "apk" else "opkg install "
                if client.run_stream(f"{add}/tmp/i18n{ti.ext} 2>&1; rm -f /tmp/i18n{ti.ext}",
                                     on_line=say_line, timeout=120).ok:
                    res.steps.append(f"Языковой пакет HomeProxy ({language})")

        # LuCI interface language: base + firewall + package-manager packs (from the
        # OpenWrt feed), so the whole UI can be localized — not just HomeProxy. The UI
        # language stays 'auto' (browser-driven); we only make the packs available.
        # Best-effort, never fatal.
        if _install_luci_i18n(client, pm, language, say):
            res.steps.append(f"Языковые пакеты LuCI ({language})")

        # --- B. register rpcd ------------------------------------------
        say(_("Перезапускаю rpcd…"))
        client.run("/etc/init.d/rpcd restart 2>/dev/null; sleep 2; true", timeout=30)

        # --- C. core ----------------------------------------------------
        say(f"Готовлю установку ядра ({core})…")
        prep = _core_mgmt(client, "prepare_install", core, "")
        if prep.get("error"):
            res.error = f"подготовка ядра: {prep['error']}"
            return res
        if prep.get("note"):
            say(prep["note"])
        say(_("Скачиваю ядро на роутер…"))
        dl = _core_mgmt(client, "download_pkg", prep["dl_url"], prep["tmp_path"],
                        attempts=3, say=say, what=_("скачивание ядра"))
        if not dl.get("result"):
            res.error = f"скачивание ядра: {dl.get('error', 'не удалось')}"
            return res
        say(_("Устанавливаю ядро…"))
        ins = _core_mgmt(client, "install_pkg", core, prep["tmp_path"], prep["pkg_manager"],
                         attempts=3, say=say, what=_("установка ядра"))
        if not ins.get("result"):
            res.error = f"установка ядра: {ins.get('error', 'не удалось')}"
            return res
        res.steps.append(f"Ядро {core} ({prep.get('variant', 'standard')})")

        # --- D. kernel modules -----------------------------------------
        say(_("Устанавливаю модули ядра (kmod-nft-tproxy, kmod-tun)…"))
        km = _core_mgmt(client, "install_kmods", pm, timeout=120,
                        attempts=3, say=say, what=_("установка модулей ядра"))
        if not km.get("result"):
            # Enrich the raw failure with a firmware-capability diagnosis: is the
            # kmod genuinely unavailable for this kernel (incompatible firmware),
            # or did the install just fail?
            from . import firmware
            detail = firmware.diagnose_kmods(client, pm)
            base = f"установка kmod: {km.get('error', 'не удалось')}"
            res.error = f"{base} — {detail}" if detail else base
            return res
        res.steps.append(_("Модули ядра"))

        # --- E. ByeDPI (+ curl, online deps auto-resolved) -------------
        if with_byedpi:
            say(_("Устанавливаю curl (нужен тестеру ByeDPI)…"))
            add = "apk add" if pm == "apk" else "opkg install"
            client.run_stream(f"{add} curl 2>&1; true", on_line=say_line, timeout=120)
            say(_("Устанавливаю ByeDPI…"))
            bp = client.ubus_homeproxy("byedpi_prepare_install", timeout=60)
            if bp.get("error") or not bp.get("dl_url"):
                say(f"ByeDPI: не удалось подготовить ({bp.get('error', 'нет ссылки')}).")
            elif not _wget(client, bp["dl_url"], bp["tmp_path"]):
                say(_("ByeDPI: не удалось скачать пакет."))
            else:
                bi = client.ubus_homeproxy(
                    "byedpi_install_pkg",
                    {"tmp_path": bp["tmp_path"], "pkg_manager": bp["pkg_manager"]}, timeout=120)
                if bi.get("result"):
                    res.steps.append("ByeDPI")
                else:
                    say(_("ByeDPI: установка не удалась."))

        # --- E2. Zapret (zapret2/nfqws2 — pulls kmod-nft-queue via depends) --
        if with_zapret:
            say(_("Устанавливаю Zapret…"))
            zp = client.ubus_homeproxy("zapret_prepare_install", timeout=60)
            if zp.get("error") or not zp.get("dl_url"):
                say(f"Zapret: не удалось подготовить ({zp.get('error', 'нет ссылки')}).")
            elif not _wget(client, zp["dl_url"], zp["tmp_path"]):
                say(_("Zapret: не удалось скачать пакет."))
            else:
                zi = client.ubus_homeproxy(
                    "zapret_install_pkg",
                    {"tmp_path": zp["tmp_path"], "pkg_manager": zp["pkg_manager"]}, timeout=180)
                if zi.get("result"):
                    res.steps.append("Zapret")
                else:
                    say(_("Zapret: установка не удалась."))

        # --- F. select core + start ------------------------------------
        say(_("Выбираю ядро и запускаю сервис…"))
        client.run(f"uci set homeproxy.config.preferred_core='{core}'; "
                   "uci commit homeproxy 2>/dev/null; true")
        client.run("/etc/init.d/homeproxy enable 2>/dev/null; true")
        if start_service:
            client.run("/etc/init.d/homeproxy start 2>/dev/null; true", timeout=60)
            res.steps.append(_("Сервис запущен"))
        else:
            res.steps.append(_("Сервис включён (старт после добавления серверов)"))

        res.ok = True
        say(_("Готово."))
        return res
    except Exception as exc:  # noqa: BLE001 — surface any failure to the UI
        res.error = f"{exc}"
        return res


# ----- Advanced: install/update a single core, update the app -----------


def install_core(client: RouterClient, ti: TargetInfo, core: str, *,
                 progress: Optional[Progress] = None) -> tuple[bool, str]:
    """Install (or update to latest) ONE core and ensure the kernel modules.

    Used by the Advanced → Core screen for "install the other core" and "update
    to latest" — reuses core_mgmt (prepare → download → install), which always
    resolves the newest build. Returns (ok, message)."""
    from .preinstall import kmods_installed

    def say(m: str) -> None:
        if progress:
            progress(m)

    say(f"Готовлю установку ядра ({core})…")
    prep = _core_mgmt(client, "prepare_install", core, "")
    if prep.get("error"):
        return False, f"подготовка: {prep['error']}"
    if prep.get("note"):
        say(prep["note"])
    say(_("Скачиваю ядро на роутер…"))
    if not _core_mgmt(client, "download_pkg", prep["dl_url"], prep["tmp_path"],
                      attempts=3, say=say, what=_("скачивание ядра")).get("result"):
        return False, _("скачивание ядра не удалось")
    say(_("Устанавливаю ядро…"))
    ins = _core_mgmt(client, "install_pkg", core, prep["tmp_path"], prep["pkg_manager"],
                     attempts=3, say=say, what=_("установка ядра"))
    if not ins.get("result"):
        return False, f"установка ядра: {ins.get('error', 'не удалось')}"
    if not kmods_installed(client):
        say(_("Устанавливаю модули ядра (kmod-nft-tproxy, kmod-tun)…"))
        if not _core_mgmt(client, "install_kmods", ti.pkg_manager, timeout=120,
                          attempts=3, say=say, what=_("установка модулей ядра")).get("result"):
            return False, _("не удалось установить модули ядра")
    return True, f"Ядро {core} установлено ({prep.get('variant', 'standard')})"


def app_installed_version(client: RouterClient) -> str:
    """Installed version of the LuCI app, or '' if absent. Returns the
    ``LEGACY_INSTALLED`` sentinel when the NEW package is absent but a REAL pre-rename
    package is installed — so the Core screen offers a migration update instead of
    wrongly reporting "not installed"."""
    is_apk = client.run("command -v apk >/dev/null 2>&1").ok
    out = client.run(
        f"apk list -I {APP_PKG} 2>/dev/null | head -1" if is_apk
        else f"opkg status {APP_PKG} 2>/dev/null | sed -n 's/^Version: //p'"
    ).stdout.strip()
    if out:
        # apk: "<pkg>-<ver> <arch> {...} ..." → strip the "<pkg>-" prefix, take field 1.
        if out.startswith(APP_PKG + "-"):
            return out[len(APP_PKG) + 1:].split()[0]
        return out.split()[0]  # opkg: the Version: line is already just the version
    if legacy_app_installed(client, "apk" if is_apk else "opkg"):
        return LEGACY_INSTALLED
    return ""


def app_versions(client: RouterClient, ti: TargetInfo, language: str = "ru") -> tuple[str, str]:
    """(installed, latest_release) versions of the LuCI app — for the Core screen.
    ``latest`` is '' if the GitHub lookup fails (offline / rate-limited)."""
    installed = app_installed_version(client)
    try:
        latest = resolve_app_assets(ti, language, use_latest=True).version
    except Exception:  # noqa: BLE001 — offline / no release; UI shows installed only
        latest = ""
    return installed, latest


def update_app(client: RouterClient, ti: TargetInfo, language: str = "ru", *,
               progress: Optional[Progress] = None) -> tuple[bool, str]:
    """Download the LATEST released LuCI app (+ language pack) and install it.
    Mirrors the install flow's app step; returns (ok, message)."""
    def say(m: str) -> None:
        if progress:
            progress(m)

    def say_line(line: str) -> None:
        if line.strip():
            say(line.rstrip())

    pm = ti.pkg_manager
    say(_("Определяю последнюю версию приложения…"))
    assets = resolve_app_assets(ti, language, use_latest=True)
    say(f"Устанавливаю приложение Re:HomeProxy {assets.version}…")
    trusted = False
    if pm == "apk" and assets.pubkey_url:
        trusted = client.run(
            f"wget -qO /tmp/hp.pub '{assets.pubkey_url}' && "
            f"cp /tmp/hp.pub /etc/apk/keys/ 2>/dev/null && echo OK; rm -f /tmp/hp.pub"
        ).stdout.strip().endswith("OK")
    if not _wget(client, assets.app_url, f"/tmp/{APP_PKG}{ti.ext}"):
        return False, _("не удалось скачать пакет приложения")
    remove_legacy_app(client, pm, say)  # clean replacement if old-name pkg present
    if pm == "apk":
        flag = "" if trusted else "--allow-untrusted "
        inst = client.run_stream(f"apk add {flag}/tmp/{APP_PKG}{ti.ext} 2>&1",
                                 on_line=say_line, timeout=180)
    else:
        inst = client.run_stream(f"opkg install /tmp/{APP_PKG}{ti.ext} 2>&1",
                                 on_line=say_line, timeout=180)
    client.run(f"rm -f /tmp/{APP_PKG}{ti.ext}")
    if not inst.ok:
        return False, f"установка не удалась: {inst.stdout.strip()[-200:]}"
    # Update EVERY homeproxy language pack the router already has (not just the
    # app's current UI language), so an installed translation like
    # luci-i18n-homeproxy-ru is bumped to the new version too — otherwise it stays
    # at the old version after the app is updated and shows stale/untranslated text.
    installed_i18n = client.run(
        "(apk info 2>/dev/null || opkg list-installed 2>/dev/null) "
        "| grep -oE 'luci-i18n-homeproxy-[a-z][a-z-]*'").stdout
    langs = {t.strip()[len("luci-i18n-homeproxy-"):] for t in installed_i18n.split() if t.strip()}
    if language and language != "en":
        langs.add(language)            # also (re)install the UI language's pack
    flag = "--allow-untrusted " if (pm == "apk" and not trusted) else ""
    add = f"apk add {flag}" if pm == "apk" else "opkg install "
    for lang in sorted(langs):
        a = assets if lang == language else resolve_app_assets(ti, lang, use_latest=True)
        if not a.i18n_url:
            continue
        say(f"Языковой пакет HomeProxy ({lang})…")
        if _wget(client, a.i18n_url, f"/tmp/i18n{ti.ext}"):
            client.run_stream(f"{add}/tmp/i18n{ti.ext} 2>&1; rm -f /tmp/i18n{ti.ext}",
                              on_line=say_line, timeout=120)
    say(_("Перезапускаю rpcd…"))
    client.run("/etc/init.d/rpcd restart 2>/dev/null; sleep 2; true", timeout=30)
    return True, f"Приложение обновлено до {assets.version}"
