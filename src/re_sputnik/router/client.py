# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
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
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import paramiko

# Where Dropbear (OpenWRT's default SSH server) keeps authorized keys.
AUTHORIZED_KEYS_PATH = "/etc/dropbear/authorized_keys"

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
        self._ssh: Optional[paramiko.SSHClient] = None

    # ----- lifecycle ----------------------------------------------------

    def __enter__(self) -> "RouterClient":
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def connect(self) -> None:
        """Open the SSH session.

        TOFU is done at the APP layer, not via the system known_hosts: we accept
        whatever key the server offers (AutoAddPolicy, no system host keys loaded
        — so a regenerated key after a factory reset doesn't raise paramiko's
        cryptic BadHostKeyException), then compare its fingerprint to the one the
        app pinned. A mismatch raises HostKeyMismatch for the UI to handle.
        """
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        # NEVER use the user's PERSONAL SSH keys or agent: the app authenticates only
        # with ITS OWN key (pkey), a password, or the fresh-router 'none' method.
        # Leaving allow_agent/look_for_keys on offered the user's ~/.ssh + agent
        # identities to the server — an info leak to a malicious/MITM router.
        try:
            ssh.connect(
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self._password,
                key_filename=self._key_filename,
                pkey=self._pkey,
                timeout=self._connect_timeout,
                allow_agent=False,
                look_for_keys=False,
            )
            self._ssh = ssh
        except paramiko.AuthenticationException as exc:
            # A factory-fresh OpenWrt has no root password, and dropbear then
            # grants access via the SSH "none" method — which paramiko's
            # high-level connect never attempts. Fall back to it whenever no
            # password was given (an empty-password router), EVEN IF we also
            # offered a key: a returning app already has a key in the keychain,
            # but a freshly reset router doesn't have it installed yet, so the
            # key auth fails and 'none' is the right path. A provided-but-wrong
            # password still fails fast (auth_none only succeeds if dropbear
            # actually offers it).
            if not self._password:
                try:
                    self._ssh = self._connect_none()
                except Exception:  # noqa: BLE001 — keep the original auth error
                    raise RouterError("authentication failed — wrong password or key") from exc
            else:
                raise RouterError("authentication failed — wrong password or key") from exc
        except OSError as exc:
            raise RouterError(f"cannot reach {self.host}:{self.port} — {exc}") from exc
        self._check_pinned_hostkey()

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

    def _connect_none(self) -> "paramiko.SSHClient":
        """Authenticate via the SSH 'none' method (password-less fresh router)."""
        transport = paramiko.Transport((self.host, self.port))
        transport.start_client(timeout=self._connect_timeout)
        transport.auth_none(self.username)  # raises if 'none' is not offered
        if not transport.is_authenticated():
            transport.close()
            raise paramiko.AuthenticationException("'none' auth not sufficient")
        ssh = paramiko.SSHClient()
        ssh._transport = transport  # drive exec_command through our authed transport
        return ssh

    def close(self) -> None:
        if self._ssh is not None:
            self._ssh.close()
            self._ssh = None

    @property
    def host_key_fingerprint(self) -> Optional[str]:
        """SHA256 fingerprint of the server key, for UI pinning/display."""
        if self._ssh is None:
            return None
        transport = self._ssh.get_transport()
        if transport is None:
            return None
        key = transport.get_remote_server_key()
        import base64
        import hashlib

        digest = hashlib.sha256(key.asbytes()).digest()
        return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")

    # ----- command execution -------------------------------------------

    def run(self, command: str, *, timeout: Optional[int] = 30) -> CommandResult:
        """Run a shell command on the router and capture its result."""
        if self._ssh is None:
            raise RouterError("not connected")
        if self._log is not None:
            self._log(f"$ {command}")
        try:
            _stdin, stdout, stderr = self._ssh.exec_command(command, timeout=timeout)
            chan = stdout.channel
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
        if self._ssh is None:
            raise RouterError("not connected")
        if self._log is not None:
            self._log(f"$ {command}")
        transport = self._ssh.get_transport()
        if transport is None:
            raise RouterError("not connected")
        try:
            chan = transport.open_session(timeout=self._connect_timeout)
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
        if self._ssh is None:
            raise RouterError("not connected")
        if self._log is not None:
            self._log(f"$ {command}")
        try:
            _stdin, stdout, stderr = self._ssh.exec_command(command, timeout=timeout)
            data = stdout.read()  # bytes — read fully before exit status
            exit_code = stdout.channel.recv_exit_status()
            err = stderr.read().decode("utf-8", "replace")
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
        if self._ssh is None:
            raise RouterError("not connected")
        data = content.encode("utf-8") if isinstance(content, str) else content
        transport = self._ssh.get_transport()
        if transport is None:
            raise RouterError("no transport")
        if self._log is not None:
            self._log(f"$ cat > {remote_path}  ({len(data)} bytes)")
        chan = transport.open_session()
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
        # Idempotent: only append if the exact key is not already present.
        check = self.run(
            f"grep -qF {shlex.quote(key_line)} {AUTHORIZED_KEYS_PATH} 2>/dev/null"
        )
        if check.ok:
            return  # already installed
        self.run(
            f"mkdir -p $(dirname {AUTHORIZED_KEYS_PATH}) && "
            f"printf '%s\\n' {shlex.quote(key_line)} >> {AUTHORIZED_KEYS_PATH} && "
            f"chmod 600 {AUTHORIZED_KEYS_PATH}"
        ).check()

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
