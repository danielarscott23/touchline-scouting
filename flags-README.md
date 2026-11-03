# Nationality flags

The embedded WOFF2 subsets in `flags-font.css` come from Google's Noto Color Emoji font, served by Google Fonts. They cover regional flags and the England, Scotland and Wales subdivision sequences. The font is registered as a Unicode-range supplement to Source Sans, so Windows browsers can display flags without relying on the operating system's flag support. No runtime font download is required.

Font project: https://github.com/googlefonts/noto-emoji

Licence: `flags-font-LICENSE.txt` (SIL Open Font License 1.1).

`scouting/nationalities.py` maps explicit exported nationality suffixes to flag sequences. Unrecognised suffixes remain visible; names never determine nationality. Northern Irish uses the United Kingdom flag, as Unicode has no separate Northern Ireland flag.
