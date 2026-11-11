"""Audio Extractor - icone vettoriali (stile Lucide) che si ricolorano col tema + icona dell'app."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QIconEngine, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from theme import P

ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><defs>
<linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#6366f1"/>
<stop offset="1" stop-color="#a855f7"/></linearGradient></defs>
<rect x="2" y="2" width="60" height="60" rx="15" fill="url(#g)"/>
<g stroke="#fff" stroke-width="4.5" stroke-linecap="round">
<line x1="15" y1="27" x2="15" y2="37"/><line x1="23.5" y1="19" x2="23.5" y2="45"/>
<line x1="32" y1="23" x2="32" y2="41"/><line x1="40.5" y1="14" x2="40.5" y2="50"/>
<line x1="49" y1="25" x2="49" y2="39"/></g></svg>"""

PATHS = {
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "folder": '<path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/>',
    "folder-plus": '<path d="M12 10v6M9 13h6"/><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    "file": '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/>',
    "image": '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.09-3.09a2 2 0 0 0-2.82 0L6 21"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    "alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4M12 17h.01"/>',
    "music": '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
    "x": '<path d="M18 6 6 18M6 6l12 12"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "circle-check": '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2m-7.07-2.93 1.41-1.41m11.32-11.32 1.41-1.41M2 12h2m16 0h2M4.93 4.93l1.41 1.41m11.32 11.32 1.41 1.41"/>',
    "moon": '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
    "monitor": '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
    "scale": '<path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1ZM2 16l3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1ZM7 21h10M12 3v18M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2"/>',
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5a5.5 5.5 0 0 1-5.5 5.5H11"/>',
    "copy": '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    "chevron-right": '<path d="m9 18 6-6-6-6"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "clapperboard": '<path d="M20.2 6 3 11l-.9-2.4c-.3-1.1.3-2.2 1.3-2.5l13.5-4c1.1-.3 2.2.3 2.5 1.3Z"/><path d="m6.2 5.3 3.1 3.9M12.4 3.4l3.1 4M3 11h18v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/>',
    "audio": '<path d="M2 10v3M6 6v11M10 3v18M14 8v7M18 5v13M22 10v3"/>',
}


def resolve(color):
    """Ruolo del tema ('text2', 'muted', ...) oppure colore '#rrggbb'."""
    if isinstance(color, str) and not color.startswith("#") and hasattr(P, color):
        return getattr(P, color)
    return color


def svg(name, color="text2", width=2.0):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{resolve(color)}" '
            f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round">{PATHS[name]}</svg>')


_renderers: dict = {}   # cache dei renderer SVG per (icona, colore, spessore)


class _ThemedEngine(QIconEngine):
    """Icona che si ricolora al cambio di tema (il colore e' risolto a ogni disegno)."""

    def __init__(self, name, color, width):
        super().__init__()
        self.name, self.color, self.width = name, color, width

    def _renderer(self, mode):
        col = "dim" if mode == QIcon.Disabled and not str(self.color).startswith("#") else self.color
        key = (self.name, resolve(col), self.width)
        r = _renderers.get(key)
        if r is None:
            r = _renderers[key] = QSvgRenderer(QByteArray(svg(self.name, col, self.width).encode()))
        return r

    def paint(self, painter, rect, mode, state):
        self._renderer(mode).render(painter, QRectF(rect))

    def pixmap(self, size, mode, state):
        pm = QPixmap(size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        self._renderer(mode).render(p, QRectF(0, 0, size.width(), size.height()))
        p.end()
        return pm

    def clone(self):
        return _ThemedEngine(self.name, self.color, self.width)


def icon(name, color="text2", width=2.0):
    return QIcon(_ThemedEngine(name, color, width))


def svg_pixmap(markup: str, w: int, h: int | None = None, dpr: float = 2.0) -> QPixmap:
    h = h or w
    img = QImage(int(w * dpr), int(h * dpr), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    QSvgRenderer(QByteArray(markup.encode())).render(p)
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm


def app_icon() -> QIcon:
    ic = QIcon()
    for sz in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(svg_pixmap(ICON_SVG, sz, dpr=1.0))
    return ic
