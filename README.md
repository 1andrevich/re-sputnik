# Re:Sputnik

Desktop wizard to set up and manage **Re:HomeProxy** on an OpenWRT router — without making the
user touch a terminal. It talks to the router over SSH and drives the diagnostics/config RPC API
that already ships with the router package (`ubus call luci.homeproxy.*`).

> Re:Sputnik is the desktop companion to the [Re:HomeProxy](https://github.com/1andrevich/homeproxy-hiddify) LuCI app.
> It does **not** bundle any proxy cores — it installs them onto the router from their official
> sources. At its core it is a generic "install + configure software on OpenWRT" platform;
> Re:HomeProxy is just the first recipe.

## Two ways in

- **⚡ Quick Setup** — a linear wizard that walks a non-technical user through connecting the
  router, installing software, importing nodes/subscriptions, Wi-Fi, and verification.
- **⚙ Advanced** — free navigation over settings: Nodes & Subscriptions, Rules, Access Control,
  ByeDPI, Core, Diagnostics.

Both share the same engine and the same `RouterClient`; Quick Setup just sequences the steps.

## Architecture (short)

```
UI (customtkinter)          wizard screens, progress, hints
Orchestrator                state machine over declarative phase recipes (YAML)
SecurityGate                consent / source / log — one gate over every executor
RouterClient (paramiko)     the ONLY door to the router: built-in scripts, ubus, uci
Secrets (keyring)           router credentials in the OS keychain
```

No AI: everything the setup assistant used to *reason* about becomes either a deterministic rule
in the engine or an explicit choice in the UI. Connectivity checks (`connection_check`,
`byedpi_strategy_test`) are the app's "eyes" — machine-readable signals that replace human
judgement.

## Tech stack

Pure Python + a few libraries — no web/HTML/CSS/JS:

| Layer | Library |
|-------|---------|
| UI | customtkinter |
| Router comms | paramiko (SSH) |
| Secrets | keyring |
| Recipes | PyYAML |
| Icons | Lucide/Phosphor (UI) + Simple Icons (brands), baked SVG→PNG at build time |

## Develop

```sh
python -m venv .venv
. .venv/Scripts/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m re_sputnik
```

## Distribution

A single portable `.exe` (Windows), `.app` (macOS, Apple Silicon), and `.AppImage` (Linux
x86_64) — no installer; drag to the Desktop / Applications (or `chmod +x` the AppImage and
double-click). All built with PyInstaller via GitHub Actions
([`.github/workflows/build.yml`](.github/workflows/build.yml)) and published on the
[Releases page](https://github.com/1andrevich/re-sputnik/releases) on each `v*` tag. Builds are
currently **unsigned** (Windows SmartScreen / macOS Gatekeeper will warn — see the workflow for
where signing/notarization plugs in).

## Trademark notice

Not affiliated with or endorsed by YouTube, Telegram, Discord, Meta, or Hiddify. Service logos
are trademarks of their respective owners and are used only to identify the services they
represent.

## License

Re:Sputnik is **free software** licensed under the **GNU General Public License v3.0**
(GPLv3): you may use, study, modify, and share it under those terms. See [`LICENSE`](LICENSE)
for the full text and [`NOTICE`](NOTICE) for third-party attributions.

Re:Sputnik is a separate program from **Re:HomeProxy** (also GPL-licensed): it talks to the
router over SSH/RPC and does not bundle or link Re:HomeProxy's source. All bundled third-party
dependencies are under permissive or weak-copyleft licenses (MIT/BSD/HPND/MPL-2.0; paramiko
under LGPL-2.1), compatible with the GPLv3.

Outside contributions are accepted under the Developer Certificate of Origin — see
[`CONTRIBUTING.md`](CONTRIBUTING.md).
