# Re:Sputnik — App Design Reference

*Self-contained design reference for Claude (web) — brand, color, type, iconography, and every screen. Screenshots live in `screenshots/` (generate them with `python scripts/capture_screens.py`; placeholders below). The app is a **Windows desktop** app (Python + customtkinter), dark theme, fixed **900×650** non-resizable window, audience largely **non-technical**, white-label-ready.*

---

## 1. Logo & brand mark — "Sputnik '57"
The 1957 Sputnik satellite (blue→cyan sphere + 4 swept antennas) climbing over **Earth's horizon** with a **signal downlink** to a ground node — *satellite + technological freedom + people connected*.

| Asset | File | Use |
|-------|------|-----|
| Master mark | `src/re_sputnik/resources/branding/logo_mark.svg` | app icon (256 viewBox, dark rounded plate) |
| Monochrome glyph | `logo_mark_mono.svg` | favicons, stamps, light/dark surfaces (`currentColor`) |
| Wordmark lockup | `logo_wordmark.svg` | About / splash — mark + `Re:Sputnik` |
| Raster icons | `icon_{16,32,48,64,128,256}.png` | in-app `CTkImage`, taskbar |
| Windows icon | `icon.ico` (16/32/48/256) | window + taskbar + executable |

**Name:** `Re:` (product-family marker — Re:HomeProxy, Re:filter) + **Sputnik** (Russian for *companion*/*satellite*). White-label = swap only the sphere/`Re:` gradient stops.

![Logo mark](../../src/re_sputnik/resources/branding/icon_256.png)

---

## 2. Color — theme "Orbit Cyan" (dark)
One accent (cyan, lifted from the logo), a navy grey-scale, and color **reserved for status only**.

| Token | Hex | Used for |
|-------|-----|----------|
| `accent` | `#38BDF8` | primary buttons, active nav, highlights, progress |
| `accent_hover` | `#0EA5E0` | hover of accent elements |
| `accent_fg` | `#0B1220` | **text/icon ON accent** (dark — white-on-cyan fails AA 2.1; dark = 8.7 ✓) |
| `bg` | `#10131A` | window background (navy, matches logo plate) |
| `surface` | `#1B2230` | cards / panels |
| `surface_hover` | `#232C3D` | hovered cards, secondary buttons |
| `text` | `#E7E8EA` | primary text |
| `text_muted` | `#93A0AE` | secondary / hint text, labels |
| `border` | `#2B3547` | card borders, dividers |
| `ok` | `#22C55E` | **status only** — success (green) |
| `warn` | `#F59E0B` | **status only** — warning (amber; also the yellow help button) |
| `fail` | `#EF4444` | **status only** — error (red) |

**Rules:** primary-button labels are **dark** (`accent_fg`), never white. Status is shown as a **colored dot + neutral label** (color-blind safe). One accent only — don't colorize neutral UI.

---

## 3. Typography — Inter (fallback Roboto), four slots
| Slot | px | weight | use |
|------|----|--------|-----|
| `title` | 22 | bold | screen titles |
| `heading` | 16 | bold | section headers, card titles |
| `body` | 13 | normal | default text, buttons, inputs |
| `small` | 11 | normal | hints, captions, status lines |

---

## 4. Iconography

### 4a. UI glyphs (Unicode, no asset files)
Used inline as button/label text:

- **Mode cards:** ⚡ Quick Setup · ⚙ Advanced · 📦 (install)
- **Status dots:** ● colored by `ok`/`warn`/`fail`/`text_muted` (the standard status indicator); ○ = blocked (in tester); ●●●○ scale in the DPI tester
- **Actions:** ✎ rename · 💾 save · 🗑 delete · 📋 copy · 👁 reveal · 🔄 refresh · 🔗 link · 📄 file · ＋ add row
- **Section/row markers:** 🔌 wired · 📶 Wi-Fi · 🔑 SSH key · 🔒 password · 🌐 network
- **Nav / state:** ← back/exit · → next · ↻ retry · ▶ run · ✓ success · ✗/✕ fail/close · ⚠ warning · ❓ help

### 4b. Service / routing icons (PNG, 24px-ish)
In `src/re_sputnik/resources/icons/`. Shown next to routing rules on the **Rules** and **Overview** pages. **Sourced from [Simple Icons](https://simpleicons.org) (CC0)**; brand logos are trademarks of their owners, used **nominatively** to identify the service (see repo `NOTICE`).

| File | Identifies | File | Identifies |
|------|-----------|------|-----------|
| `youtube` | YouTube | `telegram` | Telegram |
| `discord` | Discord | `twitter` | Twitter / X |
| `tiktok` | TikTok | `meta` | Meta (FB/IG) |
| `whatsapp` | WhatsApp | `roblox` | Roblox |
| `google_ai` | Google AI | `google_play` | Google Play |
| `cloudflare` | Cloudflare CDN | `cloudfront` | CloudFront CDN *(generic ring, not Amazon's logo)* |
| `ovh` | OVH (FR) | `hetzner` | Hetzner (DE) |
| `digitalocean` | DigitalOcean | `hdrezka` | HDRezka |
| `refilter` | Re:filter block-list | `russia-inside` | Russia-Inside list |
| `hodca` | HODCA list | `geoblock` | GeoBlock services |
| `anime` | Anime streaming | `news` | World news |
| `porn` | 18+ content | `torrent` | BitTorrent |
| `_default` | fallback for unknown rule | | |

---

## 5. Screens

The app has **two flows**: a linear **Quick Setup** wizard, and an **Advanced** settings shell (left-nav + swappable panels). Window is fixed 900×650; tall content scrolls inside its screen.

### Mode picker (entry)
Three large `ModeCard`s — ⚡ **Быстрая настройка** (Quick Setup), ⚙ **Расширенные настройки** (Advanced), and the install path — plus the mandatory Russian **disclaimer** ("as-is, no warranty, your own risk").
*(Not auto-captured — it's built inside the App shell, not a standalone screen. Capture by running the app.)*

### Quick Setup flow

**1 · Подключение к роутеру** — `connect`
Router address + credentials, **autodetect** of routers on the LAN, **saved routers** (one-click reconnect), host-key **TOFU** fingerprint, "Запомнить роутер" checkbox, and a yellow **«❓ Не понимаю, как подключить роутер»** help button (opens a popup with the wiring diagram).
![Connect](screenshots/01_connect.png)

**2 · Безопасность (first run)** — `firstrun`
Installs the app's SSH key, verifies key-auth works, *then* sets the root password (lock-out-safe order). 🔑 / 🔒 markers.
![First run](screenshots/02_firstrun.png)

**3 · Интернет** — `internet`
Checks the router's WAN/internet. If offline, offers 🔌 **wired** vs 📶 **Wi-Fi-client** uplink; detects and helps fix a **LAN/WAN subnet conflict** (double-NAT).
![Internet](screenshots/03_internet.png)

**4 · Установка ПО** — `software`
Installs the proxy core onto the router from official sources.
![Software](screenshots/04_software.png)

**5 · Компоненты** — `preinstall`
Toggles: install the **Re:HomeProxy LuCI app** (+ Russian) and optionally **ByeDPI** (+ curl).
![Preinstall](screenshots/05_preinstall.png)

**6 · Узлы** — `quick_nodes`
Import nodes: paste **share-links**, a **subscription** URL, or pick a **.conf** (WireGuard/AmneziaWG). Seeds RU routing-rule defaults.
![Quick nodes](screenshots/06_quick_nodes.png)

**7 · Wi-Fi** — `wifi_ap`
Set the router's AP SSID + password + bands (warns if no Wi-Fi chip). Generates a join **QR**.
![Wi-Fi AP](screenshots/07_wifi_ap.png)

**8 · Проверка** — `verify`
Probes connectivity through the proxy; ✓ "Всё работает" / ✗ "Нет связи через прокси", with the active node resolved to a friendly name.
![Verify](screenshots/08_verify.png)

**9 · Завершение** — `finalize`
Rename the router (hostname), firewall + zram toggles, optional **luci-app-upnp / luci-app-sqm** install (with "why needed" notes), Готово.
![Finalize](screenshots/09_finalize.png)

### Advanced — settings shell
Left nav (⚙ Настройки) with sections: **Обзор · Узлы и подписки · Правила · Контроль доступа · ByeDPI · Ядро · Диагностика · Безопасность · О программе**, and ← Выход.

**Обзор (dashboard)** — `overview`
System header (host/uptime/IP), **CPU & free-RAM** meters, **active node + latency** (color-coded: green/orange/red-65535/gray), active **core + version** + ByeDPI status, editable **Main-Node / URLTest pool** (Interval/Tolerance), **DNS** test rows (Россия — протестировано на mail.ru · server / Защищённый — andrevi.ch · server), active **rules** (read-only, with logos), **DHCP** leases, **Wi-Fi** networks with join **QR**. Header has ✎ rename.
![Overview](screenshots/adv_overview.png)

**Узлы и подписки** — `nodes`
Node list (**newest first**, scrollable, max 254) + subscriptions card + import (links / subscription / .conf), with large success/error feedback next to each action.
![Nodes](screenshots/adv_nodes.png)

**Правила** — `rules`
RU routing rules with **service logos**; read-only "Основной узел" (URLTest / ByeDPI / a friendly node name).
![Rules](screenshots/adv_rules.png)

**Контроль доступа** — `access`
Per-device access modes (По умолчанию / Мимо прокси / Только прокси / Игровой / Проксировать весь трафик); device list from DHCP leases ("● это устройство").
![Access](screenshots/adv_access.png)

**ByeDPI** — `byedpi`
Enable ByeDPI (DPI bypass) switch + the **multi-host strategy tester** (●●●○ ratings across far/near sites).
![ByeDPI](screenshots/adv_byedpi.png)

**Ядро** — `core`
Proxy-core selection (sing-box-extended / hiddify) + version + running state; protocol-compatibility note.
![Core](screenshots/adv_core.png)

**Диагностика** — `diagnostics`
Step-by-step connectivity diagnostics + multi-site probes; active node shown with friendly name and latency coloring.
![Diagnostics](screenshots/adv_diagnostics.png)

**Безопасность** — `security`
Lists SSH keys in `authorized_keys` (flags the app's own), revoke single/all, set root password (🔑 / 🔒).
![Security](screenshots/10_security.png)

**О программе** — `about`
The brand **mark** + `Re:Sputnik` + version + copyright, and a scrollable **third-party licenses** box (reads the repo `NOTICE`).
![About](screenshots/11_about.png)

---

## 6. Regenerating screenshots
```sh
python scripts/capture_screens.py     # Windows; writes docs/design/screenshots/*.png
```
Each screen flashes briefly on screen while it's grabbed. Screens are built against a fake router client, so live data (nodes, leases, latencies) shows as empty/loading states — they illustrate **layout and styling**, not real content.
