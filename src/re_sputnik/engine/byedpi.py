# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""ByeDPI — status, strategy config, and the multi-host strategy test.

The strategy test is the live "eyes" for DPI bypass: it runs ciadpi with the
given args on a throwaway port and probes far/near sites, judging each by the
TLS handshake (the precise bypass signal). Non-destructive — does not touch the
running ByeDPI.
"""

from __future__ import annotations

from typing import Callable, Optional

from ..router import RouterClient
from ..i18n import _

ENABLED_KEY = "homeproxy.config.byedpi_enabled"
CMD_KEY = "homeproxy.config.byedpi_cmd_opts"

# Named ciadpi strategy presets, mirrored from homeproxy's node.js BYEDPI_PRESETS
# (the canonical source) so the App offers the same dropdown. (name, args).
# A = community YouTube/general dumps; B–M = systematic single techniques.
STRATEGY_PRESETS: tuple[tuple[str, str], ...] = (
    ("A1 — YouTube 1", "-o1 -r-5+se -a1 -At,r,s -d1 -n google.com -Qr -f-1"),
    ("A2 — YouTube 2", "-d1 -d3+s -s6+s -d9+s -s12+s -d15+s -s20+s -d25+s -s30+s -d35+s -r1+s "
     "-S -a1 -As -d1 -d3+s -s6+s -d9+s -s12+s -d15+s -s20+s -d25+s -s30+s -d35+s -S -a1"),
    ("A3 — General 1", "-d1+s -O1 -s29+s -t 5 -An -Ku -a5 -s443+s -d80+s -d443+s -s80+s -s443+s "
     "-d53+s -s53+s -d443+s -An"),
    ("A4 — YouTube 3", '-H:"youtube.com googlevideo.com ggpht.com ytimg.com googleapis.com '
     'googleusercontent.com youtube-ui.l.google.com yt4.ggpht.com" -o1 -a1 -r-5+se -t6 -n rutube.com '
     "-An -f-1 -t8 -n www.google.com -d1 -s1+s -d1+s -s3+s -d6+s -s12+s -d14+s -s20+s -d24+s -s30+s -a1"),
    ("A5 — General 2", '-H:"youtube.com googlevideo.com ytimg.com ggpht.com youtu.be '
     'youtubei.googleapis.com" -Kt,h -d1 -s1+s -s3+s -s6+s -s9+s -s12+s -s15+s -s20+s -s30+s -a1 -An '
     '-H:"soundcloud.com api.soundcloud.com api-v2.soundcloud.com m.soundcloud.com '
     'eventgateway.soundcloud.com api-partners.soundcloud.com api-mobile.soundcloud.com wis.sndcdn.com '
     'va.sndcdn.com invite.soundcloud.com events.soundcloud.com" -Kth -Qorig -n "www.google.com" -f-1 '
     "-t5 -d1 -s1+s -s3+s -s6+s -s9+s -s12+s -s15+s -s20+s -s30+s -Mh,d,r -An "
     '-H:"sndcdn.com a-v2.sndcdn.com cf-hls-media.sndcdn.com cf-media.sndcdn.com '
     'cf-preview-media.sndcdn.com cf-hls-opus-media.sndcdn.com i1.sndcdn.com i2.sndcdn.com '
     'i3.sndcdn.com i4.sndcdn.com assets.soundcloud.com playback.media-streaming.soundcloud.cloud" '
     '-Kth -Qorig -n "www.google.com" -f-1 -t5 -s1 -d2 -Mh,d,r -An '
     '-H:"discord.com discord.gg discord.media discordapp.com cdn.discordapp.com media.discordapp.net '
     'images-ext-1.discordapp.net images-ext-2.discordapp.net images.discordapp.net gateway.discord.gg '
     'status.discord.com api.discord.com discord-attachments-uploads-prd.storage.googleapis.com '
     'hcaptcha.com recaptcha.net accounts.google.com appleid.apple.com" -Kth -Qorig -n "www.google.com" '
     "-f-1 -t5 -o1 -s1+s -s2+s -s5+s -d3+s -s7+s -s10+s -s15+s -An -Ku"),
    ("A6 — General 3", '-H:"youtube.com googlevideo.com ggpht.com ytimg.com googleapis.com '
     'googleusercontent.com youtube-ui.l.google.com yt4.ggpht.com" -o1 -a1 -r-5+se -t6 -n rutube.com -An '
     '-H:"cdn.discordapp.com canary.discord.com vdis.gd ptb.discord.com '
     'discord-attachments-uploads-prd.storage.googleapis.com discord-activities.com discord.co '
     'discord.com discord.design discord.dev discord.gg discord.gift discord.gifts discord.media '
     'discord.new discord.store discord.tools discordactivities.com discordapp.com discordapp.net '
     'media.discordapp.net images-ext-1.discordapp.net images-ext-2.discordapp.net '
     'stable.dl2.discordapp.net discordcdn.com discordmerch.com discordpartygames.com discordsays.com '
     'discordsez.com discordstatus.com" -f-1 -t8 -n www.google.com -s1+s -a5 -An '
     '-H:"soundcloud.com sndcdn.com soundcloud.app.goo.gl" -f-1 -T0.5 -Ars -d0+sm -At -r1+s -An -f-200 '
     "-s2 -s5+hm -t6 -Qr -n wb.ru"),
    ("B1 — Disorder Basic", "--disorder 1"),
    ("B2 — Disorder at SNI", "--disorder 1+s"),
    ("B3 — Disorder TLS+HTTP", "--proto tls,http --disorder 1"),
    ("B4 — Split + Disorder", "--split 1 --disorder 3"),
    ("B5 — Disorder + Auto TLS Record", "--disorder 1 --auto=torst --tlsrec 1+s"),
    ("C1 — Fake TTL=6", "--fake -1 --ttl 6"),
    ("C2 — Fake TTL=8", "--fake -1 --ttl 8"),
    ("C3 — Fake TTL=10", "--fake -1 --ttl 10"),
    ("C4 — Fake TTL=12", "--fake -1 --ttl 12"),
    ("C5 — Fake TTL=15", "--fake -1 --ttl 15"),
    ("D1 — Fake MD5", "--fake -1 --md5sig"),
    ("D2 — Disorder + Fake MD5", "--disorder 1 --fake -1 --md5sig"),
    ("D3 — Fake MD5 TLS+HTTP", "--proto tls,http --fake -1 --md5sig"),
    ("E1 — TLS Record Split", "--tlsrec 1+s"),
    ("E2 — TLS Record + Auto", "--auto=torst --tlsrec 1+s"),
    ("E3 — TLS Record + Timeout", "--auto=torst --timeout 3 --tlsrec 1+s"),
    ("E4 — Disorder + TLS Record", "--disorder 1 --tlsrec 1+s"),
    ("F1 — OOB at SNI", "--oob 1+s"),
    ("F2 — OOB at SNI+3", "--oob 3+s"),
    ("F3 — DisoOB at SNI", "--disoob 1+s"),
    ("F4 — DisoOB + Fake MD5", "--disoob 1+s --fake -1 --md5sig"),
    ("G1 — Split at SNI", "--split 1+s"),
    ("G2 — Split at SNI Middle", "--split 0+sm"),
    ("G3 — Split at 2", "--split 2"),
    ("G4 — Split + OOB", "--split 1+s --oob 2+s"),
    ("H1 — HTTP Host Case Mix", "--proto http --mod-http hcsmix"),
    ("H2 — HTTP Host Double Mix", "--proto http --mod-http hcsmix,dcsmix"),
    ("H3 — HTTP Full Mix", "--proto http --mod-http hcsmix,dcsmix,rmspace"),
    ("H4 — HTTP Mix + Disorder", "--proto tls,http --mod-http hcsmix --disorder 1"),
    ("I1 — Auto SSL Error Fallback", "--fake -1 --ttl 8 --auto=ssl_err --fake -1 --ttl 5"),
    ("I2 — Auto Reset Fallback", "--fake -1 --md5sig --auto=torst --disorder 1"),
    ("J1 — Random TLS Fake", "--fake -1 --fake-tls-mod rand"),
    ("J2 — Original TLS Fake", "--fake -1 --fake-tls-mod orig"),
    ("K1 — Aggressive Split", "--split 1+s --disorder 3+s"),
    ("K2 — Aggressive OOB + MD5", "--oob 1+s --disorder 1 --fake -1 --md5sig"),
    ("K3 — Aggressive DisoOB", "--disoob 1+s --disorder 3+s"),
    ("K4 — Aggressive Combo", "--split 1+s --oob 2+s --disorder 3+s"),
    ("K5 — TLS+HTTP Disorder + Record", "--proto tls,http --disorder 1 --tlsrec 1+s"),
    ("L1 — UDP Fake", "--proto udp --udp-fake 5"),
    ("L2 — TLS+UDP Fake MD5", "--proto tls,udp --fake -1 --md5sig --udp-fake 5"),
    ("M1 — Full TLS Bypass", "--proto tls --fake -1 --md5sig --tlsrec 1+s"),
)


def restart_service(client: RouterClient) -> bool:
    """Restart the homeproxy service so a ByeDPI change takes effect."""
    res = client.ubus_homeproxy("diag_service_restart", timeout=40)
    return bool(res.get("result"))


def get_status(client: RouterClient) -> dict:
    """{installed, version, running, pkg_manager, arch} or {error}."""
    return client.ubus_homeproxy("byedpi_status")


def get_config(client: RouterClient) -> dict:
    return {
        "enabled": client.uci_get(ENABLED_KEY) == "1",
        "cmd_opts": client.uci_get(CMD_KEY) or "",
    }


def set_enabled(client: RouterClient, on: bool) -> None:
    client.uci_set(ENABLED_KEY, "1" if on else "0")
    client.uci_commit("homeproxy")


def set_cmd_opts(client: RouterClient, opts: str) -> None:
    client.uci_set(CMD_KEY, opts.strip())
    client.uci_commit("homeproxy")


def run_test(client: RouterClient, cmd_opts: str) -> dict:
    """Run byedpi_strategy_test with a strategy string.

    Returns {result, passed, total, results:[{tag,label,ok,reason}]} or {error}.
    """
    return client.ubus_homeproxy("byedpi_strategy_test", {"cmd_opts": cmd_opts}, timeout=120)


def install(client: RouterClient, progress: Optional[Callable[[str], None]] = None) -> tuple[bool, str]:
    """Install (or reinstall to latest) ByeDPI: prepare -> curl -> wget -> install_pkg.

    curl is pulled too because the strategy tester needs it. Returns (ok, message)."""
    def say(m: str) -> None:
        if progress:
            progress(m)

    say(_("Проверяю требования…"))
    prep = client.ubus_homeproxy("byedpi_prepare_install", timeout=60)
    if prep.get("error") or not prep.get("dl_url"):
        return False, prep.get("error") or _("Не удалось подготовить установку (нет ссылки).")

    pm = prep.get("pkg_manager")
    say(_("Устанавливаю curl (нужен тестеру)…"))
    add = "apk add" if pm == "apk" else "opkg install"
    client.run(f"{add} curl 2>&1; true", timeout=120)

    say(_("Скачиваю пакет…"))
    if not client.run(f"wget -qO {prep['tmp_path']} '{prep['dl_url']}'", timeout=300).ok:
        return False, _("Не удалось скачать пакет ByeDPI.")

    say(_("Устанавливаю…"))
    inst = client.ubus_homeproxy(
        "byedpi_install_pkg",
        {"tmp_path": prep["tmp_path"], "pkg_manager": pm}, timeout=180)
    if not inst.get("result"):
        return False, inst.get("error") or _("Установка ByeDPI не удалась.")
    return True, _("ByeDPI установлен.")


def remove(client: RouterClient) -> bool:
    res = client.ubus_homeproxy("byedpi_remove", timeout=60)
    return bool(res.get("result"))
