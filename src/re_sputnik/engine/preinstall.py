# SPDX-License-Identifier: GPL-2.0-only
"""Option 3 — preinstall packages offline.

Use case: stage a router for install elsewhere, where the router itself may have
no internet. The PC running the app (which DOES have internet) downloads the
packages, pushes them to the router via write_file (cat-over-ssh; OpenWrt has no
SFTP), and installs them from the local files.

Covers: the selected core + its kernel modules (kmod-nft-tproxy + kmod-tun) and,
optionally, ByeDPI (the DPI-bypass `ciadpi` binary) + curl (needed only by the
ByeDPI strategy tester) with curl's runtime library closure.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..router import RouterClient
from ._net import http_get

OPENWRT_DL = "https://downloads.openwrt.org"
KMODS = ("kmod-nft-tproxy", "kmod-tun")
ZAPRET_KMOD = "kmod-nft-queue"   # NFQUEUE — needed only when installing Zapret
BYEDPI_REPO = "1andrevich/ByeDPI-OpenWrt"
ZAPRET_REPO = "1andrevich/zapret2-openwrt"

# curl's runtime closure, resolved from the OpenWrt packages feed by *directory
# listing* (the apk `index.json` omits SONAME library packages like libcurl4 —
# they're carried as `so:` provides — so we match the actual .apk/.ipk filenames).
# Each entry: (feed, file-name regex, installed-package-name regex). We only
# download what the router does NOT already have. SONAME suffixes (libcurl4,
# libnghttp2-14, libmbedtls21) drift across OpenWrt releases, hence the \d+.
_CurlEntry = tuple[str, str, str]
_CURL_CLOSURE: tuple[_CurlEntry, ...] = (
    ("packages", r"^curl[-_]\d",            r"^curl$"),
    ("packages", r"^libcurl\d+[-_]\d",      r"^libcurl\d+$"),
    ("packages", r"^libnghttp2-\d+[-_]\d",  r"^libnghttp2-\d+$"),
    ("base",     r"^zlib[-_]\d",            r"^zlib$"),
    ("base",     r"^ca-bundle[-_]\d",       r"^ca-bundle$"),
)
# TLS backend: present on any router that already does TLS (a proxy core does).
# Only shipped if the router has *neither* mbedtls nor openssl — then the OpenWrt
# default (mbedtls) is added so libcurl can link.
_TLS_INSTALLED = r"^(libmbedtls\d+|libopenssl\d+)$"
_TLS_FALLBACK: _CurlEntry = ("base", r"^libmbedtls\d+[-_]\d", r"^libmbedtls\d+$")

Progress = Callable[[str], None]


@dataclass(slots=True)
class TargetInfo:
    version: str          # VERSION_ID, e.g. 25.12.4
    board: str            # OPENWRT_BOARD, e.g. qualcommax/ipq60xx (already a target path)
    arch: str             # OPENWRT_ARCH, e.g. aarch64_cortex-a53
    pkg_manager: str      # apk | opkg
    is_snapshot: bool

    @property
    def ext(self) -> str:
        return ".apk" if self.pkg_manager == "apk" else ".ipk"


@dataclass(slots=True)
class Pkg:
    name: str
    url: str
    remote: str = ""      # /tmp path on the router after push


@dataclass(slots=True)
class PreinstallResult:
    ok: bool = False
    installed: list[str] = field(default_factory=list)
    error: Optional[str] = None


# ----- router facts -----------------------------------------------------


def get_target_info(client: RouterClient) -> TargetInfo:
    out = client.run("grep -E 'VERSION_ID|OPENWRT_BOARD|OPENWRT_ARCH' /etc/os-release").stdout

    def f(key: str) -> str:
        m = re.search(rf'{key}="?([^"\n]+)"?', out)
        return m.group(1).strip() if m else ""

    version = f("VERSION_ID")
    pm = "apk" if client.run("command -v apk >/dev/null 2>&1").ok else "opkg"
    is_snapshot = (not version) or version.upper() == "SNAPSHOT"
    return TargetInfo(version=version, board=f("OPENWRT_BOARD"), arch=f("OPENWRT_ARCH"),
                      pkg_manager=pm, is_snapshot=is_snapshot)


def kmods_installed(client: RouterClient) -> bool:
    """Are kmod-nft-tproxy + kmod-tun already present? (used for the SNAPSHOT path)"""
    cmd = "apk info" if client.run("command -v apk >/dev/null 2>&1").ok else "opkg list-installed"
    out = client.run(f"{cmd} 2>/dev/null").stdout
    return all(k in out for k in KMODS)


# ----- PC-side HTTP -----------------------------------------------------


def _http_get(url: str, timeout: int = 60) -> bytes:
    # TLS trust (certifi) + dead-proxy bypass live in _net.http_get.
    return http_get(url, timeout=timeout)


def _links(html: str) -> list[str]:
    return re.findall(r'href="([^"?][^"]*)"', html)


# ----- URL resolution ---------------------------------------------------


def resolve_core_url(ti: TargetInfo, core: str) -> str:
    """Core package download URL (GitHub release, arch-specific)."""
    if core == "hiddify":
        return (f"https://github.com/1andrevich/hiddify-core/releases/latest/download/"
                f"hiddify-core_{ti.arch}{ti.ext}")
    data = json.loads(_http_get(
        "https://api.github.com/repos/shtorm-7/sing-box-extended/releases/latest").decode())
    for a in data.get("assets", []):
        n = a.get("name", "")
        if "openwrt" in n and ti.arch in n and n.endswith(ti.ext):
            return a["browser_download_url"]
    raise RuntimeError(f"нет пакета sing-box-extended для {ti.arch}")


def resolve_kmod_urls(ti: TargetInfo, names: tuple[str, ...] = KMODS) -> list[Pkg]:
    """The kmod packages from the (single) kernel dir under the target's kmods/."""
    base = f"{OPENWRT_DL}/releases/{ti.version}/targets/{ti.board}/kmods/"
    subdirs = [l for l in _links(_http_get(base).decode()) if l.endswith("/") and l[0].isdigit()]
    if not subdirs:
        raise RuntimeError("не найден каталог ядра в kmods/")
    kdir = base + subdirs[0]
    files = _links(_http_get(kdir).decode())
    pkgs: list[Pkg] = []
    for want in names:
        # apk names as `kmod-nft-tproxy-<ver>.apk` (hyphen), opkg as `kmod-..._<ver>.ipk`
        # (underscore). Require the separator be followed by a version digit so a
        # longer package name can't be matched by accident.
        pat = re.compile(rf"^{re.escape(want)}[-_]\d")
        match = next((f for f in files if pat.match(f) and f.endswith(ti.ext)), None)
        if not match:
            raise RuntimeError(f"не найден {want} в {kdir}")
        pkgs.append(Pkg(name=want, url=kdir + match))
    return pkgs


def _feed_url(ti: TargetInfo, feed: str) -> str:
    return f"{OPENWRT_DL}/releases/{ti.version}/packages/{ti.arch}/{feed}/"


def _feed_files(ti: TargetInfo, feed: str) -> list[str]:
    return _links(_http_get(_feed_url(ti, feed)).decode())


def installed_packages(client: RouterClient, ti: TargetInfo) -> set[str]:
    """Set of installed package names (used to skip deps already present)."""
    if ti.pkg_manager == "apk":
        out = client.run("apk info 2>/dev/null").stdout
        return {ln.strip() for ln in out.splitlines() if ln.strip()}
    out = client.run("opkg list-installed 2>/dev/null").stdout
    return {ln.split(" ", 1)[0].strip() for ln in out.splitlines() if ln.strip()}


def resolve_byedpi_url(ti: TargetInfo) -> tuple[str, str]:
    """(download URL, version) for ByeDPI's prebuilt package for this arch."""
    data = json.loads(_http_get(
        f"https://api.github.com/repos/{BYEDPI_REPO}/releases/latest").decode())
    tag = data.get("tag_name", "")
    want = f"_{ti.arch}{ti.ext}"
    for a in data.get("assets", []):
        n = a.get("name", "")
        if n.startswith("byedpi_") and n.endswith(want):
            return a["browser_download_url"], tag.lstrip("v")
    raise RuntimeError(f"нет пакета ByeDPI для {ti.arch}")


def resolve_zapret_url(ti: TargetInfo) -> tuple[str, str]:
    """(download URL, version) for Zapret's (zapret2) prebuilt package for this arch.

    Asset names are version-less: ``zapret2_<arch>.<ext>`` (see zapret2-openwrt)."""
    data = json.loads(_http_get(
        f"https://api.github.com/repos/{ZAPRET_REPO}/releases/latest").decode())
    tag = data.get("tag_name", "")
    want = f"zapret2_{ti.arch}{ti.ext}"
    for a in data.get("assets", []):
        if a.get("name", "") == want:
            return a["browser_download_url"], tag.lstrip("v")
    raise RuntimeError(f"нет пакета Zapret для {ti.arch}")


def resolve_curl_pkgs(client: RouterClient, ti: TargetInfo) -> list[Pkg]:
    """curl + its runtime closure, minus whatever the router already has.

    The router is queried for installed packages so an offline target only
    receives the pieces it is actually missing — usually just curl + libcurl.
    """
    installed = installed_packages(client, ti)
    entries = list(_CURL_CLOSURE)
    if not any(re.match(_TLS_INSTALLED, n) for n in installed):
        entries.append(_TLS_FALLBACK)  # no TLS lib at all — ship the default

    cache: dict[str, list[str]] = {}
    pkgs: list[Pkg] = []
    for feed, file_re, name_re in entries:
        if any(re.match(name_re, n) for n in installed):
            continue  # already on the router
        files = cache.get(feed) or cache.setdefault(feed, _feed_files(ti, feed))
        fpat = re.compile(file_re)
        match = next((f for f in files if fpat.match(f) and f.endswith(ti.ext)), None)
        if not match:
            # curl/libcurl are mandatory; an unfound optional lib is tolerated
            # (the router most likely already provides it under another name).
            if name_re.startswith(r"^(curl|libcurl)") or "curl" in file_re:
                raise RuntimeError(f"не найден пакет {file_re} в фиде {feed}")
            continue
        pkgs.append(Pkg(name=match[: match.index(ti.ext)].rstrip("._-"),
                        url=_feed_url(ti, feed) + match))
    return pkgs


# ----- orchestration ----------------------------------------------------


def plan_packages(client: RouterClient, ti: TargetInfo, core: str,
                  *, with_byedpi: bool = False, with_zapret: bool = False,
                  with_app: bool = False, language: str = "ru") -> list[Pkg]:
    """Resolve every package URL the PC will download (core + kmods
    [+ LuCI app + i18n] [+ ByeDPI] [+ Zapret + kmod-nft-queue] [+ curl])."""
    pkgs = [Pkg(name=f"{core}-core", url=resolve_core_url(ti, core))]
    # Zapret's `nft queue` needs the NFQUEUE module; pull it alongside the core kmods.
    kmods = KMODS + ((ZAPRET_KMOD,) if with_zapret else ())
    pkgs += resolve_kmod_urls(ti, kmods)
    if with_app:
        # Lazy import: install_app imports THIS module at top level, so importing
        # it at module load would be circular. By call time both are fully loaded.
        from .install_app import APP_PKG, resolve_app_assets
        assets = resolve_app_assets(ti, language)
        pkgs.append(Pkg(name=APP_PKG, url=assets.app_url))
        if assets.i18n_url:
            pkgs.append(Pkg(name=f"luci-i18n-homeproxy-{language}", url=assets.i18n_url))
    if with_byedpi:
        url, ver = resolve_byedpi_url(ti)
        pkgs.append(Pkg(name=f"byedpi-{ver}", url=url))
    if with_zapret:
        url, ver = resolve_zapret_url(ti)
        pkgs.append(Pkg(name=f"zapret2-{ver}", url=url))
    # curl is a runtime dep of BOTH testers — resolve its closure once if either is on.
    if with_byedpi or with_zapret:
        pkgs += resolve_curl_pkgs(client, ti)
    return pkgs


def run(client: RouterClient, core: str, *, with_byedpi: bool = False,
        with_zapret: bool = False,
        with_app: bool = False, language: str = "ru",
        progress: Optional[Progress] = None, do_install: bool = True) -> PreinstallResult:
    """Download (PC) → push → install (router) the core + kmods offline.

    With ``with_app`` the LuCI app (+ language pack) is staged too, so an offline
    target ends up with a working Re:HomeProxy (rpcd scripts present) rather than
    just the core binary — required for the later offline node-import step."""
    res = PreinstallResult()

    def say(m: str) -> None:
        if progress:
            progress(m)

    ti = get_target_info(client)
    if ti.is_snapshot:
        if kmods_installed(client):
            say("SNAPSHOT: нужные kmod уже установлены — ставлю только ядро.")
        else:
            res.error = ("На устройстве SNAPSHOT — автоматическая установка kmod невозможна "
                         "(модули привязаны к сборке). Используйте релизную прошивку.")
            return res
    if not ti.arch or not ti.board:
        res.error = "не удалось определить arch/board роутера"
        return res

    try:
        say(f"Роутер: {ti.board} · {ti.version} · {ti.arch} ({ti.pkg_manager})")
        say("Определяю ссылки на пакеты…")
        pkgs = plan_packages(client, ti, core, with_byedpi=with_byedpi,
                             with_zapret=with_zapret, with_app=with_app, language=language)
        if ti.is_snapshot:
            pkgs = [p for p in pkgs if not p.name.startswith("kmod-")]  # kmods already present
    except Exception as exc:  # noqa: BLE001
        res.error = f"не удалось определить пакеты: {exc}"
        return res

    # Download on the PC, push to the router.
    for p in pkgs:
        try:
            say(f"Скачиваю {p.name}…")
            data = _http_get(p.url, timeout=300)
            p.remote = f"/tmp/re-preinstall-{p.name}{ti.ext}"
            say(f"Передаю {p.name} на роутер ({len(data) // 1024} КБ)…")
            client.write_file(p.remote, data)
        except Exception as exc:  # noqa: BLE001
            res.error = f"{p.name}: {exc}"
            return res

    if not do_install:
        say("Файлы переданы (установка пропущена).")
        res.ok = True
        res.installed = [p.name for p in pkgs]
        return res

    # Install from the pushed local files (offline; --allow-untrusted since the
    # PC fetched them over https, the router has no repo keys for these).
    remotes = " ".join(p.remote for p in pkgs)
    say("Устанавливаю пакеты…")
    if ti.pkg_manager == "apk":
        cmd = f"apk add --no-cache --allow-untrusted {remotes}"
    else:
        cmd = f"opkg install {remotes}"
    out = client.run(f"{cmd} 2>&1; RC=$?; rm -f {remotes}; exit $RC", timeout=180)
    if not out.ok:
        res.error = f"установка не удалась: {out.stdout.strip()[-300:]}"
        return res

    res.ok = True
    res.installed = [p.name for p in pkgs]
    if with_app:
        # Register luci.homeproxy + its rpcd scripts, exactly as the online
        # installer does, so the staged router is ready for node import offline.
        say("Перезапускаю rpcd…")
        client.run("/etc/init.d/rpcd restart 2>/dev/null; sleep 2; true")
    if with_byedpi:
        # Match the on-device installer: ByeDPI must not auto-start after a bare
        # preinstall — it's enabled later from Re:HomeProxy's ByeDPI section.
        client.run("/etc/init.d/ciadpi stop 2>/dev/null; "
                   "/etc/init.d/ciadpi disable 2>/dev/null; true")
    if with_zapret:
        # Same as zapret_install_pkg: HomeProxy runs its OWN nfqws2 (qnum 200), so the
        # package's bundled service must stay stopped/disabled.
        client.run("/etc/init.d/zapret2 stop 2>/dev/null; "
                   "/etc/init.d/zapret2 disable 2>/dev/null; true")
    say("Готово.")
    return res
