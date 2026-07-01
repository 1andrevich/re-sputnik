<p align="center">
  <img src="src/re_sputnik/resources/branding/banner_en.png" alt="Re:Sputnik" width="760">
</p>

<p align="center">
  <a href="https://t.me/one_andrevich"><img src="https://img.shields.io/badge/Telegram-Join-2CA5E0?style=flat-square&logo=telegram&logoColor=white" alt="Telegram"></a>
  <a href="https://ko-fi.com/D1D11SQNQD"><img src="https://img.shields.io/badge/Ko--fi-Support-FF5E5B?style=flat-square&logo=ko-fi&logoColor=white" alt="Ko-fi"></a>
  <a href="https://nowpayments.io/donation?api_key=decbeb76-30f8-4c6d-ba40-2d2dec7fd888"><img src="https://img.shields.io/badge/Crypto-Donate-2EBE74?style=flat-square&logo=bitcoin&logoColor=white" alt="Crypto donate"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-GPL--3.0-blue?style=flat-square" alt="License: GPL-3.0"></a>
</p>

# Re:Sputnik

**Desktop app that sets up and manages [Re:HomeProxy](https://github.com/1andrevich/homeproxy-hiddify) on an OpenWrt router — over SSH, without touching a terminal or LuCI.**

You enter the router's address and password; the app does the rest in a graphical wizard:
installs the proxy backend and a core, imports your servers, sets up routing and DPI bypass,
and lets you manage Wi-Fi, diagnostics and security afterwards.

> Re:Sputnik does **not** bundle any proxy cores — it installs them onto the router from their
> official sources, and talks to the router only over SSH/RPC (`ubus call luci.homeproxy.*`,
> `uci`, the package's own scripts). At its core it is a generic "install + configure software on
> OpenWrt" platform; Re:HomeProxy is just the first recipe.

<!-- Screenshots: add a screenshots/ folder and link the key screens here once the repo is public. -->

## Download

Grab the latest build from the [**Releases**](https://github.com/1andrevich/re-sputnik/releases)
page — no installer:

- **Windows** — `Re-Sputnik-windows-x64.exe`, double-click.
- **macOS** (Apple Silicon) — `Re-Sputnik-macos-arm64.dmg`, drag to Applications.
- **Linux** — `Re-Sputnik-linux-x86_64.AppImage` / `-aarch64.AppImage`, `chmod +x` and run.

Builds are currently **unsigned**: Windows SmartScreen warns (More info → Run anyway); macOS
Gatekeeper quarantines the app (right-click → Open, or `xattr -dr com.apple.quarantine`).

## Features

- **Install** — detects the router's architecture and package manager (opkg/apk), installs
  Re:HomeProxy and a proxy core (**hiddify-core** or **sing-box-extended**), and can pre-download
  packages on the PC for routers on throttled/restricted networks.
- **Servers** — import subscriptions (sing-box/Hiddify JSON and Xray/V2Ray JSON), share-links
  (VLESS/Reality, Hysteria2, Trojan, Shadowsocks…), `vpn://`, and `.conf` files
  (WireGuard/AmneziaWG); URLTest speed pools.
- **Routing** — ready-made modes (Russia / China / Iran / global) over the Re:filter and
  Russia Inside rule-sets.
- **DPI bypass** — built-in **ByeDPI** (47 presets) and **Zapret 2** (36 presets), plus a strategy tester that probes several sites in parallel and shows what actually works on your ISP.
- **Manage** — diagnostics (core status, DNS, routes), Wi-Fi / LAN / DHCP, passwords and SSH keys,
  backup & maintenance, SQM / UPnP.
- **Languages** — Russian, English, Persian, Chinese

## Three ways in

- **⚡ Step-by-step** — a linear wizard that walks a non-technical user through internet,
  installation, servers, and verification.
- **⚙ Advanced** — free navigation over the sections (Servers, Rules, Diagnostics, Anti-DPI,
  Core, Security…) for hands-on management.
- **📦 Pre-install packages** — download on the PC and push to the router, to install with no
  internet on the router itself.

Any mode picks up the router's current configuration instead of starting from scratch.

## Architecture (short)

```
UI (customtkinter)          wizard + settings screens; drives the setup flow
engine/*                    per-feature logic (install, nodes, rules, ByeDPI, Zapret, diagnostics…)
RouterClient (paramiko)     the ONLY door to the router: built-in scripts, ubus, uci
Secrets (keyring)           router credentials in the OS keychain
```

Commands run one at a time per connection, so concurrent requests can't get dropped by the
router's SSH daemon. No telemetry; credentials never leave your machine.

## Tech stack

Pure Python + a few libraries — no web/HTML/CSS/JS:

| Layer | Library |
|-------|---------|
| UI | customtkinter (Tk) |
| Router comms | paramiko (SSH) |
| Secrets | keyring (OS keychain) |
| Icons | Lucide/Phosphor (UI) + Simple Icons (brands), baked SVG→PNG at build time |

## Develop

```sh
python -m venv .venv
. .venv/Scripts/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m re_sputnik
pytest -q                     # tests + compile check
```

CI runs the tests on every push ([`test.yml`](.github/workflows/test.yml)); on-demand multi-platform
builds live in [`build.yml`](.github/workflows/build.yml); tagged releases (`vX.Y.Z`) build all
platforms and publish to the Releases page via [`release.yml`](.github/workflows/release.yml).
See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the contribution flow (Developer Certificate of Origin).

## Trademark notice

Not affiliated with or endorsed by YouTube, Telegram, Discord, Meta, or Hiddify. Service logos
are trademarks of their respective owners and are used only to identify the services they
represent.

## Support the project

If Re:Sputnik is useful to you, a ⭐ helps — or support development directly:

<a href="https://ko-fi.com/D1D11SQNQD" target="_blank"><img height="40" src="https://storage.ko-fi.com/cdn/kofi5.png?v=6" alt="Support on Ko-fi"></a>
&nbsp;
<a href="https://nowpayments.io/donation?api_key=decbeb76-30f8-4c6d-ba40-2d2dec7fd888" target="_blank" rel="noreferrer noopener"><img src="https://nowpayments.io/images/embeds/donation-button-white.svg" alt="Crypto & Bitcoin donation via NOWPayments"></a>

Questions and updates — [Telegram](https://t.me/one_andrevich).

## License

Re:Sputnik is **free software** under the **GNU General Public License v3.0** (GPLv3): you may
use, study, modify, and share it under those terms. See [`LICENSE`](LICENSE) for the full text
and [`NOTICE`](NOTICE) for third-party attributions.

Re:Sputnik is a separate program from **Re:HomeProxy** (also GPL-licensed): it talks to the
router over SSH/RPC and does not bundle or link Re:HomeProxy's source. All bundled third-party
dependencies are under permissive or weak-copyleft licenses (MIT/BSD/HPND/MPL-2.0; paramiko under
LGPL-2.1), compatible with the GPLv3. Contributions are accepted under the Developer Certificate
of Origin — see [`CONTRIBUTING.md`](CONTRIBUTING.md).
