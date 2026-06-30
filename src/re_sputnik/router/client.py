# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 1andrevich. Licensed under the GNU GPLv3 — see LICENSE.
"""RouterClient — the single SSH door to an OpenWRT router.

Everything the app does on the device goes through here: running built-in
scripts, calling the ``luci.homeproxy`` rpcd API over ubus, reading/writing
uci settings, and (with explicit consent) installing the app's SSH key.

This module is deliberately free of any homeproxy-specific knowledge beyond the
thin ``ubus_homeproxy`` convenience wrapper — homeproxy logic lives in recipes,
not here, so the same client can drive any "install software on OpenWRT" task.
"""

from __future__ import annotations

import json
import shlex
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import paramiko

# Where Dropbear (OpenWRT's default SSH server) keeps authorized keys.
AUTHORIZED_KEYS_PATH = "/etc/dropbear/authorized_keys"


def _load_key_file(path: str) -> "paramiko.PKey":
    """Load a private key file, trying the supported types — same set SSHClient
    auto-detected internally. Only the app's OWN key is ever loaded this way."""
    for key_type in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
        try:
            return key_type.from_private_key_file(path)
        except paramiko.SSHException:
            continue
    raise RouterError(f"could not load key file {path}")

# rpcd needs a moment after a restart before its objects answer (project note).
RPCD_SETTLE_SECONDS = 2

LogCallback = Callable[[str], None]


class RouterError(RuntimeError):
    """Any failure talking to the router (connection, auth, command, JSON)."""


class CommandTimeout(RouterError):
    """A command exceeded its wall-clock deadline. Subclasses RouterError so broad
    ``except RouterError`` handlers still catch it, while callers that must react to a
    timeout specifically (e.g. the mirror throttle-probe falling back to the mirror)
    can catch this exact type instead of treating it as a generic failure."""


class HostKeyMismatch(RouterError):
    """The router's SSH host key differs from the fingerprint we pinned.

    Legitimate after a factory reset (the key is regenerated), but also what a
    man-in-the-middle would look like — so the UI must warn and require explicit
    user acceptance before re-pinning.
    """

    def __init__(self, host: str, expected: str, got: str) -> None:
        super().__init__(f"host key for {host} changed")
        self.host = host
        self.expected = expected
        self.got = got


@dataclass(slots=True)
class CommandResult:
    """Result of a single remote command."""

    command: str
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def check(self) -> "CommandResult":
        """Raise if the command failed; otherwise return self for chaining."""
        if not self.ok:
            raise RouterError(
                f"command failed (exit {self.exit_code}): {self.command}\n"
                f"{self.stderr.strip() or self.stdout.strip()}"
            )
        return self


class RouterClient:
    """A live SSH session to one router.

    Use as a context manager::

        with RouterClient(host="192.168.1.1", password="...") as r:
            info = r.ubus_homeproxy("clash_active_node")

    Every executed command is mirrored to ``log`` (if provided) so the UI's
    read-only log panel can show exactly what the app does — this transparency
    is a core trust feature, not a debug afterthought.
    """

    def __init__(
        self,
        host: str,
        *,
        port: int = 22,
        username: str = "root",
        password: Optional[str] = None,
        key_filename: Optional[str] = None,
        pkey: Optional[paramiko.PKey] = None,
        log: Optional[LogCallback] = None,
        connect_timeout: int = 10,
        expected_fingerprint: Optional[str] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self._password = password
        self._key_filename = key_filename
        self._pkey = pkey
        self._log = log
        self._connect_timeout = connect_timeout
        self._expected_fingerprint = expected_fingerprint
        self._transport: Optional[paramiko.Transport] = None
        # One SSH transport is shared across UI worker threads (screens fire status
        # reads in parallel — e.g. the AntiDPI page loads its ByeDPI and Zapret
        # sections at once). dropbear closes a colliding concurrent session with
        # "Channel closed", so every channel-opening method below serializes on this
        # lock: exactly one command on the wire at a time. Correctness over a little
        # latency — the worker threads queue, the Tk thread never touches this lock.
        self._cmd_lock = threading.Lock()

    # ----- lifecycle ----------------------------------------------------

    def __enter__(self) -> "RouterClient":
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def connect(self) -> None:
        """Open the SSH session.

        We drive a paramiko Transport directly rather than SSHClient: the
        high-level client can't attempt the SSH 'none' method a factory-fresh
        OpenWrt uses, and we already do TOFU at the APP layer (comparing the
        server key fingerprint to the app-pinned one) instead of via system
        known_hosts — so a regenerated key after a factory reset doesn't raise
        paramiko's cryptic BadHostKeyException. The server host key is available
        right after start_client, BEFORE auth, so the pinned-fingerprint check
        runs up front and a mismatch raises HostKeyMismatch for the UI.

        NEVER uses the user's personal SSH keys/agent — only the app's own key
        (pkey / key_filename), a password, or the fresh-router 'none' method.
        """
        try:
            transport = paramiko.Transport((self.host, self.port))
            transport.start_client(timeout=self._connect_timeout)
        except (OSError, paramiko.SSHException) as exc:
            raise RouterError(f"cannot reach {self.host}:{self.port} — {exc}") from exc
        self._transport = transport
        try:
            self._authenticate(transport)
        except paramiko.AuthenticationException as exc:
            transport.close()
            self._transport = None
            raise RouterError("authentication failed — wrong password or key") from exc
        except Exception:
            transport.close()
            self._transport = None
            raise
        self._check_pinned_hostkey()

    def _authenticate(self, transport: "paramiko.Transport") -> None:
        """Dispatch SSH auth on a started transport — password, else the app key,
        else 'none'. A given password is authoritative (a wrong one fails fast).
        Without a password we try the app key first (a returning router already
        has it installed), then fall back to 'none' (a factory-fresh / just-reset
        router is passwordless and dropbear grants root via 'none', but the app's
        key isn't installed there yet)."""
        if self._password:
            transport.auth_password(self.username, self._password)
            return
        pkey = self._pkey or (
            _load_key_file(self._key_filename) if self._key_filename else None)
        if pkey is not None:
            try:
                transport.auth_publickey(self.username, pkey)
                return
            except paramiko.AuthenticationException:
                pass  # key not installed yet (fresh/reset router) — fall to 'none'
        transport.auth_none(self.username)
        if not transport.is_authenticated():
            raise paramiko.AuthenticationException("server did not grant access")

    def _check_pinned_hostkey(self) -> None:
        """Compare the connected server key against the app's pinned fingerprint.

        No pin → first sight (caller pins after showing it). Mismatch → close and
        raise HostKeyMismatch so the UI can warn and ask to accept.
        """
        if not self._expected_fingerprint:
            return
        got = self.host_key_fingerprint
        if got and got != self._expected_fingerprint:
            expected = self._expected_fingerprint
            self.close()
            raise HostKeyMismatch(self.host, expected, got)

    def close(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    @property
    def host_key_fingerprint(self) -> Optional[str]:
        """SHA256 fingerprint of the server key, for UI pinning/display."""
        if self._transport is None:
            return None
        key = self._transport.get_remote_server_key()
        import base64
        import hashlib

        digest = hashlib.sha256(key.asbytes()).digest()
        return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")

    # ----- command execution -------------------------------------------

    def run(self, command: str, *, timeout: Optional[int] = 30) -> CommandResult:
        """Run a shell command on the router and capture its result."""
        if self._transport is None:
            raise RouterError("not connected")
        if self._log is not None:
            self._log(f"$ {command}")
        with self._cmd_lock:
            try:
                chan = self._transport.open_session(timeout=self._connect_timeout)
                chan.settimeout(timeout)
                chan.exec_command(command)
                stdout = chan.makefile("r", -1)
                stderr = chan.makefile_stderr("r", -1)
                # exec_command's timeout only bounds channel *reads*; recv_exit_status()
                # waits on the command-completion event and ignores it, so a hung
                # command would block here forever (no timeout error ever surfaces).
                # Enforce a real wall-clock deadline against exit_status_ready().
                if timeout is not None:
                    deadline = time.monotonic() + timeout
                    while not chan.exit_status_ready():
                        if time.monotonic() > deadline:
                            chan.close()
                            raise CommandTimeout(
                                f"command did not finish within {timeout}s: {command[:100]}")
                        time.sleep(0.1)
                exit_code = chan.recv_exit_status()
                out = stdout.read().decode("utf-8", "replace")
                err = stderr.read().decode("utf-8", "replace")
            except CommandTimeout:
                # Distinct, expected condition (the mirror throttle-probe catches it to
                # fall back). Let it through instead of re-wrapping as a generic RouterError
                # — it's already a RouterError subclass, so broad handlers still catch it.
                raise
            except Exception as exc:  # noqa: BLE001 — surface any transport error uniformly
                raise RouterError(f"failed to run command: {exc}") from exc
        if self._log is not None and err.strip():
            self._log(err.rstrip())
        return CommandResult(command=command, exit_code=exit_code, stdout=out, stderr=err)

    def run_stream(self, command: str, *, on_line: Callable[[str], None],
                   timeout: Optional[int] = 300) -> CommandResult:
        """Run a command, delivering each combined stdout/stderr LINE to ``on_line``
        as it arrives; return the full CommandResult once the command exits.

        For long steps (package installs) so the UI shows live progress instead of a
        frozen status line. ``timeout`` here is a **stall** timeout — it fires only
        after that many seconds with *no* output, so a slow-but-progressing download
        (which keeps printing) is never killed, while a genuinely wedged command is.
        """
        if self._transport is None:
            raise RouterError("not connected")
        if self._log is not None:
            self._log(f"$ {command}")
        with self._cmd_lock:
            try:
                chan = self._transport.open_session(timeout=self._connect_timeout)
                chan.set_combine_stderr(True)
                chan.settimeout(0.5)
                chan.exec_command(command)
                captured: list[str] = []
                buf = ""
                last = time.monotonic()
                while True:
                    try:
                        data = chan.recv(8192)
                    except socket.timeout:
                        if timeout is not None and time.monotonic() - last > timeout:
                            chan.close()
                            raise TimeoutError(
                                f"no output for {timeout}s (stalled): {command[:100]}")
                        continue
                    if not data:
                        break  # EOF — command finished and channel drained
                    last = time.monotonic()
                    text = data.decode("utf-8", "replace")
                    captured.append(text)
                    buf += text
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        on_line(line)
                if buf.strip():
                    on_line(buf)
                exit_code = chan.recv_exit_status()
            except Exception as exc:  # noqa: BLE001 — surface any transport error uniformly
                raise RouterError(f"failed to run command: {exc}") from exc
        return CommandResult(command=command, exit_code=exit_code,
                             stdout="".join(captured), stderr="")

    def run_bytes(self, command: str, *, timeout: Optional[int] = 120) -> tuple[bytes, str, int]:
        """Run a command and return its stdout as RAW BYTES (not utf-8 decoded).

        For binary payloads streamed over the channel — e.g. a gzip backup from
        ``sysupgrade --create-backup -`` — where ``run()``'s utf-8 decode would
        corrupt the data and the device may lack a ``base64`` applet to encode it.
        Returns ``(stdout_bytes, stderr_text, exit_code)``.
        """
        if self._transport is None:
            raise RouterError("not connected")
        if self._log is not None:
            self._log(f"$ {command}")
        with self._cmd_lock:
            try:
                chan = self._transport.open_session(timeout=self._connect_timeout)
                chan.settimeout(timeout)
                chan.exec_command(command)
                data = chan.makefile("rb", -1).read()  # bytes — read fully before exit
                exit_code = chan.recv_exit_status()
                err = chan.makefile_stderr("r", -1).read().decode("utf-8", "replace")
            except Exception as exc:  # noqa: BLE001
                raise RouterError(f"failed to run command: {exc}") from exc
        if self._log is not None and err.strip():
            self._log(err.rstrip())
        return data, err, exit_code

    # ----- ubus / rpcd API ---------------------------------------------

    def ubus(
        self,
        obj: str,
        method: str,
        params: Optional[dict[str, Any]] = None,
        *,
        timeout: int = 30,
    ) -> dict[str, Any]:
        """Call ``ubus call <obj> <method> <params>`` and parse the JSON reply.

        Raises RouterError if ubus fails or the output is not valid JSON.
        """
        args = ["ubus", "call", obj, method]
        if params:
            args.append(shlex.quote(json.dumps(params, separators=(",", ":"))))
        result = self.run(" ".join(args), timeout=timeout)
        if not result.ok:
            raise RouterError(
                f"ubus call {obj} {method} failed (exit {result.exit_code}): "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        text = result.stdout.strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RouterError(
                f"ubus {obj} {method} returned non-JSON: {text[:200]}"
            ) from exc

    def ubus_homeproxy(
        self,
        method: str,
        params: Optional[dict[str, Any]] = None,
        *,
        timeout: int = 30,
    ) -> dict[str, Any]:
        """Convenience wrapper for the ``luci.homeproxy`` rpcd object.

        Note: ``clash_*`` methods only work while the service is running and the
        Clash API at 127.0.0.1:9090 is reachable; otherwise the reply carries an
        ``error`` key. Callers must handle that, not assume success.
        """
        return self.ubus("luci.homeproxy", method, params, timeout=timeout)

    # ----- uci (settings only — never node import / installs) -----------

    def uci_get(self, key: str) -> Optional[str]:
        """Read a single uci option, e.g. ``homeproxy.config.main_node``."""
        result = self.run(f"uci -q get {shlex.quote(key)}")
        return result.stdout.strip() if result.ok else None

    def uci_set(self, key: str, value: str) -> None:
        """Set a uci option (does not commit). Use for settings, not imports."""
        self.run(f"uci set {shlex.quote(key)}={shlex.quote(value)}").check()

    def uci_commit(self, package: str = "homeproxy") -> None:
        self.run(f"uci commit {shlex.quote(package)}").check()

    def uci_get_list(self, key: str) -> list[str]:
        """Read a uci list option as a Python list (space-separated values)."""
        res = self.run(f"uci -q get {shlex.quote(key)}")
        return res.stdout.split() if res.ok and res.stdout.strip() else []

    def uci_add_list(self, key: str, value: str) -> None:
        self.run(f"uci add_list {shlex.quote(key)}={shlex.quote(value)}").check()

    def uci_del_list(self, key: str, value: str) -> None:
        self.run(f"uci del_list {shlex.quote(key)}={shlex.quote(value)}").check()

    # ----- file push (device has no sftp-server) ------------------------

    def write_file(self, remote_path: str, content: str | bytes) -> None:
        """Write content to a remote file by piping to ``cat`` over a channel.

        The router has no sftp-server, so scp/SFTPClient fail; we stream bytes to
        ``cat > path`` via the exec channel's stdin instead.
        """
        if self._transport is None:
            raise RouterError("not connected")
        data = content.encode("utf-8") if isinstance(content, str) else content
        if self._log is not None:
            self._log(f"$ cat > {remote_path}  ({len(data)} bytes)")
        with self._cmd_lock:
            chan = self._transport.open_session()
            try:
                chan.exec_command(f"cat > {shlex.quote(remote_path)}")
                chan.sendall(data)
                chan.shutdown_write()
                rc = chan.recv_exit_status()
            finally:
                chan.close()
        if rc != 0:
            raise RouterError(f"failed to write {remote_path} (exit {rc})")

    # ----- auth bootstrap ----------------------------------------------

    def install_public_key(self, public_key: str) -> None:
        """Append the app's SSH public key to authorized_keys (idempotent).

        This is a device change and MUST only be called after explicit user
        consent — the SecurityGate / UI is responsible for obtaining it.
        """
        key_line = public_key.strip()
        if not key_line:
            raise RouterError("empty public key")
        # Idempotent: exact line already present → nothing to do.
        if self.run(
            f"grep -qF {shlex.quote(key_line)} {AUTHORIZED_KEYS_PATH} 2>/dev/null"
        ).ok:
            return
        # Match by key blob (type + base64), not the full line: if our key is already
        # there under a different comment (e.g. an older brand label), drop that line
        # first so we relabel in place instead of appending a duplicate.
        parts = key_line.split()
        blob = parts[1] if len(parts) >= 2 else key_line
        self.run(
            f"mkdir -p $(dirname {AUTHORIZED_KEYS_PATH}) && touch {AUTHORIZED_KEYS_PATH} && "
            f"tmp=$(mktemp) && grep -vF {shlex.quote(blob)} {AUTHORIZED_KEYS_PATH} > \"$tmp\" 2>/dev/null; "
            f"printf '%s\\n' {shlex.quote(key_line)} >> \"$tmp\" && "
            f"mv \"$tmp\" {AUTHORIZED_KEYS_PATH} && chmod 600 {AUTHORIZED_KEYS_PATH}"
        ).check()

    def relabel_public_key(self, public_key: str) -> bool:
        """Relabel-only: if our key (matched by blob) is present under a different
        comment, rewrite that line to ``public_key``. Cosmetic — it never adds a key
        that's absent, so it grants no new access and is safe to call opportunistically
        on reconnect. Returns True if a line was rewritten."""
        key_line = public_key.strip()
        parts = key_line.split()
        if len(parts) < 2:
            return False
        blob = parts[1]
        if self.run(
            f"grep -qF {shlex.quote(key_line)} {AUTHORIZED_KEYS_PATH} 2>/dev/null"
        ).ok:
            return False  # already correctly labelled
        if not self.run(
            f"grep -qF {shlex.quote(blob)} {AUTHORIZED_KEYS_PATH} 2>/dev/null"
        ).ok:
            return False  # our key isn't installed — not our job to add it
        self.run(
            f"tmp=$(mktemp) && grep -vF {shlex.quote(blob)} {AUTHORIZED_KEYS_PATH} > \"$tmp\" 2>/dev/null; "
            f"printf '%s\\n' {shlex.quote(key_line)} >> \"$tmp\" && "
            f"mv \"$tmp\" {AUTHORIZED_KEYS_PATH} && chmod 600 {AUTHORIZED_KEYS_PATH}"
        ).check()
        return True

    def revoke_public_key(self, public_key: str) -> bool:
        """Remove the app's SSH public key from authorized_keys (revoke access).

        Returns True if a matching line was removed. The current session stays
        open; the key just won't authorize FUTURE connections. Pair with deleting
        the local identity if you want a full revocation.
        """
        key_line = public_key.strip()
        if not key_line:
            raise RouterError("empty public key")
        if not self.run(
            f"grep -qF {shlex.quote(key_line)} {AUTHORIZED_KEYS_PATH} 2>/dev/null"
        ).ok:
            return False  # not present
        # Rewrite the file without the matching line (atomic via temp + mv).
        self.run(
            f"tmp=$(mktemp) && grep -vF {shlex.quote(key_line)} {AUTHORIZED_KEYS_PATH} > \"$tmp\" "
            f"2>/dev/null; mv \"$tmp\" {AUTHORIZED_KEYS_PATH} && chmod 600 {AUTHORIZED_KEYS_PATH}"
        ).check()
        return True

    def restart_rpcd(self) -> None:
        """Restart rpcd and wait for it to settle before further ubus calls."""
        import time

        self.run("/etc/init.d/rpcd restart").check()
        time.sleep(RPCD_SETTLE_SECONDS)

    def reload_rpcd(self) -> None:
        """Reload rpcd's ACLs + ucode objects via SIGHUP — WITHOUT a full daemon
        restart. Enough to register a freshly-installed object (``luci.homeproxy``
        right after install) and clear the stale "?" the overview shows when the
        running rpcd hasn't picked the object up yet. Lighter and faster than
        ``restart_rpcd`` and it doesn't drop other ubus sessions."""
        import time

        self.run("kill -HUP $(pidof rpcd) 2>/dev/null; true")
        time.sleep(RPCD_SETTLE_SECONDS)
