# Changelog

All notable changes to Re:Sputnik.

Versioning is [semver](https://semver.org). The version lives in **one** place,
`src/re_sputnik/__init__.py` (`__version__`); the UI footer/About screen and the
Windows exe file‑properties both read it, and the release tag (`vX.Y.Z`) must match
it (CI enforces this). To cut a release: bump `__version__`, add a section here,
commit, then push the matching tag.

## [Unreleased]

## [0.0.1] — 2026-06-25
Initial versioned baseline.
- GitHub release **mirror** support to bypass ISP throttling: a `.pub` throttle‑probe
  latches the session to a Cloudflare mirror (with GitHub fallback) and announces the
  switch in the install log.
- SNAPSHOT handling: `25.12-SNAPSHOT` is treated as 25.12‑compatible (Quick Setup
  works); Preinstall checks for kernel modules and points the user to Quick Setup when
  they can't be pre‑staged, instead of a raw 404.
- Best‑effort signing‑key fetch so a throttled/blocked GitHub never aborts an install.
