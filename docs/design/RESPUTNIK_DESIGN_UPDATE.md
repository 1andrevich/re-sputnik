# Re:Sputnik — Design Reference UPDATE (for Claude / web)

**Read this together with `RESPUTNIK_DESIGN.md`.** This is a *delta*, not a rewrite. The presentation you built is still correct — keep its structure, brand, palette, type, flow, prose voice, and everything not mentioned here. Apply only the changes below so the deck reflects the current app.

> TL;DR: (1) point every screenshot at the **English** set in `screenshots_live/`; (2) the old **“ByeDPI”** Advanced section is now **“AntiDPI”** (ByeDPI **+ Zapret 2**); (3) a new **“Extras / Дополнительно”** Advanced section exists; (4) the **Core** screen and the **Overview node pool** gained content (core-management details, per-node **country flags + protocol tags**). Two extra illustrative shots are included.

---

## 1. Screenshots → use the English `screenshots_live/` set

All capture-able screens were re-shot with the app in **English** for an international audience. **Repoint every `![...](screenshots/…png)` to `screenshots_live/…png`.** Same filenames for the existing screens, so it's a path swap:

`screenshots/01_connect.png` → `screenshots_live/01_connect.png`, and likewise for `02–11` and `adv_access / adv_core / adv_diagnostics / adv_nodes / adv_overview / adv_rules`.

Because the UI in these shots is now English, **align the screen labels/captions in the deck to the English UI** (e.g. the titles visible in the screenshots). Keep the Russian term in parentheses if you like the bilingual feel — just be consistent across the deck. Do **not** change the flow, order, or the Russian disclaimer text itself.

New files in `screenshots_live/` that have **no** counterpart in the old set: `adv_antidpi.png`, `adv_advanced.png`, `adv_core_narrow.png`, `overview_flags.png` (used below).

---

## 2. Advanced nav list changed

`RESPUTNIK_DESIGN.md` §5 lists the Advanced left-nav as:
*Обзор · Узлы и подписки · Правила · Контроль доступа · **ByeDPI** · Ядро · Диагностика · Безопасность · О программе.*

**Replace with the current nav (two changes — bold):**
*Обзор · Узлы и подписки · Правила · Контроль доступа · **AntiDPI** · Ядро · Диагностика · Безопасность · **Дополнительно** · О программе.*

---

## 3. Rename + expand the “ByeDPI” section → **“AntiDPI”**  (`adv_antidpi.png`)

The single-engine ByeDPI panel is now a **two-engine AntiDPI** section. Replace the old **ByeDPI** screen entry with:

> **AntiDPI** — `antidpi`
> DPI bypass for services that don't need a full VPN — **two tools, try both, what works depends on your ISP**:
> - **ByeDPI** (`ciadpi`) — SOCKS-level desync: install/version/arch, **Enable** toggle, ready-made **strategy** dropdown + free-form args, Save/Apply, and a **strategy tester** (● = TLS handshake succeeded, ○ = blocked).
> - **Zapret 2** (`nfqws2`) — packet-level NFQUEUE desync; *“also unblocks video (QUIC) and calls that ByeDPI can't handle.”* Its own strategy field + scoped tester.
>
> `![AntiDPI](screenshots_live/adv_antidpi.png)`

Note the tester legend is now **● / ○** (filled = pass, hollow = blocked). The old `●●●○` four-dot scale wording in §4a can stay as the *fake-TTL adaptive* rating, but the simple pass/blocked dots are what the AntiDPI tester shows.

---

## 4. New section: **Extras / Дополнительно**  (`adv_advanced.png`)

Add a new Advanced screen entry (place it after **Безопасность**, matching the nav order):

> **Дополнительно (Extras)** — `advanced`
> *“Dangerous router operations — do them only if necessary, and download a backup first.”* Houses:
> - **Router name** — rename the hostname (moved/echoed here).
> - **Settings backup** — **Download backup** / **Restore from a file…** (full LuCI-style config backup).
> - **Wi-Fi networks** — per-band editor (SSID / password / encryption / channel, separately per radio), with live radio state (“5G · radio0 — enabled, broadcasting”). Changes apply immediately.
> - *(below the fold: factory reset, LAN IP / DHCP + static leases.)*
>
> `![Extras](screenshots_live/adv_advanced.png)`

---

## 5. Updated content on existing screens

**Ядро (Core)** — richer than “core selection + version + state.” It now also has **per-core “Update to latest”** buttons, the **Re:HomeProxy app** version + **Reinstall**, and a **Core management** card (package manager, architecture, free `/tmp`, free `overlay`, kernel version). Keep `adv_core.png` as the primary image and **add the narrow-width variant** as a layout/example shot:
`![Core (narrow)](screenshots_live/adv_core_narrow.png)`

**Обзор (Overview)** — the **Active server** row and the **server pool** now show **per-node country flags + protocol tags** (e.g. 🇨🇭 Switzerland GAMING (hysteria2), 🇩🇪 Germany (vless)), and the active node resolves with its flag, protocol, latency and URLTest group. Add this illustrative shot to the Overview entry:
`![Overview — node pool with flags](screenshots_live/overview_flags.png)`

**(verify)** the Overview **DNS test** caption: §5 currently says *“Россия — протестировано на mail.ru.”* The default test host may have changed (e.g. **ya.ru**). Check the current Overview and update the caption to match what the app shows.

---

## 6. Do NOT change

- Brand mark, **Orbit-Cyan** palette, Inter type, the four type slots, the icon vocabulary (§1–4) — unchanged.
- Quick Setup flow, screen order, and the Russian disclaimer — unchanged.
- The service/routing logo set (§4b) — unchanged.
- Everything in `RESPUTNIK_DESIGN.md` not listed above stays as-is.

*Regeneration note: the live English set comes from `python scripts/capture_screens_live.py` (English locale); `overview_flags.png` and `adv_core_narrow.png` are supplemental shots illustrating the flags feature and the narrow-layout / core-management content.*
