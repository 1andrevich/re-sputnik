# SPDX-License-Identifier: GPL-2.0-only
"""Main application window and screen navigation.

The window hosts one swappable content area. The mode picker (Quick Setup vs
Advanced) is the first screen; both modes lead into the same engine. Quick Setup
now begins with the real Phase 0 connection screen.
"""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from . import APP_NAME, __version__
from . import secrets as app_secrets
from .router import RouterClient, RouterState
from .ui import scrollpatch
from .ui.theme import Palette, apply_theme, fonts

# Nested lists scroll independently of the page they sit on (see scrollpatch).
scrollpatch.apply()

# Mandatory disclaimer — mirrors the SETUP_AGENT one, adapted for a program
# (not an AI agent): "as is", no warranty, no liability, your own risk, comply
# with your country's VPN/proxy laws.
DISCLAIMER_RU = (
    "⚠️ Важно, прочитайте перед началом.\n\n"
    "Настройку выполняет программа Re:Sputnik, которая может содержать ошибки. "
    "Всё программное обеспечение и конфигурации предоставляются «как есть», без "
    "каких-либо гарантий. Авторы Re:Sputnik, Re:HomeProxy и всего "
    "предоставляемого ПО не несут ответственности за любой возможный ущерб, "
    "потерю данных, проблемы со связью, блокировки или иные последствия.\n\n"
    "Вы действуете на свой страх и риск и сами отвечаете за соблюдение законов "
    "вашей страны в отношении использования VPN/прокси.\n\n"
    "Продолжая, вы принимаете эти условия."
)


class ModeCard(ctk.CTkFrame):
    """A large, clickable card for one entry mode."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        palette: Palette,
        *,
        icon: str,
        title: str,
        subtitle: str,
        command: Callable[[], None],
        icon_color: str | None = None,
        icon_name: str | None = None,
    ) -> None:
        super().__init__(
            master,
            fg_color=palette.surface,
            corner_radius=14,
            border_width=1,
            border_color=palette.border,
        )
        self._palette = palette
        self._command = command
        self.grid_columnconfigure(0, weight=1)

        # Prefer the custom line icon; fall back to the colored emoji if its PNG
        # isn't present. ("Segoe UI Emoji" renders the glyph crisply + tinted.)
        from .ui.kit import icon as _line_icon

        self._mode_img = _line_icon(icon_name, 44) if icon_name else None
        if self._mode_img is not None:
            ctk.CTkLabel(self, image=self._mode_img, text="").grid(
                row=0, column=0, pady=(26, 6), padx=16)
        else:
            ctk.CTkLabel(self, text=icon, font=ctk.CTkFont(family="Segoe UI Emoji", size=40),
                         text_color=icon_color or palette.text).grid(
                row=0, column=0, pady=(26, 6), padx=16)
        self._title_lbl = ctk.CTkLabel(self, text=title, font=fonts.heading(), text_color=palette.text)
        self._title_lbl.grid(row=1, column=0, padx=16)
        self._subtitle_lbl = ctk.CTkLabel(
            self,
            text=subtitle,
            font=fonts.body(),
            text_color=palette.text_muted,
            justify="center",
            # Seed a bounded wrap so the caption never renders as one over-wide line
            # (which pushed the card past its third of the window and clipped at the
            # edges before <Configure> fired). _on_resize refines it to the real width.
            wraplength=230,
        )
        self._subtitle_lbl.grid(row=2, column=0, pady=(6, 26), padx=16)

        # Wrap text to the card's actual width so it never clips at the default
        # window size (or when resized) — a fixed wraplength overflows the cell.
        self.bind("<Configure>", self._on_resize)

        for widget in (self, *self.winfo_children()):
            widget.bind("<Button-1>", lambda _e: self._command())
            widget.bind("<Enter>", lambda _e: self.configure(fg_color=palette.surface_hover))
            widget.bind("<Leave>", lambda _e: self.configure(fg_color=palette.surface))

    def _on_resize(self, event: "object") -> None:
        wrap = max(getattr(event, "width", 200) - 32, 120)
        self._subtitle_lbl.configure(wraplength=wrap)
        self._title_lbl.configure(wraplength=wrap)


class App(ctk.CTk):
    """Top-level window with a single swappable content area."""

    WINDOW_W = 900
    WINDOW_H = 650

    def _cap_scaling_to_screen(self, base_w: int, base_h: int) -> None:
        """Shrink customtkinter's scaling so the fixed window fits the display.

        The window is non-resizable, and customtkinter scales geometry by the
        monitor DPI — so on a small or high-DPI screen (e.g. a 1366×768 laptop at
        150%) the physical window could exceed the screen with no way to shrink
        it. We compute the effective scaling and, if the window wouldn't fit the
        usable area (minus title bar + taskbar), reduce widget+window scaling just
        enough to fit. We never scale UP past the monitor's own DPI.
        """
        try:
            eff = ctk.ScalingTracker.get_window_scaling(self)
            avail_w = self.winfo_screenwidth() - 60
            avail_h = self.winfo_screenheight() - 100
            need_w, need_h = base_w * eff, base_h * eff
            if need_w <= avail_w and need_h <= avail_h:
                return  # fits at native DPI — leave scaling alone
            factor = min(avail_w / need_w, avail_h / need_h)
            factor = max(factor, 0.5)  # don't shrink into illegibility
            ctk.set_widget_scaling(factor)
            ctk.set_window_scaling(factor)
        except Exception:  # noqa: BLE001 — scaling is best-effort, never fatal
            pass

    def _install_clipboard_bindings(self) -> None:
        """Make Ctrl+C/V/X/A work under ANY keyboard layout.

        Tk binds the clipboard shortcuts to the *Latin* keysyms (``<Control-v>`` …),
        so under a Russian layout the physical V key emits a non-Latin keysym and the
        default ``<<Paste>>`` binding never fires — paste silently does nothing.
        Matching on the specific Cyrillic keysym is unreliable (Tk reports different
        keysyms with Ctrl held). Instead we catch the general ``<Control-KeyPress>``
        and dispatch by ``keycode`` (the physical key / Windows virtual-key code,
        independent of the active layout). Tk fires the most specific binding per
        widget class, so for a Latin layout the built-in ``<Control-v>`` wins and this
        general handler doesn't run — no double paste.
        """
        import sys

        # Physical C/V/X/A key codes → action. Keycodes are platform-specific:
        # Windows uses virtual-key codes; macOS uses hardware keycodes. (Linux/X11
        # differs again, but we don't ship a Linux build — it falls back to Tk's
        # native bindings, which work for Latin layouts.)
        if sys.platform == "darwin":
            kc_action = {8: "<<Copy>>", 9: "<<Paste>>", 7: "<<Cut>>", 0: "select-all"}
            kc_latin = {8: "c", 9: "v", 7: "x", 0: "a"}
            modifier = "Command"          # ⌘ on macOS
            mod_mask = None               # the <Command-…> binding already gates it
        else:
            kc_action = {67: "<<Copy>>", 86: "<<Paste>>", 88: "<<Cut>>", 65: "select-all"}
            kc_latin = {67: "c", 86: "v", 88: "x", 65: "a"}
            modifier = "Control"
            mod_mask = 0x0004             # Control must be held

        def handler(event):  # type: ignore[no-untyped-def]
            if mod_mask is not None and not (event.state & mod_mask):
                return None
            action = kc_action.get(event.keycode)
            if action is None:
                return None
            # Latin layout already handled it via the specific <Mod-x> binding.
            if (event.keysym or "").lower() == kc_latin.get(event.keycode):
                return None
            w = event.widget
            if action == "select-all":
                try:
                    w.select_range(0, "end")
                    w.icursor("end")
                except Exception:  # noqa: BLE001 — Text widget has no select_range
                    try:
                        w.tag_add("sel", "1.0", "end")
                    except Exception:  # noqa: BLE001
                        return None
                return "break"
            try:
                w.event_generate(action)
            except Exception:  # noqa: BLE001
                return None
            return "break"

        try:
            for cls in ("Entry", "Text", "TEntry"):
                self.bind_class(cls, f"<{modifier}-KeyPress>", handler, add="+")
        except Exception:  # noqa: BLE001 — must never break startup
            pass

    def _set_window_icon(self) -> None:
        """Title-bar / taskbar icon from the Pillow-rendered Re:Sputnik mark.

        Cross-platform PhotoImage always; on Windows also a committed .ico
        (crisper in the taskbar). Cosmetic — a failure must never block startup.
        """
        try:
            import os

            from PIL import ImageTk

            from .branding import app_icon_image

            self._icon_ref = ImageTk.PhotoImage(app_icon_image(64))  # keep ref (avoid GC)
            self.iconphoto(True, self._icon_ref)
            if os.name == "nt":
                ico = os.path.join(os.path.dirname(__file__), "resources", "branding", "icon.ico")
                if os.path.exists(ico):
                    self.iconbitmap(default=ico)
        except Exception:  # noqa: BLE001 — icon is cosmetic
            pass

    def __init__(self) -> None:
        super().__init__()
        self.palette = apply_theme("dark")

        self.title(APP_NAME)
        self._set_window_icon()
        # Cap UI scaling so the locked window always fits the screen (see below)
        # BEFORE setting geometry — .geometry() bakes in the window scaling factor.
        self._cap_scaling_to_screen(self.WINDOW_W, self.WINDOW_H)
        # Fixed, non-resizable window: every screen is laid out for one size, so
        # locking it keeps text wrapping predictable (no clipping, no awkward
        # reflow). Tall content scrolls within its screen.
        self.geometry(f"{self.WINDOW_W}x{self.WINDOW_H}")
        self.resizable(False, False)
        self.configure(fg_color=self.palette.bg)
        self._install_clipboard_bindings()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Install the main-thread poll loop that delivers background results.
        from .ui.worker import install

        install(self)

        self._content: ctk.CTkBaseClass | None = None
        self._mode = "advanced"  # quick | advanced | preinstall
        # Show the mandatory disclaimer first (once), like SETUP_AGENT does.
        if app_secrets.disclaimer_accepted():
            self.show_mode_picker()
        else:
            self.show_disclaimer()

    def show_disclaimer(self, *, on_accept: Callable[[], None] | None = None) -> None:
        p = self.palette
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(frame, text="Re:Sputnik", font=fonts.title(), text_color=p.text).grid(
            row=0, column=0, pady=(40, 10))
        card = ctk.CTkFrame(frame, fg_color=p.surface, corner_radius=14, border_width=1,
                            border_color=p.border)
        card.grid(row=1, column=0, padx=40, pady=8, sticky="n")
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text=DISCLAIMER_RU, font=fonts.body(), text_color=p.text,
                     wraplength=640, justify="left").grid(row=0, column=0, padx=24, pady=(20, 14))

        btns = ctk.CTkFrame(frame, fg_color="transparent")
        btns.grid(row=2, column=0, pady=(6, 20))
        # Re-view mode (from the footer link): just a Close button, no re-accept.
        if on_accept is None and app_secrets.disclaimer_accepted():
            ctk.CTkButton(btns, text="Закрыть", font=fonts.heading(), height=42, width=200,
                          fg_color=p.surface, hover_color=p.surface_hover,
                          command=self.show_mode_picker).grid(row=0, column=0)
        else:
            ctk.CTkButton(btns, text="Выход", font=fonts.body(), height=42, width=140,
                          fg_color="transparent", hover_color=p.surface_hover,
                          command=self.destroy).grid(row=0, column=0, padx=(0, 10))
            ctk.CTkButton(btns, text="Принимаю и продолжаю", font=fonts.heading(), height=42,
                          width=260, fg_color=p.accent, text_color=p.accent_fg, hover_color=p.accent_hover,
                          command=lambda: self._accept_disclaimer(on_accept)).grid(row=0, column=1)
        self._swap(frame)

    def _accept_disclaimer(self, on_accept: Callable[[], None] | None) -> None:
        app_secrets.accept_disclaimer()
        (on_accept or self.show_mode_picker)()

    # ----- screen swapping ----------------------------------------------

    def _swap(self, frame: ctk.CTkBaseClass) -> None:
        if self._content is not None:
            self._content.destroy()
        self._content = frame
        frame.grid(row=0, column=0, sticky="nsew")

    # ----- screens ------------------------------------------------------

    def show_mode_picker(self) -> None:
        p = self.palette
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        # Hero banner (Sputnik mark + wordmark + subtitle baked into the PNG).
        # Falls back to the plain text header if the image can't be loaded.
        shown = False
        try:
            import os

            from PIL import Image

            bpath = os.path.join(os.path.dirname(__file__), "resources", "branding", "banner.png")
            if os.path.exists(bpath):
                bimg = Image.open(bpath)
                bw, bh = bimg.size
                disp_w = 720
                self._banner_img = ctk.CTkImage(
                    light_image=bimg, dark_image=bimg, size=(disp_w, int(bh * disp_w / bw)))
                ctk.CTkLabel(frame, image=self._banner_img, text="").grid(
                    row=0, column=0, columnspan=1, pady=(22, 16))
                shown = True
        except Exception:  # noqa: BLE001 — banner is decorative
            shown = False
        if not shown:
            ctk.CTkLabel(frame, text="Re:Sputnik", font=fonts.title(), text_color=p.text).grid(
                row=0, column=0, pady=(40, 2))
            ctk.CTkLabel(
                frame, text="Настройка Re:HomeProxy на роутере OpenWRT",
                font=fonts.body(), text_color=p.text_muted).grid(row=1, column=0, pady=(0, 26))

        cards = ctk.CTkFrame(frame, fg_color="transparent")
        cards.grid(row=2, column=0, padx=24, sticky="n")
        cards.grid_columnconfigure((0, 1, 2), weight=1, uniform="cards")

        ModeCard(
            cards, p,
            icon="⚡",
            icon_name="mode_guided",
            icon_color="#FBBF24",  # amber — speed / quick (emoji fallback)
            title="Пошаговая настройка",
            subtitle="Приложение ведёт за руку: интернет, установка, серверы, проверка",
            command=self.show_quick_setup,
        ).grid(row=0, column=0, padx=10, sticky="nsew")
        ModeCard(
            cards, p,
            icon="⚙",
            icon_name="mode_advanced",
            icon_color="#38BDF8",  # cyan accent — the app's color (emoji fallback)
            title="Расширенный",
            subtitle="Свободная навигация по разделам: Серверы, Правила, Диагностика…",
            command=self.show_advanced,
        ).grid(row=0, column=1, padx=10, sticky="nsew")
        ModeCard(
            cards, p,
            icon="📦",
            icon_name="mode_preinstall",
            icon_color="#34D399",  # emerald — packages / install (emoji fallback)
            title="Предустановить пакеты",
            subtitle="Скачать на ПК и залить на роутер для установки без интернета",
            command=self.show_preinstall_connect,
        ).grid(row=0, column=2, padx=10, sticky="nsew")

        ctk.CTkLabel(
            frame,
            text="Роутер уже настроен? Любой режим подхватит текущую конфигурацию, а не начнёт с нуля.",
            font=fonts.small(),
            text_color=p.text_muted,
        ).grid(row=3, column=0, pady=(20, 4))
        foot = ctk.CTkFrame(frame, fg_color="transparent")
        foot.grid(row=4, column=0, pady=(0, 12))
        ctk.CTkLabel(foot, text=f"v{__version__}", font=fonts.small(), text_color=p.text_muted).grid(
            row=0, column=0, padx=(0, 8))
        ctk.CTkButton(foot, text="Дисклеймер", font=fonts.small(), width=90, fg_color="transparent",
                      hover_color=p.surface_hover, text_color=p.text_muted,
                      command=lambda: self.show_disclaimer()).grid(row=0, column=1)
        self._swap(frame)

    def _connect_for(self, mode: str) -> None:
        from .ui.connect_screen import ConnectScreen

        self._mode = mode
        self._swap(ConnectScreen(
            self, self.palette, on_connected=self._on_connected, on_back=self.show_mode_picker))

    def show_quick_setup(self) -> None:
        self._connect_for("quick")

    def show_advanced(self) -> None:
        self._connect_for("advanced")

    def show_preinstall_connect(self) -> None:
        self._connect_for("preinstall")

    # ----- post-connection ----------------------------------------------

    def _on_connected(self, client: RouterClient, state: RouterState) -> None:
        # Phase 1: run first-run setup (install app key + set a strong root
        # password) unless the app's key is already trusted — for EVERY mode,
        # including preinstall, so a handed-off staged device isn't left
        # password-less.
        if not state.our_key_installed:
            self.show_firstrun(client, state)
        else:
            self._after_firstrun(client, state)

    def show_preinstall(self, client: RouterClient, state: RouterState) -> None:
        from .ui.preinstall_screen import PreinstallScreen

        # After staging packages, optionally pre-configure WAN + Wi-Fi AP so the
        # device can be deployed with minimal work on-site (or handed to someone).
        self._swap(PreinstallScreen(
            self, self.palette, client, on_done=self.show_mode_picker,
            on_continue=lambda: self.show_preinstall_wan(client, state)))

    def show_preinstall_wan(self, client: RouterClient, state: RouterState) -> None:
        from .ui.internet_screen import InternetScreen

        # Staging: allow proceeding without internet (router may be away from the
        # ISP socket); WAN details are pre-entered and apply once the cable is in.
        self._swap(InternetScreen(
            self, self.palette, client, allow_skip=True,
            on_done=lambda: self.show_preinstall_ap(client, state)))

    def show_preinstall_ap(self, client: RouterClient, state: RouterState) -> None:
        from .ui.wifi_ap_screen import WifiApScreen

        self._swap(WifiApScreen(
            self, self.palette, client,
            on_done=lambda: self.show_preinstall_nodes(client, state)))

    def show_preinstall_nodes(self, client: RouterClient, state: RouterState) -> None:
        from .ui.quick_nodes_screen import QuickNodesScreen

        # Offline staging: import locally-parsed nodes (vpn:// / share-links /
        # .conf). Subscriptions need internet, so they're deferred to the online
        # finish (state becomes 'partial' → Quick Setup resumes at nodes).
        self._swap(QuickNodesScreen(
            self, self.palette, client, offline=True, on_done=self.show_mode_picker))

    def show_firstrun(self, client: RouterClient, state: RouterState) -> None:
        from .ui.firstrun_screen import FirstRunScreen

        screen = FirstRunScreen(
            self,
            self.palette,
            client,
            state,
            on_done=self._after_firstrun,
            on_back=self.show_mode_picker,
        )
        self._swap(screen)

    def _after_firstrun(self, client: RouterClient, state: RouterState) -> None:
        # Quick Setup ends with the Verify phase; Advanced jumps into the settings
        # shell. (Quick-Setup phases 2–4 for a clean router land between here and
        # Verify once built.)
        if self._mode == "quick":
            self.show_internet(client, state)
        elif self._mode == "preinstall":
            self.show_preinstall(client, state)
        else:
            self.show_settings(client, state)

    def show_internet(self, client: RouterClient, state: RouterState) -> None:
        from .ui.internet_screen import InternetScreen

        # Internet first (needed before any package install); then the software
        # phase (only on a router without Re:HomeProxy yet), then Verify.
        # Back leaves to the connection screen: firstrun (step 1) already changed
        # the root password + installed the key, so we never re-enter it; the user
        # escapes the wizard to reconnect / pick another router instead.
        screen = InternetScreen(self, self.palette, client,
                                on_done=lambda: self._after_internet(client, state),
                                on_back=lambda: self._connect_for(self._mode))
        self._swap(screen)

    def _after_internet(self, client: RouterClient, state: RouterState) -> None:
        # Clean router → install software; installed-but-no-node → nodes; else verify.
        # Back from each config step returns to Internet (the boundary — we never
        # go back past firstrun, which changed credentials). Each step threads its
        # own back, so the chain reconstructs from the live device on the way back.
        back = lambda: self.show_internet(client, state)  # noqa: E731
        if not state.homeproxy_installed:
            self.show_software(client, state, back=back)
        elif not state.has_config:
            self.show_nodes(client, state, back=back)
        else:
            self.show_verify(client, state, back=back)

    def show_software(self, client, state, back=None) -> None:
        from .ui.software_screen import SoftwareScreen

        screen = SoftwareScreen(
            self, self.palette, client, on_back=back,
            on_done=lambda: self.show_nodes(
                client, state, back=lambda: self.show_software(client, state, back=back)))
        self._swap(screen)

    def show_nodes(self, client, state, back=None) -> None:
        from .ui.quick_nodes_screen import QuickNodesScreen

        screen = QuickNodesScreen(
            self, self.palette, client, on_back=back,
            on_done=lambda: self.show_rules(
                client, state, back=lambda: self.show_nodes(client, state, back=back)))
        self._swap(screen)

    def show_rules(self, client, state, back=None) -> None:
        from .ui.rules_screen import RulesScreen

        screen = RulesScreen(
            self, self.palette, client, quick=True, on_back=back,
            on_done=lambda: self.show_wifi_ap(
                client, state, back=lambda: self.show_rules(client, state, back=back)))
        self._swap(screen)

    def show_wifi_ap(self, client, state, back=None) -> None:
        from .ui.wifi_ap_screen import WifiApScreen

        screen = WifiApScreen(
            self, self.palette, client, on_back=back,
            on_done=lambda: self.show_verify(
                client, state, back=lambda: self.show_wifi_ap(client, state, back=back)))
        self._swap(screen)

    def show_verify(self, client, state, back=None) -> None:
        from .ui.verify_screen import VerifyScreen

        screen = VerifyScreen(
            self, self.palette, client, on_back=back,
            on_done=lambda: self.show_finalize(
                client, state, back=lambda: self.show_verify(client, state, back=back)))
        self._swap(screen)

    def show_finalize(self, client, state, back=None) -> None:
        from .ui.finalize_screen import FinalizeScreen

        screen = FinalizeScreen(self, self.palette, client, on_back=back,
                                on_done=lambda: self.show_settings(client, state))
        self._swap(screen)

    def show_settings(self, client: RouterClient, state: RouterState) -> None:
        from .ui.settings_shell import SettingsShell

        shell = SettingsShell(self, self.palette, client, state, on_exit=self.show_mode_picker)
        self._swap(shell)


def run() -> None:
    App().mainloop()
