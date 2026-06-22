# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""AmneziaVPN ``vpn://`` share-link import — decoded entirely on the PC.

``vpn://`` is a container format: ``vpn://`` + base64url( qCompress(JSON) ), where
qCompress = a 4-byte big-endian uncompressed-length header followed by a raw zlib
stream. The JSON holds one or more ``containers``; we decode it here (Python has
zlib natively) and convert each into an input for HomeProxy's OWN importers —
never touching HomeProxy code or the device:

  * amnezia-awg / amnezia-awg2  → a WireGuard/AmneziaWG ``.conf``  → import_conf.uc
  * amnezia-xray                → a vless/vmess/trojan/ss share-link → import_link.uc

This mirrors the field mapping the LuCI frontend (node.js ``parseVpnLink``) does
in the browser, but headless. amnezia-openvpn / amnezia-ipsec are skipped.
"""

from __future__ import annotations

import base64
import binascii
import json
import zlib
from typing import Optional
from urllib.parse import quote, urlencode

from ..router import RouterClient
from . import nodes as nd


class VpnLinkError(Exception):
    pass


# ----- container decode -------------------------------------------------


def decode_container(uri: str) -> dict:
    """vpn:// → the decoded AmneziaVPN JSON container (raises on bad input)."""
    if not uri.startswith("vpn://"):
        raise VpnLinkError("not a vpn:// link")
    b64 = uri[6:].strip().replace("-", "+").replace("_", "/")
    b64 += "=" * (-len(b64) % 4)
    try:
        raw = base64.b64decode(b64)
    except binascii.Error as exc:
        raise VpnLinkError(f"base64 decode failed: {exc}") from exc
    if len(raw) <= 4:
        raise VpnLinkError("payload too short")
    try:
        # qCompress prepends a 4-byte big-endian length; the rest is a zlib stream.
        text = zlib.decompress(raw[4:])
    except zlib.error as exc:
        raise VpnLinkError(f"zlib decompress failed: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise VpnLinkError(f"JSON parse failed: {exc}") from exc


def _pick_container(d: dict) -> Optional[dict]:
    conts = d.get("containers") or []
    default = d.get("defaultContainer")
    return next((c for c in conts if c.get("container") == default), conts[0] if conts else None)


# ----- amnezia-awg → .conf ----------------------------------------------


def _awg_to_conf(container: dict, label: str) -> Optional[str]:
    awg = container.get("awg")
    if not awg:
        return None
    cfg = dict(awg)
    if awg.get("last_config"):  # detailed fields live here as a JSON string
        try:
            cfg.update(json.loads(awg["last_config"]))
        except (json.JSONDecodeError, TypeError):
            pass
    priv = cfg.get("client_priv_key")
    pub = cfg.get("server_pub_key")
    host = cfg.get("hostName")
    port = cfg.get("port") or awg.get("port")
    if not (priv and pub and host and port):
        return None
    client_ip = cfg.get("client_ip") or ""
    address = client_ip if "/" in client_ip else (client_ip + "/32" if client_ip else "")

    lines = ["[Interface]", f"PrivateKey = {priv}"]
    if address:
        lines.append(f"Address = {address}")
    if cfg.get("mtu"):
        lines.append(f"MTU = {cfg['mtu']}")
    # AmneziaWG obfuscation params (only if present → marks it AWG vs plain WG).
    for k in ("Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4",
              "H1", "H2", "H3", "H4", "I1", "I2", "I3", "I4", "I5"):
        if awg.get(k) not in (None, ""):
            lines.append(f"{k} = {awg[k]}")
    lines += ["", "[Peer]", f"PublicKey = {pub}"]
    if cfg.get("psk_key"):
        lines.append(f"PresharedKey = {cfg['psk_key']}")
    lines.append("AllowedIPs = 0.0.0.0/0, ::/0")
    lines.append(f"Endpoint = {host}:{port}")
    if cfg.get("persistent_keep_alive"):
        lines.append(f"PersistentKeepalive = {cfg['persistent_keep_alive']}")
    return "\n".join(lines) + "\n"


# ----- amnezia-xray → share-link ----------------------------------------

_NET_MAP = {"ws": "ws", "grpc": "grpc", "h2": "http", "http": "http",
            "httpupgrade": "httpupgrade", "xhttp": "xhttp", "splithttp": "xhttp"}


def _xray_to_link(container: dict, label: str, host_hint: str) -> Optional[str]:
    xray = container.get("xray")
    if not xray or not xray.get("last_config"):
        return None
    try:
        xc = json.loads(xray["last_config"])
    except (json.JSONDecodeError, TypeError):
        return None
    ob = next((o for o in xc.get("outbounds", [])
               if o.get("protocol") not in ("freedom", "blackhole", "dns")), None)
    if not ob:
        return None

    stream = ob.get("streamSettings") or {}
    net = _NET_MAP.get(stream.get("network"), "tcp")
    sec = stream.get("security") or "none"
    params: dict[str, str] = {"type": net, "security": sec}

    if sec == "reality":
        r = stream.get("realitySettings") or {}
        params.update({k: v for k, v in {
            "sni": r.get("serverName"), "fp": r.get("fingerprint"),
            "pbk": r.get("publicKey"), "sid": r.get("shortId"), "spx": r.get("spiderX"),
        }.items() if v})
    elif sec == "tls":
        t = stream.get("tlsSettings") or {}
        params.update({k: v for k, v in {
            "sni": t.get("serverName"), "fp": t.get("fingerprint"),
            "alpn": ",".join(t.get("alpn", [])) or None,
        }.items() if v})
        if t.get("allowInsecure"):
            params["allowInsecure"] = "1"

    if net == "ws":
        ws = stream.get("wsSettings") or {}
        if ws.get("path"):
            params["path"] = ws["path"]
        if (ws.get("headers") or {}).get("Host"):
            params["host"] = ws["headers"]["Host"]
    elif net == "grpc":
        params["serviceName"] = (stream.get("grpcSettings") or {}).get("serviceName", "")
    elif net == "xhttp":
        xh = stream.get("xhttpSettings") or stream.get("splithttpSettings") or {}
        for src, dst in (("path", "path"), ("host", "host"), ("mode", "mode")):
            if xh.get(src):
                params[dst] = xh[src]

    proto = ob["protocol"]
    frag = quote(label or host_hint or proto)

    if proto in ("vless", "vmess"):
        v = ((ob.get("settings") or {}).get("vnext") or [{}])[0]
        user = (v.get("users") or [{}])[0]
        addr, port, uid = v.get("address"), v.get("port"), user.get("id")
        if not (addr and port and uid):
            return None
        if proto == "vless":
            if sec in ("reality", "tls") and user.get("flow"):
                params["flow"] = user["flow"]
            return f"vless://{uid}@{addr}:{port}?{urlencode(params)}#{frag}"
        # vmess: classic base64(JSON) form
        vm = {"v": "2", "ps": label or proto, "add": addr, "port": str(port), "id": uid,
              "aid": str(user.get("alterId", 0)), "net": net, "type": "none",
              "host": params.get("host", ""), "path": params.get("path", ""),
              "tls": "tls" if sec == "tls" else "", "sni": params.get("sni", "")}
        return "vmess://" + base64.b64encode(
            json.dumps(vm, separators=(",", ":")).encode()).decode()

    srv = ((ob.get("settings") or {}).get("servers") or [{}])[0]
    addr, port = srv.get("address"), srv.get("port")
    if not (addr and port):
        return None
    if proto == "trojan":
        if not srv.get("password"):
            return None
        return f"trojan://{quote(srv['password'])}@{addr}:{port}?{urlencode(params)}#{frag}"
    if proto == "shadowsocks":
        method, pw = srv.get("method"), srv.get("password")
        if not (method and pw):
            return None
        userinfo = base64.urlsafe_b64encode(f"{method}:{pw}".encode()).decode().rstrip("=")
        return f"ss://{userinfo}@{addr}:{port}#{frag}"
    return None


# ----- top-level --------------------------------------------------------


def vpn_to_importable(uri: str) -> tuple[str, str]:
    """vpn:// → ('conf', conf_text) or ('link', share_link). Raises VpnLinkError."""
    d = decode_container(uri)
    container = _pick_container(d)
    if not container:
        raise VpnLinkError("no container in vpn:// link")
    label = d.get("description") or d.get("hostName") or ""
    kind = container.get("container")
    if kind in ("amnezia-awg", "amnezia-awg2"):
        conf = _awg_to_conf(container, label)
        if not conf:
            raise VpnLinkError("incomplete AmneziaWG container")
        return "conf", conf
    if kind == "amnezia-xray":
        link = _xray_to_link(container, label, d.get("hostName", ""))
        if not link:
            raise VpnLinkError("unsupported/incomplete Xray container")
        return "link", link
    raise VpnLinkError(f"unsupported container type: {kind}")


def import_vpn_links(client: RouterClient, text: str) -> dict:
    """Import one or more vpn:// links via the right HomeProxy importer.

    Returns {imported:int, failed:int, errors:[str]}. AmneziaWG links go through
    import_conf.uc; Xray links are turned into share-links and batched through
    import_link.uc.
    """
    imported = 0
    failed = 0
    errors: list[str] = []
    links: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("vpn://"):
            continue
        try:
            kind, payload = vpn_to_importable(line)
        except VpnLinkError as exc:
            failed += 1
            errors.append(str(exc))
            continue
        if kind == "conf":
            res = nd.import_conf(client, payload, label="AmneziaWG")
            if res.get("result"):
                imported += 1
            else:
                failed += 1
                errors.append(res.get("error", "import_conf failed"))
        else:
            links.append(payload)
    if links:
        res = nd.import_links(client, "\n".join(links))
        imported += len(res.get("imported") or [])
        failed += res.get("failed") or 0
        if res.get("error"):
            errors.append(res["error"])
    return {"imported": imported, "failed": failed, "errors": errors}


def import_mixed_links(client: RouterClient, text: str) -> dict:
    """Import a paste that may mix ``vpn://`` with ordinary share-links.

    vpn:// lines are decoded here and routed to the right importer; the rest go
    straight to import_link.uc. Returns {imported:int, failed:int, errors:[str]}.
    """
    vpn_lines: list[str] = []
    other: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        (vpn_lines if s.startswith("vpn://") else other).append(s)

    imported = 0
    failed = 0
    errors: list[str] = []
    if other:
        r = nd.import_links(client, "\n".join(other))
        imported += len(r.get("imported") or [])
        failed += r.get("failed") or 0
        if r.get("error"):
            errors.append(r["error"])
    if vpn_lines:
        r = import_vpn_links(client, "\n".join(vpn_lines))
        imported += r["imported"]
        failed += r["failed"]
        errors += r["errors"]
    return {"imported": imported, "failed": failed, "errors": errors}


def add_mixed_input(client: RouterClient, text: str, *, fetch: bool = True) -> dict:
    """One paste field → the right destination, classified per line.

    A line that starts with ``http://`` / ``https://`` is treated as a
    **subscription** URL (registered via add_subscription); everything else
    (``vless://`` ``vmess://`` ``hysteria2://`` ``trojan://`` ``ss://`` ``vpn://``…)
    is a single server **key** and goes through import_mixed_links. This is what
    lets the UI present one box instead of a separate "subscription" vs "key" field.

    When ``fetch`` is set and at least one *new* subscription was registered, runs
    update_subscriptions once so the servers appear immediately (skip it offline —
    fetching needs internet). Returns
    ``{subs_added:int, imported:int, failed:int, errors:[str], update?:dict}``.
    """
    subs: list[str] = []
    links: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        (subs if s.lower().startswith(("http://", "https://")) else links).append(s)

    errors: list[str] = []
    subs_added = 0
    if subs:
        existing = set(nd.list_subscriptions(client))
        for url in subs:
            if url in existing:
                continue  # add_subscription is idempotent, but skip to keep the count honest
            try:
                nd.add_subscription(client, url)
                existing.add(url)
                subs_added += 1
            except Exception as exc:  # RouterError / empty URL — report, keep going
                errors.append(str(exc))

    imported = 0
    failed = 0
    if links:
        r = import_mixed_links(client, "\n".join(links))
        imported = r["imported"]
        failed = r["failed"]
        errors += r["errors"]

    result: dict = {"subs_added": subs_added, "imported": imported,
                    "failed": failed, "errors": errors}
    if fetch and subs_added:
        result["update"] = nd.update_subscriptions(client)
    return result
