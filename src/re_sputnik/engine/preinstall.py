# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
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
import shlex
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..router import RouterClient
from ._net import http_get
from ..i18n import _

OPENWRT_DL = "https://downloads.openwrt.org"
KMODS = ("kmod-nft-tproxy", "kmod-tun")
ZAPRET_KMOD = "kmod-nft-queue"   # NFQUEUE — hiddify-core dep + needed by Zapret (always staged)

# Transitive kmod deps the OFFLINE `apk add` can't fetch (online would pull them):
# kmod-nft-tproxy needs kmod-nf-tproxy; the sing-box-based cores (both) need
# kmod-inet-diag; kmod-nft-queue needs kmod-nfnetlink-queue. The base nft/netlink
# modules THESE rest on are already present on any firewall4 router. Staged
# installed-aware + tolerant (a dep absent from the feed is assumed kernel-built-in).
KMOD_DEPS = ("kmod-nf-tproxy", "kmod-inet-diag")
ZAPRET_KMOD_DEP = "kmod-nfnetlink-queue"
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

# zapret2's prebuilt package hard-depends on GNU coreutils (sleep/sort) and gzip —
# busybox does NOT satisfy these as packages, so an OFFLINE preinstall must stage
# them too or `apk add zapret2` fails with "coreutils-sleep (no such package)" etc.
# (an online install pulls them from the feed automatically). All are in `packages`.
_ZAPRET_CLOSURE: tuple[_CurlEntry, ...] = (
    ("packages", r"^coreutils[-_]\d",       r"^coreutils$"),
    ("packages", r"^coreutils-sleep[-_]\d", r"^coreutils-sleep$"),
    ("packages", r"^coreutils-sort[-_]\d",  r"^coreutils-sort$"),
    ("packages", r"^gzip[-_]\d",            r"^gzip$"),
)

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

    @property
    def snapshot_kernel(self) -> bool:
        """True when kmods can't be pre-staged for this build: ANY snapshot-suffixed
        version (bare ``SNAPSHOT`` or versioned like ``25.12-SNAPSHOT``) carries kmods
        locked to an exact kernel hash that rotates on the OpenWrt mirror, so the PC
        can't reliably fetch a matching one. Distinct from ``is_snapshot`` (bare only),
        which gates package-feed compatibility — a versioned snapshot still uses the
        25.12 package tree, it's only its KMODS that aren't stageable."""
        return "SNAPSHOT" in (self.version or "").upper()


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
    # ONLY a bare rolling "SNAPSHOT" (or empty) is a true snapshot. A VERSIONED
    # snapshot like "25.12-SNAPSHOT" is package-compatible with the 25.12 release
    # tree and is deliberately NOT treated as a blocking snapshot — do not change
    # this to a substring match.
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
    # TLS trust (certifi) + dead-proxy bypass live in _net.http_get. For allow-listed
    # GitHub *release* URLs, fall back to the mirror (GitHub→mirror; once latched,
    # mirror-FIRST). Non-mirrorable URLs (api.github.com, downloads.openwrt.org) have a
    # single candidate and are fetched directly — same as before. On a successful mirror
    # fetch after GitHub failed, latch the session so the rest of this preinstall doesn't
    # re-hit a throttled GitHub. Keeps the FIRST (GitHub) error if every candidate fails.
    from .mirror import download_candidates, mirror_url, set_session_mirror
    first_exc: "Exception | None" = None
    candidates = download_candidates(url)
    for i, cand in enumerate(candidates):
        try:
            data = http_get(cand, timeout=timeout)
            if i > 0 and mirror_url(url):
                set_session_mirror(True)
            return data
        except Exception as exc:  # noqa: BLE001 — try the next candidate
            if first_exc is None:
                first_exc = exc
    raise first_exc if first_exc else RuntimeError("no download candidates")


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


def _kmod_dir(ti: TargetInfo) -> tuple[str, list[str]]:
    """(kernel-dir URL, file list) for the target's single kmods/<kver>/ directory."""
    base = f"{OPENWRT_DL}/releases/{ti.version}/targets/{ti.board}/kmods/"
    subdirs = [l for l in _links(_http_get(base).decode()) if l.endswith("/") and l[0].isdigit()]
    if not subdirs:
        raise RuntimeError(_("не найден каталог ядра в kmods/"))
    kdir = base + subdirs[0]
    return kdir, _links(_http_get(kdir).decode())


def _find_kmod(files: list[str], kdir: str, want: str, ext: str) -> Optional[Pkg]:
    # apk names as `kmod-nft-tproxy-<ver>.apk` (hyphen), opkg as `kmod-..._<ver>.ipk`
    # (underscore). Require the separator be followed by a version digit so a longer
    # package name can't be matched by accident.
    pat = re.compile(rf"^{re.escape(want)}[-_]\d")
    match = next((f for f in files if pat.match(f) and f.endswith(ext)), None)
    return Pkg(name=want, url=kdir + match) if match else None


def resolve_kmod_urls(ti: TargetInfo, names: tuple[str, ...] = KMODS) -> list[Pkg]:
    """The kmod packages from the (single) kernel dir under the target's kmods/."""
    kdir, files = _kmod_dir(ti)
    pkgs: list[Pkg] = []
    for want in names:
        pkg = _find_kmod(files, kdir, want, ti.ext)
        if pkg is None:
            raise RuntimeError(f"не найден {want} в {kdir}")
        pkgs.append(pkg)
    return pkgs


def resolve_kmod_deps(client: RouterClient, ti: TargetInfo, names: tuple[str, ...]) -> list[Pkg]:
    """Transitive kmod deps of the primary kmods/core, minus whatever the router
    already has — needed only for the OFFLINE preinstall path. Tolerant: a dep
    that isn't a separate package in the feed is assumed kernel-built-in and skipped
    (the deeper nft/netlink modules it rests on are already on a firewall4 router)."""
    installed = installed_packages(client, ti)
    kdir, files = _kmod_dir(ti)
    pkgs: list[Pkg] = []
    for want in names:
        if want in installed:
            continue
        pkg = _find_kmod(files, kdir, want, ti.ext)
        if pkg is not None:
            pkgs.append(pkg)
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


def resolve_luci_i18n_pkgs(client: RouterClient, ti: TargetInfo, language: str) -> list[Pkg]:
    """LuCI UI language packs from the `luci` feed — staged for the OFFLINE
    preinstall so the WHOLE web interface (every installed luci-app/mod page, not
    just Re:HomeProxy) is localized. Online install pulls these via `apk add`
    (install_app._install_luci_i18n); offline they must be downloaded. The
    component set is derived from what's actually installed on the router, and a
    component without an own pack in the feed (luci-mod-* covered by base, opkg on
    an apk system, …) is simply skipped."""
    if not language or language == "en":
        return []
    from .install_app import luci_i18n_components
    files = _feed_files(ti, "luci")
    base = _feed_url(ti, "luci")
    pkgs: list[Pkg] = []
    for comp in luci_i18n_components(client):
        want = f"luci-i18n-{comp}-{language}"
        pat = re.compile(rf"^{re.escape(want)}[-_]\d")
        match = next((f for f in files if pat.match(f) and f.endswith(ti.ext)), None)
        if match:
            pkgs.append(Pkg(name=want, url=base + match))
    return pkgs


def resolve_zapret_deps(client: RouterClient, ti: TargetInfo) -> list[Pkg]:
    """zapret2's runtime closure (coreutils + coreutils-sleep/sort + gzip), minus
    whatever the router already has — needed only for the OFFLINE preinstall path,
    since the single `apk add` of staged files can't fetch them from the network."""
    installed = installed_packages(client, ti)
    cache: dict[str, list[str]] = {}
    pkgs: list[Pkg] = []
    for feed, file_re, name_re in _ZAPRET_CLOSURE:
        if any(re.match(name_re, n) for n in installed):
            continue  # already on the router
        files = cache.get(feed) or cache.setdefault(feed, _feed_files(ti, feed))
        fpat = re.compile(file_re)
        match = next((f for f in files if fpat.match(f) and f.endswith(ti.ext)), None)
        if not match:
            # All four are hard deps of zapret2; a miss means the offline install
            # would fail later anyway — surface it now with a clear message.
            raise RuntimeError(f"не найдена зависимость Zapret «{file_re}» в фиде {feed}")
        pkgs.append(Pkg(name=match[: match.index(ti.ext)].rstrip("._-"),
                        url=_feed_url(ti, feed) + match))
    return pkgs


# ----- orchestration ----------------------------------------------------


def _has_ucode_mod_digest(ti: TargetInfo) -> bool:
    """`ucode-mod-digest` exists in the 24.10+ feeds only; 23.05 has no such package
    (and its legacy app build doesn't require it). A versioned/bare SNAPSHOT parses to
    its leading YY.MM (or, if bare, falls through to True = newest tree, which has it)."""
    m = re.match(r"(\d+)\.(\d+)", ti.version or "")
    return (int(m.group(1)), int(m.group(2))) >= (24, 10) if m else True


def resolve_app_dep_pkgs(client: RouterClient, ti: TargetInfo) -> list[Pkg]:
    """luci-app-re-homeproxy's non-default dependency `ucode-mod-digest` (LUCI_DEPENDS).
    The offline `apk add`/`opkg install` of staged files can't fetch it, so without
    staging it the dep is left UNSATISFIED (opkg: "cannot find dependency
    ucode-mod-digest") and the install fails with an opaque error. firewall4 — the other
    LUCI_DEPENDS — is on every router already. ucode-mod-digest lives in the `base` feed
    and only on 24.10+ (skip on 23.05). Staged only if the router lacks it."""
    if not _has_ucode_mod_digest(ti):
        return []
    if "ucode-mod-digest" in installed_packages(client, ti):
        return []
    files = _feed_files(ti, "base")
    pat = re.compile(r"^ucode-mod-digest[-_]\d")
    match = next((f for f in files if pat.match(f) and f.endswith(ti.ext)), None)
    if not match:
        raise RuntimeError("не найден пакет ucode-mod-digest в фиде base")
    return [Pkg(name="ucode-mod-digest", url=_feed_url(ti, "base") + match)]


def plan_packages(client: RouterClient, ti: TargetInfo, core: str,
                  *, with_byedpi: bool = False, with_zapret: bool = False,
                  with_app: bool = False, language: str = "ru") -> list[Pkg]:
    """Resolve every package URL the PC will download (core + kmods
    [+ LuCI app + i18n] [+ ByeDPI] [+ Zapret + kmod-nft-queue] [+ curl])."""
    pkgs = [Pkg(name=f"{core}-core", url=resolve_core_url(ti, core))]
    pkgs += resolve_kmod_urls(ti, KMODS)
    # kmod-nft-queue (NFQUEUE) + its kmod-nfnetlink-queue dep are staged ALWAYS now, not
    # just with Zapret: hiddify-core hard-depends on kmod-nft-queue, and pre-staging also
    # preempts an unsatisfied-dep failure when the user later enables Zapret (~14 KB total).
    # Via the TOLERANT dep-resolver (alongside kmod-nf-tproxy, kmod-inet-diag): it's
    # installed-aware, and a module built into the kernel (no separate package) is skipped.
    pkgs += resolve_kmod_deps(client, ti, KMOD_DEPS + (ZAPRET_KMOD, ZAPRET_KMOD_DEP))
    if with_app:
        # Lazy import: install_app imports THIS module at top level, so importing
        # it at module load would be circular. By call time both are fully loaded.
        from .install_app import APP_PKG, resolve_app_assets
        assets = resolve_app_assets(ti, language)
        pkgs.append(Pkg(name=APP_PKG, url=assets.app_url))
        # luci-app-re-homeproxy hard-depends on ucode-mod-digest (24.10+); the offline
        # install can't fetch it from the feed, so stage it or the dep is unsatisfied.
        pkgs += resolve_app_dep_pkgs(client, ti)
        if assets.i18n_url:
            pkgs.append(Pkg(name=f"luci-i18n-homeproxy-{language}", url=assets.i18n_url))
        # Base LuCI UI language packs (luci-i18n-base/firewall/package-manager-…) so
        # the WHOLE interface is localized, not just Re:HomeProxy — the offline
        # `apk add` can't fetch them, so stage them from the `luci` feed.
        pkgs += resolve_luci_i18n_pkgs(client, ti, language)
    if with_byedpi:
        url, ver = resolve_byedpi_url(ti)
        pkgs.append(Pkg(name=f"byedpi-{ver}", url=url))
    if with_zapret:
        url, ver = resolve_zapret_url(ti)
        pkgs.append(Pkg(name=f"zapret2-{ver}", url=url))
        # Stage zapret2's coreutils/gzip closure too — the offline `apk add` can't
        # fetch them from the network (busybox doesn't satisfy these deps).
        pkgs += resolve_zapret_deps(client, ti)
    # curl is a runtime dep of BOTH testers — resolve its closure once if either is on.
    if with_byedpi or with_zapret:
        pkgs += resolve_curl_pkgs(client, ti)
    return pkgs


def explain_install_failure(output: str, pkg_manager: str) -> str:
    """Turn raw opkg/apk install output into a SPECIFIC, actionable reason — names the
    missing package/dependency or flags out-of-space — so a maintainer can fix it
    without guessing, instead of a blind char-tail that hides the real cause (opkg
    prints `Collected errors:` to stderr, which interleaves and gets scrolled out)."""
    text = (output or "").strip()
    low = text.lower()

    # Out of space — state it plainly with the numbers opkg/apk give.
    if "no space left on device" in low or "only have" in low:
        m = re.search(r"only have\s+([\d.]+\s*k?b?)\s+available on filesystem\s+([^\s,]+)"
                      r".*?pkg\s+(\S+)\s+needs\s+([\d.]+\s*k?b?)", text, re.I)
        if m:
            return (f"недостаточно места ({m.group(2)}): свободно {m.group(1)}, "
                    f"пакету {m.group(3)} нужно {m.group(4)}")
        return "недостаточно места на роутере (No space left on device)"

    # opkg: the `Collected errors:` block names the failure (missing dep, bad arch, …).
    idx = text.find("Collected errors:")
    if idx != -1:
        bullets = []
        for ln in text[idx:].splitlines()[1:]:
            s = ln.strip()
            if not s.startswith("*"):
                continue
            s = re.sub(r"^\*\s*[A-Za-z_]+:\s*", "", s).strip()  # drop " * funcname:" noise
            if s and s not in bullets:
                bullets.append(s)
        if bullets:
            return "; ".join(bullets[:3])

    # apk: `ERROR:` lines + "no such package" / "unsatisfiable" detail.
    errs = [ln.strip() for ln in text.splitlines()
            if ln.lstrip().lower().startswith("error")
            or "no such package" in ln.lower() or "unsatisfiable" in ln.lower()]
    if errs:
        return "; ".join(dict.fromkeys(errs))[:300]

    # Fallback: last meaningful lines, minus the chatty progress noise (so we never
    # again surface "…to root… / Configuring …" as if it were the error).
    noise = re.compile(r"^(Installing|Configuring|Downloading)\b", re.I)
    meaningful = [ln.strip() for ln in text.splitlines() if ln.strip() and not noise.match(ln.strip())]
    tail = " ".join(meaningful[-4:]) if meaningful else text
    return tail[-300:] if tail else "неизвестная ошибка"


def run(client: RouterClient, core: str, *, with_byedpi: bool = False,
        with_zapret: bool = False,
        with_app: bool = False, language: str = "ru",
        progress: Optional[Progress] = None, do_install: bool = True) -> PreinstallResult:
    """Download (PC) → push → install (router) the core + kmods offline.

    With ``with_app`` the LuCI app (+ language pack) is staged too, so an offline
    target ends up with a working Re:HomeProxy (rpcd scripts present) rather than
    just the core binary — required for the later offline node-import step."""
    res = PreinstallResult()
    from .mirror import reset_session_mirror
    reset_session_mirror()  # fresh GitHub-throttle decision per preinstall

    def say(m: str) -> None:
        if progress:
            progress(m)

    ti = get_target_info(client)
    if ti.snapshot_kernel:
        # SNAPSHOT-suffixed build: kmods are locked to this exact kernel and can't be
        # pre-staged from the mirror. If they're ALREADY on the router we can stage the
        # rest; otherwise stop with a clear pointer to Quick Setup, where the router's
        # own package manager CAN pull matching kmods (apk add kmod-…).
        if kmods_installed(client):
            say(_("SNAPSHOT: нужные kmod уже установлены — ставлю остальные пакеты."))
        else:
            res.error = (_("На устройстве SNAPSHOT-сборка: модули ядра (kmod) ещё не "
                         "установлены, а предустановка не может их подобрать (они "
                         "привязаны к конкретной сборке ядра). Откройте «Пошаговую "
                         "настройку» — роутер сам установит kmod из своего репозитория, "
                         "после чего предустановка тоже заработает."))
            return res
    if not ti.arch or not ti.board:
        res.error = _("не удалось определить arch/board роутера")
        return res

    try:
        say(f"Роутер: {ti.board} · {ti.version} · {ti.arch} ({ti.pkg_manager})")
        say(_("Определяю ссылки на пакеты…"))
        pkgs = plan_packages(client, ti, core, with_byedpi=with_byedpi,
                             with_zapret=with_zapret, with_app=with_app, language=language)
        if ti.snapshot_kernel:
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
        say(_("Файлы переданы (установка пропущена)."))
        res.ok = True
        res.installed = [p.name for p in pkgs]
        return res

    # Install from the pushed local files (offline; --allow-untrusted since the
    # PC fetched them over https, the router has no repo keys for these).
    remotes = " ".join(p.remote for p in pkgs)
    say(_("Устанавливаю пакеты…"))
    if with_app:
        # If the router still has the pre-rename package, remove it first so the new
        # luci-app-re-homeproxy replaces it cleanly (offline `apk del` needs no network).
        from .install_app import remove_legacy_app
        remove_legacy_app(client, ti.pkg_manager, say)
    if ti.pkg_manager == "apk":
        # NO --no-cache: it forces apk to refetch the repo indexes over the network,
        # which defeats the whole point of an OFFLINE install (and fails on a router
        # with no/poor uplink). All deps are staged as local files, so apk needs no
        # index. See memory: apk --no-cache forces index refetch.
        cmd = f"apk add --allow-untrusted {remotes}"
    else:
        cmd = f"opkg install {remotes}"
    out = client.run(f"{cmd} 2>&1; RC=$?; rm -f {remotes}; exit $RC", timeout=180)
    if not out.ok:
        res.error = f"установка не удалась: {explain_install_failure(out.stdout, ti.pkg_manager)}"
        return res

    res.ok = True
    res.installed = [p.name for p in pkgs]
    if with_app:
        # Register luci.homeproxy + its rpcd scripts, exactly as the online
        # installer does, so the staged router is ready for node import offline.
        say(_("Перезапускаю rpcd…"))
        client.run("/etc/init.d/rpcd restart 2>/dev/null; sleep 2; true")
        # Pin the LuCI web UI to the chosen language (mirrors the online installer);
        # the base langpacks were staged above, so the interface is actually localized.
        if language and language != "en":
            client.run(f"uci set luci.main.lang={shlex.quote(language)}; "
                       "uci commit luci 2>/dev/null; true", timeout=15)
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
    say(_("Готово."))
    return res
