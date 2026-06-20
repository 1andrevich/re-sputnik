# SPDX-License-Identifier: GPL-2.0-only
"""Router maintenance — full config backup, restore, and factory reset.

Mirrors LuCI's "Backup / Flash firmware" page, done over SSH:

- backup  : ``sysupgrade --create-backup -`` streams a tar.gz of the device config
            (files in /etc/sysupgrade.conf + opkg/apk-tracked /etc changes) to
            stdout; we read those raw bytes straight off the SSH channel — same as
            the LuCI page (the router has no sftp/scp nor a base64 applet).
- restore : upload a backup tar.gz, validate it, extract into ``/`` and reboot —
            exactly what LuCI does. DESTRUCTIVE: overwrites current config.
- factory : ``firstboot -y && reboot`` wipes the overlay back to firmware defaults.

All three are guarded in the UI behind an explicit second confirmation; this
module just performs the action it is told to.
"""

from __future__ import annotations

from ..router import RouterClient, RouterError

_RESTORE_TMP = "/tmp/rs-restore.tar.gz"

# gzip magic — a sanity gate so we never try to restore an arbitrary file.
_GZIP_MAGIC = b"\x1f\x8b"


# Mirror exactly what the LuCI browser page does: stream
# `sysupgrade --create-backup -` (dash = STDOUT, NO temp file) and read the raw
# binary blob off the SSH channel. We read raw bytes (run_bytes) instead of
# base64-ing it, because this busybox has no `base64` applet. `-b -` is a fallback
# for older sysupgrade flag spellings.
_BACKUP_CMD = "/sbin/sysupgrade --create-backup - 2>/tmp/rs-backup.err || " \
              "sysupgrade -b - 2>>/tmp/rs-backup.err; " \
              "cat /tmp/rs-backup.err >&2; rm -f /tmp/rs-backup.err"


def create_backup(client: RouterClient) -> bytes:
    """Build a full config backup and return the raw tar.gz bytes.

    Uses the SAME method as the LuCI web UI — ``sysupgrade --create-backup -``
    streamed to stdout (no temp file) — read straight off the SSH channel as raw
    bytes (the router has neither sftp/scp nor a ``base64`` applet). On failure
    the router's own sysupgrade error is surfaced.
    """
    data, err, _code = client.run_bytes(_BACKUP_CMD, timeout=120)
    log = err.strip()
    if data[:2] != _GZIP_MAGIC:
        head = data[:200].decode("utf-8", "replace").strip()
        detail = (log or head or "(пустой ответ)")[:600]
        raise RouterError("резервная копия не создалась на роутере. Ответ sysupgrade:\n" + detail)
    return data


def restore_backup(client: RouterClient, data: bytes) -> None:
    """Upload a backup archive, validate it on-device, extract into ``/`` and
    reboot (the LuCI restore flow). The reboot is detached so this call returns
    before the connection drops; the caller must warn the user and reconnect.

    Raises before touching the system if ``data`` is not a valid gzip tarball.
    """
    if data[:2] != _GZIP_MAGIC:
        raise ValueError("Это не похоже на резервную копию (.tar.gz).")
    client.write_file(_RESTORE_TMP, data)
    # Validate it is a readable gzip tar before extracting over the live config.
    check = client.run(f"tar -tzf {_RESTORE_TMP} >/dev/null 2>&1 && echo OK")
    if check.stdout.strip() != "OK":
        client.run(f"rm -f {_RESTORE_TMP}")
        raise RouterError("Загруженный файл не читается как архив резервной копии.")
    # Extract into / synchronously, then reboot detached so the call returns.
    res = client.run(
        f"tar -C / -xzf {_RESTORE_TMP} && sync && rm -f {_RESTORE_TMP} && echo DONE",
        timeout=60,
    )
    if "DONE" not in res.stdout:
        raise RouterError(f"Не удалось распаковать копию: {res.stderr.strip() or res.stdout.strip()}")
    client.run("(sleep 2; reboot) >/dev/null 2>&1 &", timeout=10)


def factory_reset(client: RouterClient) -> None:
    """Wipe the overlay to firmware defaults and reboot (``firstboot``).

    Detached so the call returns before the device reboots. After this the
    router is factory-fresh: default LAN (usually 192.168.1.1), no root password,
    a regenerated SSH host key — the app will need to reconnect from scratch.
    """
    res = client.run("which firstboot >/dev/null 2>&1 && echo OK")
    if res.stdout.strip() != "OK":
        raise RouterError("На устройстве нет команды firstboot — сброс недоступен.")
    client.run("(sleep 2; firstboot -y && reboot) >/dev/null 2>&1 &", timeout=10)
