# Contributing to Re:Sputnik

Thanks for your interest in improving Re:Sputnik. It is free software under the
**GNU GPL v3.0** (see [`LICENSE`](LICENSE)).

## Developer Certificate of Origin (DCO)

Contributions are accepted under the **Developer Certificate of Origin 1.1**
(<https://developercertificate.org/>). By signing off on a commit you certify
that you wrote the change (or have the right to submit it) and agree it is
contributed under the project's license.

Sign off every commit by adding a line to the message:

```
Signed-off-by: Your Name <your.email@example.com>
```

`git commit -s` adds this automatically. The name/email must be real.

### Why a DCO (and why it matters here)

The author is the sole copyright holder and may offer the same code under
separate terms as well — for example a custom build for a partner
(dual-licensing). The DCO keeps that possible: by contributing under it you
grant the rights needed for the project to be distributed under the GPLv3 **and**
relicensed by the copyright holder, without a separate copyright-assignment form.
Your contribution always remains available to everyone under the GPLv3.

## Practical notes

- Keep changes focused; match the surrounding code style.
- Any new or changed user-facing `_()` string must update the translation
  catalogs in the same change (`src/re_sputnik/locale/*/LC_MESSAGES`).
- Run the smoke checks before opening a PR (`python -m compileall src` at minimum).
