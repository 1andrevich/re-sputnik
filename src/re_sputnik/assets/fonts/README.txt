Bundled UI fonts — under the SIL Open Font License 1.1. The full license texts
live in ../../../../THIRD_PARTY_LICENSES/ (JetBrainsMono-OFL-1.1.txt,
Vazirmatn-OFL-1.1.txt); the fonts are also summarized in the top-level NOTICE
(section 2).

  JetBrainsMono-{Regular,Medium,Bold}.ttf       monospace (IP/key/log text)
  Vazirmatn-{Regular,Medium,SemiBold,Bold}.ttf  Persian/Arabic UI (fa locale)

The Latin/Cyrillic UI uses Roboto (customtkinter's built-in font) — Inter is NOT
bundled. To opt back into Inter, drop Inter-{Regular,Medium,SemiBold,Bold}.ttf
here and theme._resolve_family() will pick it up. theme.py falls back gracefully
if a bundled font is missing (JetBrains Mono -> a system monospace).
