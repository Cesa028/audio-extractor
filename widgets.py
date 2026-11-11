"""Audio Extractor - widget riutilizzabili. Tutto cio' che e' disegnato a mano legge la palette
corrente `P` al momento del paint, quindi segue il cambio di tema dal vivo."""
from __future__ import annotations

import re

from PySide6.QtCore import QPropertyAnimation, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton, QButtonGroup, QComboBox, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLayout,
    QLineEdit, QProgressBar, QPushButton, QSizePolicy, QSlider, QVBoxLayout, QWidget,
)

import icons
from common import THUMB_H, THUMB_W, fmt_time
from engine import MAX_ZOOM, Format, Job, crop_rect
from theme import DUR_BASE, P, qcolor


def repolish(w: QWidget):
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def label(text, obj=None, wrap=False) -> QLabel:
    lab = QLabel(text)
    if obj:
        lab.setObjectName(obj)
    lab.setWordWrap(wrap)
    return lab


def sep() -> QFrame:
    f = QFrame()
    f.setObjectName("sep")
    return f


def a11y_pass(root: QWidget):
    """Rifinitura di accessibilita' su un'intera finestra: i pulsanti prendono il focus solo da tastiera,
    quelli con la sola icona usano il suggerimento come nome accessibile e i campi prendono il nome
    dall'etichetta che li precede."""
    for b in root.findChildren(QPushButton):
        if b.focusPolicy() != Qt.NoFocus:
            b.setFocusPolicy(Qt.TabFocus)
        if not b.text().strip() and not b.accessibleName():
            tip = b.toolTip().split("  (")[0].strip()
            if tip:
                b.setAccessibleName(tip)
    layouts = ([root.layout()] if root.layout() else []) + root.findChildren(QLayout)
    for lay in layouts:
        last = ""
        for i in range(lay.count()):
            w = lay.itemAt(i).widget()
            if isinstance(w, QLabel):
                txt = re.sub(r"<[^>]+>", "", w.text()).strip()
                if txt:
                    last = txt
            elif isinstance(w, (QComboBox, QSlider, QLineEdit)) and not w.accessibleName():
                name = last or w.toolTip()
                if name:
                    w.setAccessibleName(name)


def paint_focus_ring(p: QPainter, rect: QRectF, radius: float):
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(qcolor(P.focus), 2))
    p.drawRoundedRect(rect, radius, radius)


def arrow_nav(btn: QAbstractButton, e) -> bool:
    """Frecce sinistra/destra/su/giu': sposta la selezione tra i pulsanti dello stesso gruppo esclusivo."""
    d = {Qt.Key_Left: -1, Qt.Key_Up: -1, Qt.Key_Right: 1, Qt.Key_Down: 1}.get(e.key())
    grp = btn.group()
    if d is None or grp is None:
        return False
    en = [b for b in grp.buttons() if b.isEnabled()]
    if btn not in en:
        return False
    nb = en[(en.index(btn) + d) % len(en)]
    nb.setFocus(Qt.TabFocusReason)
    nb.click()
    return True


class ElidedLabel(QLabel):
    def __init__(self, text="", mode=Qt.ElideMiddle, **kw):
        super().__init__(**kw)
        self._full, self._mode = text, mode
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(30)
        self._refresh()

    def setFullText(self, t: str):
        self._full = t
        self._refresh()

    def fullText(self) -> str:
        return self._full

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._refresh()

    def _refresh(self):
        QLabel.setText(self, self.fontMetrics().elidedText(self._full, self._mode, max(self.width(), 30)))


class IconLabel(QWidget):
    """Icona vettoriale che si ricolora col tema. Trasparente al mouse."""

    def __init__(self, name="check", role="text2", size=16, width=2.0, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._w = width
        self.set_icon(name, role)

    def set_icon(self, name, role=None):
        if role:
            self._role = role
        self._name = name
        self._ic = icons.icon(name, self._role, width=self._w)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._ic.paint(p, self.rect())


class Toggle(QAbstractButton):
    def __init__(self, checked=False, name=""):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setFixedSize(42, 26)
        if name:
            self.setAccessibleName(name)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on, en = self.isChecked(), self.isEnabled()
        track = qcolor(P.accent if on else P.control)
        if not en:
            track.setAlpha(90)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(2, 2, 38, 22), 11, 11)
        p.setBrush(qcolor("#ffffff" if en else P.dim))
        p.drawEllipse(QRectF(21 if on else 5, 5, 16, 16))
        if self.hasFocus():
            paint_focus_ring(p, QRectF(1, 1, 40, 24), 12)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            return self.click()
        super().keyPressEvent(e)


class FormatTile(QAbstractButton):
    def __init__(self, fmt: Format):
        super().__init__()
        self.fmt = fmt
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(54)
        self.setToolTip(fmt.note)
        self.setAccessibleName(f"{fmt.title}, {fmt.tag}")
        self.setAccessibleDescription(fmt.note)

    def sizeHint(self):
        return QSize(100, 54)

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)

    def keyPressEvent(self, e):
        if not arrow_nav(self, e):
            super().keyPressEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        on, en = self.isChecked(), self.isEnabled()
        if on:
            bg, border = qcolor(P.accent_soft), qcolor(P.accent)
        elif self.underMouse() and en:
            bg, border = qcolor(P.surf3), qcolor(P.border_strong)
        else:
            bg, border = qcolor(P.field), qcolor(P.border_hover)
        p.setPen(QPen(border, 1.6 if on else 1))
        p.setBrush(bg)
        p.drawRoundedRect(r, 10, 10)
        f = self.font()
        f.setPointSizeF(10.5)
        f.setBold(True)
        p.setFont(f)
        p.setPen(qcolor(P.text) if en else qcolor(P.dim))
        p.drawText(r.adjusted(12, 7, -6, -r.height() / 2), Qt.AlignLeft | Qt.AlignBottom, self.fmt.title)
        f.setPointSizeF(8)
        f.setBold(False)
        p.setFont(f)
        p.setPen(qcolor(P.accent_text if on else P.muted) if en else qcolor(P.dim))
        p.drawText(r.adjusted(12, r.height() / 2 + 2, -6, -6), Qt.AlignLeft | Qt.AlignTop, self.fmt.tag)
        if self.hasFocus():
            paint_focus_ring(p, QRectF(self.rect()).adjusted(1, 1, -1, -1), 10)


class SegButton(QPushButton):
    def keyPressEvent(self, e):
        if not arrow_nav(self, e):
            super().keyPressEvent(e)


class Segmented(QWidget):
    changed = Signal(int)

    def __init__(self, labels: list[str], name: str = ""):
        super().__init__()
        self.name = name
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(0)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.group.idClicked.connect(self.changed.emit)
        self.set_labels(labels)

    def set_labels(self, labels: list[str]):
        for b in self.group.buttons():
            self.group.removeButton(b)
            self.lay.removeWidget(b)
            b.hide()
            b.deleteLater()
        n = len(labels)
        for i, text in enumerate(labels):
            b = SegButton(text, objectName="seg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.TabFocus)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.setProperty("pos", "only" if n == 1 else "first" if i == 0 else "last" if i == n - 1 else "mid")
            if self.name:
                b.setAccessibleName(f"{self.name}: {text}")
            self.group.addButton(b, i)
            self.lay.addWidget(b)
        if n:
            self.group.button(0).setChecked(True)

    def index(self) -> int:
        return max(self.group.checkedId(), 0)

    def set_index(self, i: int):
        b = self.group.button(i)
        if b:
            b.setChecked(True)


class CoverPreview(QWidget):
    """Editor dell'inquadratura: la finestra di ritaglio resta ferma al centro e l'immagine
    si sposta sotto (trascina), si ingrandisce (rotella) e si ricentra (doppio clic)."""
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.setFixedHeight(210)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.TabFocus)
        self.setAccessibleName("Anteprima della copertina")
        self.setAccessibleDescription("Frecce per spostare l'inquadratura, più e meno per lo zoom, Home per centrare")
        self.pix: QPixmap | None = None
        self.job: Job | None = None
        self.square = True
        self.text = "Seleziona un video dalla coda"
        self.loading = False
        self.dragging = False
        self.hover = False
        self._last = None

    # ---------------------------------------------------------------- stato
    def set_job(self, job: Job | None):
        self.job = job
        self.update()

    def set_square(self, sq: bool):
        self.square = sq
        self.normalize()
        self.update()

    def set_image(self, pix: QPixmap | None, text: str = ""):
        self.pix, self.text, self.loading = pix, text, False
        self.update_cursor()
        self.update()

    def set_loading(self):
        self.loading = True
        self.update()

    def interactive(self) -> bool:
        return bool(self.isEnabled() and self.job and self.pix and not self.pix.isNull())

    def update_cursor(self):
        if self.interactive():
            self.setCursor(Qt.ClosedHandCursor if self.dragging else Qt.OpenHandCursor)
        else:
            self.unsetCursor()

    def normalize(self):
        j = self.job
        if j:
            j.zoom = min(max(j.zoom, 1.0), MAX_ZOOM)
            _, j.cx, j.cy = crop_rect(j.aspect, self.square, j.cx, j.cy, j.zoom)

    def reset(self):
        if self.job:
            self.job.cx = self.job.cy = 0.5
            self.job.zoom = 1.0
            self.update()
            self.changed.emit()

    # ---------------------------------------------------------------- geometria
    def geometry_info(self):
        """(viewport, rettangolo immagine sullo schermo, crop normalizzato)"""
        j = self.job
        inner = QRectF(self.rect()).adjusted(14, 14, -14, -14)
        a = 1.0 if self.square else j.aspect
        if inner.width() / inner.height() > a:
            vh = inner.height(); vw = vh * a
        else:
            vw = inner.width(); vh = vw / a
        vp = QRectF(inner.center().x() - vw / 2, inner.center().y() - vh / 2, vw, vh)
        (x, y, w, h), _, _ = crop_rect(j.aspect, self.square, j.cx, j.cy, j.zoom)
        img_w, img_h = vw / w, vh / h
        img = QRectF(vp.left() - x * img_w, vp.top() - y * img_h, img_w, img_h)
        return vp, img, (x, y, w, h)

    # ---------------------------------------------------------------- disegno
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        frame = QPainterPath()
        frame.addRoundedRect(r, 12, 12)
        p.setPen(QPen(qcolor(P.preview_bd), 1))
        p.setBrush(qcolor(P.preview_bg))
        p.drawPath(frame)
        if not (self.job and self.pix and not self.pix.isNull()):
            p.setPen(qcolor(P.muted))
            p.drawText(r.adjusted(20, 0, -20, 0), Qt.AlignCenter | Qt.TextWordWrap, self.text)
            self._paint_loading(p, r)
            return
        vp, img, _ = self.geometry_info()
        p.save()
        p.setClipPath(frame)
        p.drawPixmap(img, self.pix, QRectF(self.pix.rect()))
        # oscura tutto ciò che resta fuori dall'inquadratura
        outside = QPainterPath()
        outside.addRect(r)
        hole = QPainterPath()
        hole.addRoundedRect(vp, 6, 6)
        p.fillPath(outside.subtracted(hole), qcolor(P.crop_shade))
        p.restore()
        # bordo + griglia dei terzi durante lo spostamento
        if self.dragging:
            p.setPen(QPen(qcolor("rgba(255,255,255,70)"), 1))
            for k in (1, 2):
                xk = vp.left() + vp.width() * k / 3
                yk = vp.top() + vp.height() * k / 3
                p.drawLine(int(xk), int(vp.top()), int(xk), int(vp.bottom()))
                p.drawLine(int(vp.left()), int(yk), int(vp.right()), int(yk))
        edge = qcolor(P.crop_edge)
        edge.setAlpha(edge.alpha() if self.isEnabled() else 70)
        p.setPen(QPen(edge, 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(vp, 6, 6)

        f = self.font()
        f.setPointSizeF(8.5)
        p.setFont(f)
        if self.job.zoom > 1.001:
            self._pill(p, QRectF(r.left() + 10, r.top() + 10, 58, 20), f"{self.job.zoom * 100:.0f}%")
        if self.hover and self.isEnabled() and not self.dragging:
            text = "Trascina  ·  Rotella per lo zoom  ·  Doppio clic per centrare"
            w = p.fontMetrics().horizontalAdvance(text) + 20
            self._pill(p, QRectF(r.center().x() - w / 2, r.bottom() - 30, w, 20), text)
        if not self.isEnabled():
            shade = qcolor(P.bg)
            shade.setAlpha(150)
            p.fillPath(frame, shade)
        self._paint_loading(p, r)

    def _pill(self, p: QPainter, rect: QRectF, text: str):
        p.setPen(Qt.NoPen)
        p.setBrush(qcolor(P.pill_bg))
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        p.setPen(qcolor(P.pill_text))
        p.drawText(rect, Qt.AlignCenter, text)

    def _paint_loading(self, p: QPainter, r: QRectF):
        if self.loading:
            f = self.font(); f.setPointSizeF(8.5); p.setFont(f)
            self._pill(p, QRectF(r.right() - 98, r.top() + 10, 88, 20), "Caricamento…")

    # ---------------------------------------------------------------- mouse
    def enterEvent(self, e):
        self.hover = True; self.update(); super().enterEvent(e)

    def leaveEvent(self, e):
        self.hover = False; self.update(); super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.interactive():
            self.dragging = True
            self._last = e.position()
            self.update_cursor()
            self.update()

    def mouseMoveEvent(self, e):
        if not (self.dragging and self.interactive()):
            return
        pos = e.position()
        d = pos - self._last
        self._last = pos
        _, img, _ = self.geometry_info()
        self.job.cx -= d.x() / img.width()
        self.job.cy -= d.y() / img.height()
        self.normalize()
        self.update()
        self.changed.emit()

    def mouseReleaseEvent(self, e):
        if self.dragging:
            self.dragging = False
            self.update_cursor()
            self.update()

    def mouseDoubleClickEvent(self, e):
        if self.interactive():
            self.reset()

    def wheelEvent(self, e):
        if not self.interactive():
            return e.ignore()
        steps = e.angleDelta().y() / 120
        if not steps:
            return
        self.zoom_to(self.job.zoom * (1.15 ** steps), e.position())
        e.accept()

    def zoom_to(self, z: float, anchor=None):
        """Zoom mantenendo fermo il punto sotto il cursore (o il centro)."""
        j = self.job
        if not j:
            return
        vp, img, (x, y, w, h) = self.geometry_info()
        anchor = anchor if anchor is not None else vp.center()
        u = (anchor.x() - img.left()) / img.width()
        v = (anchor.y() - img.top()) / img.height()
        fx = (anchor.x() - vp.left()) / vp.width()
        fy = (anchor.y() - vp.top()) / vp.height()
        z = min(max(z, 1.0), MAX_ZOOM)
        nw, nh = w * j.zoom / z, h * j.zoom / z
        j.zoom = z
        j.cx = u - fx * nw + nw / 2
        j.cy = v - fy * nh + nh / 2
        self.normalize()
        self.update()
        self.changed.emit()



class DropZone(QFrame):
    clicked = Signal()

    def __init__(self):
        super().__init__(objectName="dropZone")
        v = QVBoxLayout(self)
        v.setAlignment(Qt.AlignCenter)
        v.setSpacing(10)
        ic = IconLabel("clapperboard", "drop_icon", 56, 1.6)
        ic.setAccessibleName("Zona di rilascio dei video")
        t = QLabel("Trascina qui i tuoi video", objectName="dropTitle")
        t.setAlignment(Qt.AlignCenter)
        s = QLabel("Anche intere cartelle  ·  MP4, MKV, MOV, AVI, WEBM e molti altri", objectName="dropSub")
        s.setAlignment(Qt.AlignCenter)
        s2 = QLabel("oppure premi Ctrl+O", objectName="dropSub")
        s2.setAlignment(Qt.AlignCenter)
        self.btn = QPushButton(icons.icon("plus", "accent_text"), "  Scegli file", objectName="accentSoft")
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.setToolTip("Scegli uno o più video  (Ctrl+O)")
        self.btn.clicked.connect(self.clicked.emit)
        v.addWidget(ic, 0, Qt.AlignCenter)
        v.addWidget(t)
        v.addWidget(s)
        v.addSpacing(8)
        v.addWidget(self.btn, 0, Qt.AlignCenter)
        v.addWidget(s2)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()


class Thumb(QWidget):
    """Miniatura arrotondata; lo sfondo e l'icona segnaposto seguono il tema."""

    def __init__(self, thumb_path=None):
        super().__init__()
        self.setFixedSize(THUMB_W, THUMB_H)
        self.src = QPixmap(str(thumb_path)) if thumb_path else None
        self._ph = icons.icon("music", "muted", width=1.6)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), 8, 8)
        p.setClipPath(path)
        p.fillRect(QRectF(0, 0, w, h), qcolor(P.surf3))
        if self.src and not self.src.isNull():
            s = self.src.scaled(int(w * 2), int(h * 2), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            sw, sh = s.width() / 2, s.height() / 2
            p.drawPixmap(QRectF((w - sw) / 2, (h - sh) / 2, sw, sh), s, QRectF(s.rect()))
        else:
            self._ph.paint(p, self.rect().adjusted(w // 2 - 14, h // 2 - 14, -(w // 2 - 14), -(h // 2 - 14)))


class Badge(QFrame):
    """Etichetta di stato con icona opzionale (colori dal tema tramite il foglio di stile)."""
    ICONS = {"ok": ("check", "ok"), "err": ("alert", "err"), "warn": ("alert", "warn")}

    def __init__(self):
        super().__init__(objectName="badge")
        h = QHBoxLayout(self)
        h.setContentsMargins(9, 3, 10, 3)
        h.setSpacing(5)
        self.ic = IconLabel("check", "ok", 12, 2.6)
        self.lbl = QLabel()
        h.addWidget(self.ic)
        h.addWidget(self.lbl)

    def set_state(self, state: str, text: str):
        self.lbl.setText(text)
        self.setProperty("state", state)
        ic = self.ICONS.get(state)
        self.ic.setVisible(bool(ic))
        if ic:
            self.ic.set_icon(*ic)
        self.setAccessibleName(text)
        repolish(self)
        for c in self.findChildren(QLabel):
            repolish(c)

    def state(self) -> str:
        return self.property("state") or ""

    def setText(self, text: str):
        self.lbl.setText(text)
        self.setAccessibleName(text)


class QueueRow(QWidget):
    remove_requested = Signal(object)
    detail_requested = Signal(object)

    def __init__(self, job: Job):
        super().__init__(objectName="row")
        self.job = job
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 10, 8, 10)
        h.setSpacing(14)

        self.thumb = Thumb(job.thumb)
        h.addWidget(self.thumb, 0, Qt.AlignVCenter)

        v = QVBoxLayout()
        v.setSpacing(3)
        self.title = ElidedLabel(job.path.name, objectName="rowTitle")
        self.title.setToolTip(str(job.path))
        parts = [fmt_time(job.duration) if job.duration else "durata sconosciuta"]
        if job.has_video and job.width:
            parts.append(f"{job.width}×{job.height}")
        elif not job.has_video:
            parts.append("solo audio")
        if len(job.tracks) > 1:
            parts.append(f"{len(job.tracks)} tracce audio")
        meta = QLabel("  ·  ".join(parts), objectName="rowMeta")
        v.addWidget(self.title)
        v.addWidget(meta)
        v.addSpacing(3)
        self.track: QComboBox | None = None
        if len(job.tracks) > 1:
            self.track = QComboBox(objectName="rowCombo")
            for n, t in enumerate(job.tracks, 1):
                self.track.addItem(f"Traccia {n}  ·  {t.desc}", t.index)
            self.track.setCurrentIndex(min(job.track_sel, len(job.tracks) - 1))
            self.track.currentIndexChanged.connect(lambda i: setattr(job, "track_sel", i))
            self.track.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            self.track.setMaximumWidth(380)
            self.track.setAccessibleName(f"Traccia audio di {job.path.name}")
            v.addWidget(self.track, 0, Qt.AlignLeft)
        else:
            line = QHBoxLayout()
            line.setSpacing(6)
            if job.tracks:
                line.addWidget(IconLabel("music", "muted", 14, 2.0))
                line.addWidget(ElidedLabel(job.tracks[0].desc, Qt.ElideRight, objectName="rowTrack"), 1)
            else:
                line.addWidget(IconLabel("alert", "warn", 14, 2.2))
                line.addWidget(ElidedLabel(job.error or "Nessuna traccia audio", Qt.ElideRight,
                                           objectName="warnText"), 1)
            v.addLayout(line)
        h.addLayout(v, 1)

        right = QVBoxLayout()
        right.setSpacing(6)
        right.addStretch()
        self.badge = Badge()
        self.bar = QProgressBar(objectName="mini")
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedWidth(120)
        self.bar.hide()
        self.btn_detail = QPushButton("Dettagli", objectName="rowDetail")
        self.btn_detail.setCursor(Qt.PointingHandCursor)
        self.btn_detail.setToolTip("Mostra il messaggio completo dell'errore, da copiare")
        self.btn_detail.setAccessibleName(f"Dettagli dell'errore di {job.path.name}")
        self.btn_detail.clicked.connect(lambda: self.detail_requested.emit(self.job))
        self.btn_detail.hide()
        right.addWidget(self.badge, 0, Qt.AlignRight)
        right.addWidget(self.bar, 0, Qt.AlignRight)
        right.addWidget(self.btn_detail, 0, Qt.AlignRight)
        right.addStretch()
        h.addLayout(right)

        self.btn_rm = QPushButton(icons.icon("x", "muted", width=2.2), "", objectName="rowRemove")
        self.btn_rm.setIconSize(QSize(16, 16))
        self.btn_rm.setCursor(Qt.PointingHandCursor)
        self.btn_rm.setFocusPolicy(Qt.NoFocus)    # da tastiera: seleziona la riga e premi Canc
        self.btn_rm.setToolTip("Rimuovi dalla coda  (Canc)")
        self.btn_rm.setAccessibleName(f"Rimuovi {job.path.name} dalla coda")
        self.btn_rm.clicked.connect(lambda: self.remove_requested.emit(self.job))
        h.addWidget(self.btn_rm, 0, Qt.AlignVCenter)
        a11y_pass(self)

        if job.tracks:
            self.set_state("idle", "Pronto")
        else:
            self.set_state("warn", "Saltato", job.error)

    def track_index(self) -> int | None:
        if self.track:
            return self.track.currentData()
        return self.job.tracks[0].index if self.job.tracks else None

    def set_state(self, state: str, text: str, tip: str = ""):
        self.badge.set_state(state, text)
        self.badge.setToolTip(tip)
        self.bar.setVisible(state == "run")
        self.btn_detail.setVisible(state == "err" or (state == "warn" and bool(self.job.detail)))
        if state != "run":
            self.bar.setValue(0)

    def set_progress(self, frac: float):
        self.bar.setValue(int(frac * 1000))

    def set_busy(self, busy: bool):
        self.btn_rm.setEnabled(not busy)
        if self.track:
            self.track.setEnabled(not busy)


class Toast(QLabel):
    """Messaggio non invasivo che compare in basso e svanisce da solo."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setTextFormat(Qt.PlainText)
        self.setAccessibleName("Notifica")
        self.eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.eff)
        self.anim = QPropertyAnimation(self.eff, b"opacity", self)
        self.anim.setDuration(DUR_BASE)
        self.timer = QTimer(self, singleShot=True)
        self.timer.timeout.connect(self._fade_out)
        self._fading = False
        self.anim.finished.connect(lambda: self._fading and self.hide())
        self.hide()

    def show_msg(self, text, ms=3200):
        self.setText(text)
        self.setMaximumWidth(max(240, self.parentWidget().width() - 80))
        self.setWordWrap(True)
        self.adjustSize()
        par = self.parentWidget()
        self.move((par.width() - self.width()) // 2, par.height() - self.height() - 28)
        self.raise_()
        self.show()
        self.anim.stop()
        self._fading = False
        self.anim.setStartValue(self.eff.opacity() if self.isVisible() else 0.0)
        self.anim.setEndValue(1.0)
        self.anim.start()
        self.timer.start(ms)

    def _fade_out(self):
        self.anim.stop()
        self.anim.setStartValue(1.0)
        self.anim.setEndValue(0.0)
        self._fading = True
        self.anim.start()
