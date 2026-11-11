"""Audio Extractor - design token e temi (scuro / chiaro).

Colori, raggi, spaziature e durate vivono qui. Gli altri moduli leggono sempre `P.<nome>` al momento
del disegno, quindi il cambio di tema e' immediato: `apply("dark" | "light" | "system")` aggiorna `P`.
"""
from __future__ import annotations

import ctypes
import os
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette

# --------------------------------------------------------------------------- #
# Token non cromatici
# --------------------------------------------------------------------------- #
R_XS, R_SM, R_MD, R_LG, R_XL = 5, 6, 8, 10, 14           # raggi (px)
SP_1, SP_2, SP_3, SP_4, SP_5, SP_6 = 4, 8, 12, 16, 20, 24  # spaziature (griglia da 4 px)
DUR_FAST, DUR_BASE, DUR_SLOW = 120, 220, 320            # animazioni (ms)
FONT_FAMILY = "'Segoe UI Variable Text', 'Segoe UI', sans-serif"
FS_BASE, FS_SMALL, FS_H2, FS_H1 = 10, 9, 10.5, 16        # corpi in pt

THEMES = ("system", "dark", "light")
THEME_LABELS = {"system": "Come il sistema", "dark": "Scuro", "light": "Chiaro"}

# --------------------------------------------------------------------------- #
# Palette
# --------------------------------------------------------------------------- #
DARK = dict(
    dark=True,
    bg="#0e1015", surf="#14171f", surf2="#1a1d26", surf3="#242937", field="#1c2029", bar="#171a23",
    border="#2b303e", border_hover="#6b738a", border_strong="#8a92a8",
    text="#e7e9ee", text2="#b4b9c8", muted="#9198aa", dim="#6e768b",
    accent="#6366f1", accent2="#a855f7", focus="#a5b4fc", control="#7a8396",
    btn1="#4f46e5", btn2="#7c3aed", btn_hi1="#5b52f0", btn_hi2="#8546f2", on_accent="#ffffff",
    accent_text="#a5b4fc", info_text="#c7cbff",
    ok="#4ade80", err="#f87171", warn="#f5b452",
    ok_bg="rgba(74,222,128,0.12)", err_bg="rgba(248,113,113,0.12)", warn_bg="rgba(245,180,82,0.12)",
    warn_bd="rgba(245,180,82,0.30)",
    accent_soft="rgba(99,102,241,0.18)", accent_soft_hi="rgba(99,102,241,0.28)",
    accent_bd="rgba(99,102,241,0.55)", shared_bg="rgba(99,102,241,0.10)", shared_bd="rgba(99,102,241,0.40)",
    danger_bg="rgba(248,113,113,0.12)", danger_bd="rgba(248,113,113,0.45)", danger_text="#fca5a5",
    danger_hover="rgba(248,113,113,0.22)",
    card="#151821", card_bd="#222735", card_hover="#191c27", card_hover_bd="#313748",
    card_sel="#1b1e30", card_sel_bd="#6366f1", sel="#34378f",
    scroll="#363c4e", scroll_hover="#4d556b", groove="#2b303e", slider_off="#3a3f50",
    handle_hover="#e0e1ff", handle_off="#555b6c",
    preview_bg="#0b0d12", preview_bd="#232733", crop_shade="rgba(8,9,13,185)",
    pill_bg="rgba(0,0,0,170)", pill_text="#ffffff", crop_edge="rgba(255,255,255,225)",
    drop_bg="#12141b", drop_bd="#69718a", drop_drag_bg="rgba(99,102,241,0.09)", drop_icon="#8b91f8",
    toast_bg="#242937", toast_bd="#6b738a",
    titlebar=0x0015100E, titletext=0x00EEE9E7,
)

LIGHT = dict(
    dark=False,
    bg="#f4f5f9", surf="#ffffff", surf2="#f1f3f8", surf3="#e5e8f0", field="#ffffff", bar="#fafbfd",
    border="#d8dce6", border_hover="#8790a5", border_strong="#6b7489",
    text="#1a1f2e", text2="#3d4558", muted="#566077", dim="#7a8296",
    accent="#4f46e5", accent2="#7c3aed", focus="#3730a3", control="#6f788c",
    btn1="#4f46e5", btn2="#7c3aed", btn_hi1="#5b52f0", btn_hi2="#8546f2", on_accent="#ffffff",
    accent_text="#4338ca", info_text="#4338ca",
    ok="#0a7650", err="#c8203f", warn="#98590a",
    ok_bg="rgba(11,127,85,0.11)", err_bg="rgba(200,32,63,0.09)", warn_bg="rgba(184,110,0,0.12)",
    warn_bd="rgba(184,110,0,0.35)",
    accent_soft="rgba(79,70,229,0.12)", accent_soft_hi="rgba(79,70,229,0.20)",
    accent_bd="rgba(79,70,229,0.55)", shared_bg="rgba(79,70,229,0.07)", shared_bd="rgba(79,70,229,0.30)",
    danger_bg="rgba(200,32,63,0.08)", danger_bd="rgba(200,32,63,0.45)", danger_text="#a91833",
    danger_hover="rgba(200,32,63,0.16)",
    card="#ffffff", card_bd="#dfe3ec", card_hover="#f8f9fc", card_hover_bd="#c3cada",
    card_sel="#eceafd", card_sel_bd="#4f46e5", sel="#e0defc",
    scroll="#c1c7d4", scroll_hover="#a1a9ba", groove="#d3d8e3", slider_off="#c3c9d6",
    handle_hover="#f1ecff", handle_off="#aab2c4",
    preview_bg="#e6e9f0", preview_bd="#d8dce6", crop_shade="rgba(8,9,13,170)",
    pill_bg="rgba(0,0,0,170)", pill_text="#ffffff", crop_edge="rgba(255,255,255,235)",
    drop_bg="#fafbfd", drop_bd="#8790a5", drop_drag_bg="rgba(79,70,229,0.07)", drop_icon="#5558e6",
    toast_bg="#ffffff", toast_bd="#8790a5",
    titlebar=0x00F9F5F4, titletext=0x002E1F1A,
)

# Palette corrente (aggiornata sul posto da apply())
P = SimpleNamespace(name="dark", **DARK)


def system_is_dark() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() != Qt.ColorScheme.Light
    except Exception:  # noqa: BLE001
        return True


def resolve(pref: str) -> str:
    if pref not in ("dark", "light"):
        return "dark" if system_is_dark() else "light"
    return pref


def apply(pref: str) -> str:
    """Imposta la palette corrente. Ritorna il nome effettivo ('dark' | 'light')."""
    name = resolve(pref)
    for k, v in (DARK if name == "dark" else LIGHT).items():
        setattr(P, k, v)
    P.name = name
    return name


def qcolor(spec) -> QColor:
    """QColor da '#rrggbb' oppure 'rgba(r,g,b,a)' (a 0-1 oppure 0-255)."""
    if isinstance(spec, QColor):
        return QColor(spec)
    s = str(spec)
    if s.startswith("rgba"):
        r, g, b, a = [x.strip() for x in s[s.index("(") + 1:s.index(")")].split(",")]
        af = float(a)
        return QColor(int(r), int(g), int(b), int(round(af * 255)) if af <= 1 else int(af))
    return QColor(s)


def app_palette() -> QPalette:
    pal = QPalette()
    for role, key in ((QPalette.Window, "bg"), (QPalette.Base, "field"), (QPalette.AlternateBase, "surf2"),
                      (QPalette.Button, "field"), (QPalette.ToolTipBase, "field"), (QPalette.WindowText, "text"),
                      (QPalette.Text, "text"), (QPalette.ButtonText, "text"), (QPalette.ToolTipText, "text"),
                      (QPalette.Highlight, "accent"), (QPalette.HighlightedText, "on_accent"),
                      (QPalette.PlaceholderText, "dim"), (QPalette.Link, "accent_text")):
        pal.setColor(role, qcolor(getattr(P, key)))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, qcolor(P.dim))
    return pal


def titlebar(widget):
    """Barra del titolo di Windows allineata al tema."""
    if os.name != "nt":
        return
    try:
        hwnd = int(widget.winId())
        dwm = ctypes.windll.dwmapi
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(ctypes.c_int(1 if P.dark else 0)), 4)
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(ctypes.c_int(P.titlebar)), 4)   # Win11: colore barra
        dwm.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(ctypes.c_int(P.titletext)), 4)  # Win11: colore testo
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------- #
# Foglio di stile (generato dai token)
# --------------------------------------------------------------------------- #
def stylesheet(asset_dir: str) -> str:
    return f"""
* {{ font-family: {FONT_FAMILY}; font-size: {FS_BASE}pt; color: {P.text}; outline: none; }}
QMainWindow, QDialog, #leftPane {{ background: {P.bg}; }}
QMessageBox {{ background: {P.bg}; }}
#sidebar {{ background: {P.surf}; border-left: 1px solid {P.border}; }}
#sideInner, QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
#actionBar {{ background: {P.bar}; border-top: 1px solid {P.border}; border-left: 1px solid {P.border}; }}
#sharedBox {{ background: {P.shared_bg}; border: 1px solid {P.shared_bd}; border-radius: {R_MD}px; }}
#sharedText {{ color: {P.info_text}; font-size: {FS_SMALL}pt; }}

#appTitle {{ font-size: {FS_H1}pt; font-weight: 700; }}
#appSub {{ color: {P.muted}; }}
#h1 {{ font-size: 13pt; font-weight: 700; }}
QPushButton#sectionHead {{ background: transparent; border: 2px solid transparent; border-radius: {R_SM}px;
    text-align: left; padding: 2px 4px; color: {P.muted}; font-size: 8.5pt; font-weight: 700; }}
QPushButton#sectionHead:hover {{ color: {P.text}; background: transparent; }}
QPushButton#sectionHead:focus {{ border: 2px solid {P.focus}; padding: 2px 4px; }}
#sectionTitle {{ color: {P.muted}; font-size: 8.5pt; font-weight: 700; letter-spacing: 1.3px; }}
#fieldLabel {{ color: {P.text2}; font-size: {FS_SMALL}pt; }}
#hint {{ color: {P.muted}; font-size: {FS_SMALL}pt; }}
#muted {{ color: {P.muted}; }}
#small {{ color: {P.muted}; font-size: {FS_SMALL}pt; }}
#warn {{ color: {P.warn}; background: {P.warn_bg}; border: 1px solid {P.warn_bd}; border-radius: {R_MD}px;
         padding: 8px 10px; font-size: {FS_SMALL}pt; }}
#warnText {{ color: {P.warn}; font-size: {FS_SMALL}pt; }}
#countLabel {{ color: {P.muted}; font-size: {FS_SMALL}pt; }}
#summary {{ color: {P.text2}; font-size: {FS_SMALL}pt; }}
#estimate {{ color: {P.accent_text}; font-weight: 700; }}
#statusText {{ color: {P.muted}; font-size: {FS_SMALL}pt; }}
#divider {{ background: {P.border}; min-height: 1px; max-height: 1px; border: none; }}
QFrame#sep {{ background: {P.border}; min-height: 1px; max-height: 1px; border: none; }}

QComboBox, QLineEdit {{ background: {P.field}; border: 1px solid {P.border_hover}; border-radius: {R_MD}px;
    padding: 6px 10px; min-height: 20px; selection-background-color: {P.accent}; selection-color: {P.on_accent}; }}
QComboBox:hover, QLineEdit:hover {{ border-color: {P.border_strong}; }}
QComboBox:focus, QLineEdit:focus {{ border: 2px solid {P.focus}; padding: 5px 9px; }}
QComboBox:disabled, QLineEdit:disabled {{ color: {P.dim}; background: {P.surf}; border-color: {P.border}; }}
QComboBox {{ combobox-popup: 0; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url({asset_dir}/chev-{P.name}.svg); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {P.field}; border: 1px solid {P.border_hover}; padding: 4px; outline: 0;
    selection-background-color: {P.sel}; selection-color: {P.text}; }}
QComboBox QAbstractItemView::item {{ min-height: 26px; padding: 0 6px; }}
QTextBrowser, QPlainTextEdit {{ background: {P.field}; border: 1px solid {P.border_hover}; border-radius: {R_MD}px;
    padding: 6px; selection-background-color: {P.accent}; selection-color: {P.on_accent}; }}
QTextBrowser:focus, QPlainTextEdit:focus {{ border: 2px solid {P.focus}; padding: 5px; }}

QPushButton {{ background: {P.field}; border: 1px solid {P.border_hover}; border-radius: {R_MD}px; padding: 7px 14px;
    color: {P.text}; }}
QPushButton:hover {{ background: {P.surf3}; border-color: {P.border_strong}; }}
QPushButton:pressed {{ background: {P.surf2}; }}
QPushButton:focus {{ border: 2px solid {P.focus}; padding: 6px 13px; }}
QPushButton:disabled {{ color: {P.dim}; background: {P.surf}; border-color: {P.border}; }}
QPushButton#ghost {{ background: transparent; border-color: transparent; color: {P.text2}; }}
QPushButton#ghost:hover {{ background: {P.surf3}; border-color: transparent; color: {P.text}; }}
QPushButton#ghost:focus {{ border: 2px solid {P.focus}; }}
QPushButton#ghost:disabled {{ color: {P.dim}; background: transparent; }}
QPushButton#accentSoft {{ background: {P.accent_soft}; border: 1px solid {P.accent_bd}; color: {P.accent_text};
    font-weight: 600; }}
QPushButton#accentSoft:hover {{ background: {P.accent_soft_hi}; }}
QPushButton#accentSoft:focus {{ border: 2px solid {P.focus}; }}
QPushButton#accentSoft:disabled {{ background: {P.surf}; color: {P.dim}; border-color: {P.border}; }}
QPushButton#primary {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {P.btn1}, stop:1 {P.btn2});
    border: 2px solid transparent; border-radius: {R_LG}px; color: {P.on_accent}; font-weight: 700;
    font-size: 10.5pt; padding: 9px 20px; }}
QPushButton#primary:hover {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {P.btn_hi1}, stop:1 {P.btn_hi2}); }}
QPushButton#primary:focus {{ border: 2px solid {P.focus}; padding: 9px 20px; }}
QPushButton#primary:disabled {{ background: {P.surf3}; color: {P.dim}; border: 2px solid transparent; }}
QPushButton#danger {{ background: {P.danger_bg}; border: 2px solid {P.danger_bd}; border-radius: {R_LG}px;
    color: {P.danger_text}; font-weight: 700; font-size: 10.5pt; padding: 9px 20px; }}
QPushButton#danger:hover {{ background: {P.danger_hover}; }}
QPushButton#danger:focus {{ border: 2px solid {P.focus}; }}

QPushButton#seg {{ background: {P.field}; border: 1px solid {P.border_hover}; border-radius: 0; padding: 6px 10px;
    color: {P.text2}; }}
QPushButton#seg[pos="first"] {{ border-top-left-radius: {R_MD}px; border-bottom-left-radius: {R_MD}px; }}
QPushButton#seg[pos="last"] {{ border-top-right-radius: {R_MD}px; border-bottom-right-radius: {R_MD}px; }}
QPushButton#seg[pos="only"] {{ border-radius: {R_MD}px; }}
QPushButton#seg:hover {{ color: {P.text}; background: {P.surf3}; }}
QPushButton#seg:checked {{ background: {P.accent_soft}; border: 1px solid {P.accent}; color: {P.text}; font-weight: 600; }}
QPushButton#seg:focus {{ border: 2px solid {P.focus}; padding: 5px 9px; }}
QPushButton#seg:disabled {{ color: {P.dim}; background: {P.surf}; border-color: {P.border}; }}

QPushButton#rowRemove {{ background: transparent; border: 1px solid transparent; padding: 5px; border-radius: {R_SM}px; }}
QPushButton#rowRemove:hover {{ background: {P.danger_bg}; }}
QPushButton#rowRemove:disabled {{ background: transparent; }}
QPushButton#rowDetail {{ background: transparent; border: 1px solid transparent; color: {P.accent_text};
    padding: 2px 6px; font-size: 8.5pt; border-radius: {R_XS}px; text-decoration: underline; }}
QPushButton#rowDetail:hover {{ background: {P.surf3}; }}
QPushButton#rowDetail:focus {{ border: 2px solid {P.focus}; padding: 1px 5px; }}

QListWidget#queue {{ background: transparent; border: 2px solid transparent; border-radius: {R_XL}px; }}
QListWidget#queue:focus {{ border: 2px solid {P.focus}; }}
QListWidget#queue::item {{ background: {P.card}; border: 1px solid {P.card_bd}; border-radius: 12px; }}
QListWidget#queue::item:hover {{ background: {P.card_hover}; border-color: {P.card_hover_bd}; }}
QListWidget#queue::item:selected {{ background: {P.card_sel}; border: 1px solid {P.card_sel_bd}; }}
QListWidget#queue[drag="true"] {{ background: {P.drop_drag_bg}; border: 2px dashed {P.accent}; }}
#row {{ background: transparent; }}
#rowTitle {{ font-weight: 600; font-size: 10.5pt; }}
#rowMeta {{ color: {P.muted}; font-size: {FS_SMALL}pt; }}
#rowTrack {{ color: {P.text2}; font-size: {FS_SMALL}pt; }}
QComboBox#rowCombo {{ padding: 3px 8px; font-size: {FS_SMALL}pt; min-height: 18px; border-radius: {R_SM}px; }}
QComboBox#rowCombo:focus {{ padding: 2px 7px; }}

#badge {{ border-radius: 10px; background: {P.surf3}; }}
#badge QLabel {{ font-size: 8.5pt; font-weight: 600; color: {P.text2}; background: transparent; }}
#badge[state="run"] {{ background: {P.accent_soft}; }}
#badge[state="run"] QLabel {{ color: {P.accent_text}; }}
#badge[state="ok"] {{ background: {P.ok_bg}; }}
#badge[state="ok"] QLabel {{ color: {P.ok}; }}
#badge[state="err"] {{ background: {P.err_bg}; }}
#badge[state="err"] QLabel {{ color: {P.err}; }}
#badge[state="warn"] {{ background: {P.warn_bg}; }}
#badge[state="warn"] QLabel {{ color: {P.warn}; }}

#dropZone {{ border: 2px dashed {P.drop_bd}; border-radius: 18px; background: {P.drop_bg}; }}
#dropZone[drag="true"] {{ border-color: {P.accent}; background: {P.drop_drag_bg}; }}
#dropZone QLabel {{ background: transparent; border: none; }}
#dropTitle {{ font-size: 14pt; font-weight: 700; }}
#dropSub {{ color: {P.muted}; }}

QProgressBar {{ background: {P.surf3}; border: none; border-radius: 3px; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {P.accent}, stop:1 {P.accent2}); border-radius: 3px; }}
QProgressBar#mini {{ min-height: 4px; max-height: 4px; border-radius: 2px; }}
QProgressBar#mini::chunk {{ border-radius: 2px; }}
QProgressBar#overall {{ min-height: 6px; max-height: 6px; }}

QSlider::groove:horizontal {{ height: 4px; background: {P.groove}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {P.accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: #ffffff; border: 2px solid {P.accent}; width: 12px; height: 12px;
    margin: -6px 0; border-radius: 8px; }}
QSlider::handle:horizontal:hover {{ background: {P.handle_hover}; }}
QSlider::handle:horizontal:focus {{ background: {P.accent}; border-color: {P.focus}; }}
QSlider::sub-page:horizontal:disabled {{ background: {P.slider_off}; }}
QSlider::handle:horizontal:disabled {{ background: {P.handle_off}; border-color: {P.handle_off}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {P.scroll}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {P.scroll_hover}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ height: 0px; }}
QToolTip {{ background: {P.field}; color: {P.text}; border: 1px solid {P.border_hover}; padding: 6px 8px; }}
QMenu {{ background: {P.field}; border: 1px solid {P.border_hover}; padding: 5px; }}
QMenu::item {{ padding: 7px 26px 7px 10px; border-radius: {R_XS}px; }}
QMenu::item:selected {{ background: {P.sel}; }}
QMenu::item:disabled {{ color: {P.dim}; }}
QMenu::icon {{ padding-left: 8px; }}
QLabel#toast {{ background: {P.toast_bg}; border: 1px solid {P.toast_bd}; border-radius: {R_LG}px;
                padding: 10px 16px; color: {P.text}; }}
"""


apply("dark")
