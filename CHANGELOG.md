# Changelog

All notable changes to Re:Sputnik.

Versioning is [semver](https://semver.org). The version lives in **one** place,
`src/re_sputnik/__init__.py` (`__version__`); the UI footer/About screen and the
Windows exe file‑properties both read it, and the release tag (`vX.Y.Z`) must match
it (CI enforces this). To cut a release: bump `__version__`, add a section here,
commit, then push the matching tag.

## [Unreleased]

## [0.0.10] — 2026-06-29
- Install/update now follow the latest published Re:HomeProxy release instead of the
  hand-pinned beta tag (`PINNED_TAG`/`PINNED_TAG_LEGACY` set to None), now that a
  stable release has shipped. Version resolution reverted to **stable-preferred** —
  the newest non-prerelease release is chosen (falling back to any-status only when
  no stable exists), so a future dev/prerelease tag no longer overrides stable.

## [0.0.9] — 2026-06-28
- Fixed the link-speed unit showing untranslated Cyrillic ("Гбит/с" / "Мбит/с") in
  other languages — it was a hardcoded f-string. Now localized (EN/ZH "Gbps/Mbps",
  FA "گیگابیت/مگابیت بر ثانیه").
- Fixed intermittent "failed to run command: Channel closed" errors (seen e.g. on the
  AntiDPI page's Zapret2 card). Screens fire their status reads on background threads,
  and several screens load two sections at once — those threads were opening SSH
  channels on the **one shared transport simultaneously**, which OpenWrt's dropbear
  rejects by closing the colliding session. Command execution is now serialized on a
  per-connection lock (one command on the wire at a time), so parallel loads queue
  instead of clobbering each other. Slightly less parallel, but reliable.
- Monospace text (install/diagnostics logs, key fingerprints, command and paste
  fields) now renders in the bundled JetBrains Mono consistently on every platform,
  instead of a hardcoded Consolas that only existed on Windows. Eleven spots across
  nine screens (Software, Pre-install, Core, Diagnostics, Security, Overview, both
  Servers screens, and Anti-DPI) were routed through the shared `fonts.mono()` slot.
  The Latin/Cyrillic UI stays on Roboto (Inter was tried and dropped).
- Removed two never-instantiated UI-kit components (`RouterRow`, `LogPanel`) left over
  from an earlier design draft — screens build their own equivalents inline — along
  with the three palette tokens only they used (`console_bg`, `console_head_bg`,
  `border_row`). Also a static-analysis cleanup: cleared the remaining lint findings
  (ambiguous `l` loop names, semicolon-joined statements). No behavioural change.

## [0.0.8] — 2026-06-27
- Install/pre-install log is now fully localized: the per-package download/push lines
  and several status messages were built with f-strings (untranslatable), so the log
  stayed Russian in other languages. They now go through translation (EN/FA/ZH).
- The "I have whitelists" option (Quick Setup / Pre-install) is shown only for Russian
  — whitelist filtering (state-approved sites like Yandex/VK) is a Russian regime and
  doesn't apply to the China/Iran modes. Its translations were dropped accordingly.
- Readability: the smallest text slot (footer hints, captions, version, language
  picker) is bumped 11→12 px in every language. Persian gets more: a proper bundled
  Persian/Arabic font (Vazirmatn, OFL) and a proportional size bump across all slots,
  since Arabic script reads smaller and denser than Latin/Cyrillic at the same size.
- Quick Setup: when the "Auto" (fastest) pool ends up empty because the router's
  active core can't run the only server types you added (e.g. AmneziaWG on
  hiddify-core), the error now spells out the exact cause and how to fix it (switch
  the core, or add compatible servers) instead of a vague "no suitable servers".
- Pre-install: Re:HomeProxy is now always installed — the whole app depends on its
  backend — so it's shown as information rather than an on/off choice. The
  language-pack note now reflects the language that's actually staged (it previously
  always said "Russian" regardless of the chosen UI language).
- The app's SSH key is now labelled `re-sputnik@<hostname>` instead of a bare
  `re-sputnik`, so when you manage one router from several computers you can tell
  which key belongs to which PC. Existing keys are relabelled in place on next
  connect (same key/fingerprint). Falls back to bare `re-sputnik` if the hostname
  can't be read.
- After "delete application data", the app now shows a live countdown and closes
  itself (a clean restart is required) instead of asking the user to restart it
  manually.
- Finished the `re-companion → re-sputnik` rename that earlier passes missed:
  the app's SSH key is relabelled in place on the router (same key/fingerprint,
  nothing to re-authorize), the config folder migrates from `…/re-companion` to
  `…/re-sputnik` carrying over saved profiles, and the remaining internal labels
  (HTTP User-Agent, syslog tag, temp filenames) now read `re-sputnik`.
- Overview DNS card: the region row no longer shows a misleading yellow "?" on
  routers whose installed backend predates the `russia_* → region_*` rename — the
  app now reads the older `russia_*` result (and skips the row entirely if there's
  genuinely no region data).
- Text fields now have a right-click menu (Cut / Copy / Paste / Select all) in
  addition to the keyboard shortcuts, working under any keyboard layout. Translated
  to EN/FA/ZH.
- Code-quality pass (static-analysis cleanup): made the shared screen-icon map a
  public name, removed dead locals/imports/parameters, simplified a chained
  comparison, made a stateless helper static, fixed lambda arg naming, and fixed a
  loop variable that shadowed the gettext `_`.

## [0.0.4] — 2026-06-27
- Refuse OpenWrt older than 23.05 up front with a clear "firmware too old" message
  (EN/FA/ZH) instead of failing deep in the install on an unsatisfiable dependency.
- SSH connection reworked onto a paramiko Transport (public API only) — removes a
  fragile internal hack and makes fresh/passwordless‑router onboarding a first‑class
  path; added auth‑dispatch smoke tests.
- Keychain rename: entries migrate from the old `re-companion` service name to
  `re-sputnik` on first read — existing installs keep their key, passwords and pins.
- Mirror: host is overridable at runtime (`RS_MIRROR_BASE`) and the program can fall
  back across multiple mirror hosts.
- CI: tests run on every push/PR and gate tagged releases; the app version is the
  single source of truth (pyproject reads it dynamically).

## [0.0.3] — 2026-06-27
- Offline preinstall now stages the LuCI app's `ucode-mod-digest` dependency
  (24.10+) and always stages `kmod-nft-queue` (+ `kmod-nfnetlink-queue`) — fixes
  "cannot find dependency" failures on install and preempts the Zapret NFQUEUE
  kmod gap.
- Install failures now report the real cause (missing package/dependency, out of
  space) instead of an opaque output tail.
- On a quick‑setup download failure on a restricted network, the app now points
  the user to Pre‑install (run with a VPN on the PC). Translated to EN/FA/ZH.

## [0.0.2] — 2026-06-26
- English UI: fixed 183 fuzzy catalog entries that silently fell back to Russian;
  "Дополнительно" relabelled "Extras". EN/FA/ZH verified fully translated.
- Extras screen reordered: Permanent IP, Proxy routing, UPnP and SQM now sit
  above LAN & DHCP.

## [0.0.1] — 2026-06-25
Initial versioned baseline.
- GitHub release **mirror** support to bypass ISP throttling: a `.pub` throttle‑probe
  latches the session to a Cloudflare mirror (with GitHub fallback) and announces the
  switch in the install log.
- SNAPSHOT handling: `25.12-SNAPSHOT` is treated as 25.12‑compatible (Quick Setup
  works); Preinstall checks for kernel modules and points the user to Quick Setup when
  they can't be pre‑staged, instead of a raw 404.
- Best‑effort signing‑key fetch so a throttled/blocked GitHub never aborts an install.
