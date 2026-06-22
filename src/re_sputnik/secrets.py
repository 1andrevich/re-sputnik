# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Secrets: the app's SSH identity, generated passwords, and OS-keychain storage.

Nothing sensitive is written to plaintext files. The app's SSH keypair and each
router's root password live in the OS keychain (Windows Credential Manager /
macOS Keychain) via ``keyring``. The user is asked for consent before anything
is stored — the UI is responsible for that prompt; this module just persists.
"""

from __future__ import annotations

import io
import secrets as _secrets
import string
from dataclasses import dataclass

import keyring
import paramiko
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .i18n import _, N_

SERVICE = "re-companion"
_KEY_PRIV = "ssh-private-key"
_KEY_PUB = "ssh-public-key"
_KEY_COMMENT = "re-companion"


class SecretsError(RuntimeError):
    """Keychain unavailable or a stored secret is malformed."""


# ----- password input/validation ---------------------------------------

# Characters that are error-prone or incompatible for a router root password set
# over SSH / typed at the console: whitespace + the shell-hostile quartet (quotes,
# backslash, backtick, dollar). The milder specials (!@#%^&*()-_=+[]{};:,.?/ …)
# are allowed — not everything is forbidden, only this incompatible subset.
_PW_FORBIDDEN = "'\"\\`$ \t"
_PW_CHAR_LABEL = {" ": N_("пробел"), "\t": N_("табуляция")}


def is_password_input_char(proposed: str) -> bool:
    """Validation predicate for the password entry: allow only ASCII printable
    characters. Non-ASCII (a Cyrillic/other keyboard layout) is blocked at the
    keystroke; digits and Latin letters (same on any layout) always pass."""
    return all(0x20 <= ord(c) <= 0x7E for c in proposed)


def password_problem(password: str) -> "str | None":
    """Return a human error if the password can't be used as a router root
    password, else None. Two classes: non-ASCII (wrong keyboard layout) and the
    incompatible special characters in ``_PW_FORBIDDEN``."""
    if not password:
        return None
    if any(ord(c) < 0x20 or ord(c) > 0x7E for c in password):
        return _("Пароль содержит символы не из английской раскладки. Переключитесь на "
                 "английскую раскладку и используйте латинские буквы, цифры и спецзнаки.")
    bad = [_(_PW_CHAR_LABEL.get(c, c)) for c in dict.fromkeys(password) if c in _PW_FORBIDDEN]
    if bad:
        return (_("Эти символы несовместимы и не разрешены в пароле: ") + ", ".join(bad)
                + _(" Уберите их (можно использовать другие спецзнаки: ! @ # % ^ & * - _ = + и т.п.)."))
    return None


# ----- password generation ---------------------------------------------

_LOWER = string.ascii_lowercase
_UPPER = string.ascii_uppercase
_DIGITS = string.digits
# Avoid quoting-hostile characters; still plenty of entropy.
def generate_password(length: int = 20) -> str:
    """A max-entropy random password (crypto RNG), letters + digits ONLY.

    Project policy for the router root password:
    - high-entropy random, NOT a memorable passphrase (that's only for Wi-Fi);
    - NO special characters. Specials (``$``, ``%``, ``^`` …) break shell quoting
      when the password is set over SSH (``passwd``) and are error-prone to type.
    Letters+digits at 20 chars is ~119 bits — far beyond what's needed.
    """
    length = max(length, 16)
    alphabet = _LOWER + _UPPER + _DIGITS
    while True:
        pw = "".join(_secrets.choice(alphabet) for _ in range(length))
        if (
            any(c in _LOWER for c in pw)
            and any(c in _UPPER for c in pw)
            and any(c in _DIGITS for c in pw)
        ):
            return pw


# Short, unambiguous words for a memorable Wi-Fi passphrase (no lookalikes).
_WIFI_WORDS = (
    "apple", "amber", "anchor", "arrow", "basil", "bison", "blossom", "branch",
    "breeze", "cabin", "cactus", "candle", "canyon", "cedar", "cherry", "cloud",
    "clover", "comet", "copper", "coral", "cosmos", "cotton", "crystal", "daisy",
    "delta", "dolphin", "dragon", "ember", "falcon", "fern", "forest", "garden",
    "ginger", "glacier", "harbor", "hazel", "indigo", "island", "jasmine", "jungle",
    "kettle", "lagoon", "lantern", "lemon", "lily", "lotus", "maple", "marble",
    "meadow", "melon", "meteor", "mint", "nectar", "ocean", "olive", "orbit",
    "otter", "pebble", "pepper", "pine", "planet", "poppy", "prairie", "quartz",
    "rabbit", "river", "robin", "saffron", "sage", "salmon", "shadow", "silver",
    "spruce", "summit", "sunset", "thunder", "tiger", "tulip", "valley", "velvet",
    "violet", "walnut", "willow", "winter", "zephyr",
)


def generate_wifi_passphrase(words: int = 3) -> str:
    """A memorable Wi-Fi passphrase like ``bison-cedar-nect74ar``.

    Per policy, Wi-Fi (unlike the admin login) may use a memorable word
    passphrase. Three random words from an ~85-word unambiguous list, with two
    digits each injected at a random *interior* position of a random word —
    deliberately NOT tacked on the end, so the digit placement isn't predictable
    (``biso4n-cedar-n7ctar`` rather than ``bison-cedar-nectar-47``). The digits
    may land in the same word or different ones. ~38 bits from the words plus the
    digits/positions — past WPA2's 8-char minimum and well beyond a typed human
    password, while still readable.
    """
    words = max(words, 2)
    picked = [_secrets.choice(_WIFI_WORDS) for _ in range(words)]
    for _ in range(2):  # two digits, each into a random interior spot of a random word
        w = _secrets.randbelow(len(picked))
        word = picked[w]
        pos = _secrets.randbelow(len(word) - 1) + 1  # 1..len-1: keep a letter each side
        picked[w] = word[:pos] + str(_secrets.randbelow(10)) + word[pos:]
    return "-".join(picked)


# ----- the app's SSH identity ------------------------------------------


@dataclass(slots=True)
class AppIdentity:
    """The app's single SSH keypair, installed on every managed router."""

    pkey: paramiko.PKey       # private key, loaded for paramiko auth
    public_line: str          # OpenSSH "ssh-ed25519 AAAA... comment" line


def _generate_openssh_keypair(comment: str = _KEY_COMMENT) -> tuple[str, str]:
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    ).decode("ascii")
    return priv_pem, f"{pub} {comment}"


def _load_paramiko_key(priv_pem: str) -> paramiko.PKey:
    try:
        return paramiko.Ed25519Key.from_private_key(io.StringIO(priv_pem))
    except paramiko.SSHException as exc:
        raise SecretsError(f"stored SSH key is unreadable: {exc}") from exc


# Per-process cache of keychain reads. On macOS an UNSIGNED app gets no durable
# "Always Allow", so EVERY keychain access re-prompts — and a single connect reads
# several items (app key ×2, host-key pin, password). Without caching the user sees
# the permission dialog "again and again", and a denial that callers swallow makes
# the next action re-prompt in a loop. Caching reads each item at most once per
# launch; a denial is remembered too (restart the app to re-grant).
_KR_DENIED = object()
_kr_cache: dict[str, object] = {}


def _kr_get(name: str) -> str | None:
    if name in _kr_cache:
        cached = _kr_cache[name]
        if cached is _KR_DENIED:
            raise SecretsError("keychain access was denied earlier this session "
                               "(restart the app to retry)")
        return cached  # type: ignore[return-value]
    try:
        val = keyring.get_password(SERVICE, name)
    except keyring.errors.KeyringError as exc:
        _kr_cache[name] = _KR_DENIED  # don't re-prompt for this item this session
        raise SecretsError(f"keychain not available: {exc}") from exc
    _kr_cache[name] = val
    return val


def _kr_set(name: str, value: str) -> None:
    try:
        keyring.set_password(SERVICE, name, value)
    except keyring.errors.KeyringError as exc:
        raise SecretsError(f"cannot write to keychain: {exc}") from exc
    _kr_cache[name] = value  # keep the cache coherent with the new value


def existing_public_key() -> str | None:
    """Return the stored public key WITHOUT creating one (for state detection)."""
    try:
        return _kr_get(_KEY_PUB)
    except SecretsError:
        return None


def load_or_create_app_identity() -> AppIdentity:
    """Return the app's SSH identity, creating + storing it on first use."""
    priv = _kr_get(_KEY_PRIV)
    pub = _kr_get(_KEY_PUB)
    if priv and pub:
        return AppIdentity(pkey=_load_paramiko_key(priv), public_line=pub)
    priv, pub = _generate_openssh_keypair()
    _kr_set(_KEY_PRIV, priv)
    _kr_set(_KEY_PUB, pub)
    return AppIdentity(pkey=_load_paramiko_key(priv), public_line=pub)


# ----- per-router root password ----------------------------------------


def store_router_password(host: str, password: str) -> None:
    _kr_set(f"root@{host}", password)


def get_router_password(host: str) -> str | None:
    return _kr_get(f"root@{host}")


def forget_router_password(host: str) -> None:
    _kr_cache.pop(f"root@{host}", None)
    try:
        keyring.delete_password(SERVICE, f"root@{host}")
    except keyring.errors.KeyringError:
        pass


# ----- host-key pinning (app-level TOFU) -------------------------------


def get_hostkey_pin(host: str) -> str | None:
    """The pinned SSH host-key fingerprint for a router, if any."""
    try:
        return _kr_get(f"hostkey@{host}")
    except SecretsError:
        return None


def pin_hostkey(host: str, fingerprint: str) -> None:
    _kr_set(f"hostkey@{host}", fingerprint)


def forget_hostkey(host: str) -> None:
    _kr_cache.pop(f"hostkey@{host}", None)
    try:
        keyring.delete_password(SERVICE, f"hostkey@{host}")
    except keyring.errors.KeyringError:
        pass


# ----- full revocation --------------------------------------------------


# ----- disclaimer acceptance -------------------------------------------

# Bump when the EULA / disclaimer changes materially so users re-accept.
# v2: disclaimer became a full EULA acceptance gate (license + third-party credits).
DISCLAIMER_VERSION = "2"


def disclaimer_accepted() -> bool:
    """True if the user has accepted the current disclaimer version."""
    try:
        return _kr_get("disclaimer-accepted") == DISCLAIMER_VERSION
    except SecretsError:
        return False


def accept_disclaimer() -> None:
    try:
        _kr_set("disclaimer-accepted", DISCLAIMER_VERSION)
    except SecretsError:
        pass  # non-fatal: worst case it's shown again next launch


def delete_app_identity() -> None:
    """Delete the app's local SSH keypair from the keychain (full revocation).

    After this the app forgets its key entirely; a new one is generated on next
    use. Revoke it on the router first (RouterClient.revoke_public_key) so the
    old key no longer grants access anywhere.
    """
    for name in (_KEY_PRIV, _KEY_PUB):
        _kr_cache.pop(name, None)
        try:
            keyring.delete_password(SERVICE, name)
        except keyring.errors.KeyringError:
            pass
