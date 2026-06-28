# Re:Sputnik — Quick Setup redesign: implementation guide for Claude Code

This is the developer handoff for the design polish done in `Re Sputnik Quick Setup.dc.html`.
Goal of the pass (per the design owner): **keep the flow, Russian copy, Orbit-Cyan palette, Inter type, and the fixed 900×650 window — but unify the chrome, standardize components, and fix the broken empty states so the wizard reads as one crafted product instead of a stack of generic dark forms.**

Target app: Windows desktop, Python + customtkinter, dark theme, fixed 900×650 non-resizable. Implement these as **shared widgets reused across all 9 Quick Setup screens**, then apply the per-screen notes.

> The HTML mockup is the source of truth for spacing/colors. Where a CSS effect (gradient, box-shadow, blur) is awkward in customtkinter, the "ctk mapping" notes give the pragmatic substitute. Nothing here changes copy or flow.

---

## ⚠ Do NOT redesign the brand — these already exist and are final

The app **already has an established logo/mark and color palette** (`Sputnik '57` mark in `resources/branding/`, and the "Orbit Cyan" theme). **Do not redraw the logo, do not pick new brand colors, do not change the accent, and do not restyle the existing marks.** Reuse the shipped logo assets as-is.

Everything below works *within* that existing system:
- The **accent and all named tokens** (`accent`, `bg`, `surface`, `text`, `ok/warn/fail`, etc.) are the existing palette — kept verbatim.
- The few **"new" tokens** in §1 are not new brand colors — they are darker/lighter **tints of the same navy-grey ramp** for chrome and recessed surfaces (e.g. a titlebar that's a notch darker than the window). If you'd rather derive them from the existing tokens than hardcode, that's fine; the hex values are just the target.
- The **Sputnik mark** in the titlebar is the **existing PNG/SVG asset** — the gradient sphere in the HTML mockup is only a stand-in for it. Do not recreate the mark in code.

---

## 0. What changed, in one paragraph

Added a persistent **app chrome** (titlebar with the Sputnik mark + a 9-step progress strip) on every screen; replaced ad-hoc section titles with a **icon-chip section header**; standardized **checkbox / radio / toggle / text field / dropdown / primary+secondary buttons** into one spec; turned the two empty "loading" voids (Интернет, Проверка) into an **orbital loader + skeleton**; turned the two raw black console voids (Установка ПО, Предустановить) into a titled **log panel**; and gave the saved-router rows on screen 1 real structure (icon chip + name + mono endpoint + delete).

---

## 1. Color tokens

Existing brand tokens are unchanged (see the warning above). The redesign only adds a few **structural tints of the same navy-grey ramp** for the chrome and recessed surfaces — no new brand/accent colors. Add these to the theme dict (or derive them from the existing ramp).

| Token | Hex | Role | Status |
|---|---|---|---|
| `accent` | `#38BDF8` | primary action, active progress, dots, radio/checkbox/toggle ON | existing |
| `accent_hover` | `#0EA5E0` | hover of accent | existing |
| `accent_fg` | `#0B1220` | text/icon **on** accent (dark) | existing |
| `accent_disabled` | `rgba(56,189,248,.45)` → `#7CC9E6` flat | disabled primary button (e.g. zram while "Проверяю…") | **new** |
| `bg` | `#10131A` | window / screen background | existing |
| `surface` | `#1B2230` | cards / panels | existing |
| `surface_hover` | `#232C3D` | secondary buttons, hovered cards | existing |
| `field_bg` | `#141925` | text inputs, recessed rows (darker than surface) | **new** |
| `chrome_bg` | `#0B0E14` | titlebar background | **new** |
| `strip_bg` | `#0E121A` | progress strip + footer background | **new** |
| `border` | `#2B3547` | card borders, field borders | existing |
| `border_dim` | `#1C2330` | chrome dividers (titlebar/strip/footer) | **new** |
| `text` | `#E7E8EA` | primary text, entered values | existing |
| `text_strong` | `#CDD5DF` | control labels next to checkboxes/toggles | **new (tint)** |
| `text_mid` | `#AEB9C6` | strip "Быстрая настройка" label, deselected radio label | **new (tint)** |
| `text_muted` | `#93A0AE` | subtitles, field labels | existing |
| `text_dim` | `#7B8A9C` | hints, captions, mono endpoints, status idle | **new (tint)** |
| `text_faint` | `#5F6E80` | placeholders, log body, window-control glyphs | **new (tint)** |
| `seg_future` | `#26303F` | not-yet-reached progress segment | **new** |
| `ok / warn / fail` | `#22C55E / #F59E0B / #EF4444` | status only; `warn` also = yellow help button | existing |

**Rule reminders (unchanged, now enforced everywhere):** primary-button labels are always dark `accent_fg`, never white. One accent only — neutral UI stays grey. Status = colored dot + neutral label.

---

## 2. Typography

No scale change. Confirm slots and add a **mono** slot used for technical strings.

| Slot | px | weight | use |
|---|---|---|---|
| `title` | 22 | 700 | screen `<h1>` |
| `heading` | 15–16 | 700 | card / section headers |
| `body` | 13 | 400/600 | default text, buttons, inputs, control labels (600 when it's a control label) |
| `small` | 11–12 | 400 | hints, captions, status lines, field labels |
| `mono` | 11–12 | 400/500 | **JetBrains Mono** — IPs, `root@host:port`, generated password, log output, console label, vless/hysteria placeholders |

Add **JetBrains Mono** to bundled fonts (or fall back to the OS mono). It's the new signal that a string is "machine/technical."

---

## 3. Shared chrome (build once, reuse on all 9 screens)

Screen layout is now a fixed vertical stack inside the 900×650 window:

```
┌ Titlebar ───────────────── 44px (flex:none) ┐
├ Progress strip ──────────── ~46px (flex:none)┤
│ Content (scrolls) ───────── flex:1           │
└ Footer action bar ──────── ~78px, optional ──┘
```

### 3.1 Titlebar — `AppTitleBar`
- Height **44px**, bg `chrome_bg`, bottom border 1px `border_dim`, horizontal padding 14px.
- **Left:** Sputnik mark (24px) + wordmark. Wordmark = `Re:` in `accent` + `Sputnik` in `text`, 13px/700, letter-spacing .2px.
- **Right:** three window-control glyphs `‒  ▢  ✕`, color `text_faint`, 12px, gap 17px.
- **ctk mapping:** Use the existing raster mark asset — `resources/branding/icon_32.png` via `CTkImage` at ~22px. **Do not** recreate the CSS gradient sphere in code. The mockup's gradient/orbit-ring is just a stand-in for that PNG.

### 3.2 Step progress strip — `StepStrip(step, total=9, label="Подключение")`
- bg `strip_bg`, bottom border 1px `border_dim`, padding 9/18/10.
- Top row: left label `Быстрая настройка` (`text_mid`, 11px/600) — *(optional: swap to the current step's short name if you prefer)*; right `Шаг {step} из 9` (`text_dim`, 11px).
- Below: **9 segments** in a flex row, each `flex:1`, height **3px**, radius 2px, gap 4px. Segments `1..step` = `accent`; `step+1..9` = `seg_future`.
- **ctk mapping:** 9 `CTkFrame`s in a grid row with `weight=1` columns, `height=3`, `corner_radius=2`, `fg_color` per state. Recompute on each screen show.

> This strip is the single biggest "feels like one product" change — it ties all 9 screens together and removes the need to repeat the step name as a heading.

### 3.3 Footer action bar — `FooterBar`
- bg `strip_bg`, top border 1px `border_dim`, padding 14/28/18, vertical stack gap ~11.
- Holds the screen's **primary button** (full width) and optional **back/skip link** below it (left-aligned).
- Present on screens **1, 2, 7-area, 8, 9**; absent on 3 (pure loading) and on 4/5/6 where the action lives inside content (see per-screen notes).

---

## 4. Shared components

### 4.1 Section header with icon chip — `SectionHeader(glyph, title)`
- Chip: **30×30**, radius 9, bg `rgba(56,189,248,.13)` (flat `#1B2B3A` over `surface` is fine in ctk), glyph centered 15px.
- Title: 15px/700 `text`, 10px gap from chip.
- Glyph vocabulary (Unicode, from the design ref): 🔑 SSH key · 🔒 password · 📦 core/install · 🔗 subscription/links · 📄 file/keys · 🌐 network/router-name · 📶 Wi-Fi · 🔌 wired.
- **ctk mapping:** `CTkLabel` with a rounded `CTkFrame` behind the glyph; or one `CTkLabel` with `fg_color` + `corner_radius` for the chip.

### 4.2 Card — `Card`
- bg `surface`, border 1px `border`, radius 12, padding 16-18, inner vertical gap 11-12.
- **ctk:** `CTkFrame(corner_radius=12, border_width=1, border_color=border, fg_color=surface)`.

### 4.3 Text field — `Field(label, value/placeholder, width=fill)`
- Optional label above (12px `text_muted`) **or** to the left in a 96px column (screen 1 uses left labels; screens 7/9 use top labels — keep both layouts).
- Input: bg `field_bg`, border 1px `border`, radius 8, padding 9-10/12, value 13px `text`, placeholder 13px `text_faint`.
- **ctk:** `CTkEntry` with `fg_color=field_bg, border_color=border, corner_radius=8, text_color=text, placeholder_text_color=text_faint`.

### 4.4 Dropdown — `Dropdown`
- Same field shell + a **cyan caret box** flush-right: 38px wide, full height, bg `accent`, `▾` in `accent_fg`.
- **ctk:** `CTkOptionMenu` with `button_color=accent, button_hover_color=accent_hover, fg_color=field_bg, text_color=text_dim` for the "поиск…" placeholder state.

### 4.5 Checkbox — `Check`
- 18×18, radius 5. **Checked:** bg `accent`, `✓` `accent_fg` 11px/800. **Unchecked:** transparent, 1.5px border `#3A4659`.
- Label: 12.5px `text_strong`, 10px gap.
- **ctk:** `CTkCheckBox(fg_color=accent, checkmark_color=accent_fg, border_color=#3A4659, corner_radius=5)`.

### 4.6 Radio — `Radio`
- 18×18 circle. **Selected:** 2px border `accent` + 8px center dot `accent`; label `text`/600. **Unselected:** 2px border `#3A4659`; label `text_mid`.
- Each radio row may carry a 11.5px `text_dim` description line under the label (used in core selection).
- **ctk:** `CTkRadioButton(fg_color=accent, border_color=#3A4659)`.

### 4.7 Toggle — `Toggle`
- Track 38×21, radius 11, pad 2; knob 17×17 circle. **ON:** track `accent`, knob `accent_fg`, knob right. **OFF:** track `#2B3547`, knob `#6B7A8D`, knob left.
- **ctk:** `CTkSwitch(progress_color=accent, button_color=accent_fg(on)/#6B7A8D(off), fg_color=#2B3547)`. Optional description line under it at 11.5px `text_dim`, indented to align past the track (~51px).

### 4.8 Buttons
| Variant | bg | text | height | radius | use |
|---|---|---|---|---|---|
| Primary | `accent` (hover `accent_hover`) | `accent_fg` 14/700 | 46 | 9 | main step action (full width in footer/content) |
| Primary-small | `accent` | `accent_fg` 12.5/700 | 36-38 | 8 | "Добавить и обновить", "Импортировать", "Переименовать" |
| Primary-disabled | `accent_disabled` flat | `accent_fg` | 36 | 8 | zram button while checking |
| Secondary | `surface_hover`, 1px `border` | `text_strong` 12.5/500-600 | 34-38 | 8 | "＋ строка", "Импорт .conf…", "Сгенерировать", "↻ Проверить снова", "Установить" (LuCI extra) |
| Help (warn) | `warn` `#F59E0B` | `#241A05` 11.5/600 | auto | 8 | "❓ Не понимаю, как подключить роутер" (screen 1, top-right) |
| Link | none | `text_muted` 12.5 (or `accent` for "↻ Сгенерировать заново" / "Копировать") | — | — | "← Назад", "Пропустить", inline text actions |

### 4.9 Saved-router row — `RouterRow(ip, endpoint, kind)`
- bg `field_bg`, border 1px `border_row`, radius 9, padding 9/12, gap 12.
- Left icon chip 28×28 radius 7, bg `rgba(56,189,248,.1)`, glyph `accent` (🔌 wired / 🌐 by-IP).
- Middle: name 13px/600 `text`; endpoint 11px `text_dim` **mono** (`root@host:port`).
- Right: `✕` delete, 26×26, `text_faint`, hover → `surface_hover`.
- ⚠ **HTML-only gotcha, ignore in Python:** in the browser mockup, Cloudflare email-obfuscation rewrote `root@host:port` into a fake mailto link, so the mockup splits the `@` into its own span. This is a hosting artifact of the HTML preview — **the Python app has no such issue; render the string normally.**

### 4.10 Log / console panel — `LogPanel(title)`  *(replaces the raw black voids)*
- Outer: bg `console_bg`, border 1px `border_dim`, radius 10, clipped.
- Header bar: bg `console_head_bg`, bottom border `border_dim`, padding 8/13 — a 6px `text_faint` dot + label (e.g. `ЖУРНАЛ УСТАНОВКИ`) in **mono** 10.5px, letter-spacing 1px, `text_faint`.
- Body: mono 11.5px `text_faint`, min-height 80-90px, line-height 1.7. Empty state: `Журнал установки появится здесь…`. Streams real install output here.
- **ctk:** `CTkFrame` header + `CTkTextbox(state=disabled, fg_color=console_bg, font=mono)`.

### 4.11 Orbital loader — `OrbitLoader(size)`  *(replaces the empty loading voids)*
- Concentric tilted rings + a glowing cyan sphere center; pair with a status line (cyan dot + "Проверяю…") and 2-3 **skeleton bars** (`field_bg`/`surface_hover`, radius 6, varying widths).
- **ctk:** simplest faithful version = the mark PNG centered + an indeterminate `CTkProgressBar(mode="indeterminate")` or a small spinner; the tilted-ring look is decorative. The point is **never show an empty black rectangle while checking** — always loader + skeleton.

### 4.12 Status line + dot
- 7px circle + label. In-progress = `accent` with soft glow + `text_muted` label. Idle/checking-misc = `text_dim` dot + `text_dim` label. Use for "Проверяю доступ в интернет…", "Проверяю, что уже установлено…", "Проверяю…".

---

## 5. Per-screen changes

**01 · Подключение к роутеру**
- Help button restyled to the `warn` spec, pinned top-right of the header (was floating/inconsistent).
- "Сохранённые роутеры" rows rebuilt with `RouterRow` (icon chip + name + mono endpoint + delete) — previously cramped/iconless.
- Form uses the **left-label** field layout (96px label column); the "Порт" field is fixed 88px wide (was full width).
- "Найдено" is the `Dropdown` with cyan caret. Hint line aligned under the field column. Checkbox = `Check`. Footer: single primary "Подключиться" (no back — first step).

**02 · Безопасность (firstrun)**
- Two cards with `SectionHeader` 🔑 / 🔒. Radios + password field (mono) + cyan text-links "↻ Сгенерировать заново" / "Копировать". Footer: "Применить" + "← Назад" link.

**03 · Интернет** — *was an empty black void.*
- Header + status line, then **`OrbitLoader` + skeleton** centered in the content area. No footer (auto-advances). 

**04 · Установка ПО** — *had a raw black console.*
- `SectionHeader` 📦 "Ядро" with two description-radios; ByeDPI `Toggle` card; primary "Установить" inside content; **`LogPanel` ("ЖУРНАЛ УСТАНОВКИ")** instead of the black box.

**05 · Предустановить пакеты** — *same black-console fix.*
- 📦 core radios + "Обязательно: kmod-…" caption; **ON** toggle "Установить LuCI-приложение Re:HomeProxy (+ русский язык)" with description; OFF ByeDPI toggle; primary "Скачать и установить"; **`LogPanel` ("ЖУРНАЛ ЗАГРУЗКИ")**.

**06 · Узлы и подписка**
- Two cards: 🔗 "Подписки (URL)" (field + primary-small "Добавить и обновить" + secondary "＋ строка") and 📄 "Ссылки-ключи или .conf" (mono textarea on `console_bg` + "Импортировать" + "Импорт .conf…"). Empty textarea shows mono `vless://…` / `hysteria2://…` hints.

**07 · Точка доступа**
- Single card, **top-label** fields: SSID; password row = field + 👁 reveal (secondary) + "Сгенерировать" (secondary); `Check` "Включить также 6 ГГц…"; primary "Создать сеть" inside the card; "Пропустить" link below.

**08 · Проверка** — *was an empty box.*
- Header + status line; a **result panel** (`field_bg` card) containing `OrbitLoader` + 2 skeleton bars while probing. Footer: secondary "↻ Проверить снова" (left, auto-width) above full-width primary "Готово".

**09 · Завершение**
- 🌐 "Имя роутера" card (field + primary-small "Переименовать"); OFF toggle "Проверять обновления прошивки…" with description; "zram-swap (рекомендуется)" card with idle status + **disabled** primary while "Проверяю…"; "Дополнительные приложения LuCI" card with description + secondary "Установить". Footer: full-width primary "Готово".

---

## 6. customtkinter implementation notes / caveats

- **No CSS gradients / box-shadow / blur.** Drop shadows in the mockup are presentation-only — omit. The sphere gradient → use the existing PNG mark assets. Glows on status dots → omit or fake with a slightly lighter ring; not required.
- **Rounded corners** map cleanly to `corner_radius`. The 3px progress segments and 18px controls are all `CTkFrame`/native widgets with explicit sizes.
- **`rgba(...)` chip/overlay colors** — customtkinter wants solid hex. Pre-flatten over the parent: chip on `surface` ≈ `#1B2B3A`; chip on `field_bg` ≈ `#15222F`. (Or just use a solid muted-cyan `#163142`.)
- **Fixed window 900×650** unchanged; content region scrolls via `CTkScrollableFrame`. Titlebar + strip + footer are `flex:none` (pack with `side=top/bottom`, scroll frame fills middle).
- **Build order:** implement §3 chrome + §4 components as reusable classes first, then refactor each of the 9 screen builders to use them. This is where the consistency win comes from — avoid re-styling per screen.
- **Native window titlebar:** if the app keeps the OS titlebar, the in-app `AppTitleBar` is still wanted as a branded header band — but then the `‒ ▢ ✕` glyphs are decorative; either wire them to the real min/close or drop them to avoid a fake duplicate. Decide with the design owner.

---

## 6b. Custom iconography + banner (replaces generic icons & emoji)

Preview: `Re Sputnik Icons and Banner.dc.html`. Master assets: `assets/icons/*.svg` + `assets/banner_hero.svg`.

**Why:** the lightning/gear/box on the mode picker and the 🔌🔑🔒📦🔗📄🌐📶 emoji in the section headers were the "generic" problem. This is a single hand-built set with a **satellite/orbit signature** — 24×24 grid, 1.7 stroke, round caps, single accent `#38BDF8`, `fill:none`.

**Mode-picker icons (replace lightning / gear / box):**
| File | Screen card | Motif |
|---|---|---|
| `mode_guided.svg` | Пошаговая настройка | ascending steps to a glowing end-node |
| `mode_advanced.svg` | Расширенный | three slider tracks with node-knobs |
| `mode_preinstall.svg` | Предустановить пакеты | down-arrow into an open tray |

**Section-header / step library (replace the emoji):** `connect, key, lock, package, link, file, globe, wifi, nodes, verify, finalize, resource` — map 1:1 to the glyph slots in §4.1. One set serves three sizes: 30px section-header chip, the 9-step rail, and the 64px mode-card chip.

**Banner — `banner_hero.svg` (880×300):** replaces the plain centred text header on the mode-picker. Orbital backdrop (concentric faint rings + star dots + bottom glow) and the Sputnik mark. The SVG bakes the wordmark + subtitle as a master, but in-app **keep them as live ctk labels on top of the backdrop image** so the copy stays editable. The mark in the banner is the same brand asset — don't redraw it (see brand warning at top).

**customtkinter wiring:**
1. SVGs are `stroke=#38BDF8, fill=none`. Recolour by swapping the stroke string before rastering (e.g. for a disabled/muted state).
2. ctk can't load SVG — rasterise to PNG @1x/2x with `cairosvg`, then `CTkImage(light_image=img, size=(24,24))`.
3. One cached helper: `icon(name, size, color="#38BDF8") -> CTkImage`. Build the mode cards, the 9-step rail, and the section headers from that single call.
4. Banner: `banner_hero.svg` (or a pre-rasterised PNG) as the full-width header image; overlay the live wordmark/subtitle labels.

> These are line icons, not the brand logo. The logo/mark itself is unchanged and still comes from the existing branding assets.

---

## 7. Out of scope (not touched this pass)
- Mode-picker entry screen, and the entire **Advanced** settings shell (Обзор / Узлы / Правила / Контроль доступа / ByeDPI / Ядро / Диагностика / Безопасность / О программе). The same chrome + component system should extend to them next; the dashboard meters, rule rows with service logos, and DPI tester (●●●○) will need their own specs.
- Copy, flow order, and the Russian disclaimer — unchanged by request.
- **Logo / mark and the brand color palette — do not touch (see the warning at the top).** Reuse existing assets and the existing Orbit-Cyan tokens as-is.
