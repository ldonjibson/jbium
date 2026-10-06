"""
Verified font download URLs + platform requirements.

Single source of truth shared with the repo tree's
fonts/download_fonts.py (which imports this module when running from
a checkout, falling back to its own copy under pip installs that
vendored the file). Every URL was verified live (HTTP 200 + sfnt
magic bytes) before being written — this table's original entries
were mostly 404, which is why the font bundles shipped manifest-only
and the runtime font defense was dead on every box that ran it.

Variable-font files on google/fonts carry bracket axes in their
names (NotoSans[wdth,wght].ttf) — the brackets stay URL-encoded
(%5B/%5D) in these paths or the request 404s.
"""

GF = "https://github.com/google/fonts/raw/main"

URLS = {
    # ── Liberation Fonts (Arial/Times/Courier compatible) ──
    # The release's asset list is empty; the tarball lives in the
    # release's file attachments instead.
    "liberation": {
        "url": "https://github.com/liberationfonts/liberation-fonts/files/7261482/liberation-fonts-ttf-2.1.5.tar.gz",
        "type": "tar.gz",
        "extract_patterns": {
            "LiberationSans-Regular.ttf": "LiberationSans-Regular.ttf",
            "LiberationSans-Bold.ttf": "LiberationSans-Bold.ttf",
            "LiberationSans-Italic.ttf": "LiberationSans-Italic.ttf",
            "LiberationSans-BoldItalic.ttf": "LiberationSans-BoldItalic.ttf",
            "LiberationSerif-Regular.ttf": "LiberationSerif-Regular.ttf",
            "LiberationSerif-Bold.ttf": "LiberationSerif-Bold.ttf",
            "LiberationMono-Regular.ttf": "LiberationMono-Regular.ttf",
            "LiberationMono-Bold.ttf": "LiberationMono-Bold.ttf",
        }
    },

    # ── Carlito (Calibri-compatible) ──
    "carlito": {
        "base_url": GF + "/ofl/carlito",
        "type": "direct",
        "files": {
            "Carlito-Regular.ttf": "Carlito-Regular.ttf",
            "Carlito-Bold.ttf": "Carlito-Bold.ttf",
            "Carlito-Italic.ttf": "Carlito-Italic.ttf",
            "Carlito-BoldItalic.ttf": "Carlito-BoldItalic.ttf",
        }
    },

    # ── Caladea (Cambria-compatible) ──
    "caladea": {
        "base_url": GF + "/ofl/caladea",
        "type": "direct",
        "files": {
            "Caladea-Regular.ttf": "Caladea-Regular.ttf",
            "Caladea-Bold.ttf": "Caladea-Bold.ttf",
        }
    },

    # ── Noto Sans (base) — variable fonts on google/fonts ──
    "noto_sans": {
        "base_url": GF + "/ofl/notosans",
        "type": "direct",
        "files": {
            "NotoSans-Regular.ttf": "NotoSans%5Bwdth,wght%5D.ttf",
            "NotoSans-Italic.ttf": "NotoSans-Italic%5Bwdth,wght%5D.ttf",
        }
    },

    # ── Noto Serif ──
    "noto_serif": {
        "base_url": GF + "/ofl/notoserif",
        "type": "direct",
        "files": {
            "NotoSerif-Regular.ttf": "NotoSerif%5Bwdth,wght%5D.ttf",
            "NotoSerif-Italic.ttf": "NotoSerif-Italic%5Bwdth,wght%5D.ttf",
        }
    },

    # ── Noto Sans Mono — archived NotoMono is gone; the maintained
    #    family on google/fonts is NotoSansMono (variable) ──
    "noto_mono": {
        "base_url": GF + "/ofl/notosansmono",
        "type": "direct",
        "files": {
            "NotoMono-Regular.ttf": "NotoSansMono%5Bwdth,wght%5D.ttf",
        }
    },

    # ── Noto Sans JP (Japanese) ──
    "noto_sans_jp": {
        "base_url": GF + "/ofl/notosansjp",
        "type": "direct",
        "files": {
            "NotoSansJP-Regular.ttf": "NotoSansJP%5Bwght%5D.ttf",
        }
    },

    # ── Noto Sans KR (Korean) ──
    "noto_sans_kr": {
        "base_url": GF + "/ofl/notosanskr",
        "type": "direct",
        "files": {
            "NotoSansKR-Regular.ttf": "NotoSansKR%5Bwght%5D.ttf",
        }
    },

    # ── Noto Sans SC (Simplified Chinese) ──
    "noto_sans_sc": {
        "base_url": GF + "/ofl/notosanssc",
        "type": "direct",
        "files": {
            "NotoSansSC-Regular.ttf": "NotoSansSC%5Bwght%5D.ttf",
        }
    },

    # ── Noto Sans TC (Traditional Chinese) ──
    "noto_sans_tc": {
        "base_url": GF + "/ofl/notosanstc",
        "type": "direct",
        "files": {
            "NotoSansTC-Regular.ttf": "NotoSansTC%5Bwght%5D.ttf",
        }
    },

    # ── Noto Sans Arabic ──
    "noto_sans_arabic": {
        "base_url": GF + "/ofl/notosansarabic",
        "type": "direct",
        "files": {
            "NotoSansArabic-Regular.ttf": "NotoSansArabic%5Bwdth,wght%5D.ttf",
        }
    },

    # ── DejaVu (classic Linux) — real release assets ──
    "dejavu": {
        "url": "https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/dejavu-fonts-ttf-2.37.tar.bz2",
        "type": "tar.bz2",
        "extract_patterns": {
            "DejaVuSans.ttf": "DejaVuSans.ttf",
            "DejaVuSans-Bold.ttf": "DejaVuSans-Bold.ttf",
            "DejaVuSansMono.ttf": "DejaVuSansMono.ttf",
            "DejaVuSansMono-Bold.ttf": "DejaVuSansMono-Bold.ttf",
            "DejaVuSerif.ttf": "DejaVuSerif.ttf",
            "DejaVuSerif-Bold.ttf": "DejaVuSerif-Bold.ttf",
        }
    },

    # ── Ubuntu Font (UFL license dir on google/fonts) ──
    "ubuntu_font": {
        "base_url": GF + "/ufl/ubuntu",
        "type": "direct",
        "files": {
            "Ubuntu-Regular.ttf": "Ubuntu-Regular.ttf",
            "Ubuntu-Bold.ttf": "Ubuntu-Bold.ttf",
            "UbuntuMono-Regular.ttf": "../ubuntumono/UbuntuMono-Regular.ttf",
        }
    },

    # ── Gelasio (Georgia-compatible) ──
    "gelasio": {
        "base_url": GF + "/ofl/gelasio",
        "type": "direct",
        "files": {
            "Gelasio-Regular.ttf": "Gelasio%5Bwght%5D.ttf",
            "Gelasio-Bold.ttf": "Gelasio%5Bwght%5D.ttf",
        }
    },

    # ── EB Garamond ──
    "eb_garamond": {
        "base_url": GF + "/ofl/ebgaramond",
        "type": "direct",
        "files": {
            "EBGaramond-Regular.ttf": "EBGaramond%5Bwght%5D.ttf",
        }
    },
}

# ═════════════════════════════════════════════
# Platform Requirements
# ═════════════════════════════════════════════

PLATFORM_FONTS = {
    "windows": [
        "liberation",
        "carlito",
        "caladea",
        "noto_sans",
        "noto_serif",
        "noto_mono",
        "noto_sans_jp",
        "noto_sans_kr",
        "noto_sans_sc",
        "noto_sans_tc",
        "noto_sans_arabic",
        "dejavu",
        "gelasio",
    ],
    "macos": [
        "noto_sans",
        "noto_serif",
        "noto_mono",
        "liberation",
        "dejavu",
        "noto_sans_jp",
        "noto_sans_kr",
        "noto_sans_sc",
        "noto_sans_tc",
        "eb_garamond",
        "gelasio",
    ],
    "linux": [
        "noto_sans",
        "noto_serif",
        "noto_mono",
        "dejavu",
        "liberation",
        "ubuntu_font",
        "noto_sans_jp",
        "noto_sans_kr",
        "noto_sans_sc",
        "noto_sans_arabic",
    ],
}