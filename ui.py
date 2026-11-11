"""Audio Extractor - finestra principale: coda, impostazioni, estrazione, tema e scorciatoie."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QProcess, QSize, Qt, QThread, QTimer
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QProgressBar,
    QPushButton, QScrollArea, QSlider, QStackedWidget, QVBoxLayout, QWidget,
)

import icons
import theme
from common import (
    APP_NAME, IMAGE_EXT, VIDEO_EXT, fmt_size, fmt_time, log, reveal, settings, unique_path,
)
from dialogs import AboutDialog, ErrorDialog
from engine import (
    COPY_EXT, COVER_BY_EXT, FORMAT_BY_KEY, FORMATS, MAX_ZOOM, SAR_FIX, Format, Job, Mode, ProbeWorker, Quality,
    build_audio_args, cover_filter, cover_owner, cover_source, frame_args, friendly_error, image_aspect,
)
from theme import THEME_LABELS, THEMES, titlebar
from widgets import (
    CoverPreview, DropZone, ElidedLabel, FormatTile, IconLabel, QueueRow, Segmented, Toast, Toggle,
    a11y_pass, repolish,
)


def write_ui_assets(folder: Path) -> str:
    """Freccia dei menu a tendina (usata dal foglio di stile), una per tema."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("dark", "light"):
        color = theme.DARK["muted"] if name == "dark" else theme.LIGHT["muted"]
        (folder / f"chev-{name}.svg").write_text(icons.svg("chevron-down", color, 2.4), encoding="utf-8")
    return folder.as_posix()


def apply_theme(app: QApplication, pref: str, asset_dir: Path) -> str:
    """Applica il tema ('system' | 'dark' | 'light') a tutta l'applicazione, senza riavvio."""
    name = theme.apply(pref)
    app.setPalette(theme.app_palette())
    app.setStyleSheet(theme.stylesheet(write_ui_assets(asset_dir)))
    for w in app.topLevelWidgets():
        if w.isVisible():
            titlebar(w)
    for w in app.allWidgets():
        w.update()
    return name


def read_theme_pref() -> str:
    v = settings().value("theme", "system")
    return v if v in THEMES else "system"


class MainWindow(QMainWindow):
    def __init__(self, ffmpeg: str, tmp: Path):
        super().__init__()
        self.ffmpeg, self.tmp = ffmpeg, tmp
        self.settings = settings()
        self.theme_pref = read_theme_pref()
        self._undo: list[list] = []
        self.jobs: list[Job] = []
        self.queue: list[Job] = []
        self.cur: Job | None = None
        self.proc: QProcess | None = None
        self.steps: list[str] = []
        self.ctx = SimpleNamespace()
        self.cancelled = False
        self.last_output: Path | None = None
        self._threads: list[QThread] = []
        self._probing = 0
        self.preview_proc: QProcess | None = None
        self.preview_key = None
        self.preview_timer = QTimer(self, singleShot=True, interval=160)
        self.preview_timer.timeout.connect(self.make_preview)
        self._restoring = False

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icons.app_icon())
        self.setMinimumSize(1060, 680)
        self.setAcceptDrops(True)

        root = QWidget()
        self.setCentralWidget(root)
        rl = QHBoxLayout(root)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(self.build_left(), 1)
        rl.addWidget(self.build_sidebar())

        self.toast = Toast(root)
        self.refresh_theme_ui()
        self.load_settings()
        self.refresh_queue_ui()
        self.restore_window()
        self.setup_shortcuts()
        a11y_pass(self)
        root.setFocusPolicy(Qt.NoFocus)
        self.retab()
        self.setFocus(Qt.OtherFocusReason)
        try:
            QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_scheme_changed)
        except Exception:  # noqa: BLE001
            pass

    # ================================================================ finestra, tema, scorciatoie
    def restore_window(self):
        """Ripristina posizione e dimensione salvate, solo se restano dentro uno schermo disponibile."""
        geo = self.settings.value("geometry")
        ok = False
        if geo:
            try:
                ok = self.restoreGeometry(geo)
            except Exception:  # noqa: BLE001
                ok = False
        if ok:
            fr = self.frameGeometry()
            ok = any(sc.availableGeometry().intersected(fr).width() >= 200
                     and sc.availableGeometry().intersected(fr).height() >= 100
                     for sc in QGuiApplication.screens())
        if not ok:
            avail = QGuiApplication.primaryScreen().availableGeometry() if QGuiApplication.primaryScreen() else None
            w, h = 1380, 752
            if avail:
                w, h = min(w, avail.width() - 20), min(h, avail.height() - 50)
            self.resize(w, h)
            if avail:
                self.move(avail.center().x() - w // 2, avail.center().y() - (h + 30) // 2)

    def save_window(self):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.sync()

    def showEvent(self, e):
        titlebar(self)
        super().showEvent(e)

    def set_theme(self, pref: str):
        self.theme_pref = pref if pref in THEMES else "system"
        self.settings.setValue("theme", self.theme_pref)
        apply_theme(QApplication.instance(), self.theme_pref, self.tmp / "ui")
        self.refresh_theme_ui()
        self.toast.show_msg(f"Tema: {THEME_LABELS[self.theme_pref]}", 1600)

    def _on_scheme_changed(self, *_):
        if self.theme_pref == "system":
            apply_theme(QApplication.instance(), "system", self.tmp / "ui")
            self.refresh_theme_ui()

    def refresh_theme_ui(self):
        ic = {"system": "monitor", "dark": "moon", "light": "sun"}[self.theme_pref]
        self.btn_theme.setIcon(icons.icon(ic))
        self.btn_theme.setToolTip(f"Tema: {THEME_LABELS[self.theme_pref]}  (clic per cambiare)")
        self.btn_theme.setAccessibleName(f"Tema dell'interfaccia: {THEME_LABELS[self.theme_pref]}")
        for key, act in self.theme_actions.items():
            act.setChecked(key == self.theme_pref)
        self.preview.update()

    def show_theme_menu(self):
        menu = QMenu(self)
        for key in THEMES:
            menu.addAction(self.theme_actions[key])
        menu.exec(self.btn_theme.mapToGlobal(self.btn_theme.rect().bottomLeft()))

    def setup_shortcuts(self):
        def sc(keys, fn):
            for k in ([keys] if isinstance(keys, str) else keys):
                QShortcut(QKeySequence(k), self, activated=fn)
        sc("Ctrl+O", self.pick_files)
        sc("Ctrl+Shift+O", self.pick_folder)
        sc(["Ctrl+Return", "Ctrl+Enter"], self.start_shortcut)
        sc("Esc", lambda: self.is_running() and self.cancel())
        sc("Del", self.remove_selected)
        sc("Ctrl+Z", self.undo_remove)
        sc("F1", self.show_about)

    def retab(self):
        """Ordine di tabulazione logico: intestazione, coda, pannello (dall'alto in basso), azioni."""
        def tabbable(w):
            return bool(w.focusPolicy().value & 1)
        side = [w for w in self.side_inner.findChildren(QWidget) if tabbable(w) and w.isVisibleTo(self.side_inner)]
        side.sort(key=lambda w: (w.mapTo(self.side_inner, w.rect().center()).y() // 14,
                                 w.mapTo(self.side_inner, w.rect().center()).x()))
        order = [self.btn_theme, self.btn_about, self.btn_add_dir, self.btn_add, self.drop.btn, self.list,
                 self.btn_clear_done, self.btn_clear, *side, self.btn_open, self.btn_start, self.btn_cancel]
        order = [w for w in order if tabbable(w)]
        for a, b in zip(order, order[1:]):
            QWidget.setTabOrder(a, b)

    def start_shortcut(self):
        if not self.is_running() and self.btn_start.isEnabled():
            self.start()

    # ================================================================ layout
    def build_left(self) -> QWidget:
        w = QWidget(objectName="leftPane")
        v = QVBoxLayout(w)
        v.setContentsMargins(28, 22, 22, 18)
        v.setSpacing(16)

        head = QHBoxLayout()
        head.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(icons.svg_pixmap(icons.ICON_SVG, 40))
        logo.setAccessibleName("Logo di Audio Extractor")
        head.addWidget(logo)
        tv = QVBoxLayout()
        tv.setSpacing(0)
        tv.addWidget(QLabel(APP_NAME, objectName="appTitle"))
        tv.addWidget(QLabel("Estrai l'audio dai tuoi video.", objectName="appSub"))
        head.addLayout(tv)
        head.addStretch()
        self.btn_theme = QPushButton("", objectName="ghost")
        self.btn_theme.setIconSize(QSize(18, 18))
        self.btn_theme.clicked.connect(self.show_theme_menu)
        self.theme_actions: dict[str, QAction] = {}
        grp = QActionGroup(self)
        for key in THEMES:
            act = QAction(icons.icon({"system": "monitor", "dark": "moon", "light": "sun"}[key]),
                          THEME_LABELS[key], self, checkable=True)
            act.triggered.connect(lambda _=False, k=key: self.set_theme(k))
            grp.addAction(act)
            self.theme_actions[key] = act
        self.btn_about = QPushButton(icons.icon("info"), "", objectName="ghost")
        self.btn_about.setIconSize(QSize(18, 18))
        self.btn_about.setToolTip("Informazioni, licenza e componenti di terze parti  (F1)")
        self.btn_about.setAccessibleName("Informazioni")
        self.btn_about.clicked.connect(self.show_about)
        self.btn_add_dir = QPushButton(icons.icon("folder-plus"), "", objectName="ghost")
        self.btn_add_dir.setIconSize(QSize(18, 18))
        self.btn_add_dir.setAccessibleName("Aggiungi cartella")
        self.btn_add_dir.setToolTip("Aggiungi cartella: tutti i video al suo interno  (Ctrl+Maiusc+O)")
        self.btn_add_dir.clicked.connect(self.pick_folder)
        self.btn_add = QPushButton(icons.icon("plus", "accent_text"), "  Aggiungi video", objectName="accentSoft")
        self.btn_add.setToolTip("Scegli uno o più video  (Ctrl+O)")
        self.btn_add.clicked.connect(self.pick_files)
        for b in (self.btn_theme, self.btn_about, self.btn_add_dir, self.btn_add):
            b.setCursor(Qt.PointingHandCursor)
            head.addWidget(b)
        v.addLayout(head)

        self.stack = QStackedWidget()
        self.drop = DropZone()
        self.drop.clicked.connect(self.pick_files)
        self.stack.addWidget(self.drop)
        self.list = QListWidget(objectName="queue")
        self.list.setSpacing(4)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setAccessibleName("Coda dei video")
        self.list.setAccessibleDescription("Frecce per scorrere, Canc per rimuovere, Ctrl+Z per annullare la rimozione")
        self.list.currentRowChanged.connect(self.on_current_changed)
        self.list.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.stack.addWidget(self.list)
        v.addWidget(self.stack, 1)

        foot = QHBoxLayout()
        self.lbl_count = QLabel("", objectName="countLabel")
        foot.addWidget(self.lbl_count)
        foot.addStretch()
        self.btn_clear_done = QPushButton(icons.icon("circle-check"), "  Rimuovi completati", objectName="ghost")
        self.btn_clear_done.clicked.connect(self.clear_done)
        self.btn_clear = QPushButton(icons.icon("x"), "  Svuota coda", objectName="ghost")
        self.btn_clear.setToolTip("Svuota la coda  (Ctrl+Z per annullare)")
        self.btn_clear.clicked.connect(self.clear_list)
        for b in (self.btn_clear_done, self.btn_clear):
            b.setCursor(Qt.PointingHandCursor)
            foot.addWidget(b)
        v.addLayout(foot)
        return w

    def show_about(self):
        AboutDialog(self).exec()

    def section(self, title: str, lay: QVBoxLayout, right: QWidget | None = None) -> QVBoxLayout:
        """Sezione del pannello con intestazione che si comprime (stato ricordato)."""
        if lay.count():
            lay.addSpacing(6)
            d = QFrame(objectName="divider")
            lay.addWidget(d)
            lay.addSpacing(6)
        h = QHBoxLayout()
        head = QPushButton(title.upper(), objectName="sectionHead")
        head.setCursor(Qt.PointingHandCursor)
        head.setCheckable(True)
        head.setFocusPolicy(Qt.TabFocus)
        head.setAccessibleName(f"Sezione {title}")
        h.addWidget(head)
        h.addStretch()
        if right:
            h.addWidget(right)
        lay.addLayout(h)
        container = QWidget()
        body = QVBoxLayout(container)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)
        lay.addWidget(container)
        key = f"collapsed/{title}"

        def sync(open_: bool):
            container.setVisible(open_)
            head.setIcon(icons.icon("chevron-down" if open_ else "chevron-right", "muted"))
            head.setToolTip(("Comprimi " if open_ else "Espandi ") + f"la sezione {title}")

        def toggled(open_: bool):
            sync(open_)
            self.settings.setValue(key, not open_)

        head.setChecked(not self.settings.value(key, False, type=bool))
        sync(head.isChecked())
        head.toggled.connect(toggled)
        return body

    def field(self, label: str, widget: QWidget) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(5)
        lbl = QLabel(label, objectName="fieldLabel")
        v.addWidget(lbl)
        v.addWidget(widget)
        w.label = lbl
        return w

    def toggle_row(self, text: str, toggle: Toggle) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 2, 0, 2)
        lbl = QLabel(text)
        h.addWidget(lbl, 1)
        h.addWidget(toggle)
        w.label = lbl
        return w

    def build_sidebar(self) -> QWidget:
        side = QFrame(objectName="sidebar")
        side.setFixedWidth(410)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(0)

        scroll = self.side_scroll = QScrollArea()
        scroll.setFocusPolicy(Qt.NoFocus)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.side_inner = QWidget(objectName="sideInner")
        lay = QVBoxLayout(self.side_inner)
        lay.setContentsMargins(22, 22, 20, 18)
        lay.setSpacing(10)
        scroll.setWidget(self.side_inner)
        sv.addWidget(scroll, 1)

        # ---- Formato
        body = self.section("Formato", lay)
        grid = QGridLayout()
        grid.setSpacing(8)
        self.fmt_group = QButtonGroup(self)
        self.fmt_group.setExclusive(True)
        self.tiles: dict[str, FormatTile] = {}
        for i, f in enumerate(FORMATS):
            t = FormatTile(f)
            self.fmt_group.addButton(t, i)
            self.tiles[f.key] = t
            grid.addWidget(t, i // 3, i % 3)
        self.fmt_group.idToggled.connect(lambda i, on: on and self.on_format_changed())
        body.addLayout(grid)
        self.lbl_fmt_note = QLabel("", objectName="hint")
        self.lbl_fmt_note.setWordWrap(True)
        body.addWidget(self.lbl_fmt_note)

        # ---- Qualità
        body = self.section("Qualità", lay)
        self.seg_mode = Segmented(["CBR", "VBR"], "Modalità")
        self.seg_mode.changed.connect(self.on_mode_changed)
        self.f_mode = self.field("Modalità", self.seg_mode)
        body.addWidget(self.f_mode)
        self.cb_quality = QComboBox()
        self.cb_quality.currentIndexChanged.connect(self.on_quality_changed)
        self.f_quality = self.field("Bitrate", self.cb_quality)
        body.addWidget(self.f_quality)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.cb_rate = QComboBox()
        self.cb_rate.currentIndexChanged.connect(self.on_rate_changed)
        self.cb_channels = QComboBox()
        for label, val in [("Originali", None), ("Stereo", 2), ("Mono", 1)]:
            self.cb_channels.addItem(label, val)
        self.cb_channels.currentIndexChanged.connect(self.on_channels_changed)
        row.addWidget(self.field("Frequenza", self.cb_rate), 1)
        row.addWidget(self.field("Canali", self.cb_channels), 1)
        body.addLayout(row)

        # ---- Copertina
        self.btn_image = QPushButton(icons.icon("image"), "  Carica immagine…", objectName="ghost")
        self.btn_image.setToolTip("Usa un'immagine dal PC (jpg, png, webp…) al posto del fotogramma del video.\n"
                                  "Puoi anche trascinarla nella finestra.")
        self.btn_image.setAccessibleName("Carica un'immagine di copertina")
        self.btn_image.setCursor(Qt.PointingHandCursor)
        self.btn_image.clicked.connect(self.pick_cover_image)
        body = self.section("Copertina", lay, self.btn_image)
        self.tg_embed = Toggle(True, "Incorpora la copertina nel file audio")
        self.tg_embed.toggled.connect(self.on_cover_settings)
        self.row_embed = self.toggle_row("Incorpora nel file audio", self.tg_embed)
        body.addWidget(self.row_embed)
        self.lbl_cover_warn = QLabel("", objectName="warn")
        self.lbl_cover_warn.setWordWrap(True)
        body.addWidget(self.lbl_cover_warn)
        self.tg_jpg = Toggle(False, "Salva la copertina anche come immagine jpg")
        self.tg_jpg.toggled.connect(self.on_cover_settings)
        body.addWidget(self.toggle_row("Salva anche come immagine .jpg", self.tg_jpg))
        self.cover_box = QWidget()
        cb = QVBoxLayout(self.cover_box)
        cb.setContentsMargins(0, 4, 0, 0)
        cb.setSpacing(8)
        self.seg_shape = Segmented(["Quadrata", "Proporzioni originali"], "Forma della copertina")
        self.seg_shape.changed.connect(self.on_cover_settings)
        cb.addWidget(self.seg_shape)
        self.shared_box = QFrame(objectName="sharedBox")
        sb = QHBoxLayout(self.shared_box)
        sb.setContentsMargins(12, 8, 8, 8)
        sb.setSpacing(8)
        sb.addWidget(IconLabel("link", "info_text", 16, 2.0))
        self.lbl_shared = ElidedLabel("", Qt.ElideMiddle, objectName="sharedText")
        sb.addWidget(self.lbl_shared, 1)
        self.btn_own_cover = QPushButton("Personalizza", objectName="ghost")
        self.btn_own_cover.setToolTip("Dai a questo video una copertina sua, presa dal suo fotogramma")
        self.btn_own_cover.setCursor(Qt.PointingHandCursor)
        self.btn_own_cover.clicked.connect(self.make_cover_own)
        sb.addWidget(self.btn_own_cover)
        self.shared_box.hide()
        cb.addWidget(self.shared_box)
        self.image_box = QFrame(objectName="sharedBox")
        ib = QHBoxLayout(self.image_box)
        ib.setContentsMargins(12, 8, 8, 8)
        ib.setSpacing(8)
        ib.addWidget(IconLabel("image", "info_text", 16, 2.0))
        self.lbl_image = ElidedLabel("", Qt.ElideMiddle, objectName="sharedText")
        ib.addWidget(self.lbl_image, 1)
        self.btn_drop_image = QPushButton("Rimuovi", objectName="ghost")
        self.btn_drop_image.setToolTip("Torna a usare un fotogramma del video")
        self.btn_drop_image.setCursor(Qt.PointingHandCursor)
        self.btn_drop_image.clicked.connect(self.remove_cover_image)
        ib.addWidget(self.btn_drop_image)
        self.image_box.hide()
        cb.addWidget(self.image_box)
        self.preview = CoverPreview()
        self.preview.changed.connect(self.on_crop_changed)
        cb.addWidget(self.preview)
        self.frame_box = QWidget()
        fb = QVBoxLayout(self.frame_box)
        fb.setContentsMargins(0, 0, 0, 0)
        fb.setSpacing(8)
        fr = QHBoxLayout()
        fr.addWidget(QLabel("Fotogramma", objectName="fieldLabel"))
        fr.addStretch()
        self.lbl_frame_time = QLabel("", objectName="hint")
        fr.addWidget(self.lbl_frame_time)
        fb.addLayout(fr)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setCursor(Qt.PointingHandCursor)
        self.slider.setFixedHeight(26)
        self.slider.setAccessibleName("Fotogramma della copertina")
        self.slider.valueChanged.connect(self.on_slider)
        fb.addWidget(self.slider)
        cb.addWidget(self.frame_box)
        zr = QHBoxLayout()
        zr.addWidget(QLabel("Zoom", objectName="fieldLabel"))
        zr.addStretch()
        self.lbl_zoom = QLabel("100%", objectName="hint")
        zr.addWidget(self.lbl_zoom)
        cb.addLayout(zr)
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(100, int(MAX_ZOOM * 100))
        self.zoom_slider.setCursor(Qt.PointingHandCursor)
        self.zoom_slider.setFixedHeight(26)
        self.zoom_slider.setAccessibleName("Zoom della copertina")
        self.zoom_slider.valueChanged.connect(self.on_zoom_slider)
        cb.addWidget(self.zoom_slider)
        sr = QHBoxLayout()
        sr.setSpacing(10)
        self.btn_center = QPushButton("Centra")
        self.btn_center.setToolTip("Riporta l'inquadratura al centro e toglie lo zoom")
        self.btn_center.clicked.connect(self.preview.reset)
        self.btn_apply_all = QPushButton("Usa per tutti i video")
        self.btn_apply_all.setToolTip("Mette questa stessa immagine come copertina di tutti i video in coda "
                                      "(viene estratta una volta sola)")
        self.btn_apply_all.clicked.connect(self.share_cover_with_all)
        for b in (self.btn_center, self.btn_apply_all):
            b.setCursor(Qt.PointingHandCursor)
            sr.addWidget(b, 1)
        cb.addLayout(sr)
        self.cover_hint = QLabel("", objectName="hint")
        self.cover_hint.setWordWrap(True)
        cb.addWidget(self.cover_hint)
        body.addWidget(self.cover_box)

        # ---- Destinazione
        body = self.section("Destinazione", lay)
        self.seg_dest = Segmented(["Stessa del video", "Altra cartella"], "Destinazione")
        self.seg_dest.changed.connect(self.on_dest_changed)
        body.addWidget(self.seg_dest)
        self.dest_row = QWidget()
        dr = QHBoxLayout(self.dest_row)
        dr.setContentsMargins(0, 0, 0, 0)
        dr.setSpacing(8)
        self.ed_dest = QLineEdit()
        self.ed_dest.setPlaceholderText("Scegli una cartella…")
        self.ed_dest.setAccessibleName("Cartella di destinazione")
        self.ed_dest.textChanged.connect(lambda t: self.settings.setValue("dest", t))
        self.btn_dest = QPushButton(icons.icon("folder"), "  Sfoglia")
        self.btn_dest.setCursor(Qt.PointingHandCursor)
        self.btn_dest.setToolTip("Scegli la cartella di destinazione")
        self.btn_dest.clicked.connect(self.pick_dest)
        dr.addWidget(self.ed_dest, 1)
        dr.addWidget(self.btn_dest)
        body.addWidget(self.dest_row)
        lay.addStretch()

        # ---- Barra azioni
        bar = QFrame(objectName="actionBar")
        bv = QVBoxLayout(bar)
        bv.setContentsMargins(22, 14, 20, 18)
        bv.setSpacing(10)
        sr = QHBoxLayout()
        self.lbl_summary = ElidedLabel("", Qt.ElideRight, objectName="summary")
        self.lbl_estimate = QLabel("", objectName="estimate")
        sr.addWidget(self.lbl_summary, 1)
        sr.addWidget(self.lbl_estimate)
        bv.addLayout(sr)
        self.progress = QProgressBar(objectName="overall")
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        bv.addWidget(self.progress)
        self.lbl_status = ElidedLabel("Pronto.", Qt.ElideRight, objectName="statusText")
        bv.addWidget(self.lbl_status)
        br = QHBoxLayout()
        br.setSpacing(10)
        self.btn_open = QPushButton(icons.icon("folder"), "  Apri cartella")
        self.btn_open.setToolTip("Mostra l'ultimo file estratto in Esplora risorse")
        self.btn_open.setCursor(Qt.PointingHandCursor)
        self.btn_open.clicked.connect(self.open_output)
        self.btn_open.setEnabled(False)
        self.btn_start = QPushButton("Estrai audio", objectName="primary")
        self.btn_start.setToolTip("Avvia l'estrazione  (Ctrl+Invio)")
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.clicked.connect(self.start)
        self.btn_cancel = QPushButton("Annulla", objectName="danger")
        self.btn_cancel.setToolTip("Interrompe l'estrazione  (Esc)")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.cancel)
        self.btn_cancel.hide()
        br.addWidget(self.btn_open)
        br.addWidget(self.btn_start, 1)
        br.addWidget(self.btn_cancel, 1)
        bv.addLayout(br)
        sv.addWidget(bar)
        return side

    # ================================================================ settings
    def load_settings(self):
        s = self.settings
        self._restoring = True
        key = s.value("format", "mp3")
        (self.tiles.get(key) or self.tiles["mp3"]).setChecked(True)
        self.cb_channels.setCurrentIndex(int(s.value("channels", 0)))
        self.tg_embed.setChecked(s.value("embed", True, type=bool))
        self.tg_jpg.setChecked(s.value("jpg", False, type=bool))
        self.seg_shape.set_index(int(s.value("shape", 0)))
        self.preview.set_square(self.seg_shape.index() == 0)
        self.seg_dest.set_index(int(s.value("dest_mode", 0)))
        self.ed_dest.setText(s.value("dest", ""))
        self._restoring = False
        self.on_format_changed()
        self.on_dest_changed()

    def closeEvent(self, e):
        if self.is_running():
            box = QMessageBox(QMessageBox.Question, APP_NAME, "Estrazione in corso. Vuoi interromperla e uscire?",
                              parent=self)
            quit_btn = box.addButton("Interrompi ed esci", QMessageBox.DestructiveRole)
            box.addButton("Continua", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is not quit_btn:
                e.ignore()
                return
            self.cancel()
        self.save_window()
        super().closeEvent(e)

    # ================================================================ formato
    @property
    def fmt(self) -> Format:
        b = self.fmt_group.checkedButton()
        return b.fmt if b else FORMAT_BY_KEY["mp3"]

    def mode(self) -> Mode:
        return self.fmt.modes[min(self.seg_mode.index(), len(self.fmt.modes) - 1)]

    def quality(self) -> Quality:
        m = self.mode()
        return m.qualities[min(max(self.cb_quality.currentIndex(), 0), len(m.qualities) - 1)]

    def on_format_changed(self):
        if self._restoring:
            return
        f, s = self.fmt, self.settings
        s.setValue("format", f.key)
        self.lbl_fmt_note.setText(f.note)
        multi = len(f.modes) > 1
        self.f_mode.setVisible(multi)
        if multi:
            self.seg_mode.set_labels([m.short for m in f.modes])
            self.seg_mode.set_index(min(int(s.value(f"mode/{f.key}", 0)), len(f.modes) - 1))
        else:
            self.seg_mode.set_labels(["—"])
        self.cb_rate.blockSignals(True)
        self.cb_rate.clear()
        if f.key == "opus":
            self.cb_rate.addItem("48 kHz (fisso)", None)
        else:
            self.cb_rate.addItem("Originale", None)
        for r in f.rates:
            self.cb_rate.addItem(f"{r / 1000:g} kHz", r)
        self.cb_rate.setCurrentIndex(min(int(s.value(f"rate/{f.key}", 0)), self.cb_rate.count() - 1))
        self.cb_rate.setEnabled(bool(f.rates))
        self.cb_rate.blockSignals(False)
        self.cb_channels.setEnabled(f.key != "copy")
        self.on_mode_changed(save=False)
        self.update_cover_ui()
        QTimer.singleShot(0, self.retab)

    def on_mode_changed(self, *_, save=True):
        f, m = self.fmt, self.mode()
        if save and len(f.modes) > 1:
            self.settings.setValue(f"mode/{f.key}", self.seg_mode.index())
        self.f_quality.label.setText(m.title)
        self.cb_quality.blockSignals(True)
        self.cb_quality.clear()
        for q in m.qualities:
            self.cb_quality.addItem(q.label)
        saved = self.settings.value(f"q/{f.key}/{self.seg_mode.index()}", None)
        self.cb_quality.setCurrentIndex(min(int(saved) if saved is not None else m.default,
                                            len(m.qualities) - 1))
        self.cb_quality.setEnabled(len(m.qualities) > 1)
        self.cb_quality.blockSignals(False)
        self.update_summary()

    def on_quality_changed(self, i):
        self.settings.setValue(f"q/{self.fmt.key}/{self.seg_mode.index()}", i)
        self.update_summary()

    def on_rate_changed(self, i):
        self.settings.setValue(f"rate/{self.fmt.key}", i)
        self.update_summary()

    def on_channels_changed(self, i):
        self.settings.setValue("channels", i)
        self.update_summary()

    def update_summary(self):
        f, q = self.fmt, self.quality()
        parts = [f.title]
        if f.key != "copy":
            parts.append(q.label.split("  ·  ")[0])
            if self.cb_rate.currentData():
                parts.append(self.cb_rate.currentText())
            if self.cb_channels.currentData():
                parts.append(self.cb_channels.currentText())
        else:
            parts.append("copia diretta")
        if self.cover_wanted():
            parts.append("copertina")
        self.lbl_summary.setFullText("  ·  ".join(parts))
        jobs = [j for j in self.jobs if j.tracks]
        total = sum(j.duration for j in jobs)
        if not jobs:
            est = ""
        elif f.key == "copy":
            est = "≈ come la sorgente"
        elif f.key == "wav":
            depth = (16, 24, 32, 32)[min(self.cb_quality.currentIndex(), 3)]
            rate = self.cb_rate.currentData() or 48000
            ch = self.cb_channels.currentData() or 2
            est = f"≈ {fmt_size(total * rate * depth * ch / 8 / 1_048_576)}"
        elif q.kbps:
            est = f"≈ {fmt_size(total * q.kbps / 8 / 1024)}"
        else:
            est = "≈ " + fmt_size(total * 900 / 8 / 1024) if f.key in ("flac", "alac") else ""
        self.lbl_estimate.setText(est)

    # ================================================================ copertina
    def cover_support(self) -> str | None:
        f = self.fmt
        return "maybe" if f.key == "copy" else COVER_BY_EXT.get(f.ext)

    def cover_wanted(self) -> bool:
        return (self.tg_embed.isChecked() and self.cover_support() is not None) or self.tg_jpg.isChecked()

    def update_cover_ui(self):
        sup = self.cover_support()
        self.tg_embed.setEnabled(sup is not None and not self.is_running())
        self.row_embed.label.setEnabled(sup is not None)
        if sup is None:
            self.lbl_cover_warn.setText(f"{self.fmt.title} non supporta copertine incorporate. "
                                        "Puoi comunque salvarla come immagine.")
            self.lbl_cover_warn.setObjectName("warn")
        elif sup == "maybe":
            self.lbl_cover_warn.setText("Con la copia diretta dipende dalla traccia originale: "
                                        "funziona con MP3, AAC, FLAC, Opus e Vorbis.")
            self.lbl_cover_warn.setObjectName("hint")
        else:
            self.lbl_cover_warn.setText("")
        repolish(self.lbl_cover_warn)
        self.lbl_cover_warn.setVisible(bool(self.lbl_cover_warn.text()))
        on = self.cover_wanted()
        self.cover_box.setEnabled(on and not self.is_running())
        self.btn_image.setEnabled(on and not self.is_running())
        self.update_summary()
        self.request_preview()

    def on_cover_settings(self, *_):
        if self._restoring:
            return
        self.settings.setValue("embed", self.tg_embed.isChecked())
        self.settings.setValue("jpg", self.tg_jpg.isChecked())
        self.settings.setValue("shape", self.seg_shape.index())
        self.preview.set_square(self.seg_shape.index() == 0)
        self.update_cover_ui()

    def current_job(self) -> Job | None:
        r = self.list.currentRow()
        return self.jobs[r] if 0 <= r < len(self.jobs) else None

    def selected_jobs(self) -> list[Job]:
        rows = sorted({self.list.row(i) for i in self.list.selectedItems()})
        js = [self.jobs[r] for r in rows if 0 <= r < len(self.jobs)]
        if not js and (c := self.current_job()):
            js = [c]
        return js

    def cover_job(self) -> Job | None:
        """Il video da cui viene presa la copertina del video selezionato."""
        j = self.current_job()
        return cover_owner(j) if j else None

    def on_current_changed(self, _row):
        j = self.cover_job()
        self.slider.blockSignals(True)
        self.slider.setValue(int((j.cover_pos if j else 0.2) * 1000))
        self.slider.blockSignals(False)
        self.preview.set_job(j)
        self.preview.normalize()
        self.sync_zoom_ui()
        self.update_frame_label()
        self.update_shared_ui()
        self.request_preview()

    def update_shared_ui(self):
        j = self.current_job()
        shared = bool(j and j.cover_from)
        self.shared_box.setVisible(shared)
        if shared:
            self.lbl_shared.setFullText(f"Copertina presa da «{j.cover_from.path.name}»")
        o = cover_owner(j) if j else None
        img = bool(o and o.image)
        self.image_box.setVisible(img and not shared)
        if img:
            self.lbl_image.setFullText(f"Immagine: {o.image.name}")
            self.lbl_image.setToolTip(str(o.image))
        self.frame_box.setVisible(not (o and not o.has_video) and not img)
        QTimer.singleShot(0, self.retab)
        n = sum(1 for x in self.jobs if x.cover_from)
        if img and not n:
            self.cover_hint.setText("La copertina è un'immagine esterna: trascina l'anteprima e usa lo zoom "
                                    "per scegliere cosa inquadrare.")
        elif n:
            self.cover_hint.setText(f"{n + 1} video usano la stessa copertina: viene estratta una volta sola. "
                                    "Le modifiche valgono per tutti.")
        else:
            self.cover_hint.setText("Ogni video ha la sua copertina: selezionalo nella coda, scegli il momento "
                                    "e trascina l'anteprima per decidere cosa inquadrare.")

    def on_slider(self, v):
        for j in {id(cover_owner(x)): cover_owner(x) for x in self.selected_jobs()}.values():
            j.cover_pos = v / 1000
        self.update_frame_label()
        self.request_preview()

    def on_zoom_slider(self, v):
        if self.cover_job():
            self.preview.zoom_to(v / 100)

    def on_crop_changed(self):
        self.sync_zoom_ui()

    def sync_zoom_ui(self):
        j = self.cover_job()
        z = j.zoom if j else 1.0
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(int(round(z * 100)))
        self.zoom_slider.blockSignals(False)
        self.lbl_zoom.setText(f"{z * 100:.0f}%")

    def share_cover_with_all(self):
        src = self.cover_job()
        if not src or not cover_source(src):
            return
        src.cover_from = None
        for j in self.jobs:
            if j is not src:
                j.cover_from = src
        self.update_shared_ui()
        self.lbl_status.setFullText(f"Tutti i video useranno la copertina di «{src.path.name}».")

    def make_cover_own(self):
        j = self.current_job()
        if not j or not j.cover_from:
            return
        src = j.cover_from
        j.cover_from = None
        if src.image and not j.image:          # parte dalla stessa immagine, poi la si cambia a piacere
            j.frame_aspect, j.image, j.aspect = j.aspect, src.image, src.aspect
        if j.has_video or j.image:
            j.cx, j.cy, j.zoom = src.cx, src.cy, src.zoom
        self.on_current_changed(self.list.currentRow())

    def pick_cover_image(self):
        if self.is_running():
            return
        if not self.jobs:
            self.toast.show_msg("Aggiungi prima un video, poi scegli l'immagine di copertina.")
            return
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXT))
        f, _ = QFileDialog.getOpenFileName(self, "Scegli l'immagine di copertina",
                                           self.settings.value("last_image_dir", ""),
                                           f"Immagini ({exts});;Tutti i file (*.*)")
        if f:
            self.settings.setValue("last_image_dir", str(Path(f).parent))
            self.set_cover_image(Path(f))

    def set_cover_image(self, path: Path):
        """Usa un'immagine esterna come copertina dei video selezionati
        (e di quelli che ne condividono la copertina)."""
        sel, cur = self.selected_jobs(), self.current_job()
        if cur and cur not in sel:
            sel = [cur]
        targets = list({id(cover_owner(x)): cover_owner(x) for x in sel}.values())
        if not targets:
            self.lbl_status.setFullText("Aggiungi prima un video, poi l'immagine di copertina.")
            return
        aspect = image_aspect(self.ffmpeg, path)
        if not aspect:
            self.toast.show_msg(f"Impossibile leggere l'immagine «{path.name}»: prova con un altro file.", 4500)
            return
        for o in targets:
            if not o.image:
                o.frame_aspect = o.aspect
            o.image, o.aspect = path, aspect
            o.cx = o.cy = 0.5
            o.zoom = 1.0
        if not self.cover_wanted():
            if self.cover_support() is None:
                self.tg_jpg.setChecked(True)
            else:
                self.tg_embed.setChecked(True)
        n = sum(1 for x in self.jobs if cover_owner(x) in targets)
        self.lbl_status.setFullText(f"Copertina «{path.name}» impostata per "
                                    + ("1 video." if n == 1 else f"{n} video."))
        self.on_current_changed(self.list.currentRow())

    def remove_cover_image(self):
        o = self.cover_job()
        if not o or not o.image:
            return
        o.image = None
        o.aspect = o.frame_aspect
        o.cx = o.cy = 0.5
        o.zoom = 1.0
        self.on_current_changed(self.list.currentRow())

    def update_frame_label(self):
        j = self.cover_job()
        if j and j.duration and not j.image:
            self.lbl_frame_time.setText(f"{fmt_time(j.cover_pos * j.duration)} / {fmt_time(j.duration)}")
        else:
            self.lbl_frame_time.setText("")

    def request_preview(self):
        self.preview_timer.start()

    def make_preview(self):
        j = self.cover_job()
        if not j:
            self.preview_key = None
            self.preview.set_job(None)
            self.preview.set_image(None, "Aggiungi un video per vedere l'anteprima della copertina")
            return
        src = cover_source(j)
        if not src:
            self.preview_key = None
            self.preview.set_image(None, "Questo file non ha video:\nusa «Carica immagine…» per dargli una copertina")
            return
        path, t = src
        key = (id(j), str(path), None if t is None else round(t, 2))
        self.preview.set_job(j)
        if self.preview_key == key and self.preview.pix is not None:
            self.preview.update()      # stesso fotogramma: cambia solo l'inquadratura
            return
        if self.preview_proc and self.preview_proc.state() != QProcess.NotRunning:
            self.preview_proc.kill()
            self.preview_proc.waitForFinished(300)
        out = self.tmp / f"preview_{uuid.uuid4().hex}.jpg"
        # fotogramma intero (solo correzione SAR): il ritaglio lo fa l'anteprima in tempo reale
        vf = SAR_FIX + ",scale='min(1280,iw)':'min(1280,ih)':force_original_aspect_ratio=decrease"
        args = frame_args(path, t, vf, out, 3)
        proc = QProcess(self)
        proc.finished.connect(lambda *_a, proc=proc, out=out, j=j, key=key: self.on_preview_done(proc, out, j, key))
        self.preview_proc = proc
        self.preview.set_loading()
        proc.start(self.ffmpeg, args)

    def on_preview_done(self, proc: QProcess, out: Path, job: Job, key):
        proc.deleteLater()
        if proc is not self.preview_proc:
            out.unlink(missing_ok=True)
            return
        self.preview_proc = None
        pix = QPixmap(str(out)) if out.is_file() else QPixmap()
        if pix.isNull():
            self.preview_key = None
            self.preview.set_image(None, "Impossibile leggere l'immagine" if job.image
                                   else "Impossibile leggere il fotogramma in questo punto")
        else:
            job.aspect = pix.width() / pix.height()
            self.preview_key = key
            self.preview.set_image(pix)
            self.preview.normalize()
        out.unlink(missing_ok=True)

    # ================================================================ destinazione
    def on_dest_changed(self, *_):
        custom = self.seg_dest.index() == 1
        self.dest_row.setVisible(custom)
        self.settings.setValue("dest_mode", self.seg_dest.index())

    def pick_dest(self):
        d = QFileDialog.getExistingDirectory(self, "Cartella di destinazione", self.ed_dest.text())
        if d:
            self.ed_dest.setText(str(Path(d)))

    # ================================================================ coda
    def pick_files(self):
        if self.is_running():
            return
        exts = " ".join(f"*{e}" for e in sorted(VIDEO_EXT))
        files, _ = QFileDialog.getOpenFileNames(self, "Scegli i video", self.settings.value("last_dir", ""),
                                                f"Video ({exts});;Tutti i file (*.*)")
        if files:
            self.settings.setValue("last_dir", str(Path(files[0]).parent))
            self.add_paths([Path(f) for f in files])

    def pick_folder(self):
        if self.is_running():
            return
        d = QFileDialog.getExistingDirectory(self, "Scegli una cartella di video", self.settings.value("last_dir", ""))
        if d:
            self.settings.setValue("last_dir", d)
            self.add_paths([Path(d)])

    def add_paths(self, paths: list[Path]):
        images = [p for p in paths if p.is_file() and p.suffix.lower() in IMAGE_EXT]
        if images:                      # immagine trascinata: diventa la copertina
            paths = [p for p in paths if p not in images]
            self.set_cover_image(images[0])
            if not paths:
                return
        expanded = []
        for p in paths:
            if p.is_dir():
                expanded += sorted(f for f in p.rglob("*") if f.suffix.lower() in VIDEO_EXT)
            elif p.is_file():
                expanded.append(p)
        known = {j.path for j in self.jobs}
        new = [p for p in dict.fromkeys(expanded) if p not in known]
        if not new:
            if paths:
                self.lbl_status.setFullText("Nessun nuovo video da aggiungere.")
            return
        self._probing += len(new)
        self.update_status_idle()
        th = QThread(self)
        w = ProbeWorker(self.ffmpeg, new, self.tmp)
        w.moveToThread(th)
        th.started.connect(w.run)
        w.probed.connect(self.on_probed)
        w.finished.connect(th.quit)
        th.finished.connect(lambda: self._threads.remove(th))
        th.finished.connect(w.deleteLater)
        th._worker = w
        self._threads.append(th)
        th.start()

    def insert_job(self, job: Job, index: int | None = None):
        row = QueueRow(job)
        row.remove_requested.connect(lambda j: self.remove_jobs([j]))
        row.detail_requested.connect(self.show_job_detail)
        job.row = row
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, max(row.sizeHint().height(), 90)))
        if index is None or index >= len(self.jobs):
            self.jobs.append(job)
            self.list.addItem(item)
        else:
            self.jobs.insert(index, job)
            self.list.insertItem(index, item)
        self.list.setItemWidget(item, row)
        if job.output:
            row.set_state("ok", "Fatto", str(job.output))

    def on_probed(self, job: Job):
        self._probing = max(self._probing - 1, 0)
        if any(j.path == job.path for j in self.jobs):
            self.update_status_idle()
            return
        if not job.tracks:
            log.info("File saltato %s: %s\n%s", job.path, job.error, job.detail)
        self.insert_job(job)
        if self.list.currentRow() < 0:
            self.list.setCurrentRow(0)
        self.refresh_queue_ui()

    def remove_jobs(self, jobs: list[Job]):
        """Toglie dalla coda i video indicati; l'ultima rimozione si puo' annullare con Ctrl+Z."""
        if self.is_running():
            return
        jobs = [j for j in self.jobs if j in jobs]
        if not jobs:
            return
        entry = []
        for j in jobs:
            entry.append((self.jobs.index(j), j, [x for x in self.jobs if x.cover_from is j]))
        for _i, j, deps in reversed(entry):
            for x in deps:
                x.cover_from = None
            r = self.jobs.index(j)
            self.list.takeItem(r)
            self.jobs.pop(r)
        self._undo = (self._undo + [entry])[-10:]
        self.refresh_queue_ui()
        self.request_preview()
        n = len(jobs)
        self.toast.show_msg(f"{'1 video rimosso' if n == 1 else f'{n} video rimossi'}  ·  Ctrl+Z per annullare")

    def remove_selected(self):
        if isinstance(QApplication.focusWidget(), QLineEdit):
            return
        self.remove_jobs(self.selected_jobs())

    def undo_remove(self):
        if self.is_running() or not self._undo:
            return
        entry = self._undo.pop()
        for i, j, deps in sorted(entry, key=lambda t: t[0]):
            self.insert_job(j, i)
            for x in deps:
                if x in self.jobs:
                    x.cover_from = j
        first = min(i for i, _j, _d in entry)
        self.list.setCurrentRow(min(first, len(self.jobs) - 1))
        self.refresh_queue_ui()
        self.request_preview()
        n = len(entry)
        self.toast.show_msg("1 video ripristinato" if n == 1 else f"{n} video ripristinati")

    def clear_list(self):
        self.remove_jobs(list(self.jobs))

    def clear_done(self):
        self.remove_jobs([j for j in self.jobs if j.output])

    def show_job_detail(self, job: Job):
        msg = job.error or "Operazione non riuscita."
        ErrorDialog(self, f"Problema con «{job.path.name}»", msg, job.detail or msg).exec()

    def refresh_queue_ui(self):
        n = len(self.jobs)
        self.stack.setCurrentIndex(1 if n else 0)
        total = sum(j.duration for j in self.jobs)
        self.lbl_count.setText(f"{n} {'video' if n == 1 else 'video'} in coda  ·  {fmt_time(total)} totali" if n else "")
        self.btn_clear.setVisible(n > 0)
        self.btn_clear_done.setVisible(any(j.output for j in self.jobs))
        self.btn_start.setEnabled(any(j.tracks for j in self.jobs) and self._probing <= 0)
        self.update_summary()
        self.update_status_idle()
        self.update_shared_ui()

    def update_status_idle(self):
        if self.is_running():
            return
        if self._probing > 0:
            self.lbl_status.setFullText(f"Analisi in corso… ({self._probing} rimanenti)")
            self.btn_start.setEnabled(False)
        elif not self.jobs:
            self.lbl_status.setFullText("Aggiungi uno o più video per iniziare.")
        elif self.lbl_status.text().startswith(("Analisi", "Aggiungi")):
            self.lbl_status.setFullText("Pronto.")
            self.btn_start.setEnabled(any(j.tracks for j in self.jobs))

    def on_item_double_clicked(self, item):
        j = self.jobs[self.list.row(item)]
        reveal(j.output if j.output and j.output.exists() else j.path)

    # drag & drop sull'intera finestra
    def _set_drag(self, on: bool):
        for w in (self.drop, self.list):
            w.setProperty("drag", on)
            repolish(w)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and not self.is_running():
            e.acceptProposedAction()
            self._set_drag(True)
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls() and not self.is_running():
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._set_drag(False)

    def dropEvent(self, e):
        self._set_drag(False)
        self.add_paths([Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()])
        e.acceptProposedAction()

    # ================================================================ estrazione
    def is_running(self) -> bool:
        return bool(self.queue) or self.cur is not None

    def set_busy(self, busy: bool):
        self.side_inner.setEnabled(not busy)
        for b in (self.btn_add, self.btn_add_dir, self.btn_clear, self.btn_clear_done):
            b.setEnabled(not busy)
        for j in self.jobs:
            j.row.set_busy(busy)
        self.btn_start.setVisible(not busy)
        self.btn_cancel.setVisible(busy)
        self.btn_open.setEnabled(not busy and self.last_output is not None)
        if not busy:
            self.update_cover_ui()

    def start(self):
        if self.seg_dest.index() == 1 and not self.ed_dest.text().strip():
            self.toast.show_msg("Scegli prima la cartella di destinazione.")
            self.ed_dest.setFocus()
            return
        self.queue = [j for j in self.jobs if j.tracks]
        if not self.queue:
            return
        for j in self.jobs:
            if j.tracks:
                j.output = None
                j.error = j.detail = ""
                j.row.set_state("idle", "In coda")
        self.cancelled = False
        self.ok_count = self.err_count = 0
        self.n_total = len(self.queue)
        self.done_dur = 0.0
        self.total_dur = sum(j.duration for j in self.queue) or 1.0
        self.last_output = None
        self.cover_cache: dict = {}          # chiave copertina -> jpg già estratto
        self.saved_jpgs: set = set()         # (cartella, chiave) già salvati come .jpg
        owners = [id(cover_owner(j)) for j in self.queue]
        self.shared_owners = {o for o in owners if owners.count(o) > 1}
        self.progress.setValue(0)
        self.set_busy(True)
        self.next_job()

    def cover_key(self, job: Job):
        o = cover_owner(job)
        path, t = cover_source(o)
        return (id(o), str(path), None if t is None else round(t, 3),
                round(o.cx, 5), round(o.cy, 5), round(o.zoom, 4), self.seg_shape.index())

    def output_dir(self, job: Job) -> Path:
        if self.seg_dest.index() == 1 and self.ed_dest.text().strip():
            return Path(self.ed_dest.text().strip())
        return job.path.parent

    def next_job(self):
        if self.cancelled or not self.queue:
            return self.finish()
        job = self.cur = self.queue.pop(0)
        track_idx = job.row.track_index()
        track = next(t for t in job.tracks if t.index == track_idx)
        f = self.fmt
        ext = f.ext or COPY_EXT.get(track.codec, "mka")
        if f.key == "copy" and track.codec.startswith("pcm_"):
            ext = "wav"
        try:
            out_dir = self.output_dir(job)
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            job.error = "Impossibile creare la cartella di destinazione."
            job.detail = str(e)
            log.error("Cartella di destinazione %s: %s", job.path, e)
            job.row.set_state("err", "Errore", job.error)
            self.err_count += 1
            self.cur = None
            return self.next_job()
        suffix = f" [traccia {job.tracks.index(track) + 1}]" if len(job.tracks) > 1 else ""
        embed = COVER_BY_EXT.get(ext) if self.tg_embed.isChecked() else None
        want_cover = cover_source(cover_owner(job)) is not None and bool(embed or self.tg_jpg.isChecked())
        self.ctx = SimpleNamespace(
            track=track, out=unique_path(out_dir / f"{job.path.stem}{suffix}.{ext}"),
            embed=embed if want_cover else None, cover=None, meta=None, cover_failed=False, cover_key=None)
        self.steps = (["cover"] if want_cover else []) + (["meta"] if self.ctx.embed == "vorbis" else []) + ["audio"]
        self.lbl_status.setFullText(f"File {self.ok_count + self.err_count + 1} di {self.n_total}  ·  {job.path.name}")
        job.row.set_state("run", "Estrazione…")
        self.list.scrollToItem(self.list.item(self.jobs.index(job)))
        self.run_step()

    def run_step(self):
        if self.cancelled:
            return self.next_job()
        if not self.steps:
            return
        kind = self.steps.pop(0)
        args = getattr(self, f"args_{kind}")(self.cur)
        if args is None:
            return self.run_step()
        self.ctx.stderr = ""
        p = QProcess(self)
        p.readyReadStandardError.connect(lambda p=p: self._read_err(p))
        if kind == "audio":
            p.readyReadStandardOutput.connect(lambda p=p: self.on_progress(p))
        p.finished.connect(lambda code, st, p=p, kind=kind: self.on_step_done(p, kind, code, st))
        self.proc = p
        p.start(self.ffmpeg, args)

    def _read_err(self, p: QProcess):
        self.ctx.stderr = (self.ctx.stderr + bytes(p.readAllStandardError()).decode(errors="replace"))[-3000:]

    def args_cover(self, job: Job):
        key = self.cover_key(job)
        self.ctx.cover_key = key
        cached = self.cover_cache.get(key)
        if cached is not None:                  # già estratta per un altro video: riuso
            self.ctx.cover = cached or None
            if not cached:
                self.ctx.cover_failed = True
                self.ctx.embed = None
            return None
        o = cover_owner(job)
        out = self.tmp / f"cover_{uuid.uuid4().hex}.jpg"
        self.ctx.cover_path = out
        path, t = cover_source(o)
        return frame_args(path, t, cover_filter(o, self.seg_shape.index() == 0, 1200), out, 2)

    def args_meta(self, job: Job):
        if not self.ctx.cover:
            self.ctx.embed = None
            return None
        out = self.tmp / f"meta_{uuid.uuid4().hex}.txt"
        self.ctx.meta_path = out
        return ["-hide_banner", "-loglevel", "error", "-y", "-i", str(job.path), "-f", "ffmetadata", str(out)]

    def args_audio(self, job: Job):
        c = self.ctx
        return build_audio_args(
            job.path, c.out, fmt=self.fmt, track_index=c.track.index, quality_args=self.quality().args,
            rate=self.cb_rate.currentData(), channels=self.cb_channels.currentData(), cover=c.cover,
            embed=c.embed, meta=c.meta, tmp=self.tmp)

    def on_progress(self, p: QProcess):
        job = self.cur
        if not job:
            return
        for line in bytes(p.readAllStandardOutput()).decode(errors="replace").splitlines():
            if line.startswith(("out_time_us=", "out_time_ms=")):
                try:
                    t = int(line.split("=", 1)[1]) / 1_000_000
                except ValueError:
                    continue
                frac = min(max(t / job.duration, 0), 1.0) if job.duration else 0.0
                job.row.set_progress(frac)
                job.row.badge.setText(f"{frac * 100:.0f}%")
                self.progress.setValue(int((self.done_dur + frac * job.duration) / self.total_dur * 1000))

    def on_step_done(self, p: QProcess, kind: str, code: int, status):
        p.deleteLater()
        self.proc = None
        job, c = self.cur, self.ctx
        if job is None:
            return
        ok = code == 0 and status == QProcess.NormalExit
        if self.cancelled:
            c.out.unlink(missing_ok=True)
            job.row.set_state("warn", "Annullato")
            self.cur = None
            return self.finish()
        if kind == "cover":
            cp = c.cover_path
            if ok and cp.is_file() and cp.stat().st_size:
                c.cover = cp
            else:
                c.cover_failed = True
                c.embed = None
            self.cover_cache[c.cover_key] = c.cover or ""
            return self.run_step()
        if kind == "meta":
            c.meta = c.meta_path if ok else None
            return self.run_step()
        # audio
        if ok and c.out.exists():
            job.output = c.out
            self.last_output = c.out
            size = c.out.stat().st_size / 1_048_576
            tip = str(c.out)
            if self.tg_jpg.isChecked() and c.cover:
                shared = id(cover_owner(job)) in self.shared_owners
                if shared:      # copertina condivisa: un solo cover.jpg per cartella
                    tag = (str(c.out.parent), c.cover_key)
                    jpg = None if tag in self.saved_jpgs else unique_path(c.out.parent / "cover.jpg")
                    self.saved_jpgs.add(tag)
                else:
                    jpg = unique_path(c.out.with_suffix(".jpg"))
                if jpg:
                    try:
                        shutil.copyfile(c.cover, jpg)
                        tip += f"\n{jpg}"
                    except OSError:
                        pass
            if c.cover_failed:
                job.row.set_state("warn", f"Fatto · {fmt_size(size)}", tip + "\nCopertina non estratta")
            else:
                job.row.set_state("ok", fmt_size(size), tip)
            self.ok_count += 1
        else:
            c.out.unlink(missing_ok=True)
            job.error = friendly_error(c.stderr, code)
            job.detail = (c.stderr.strip() or f"ffmpeg ha restituito il codice {code}")
            log.error("Estrazione fallita %s (codice %s): %s", job.path, code, c.stderr.strip()[-1500:])
            job.row.set_state("err", "Errore", job.error)
            self.err_count += 1
        self.done_dur += job.duration
        self.cur = None
        self.next_job()

    def cancel(self):
        self.cancelled = True
        self.queue.clear()
        if self.proc and self.proc.state() != QProcess.NotRunning:
            self.proc.kill()
        else:
            self.finish()

    def finish(self):
        for j in self.jobs:
            if j.tracks and j.output is None and j.row.badge.state() not in ("err", "warn"):
                j.row.set_state("idle", "Pronto")
        self.cur = None
        self.queue.clear()
        self.set_busy(False)
        if self.cancelled:
            self.lbl_status.setFullText("Operazione annullata.")
            self.toast.show_msg("Estrazione annullata")
        else:
            self.progress.setValue(1000)
            msg = f"Completato  ·  {self.ok_count} {'file estratto' if self.ok_count == 1 else 'file estratti'}"
            if self.err_count:
                msg += f"  ·  {self.err_count} {'errore' if self.err_count == 1 else 'errori'} (premi «Dettagli» sulla riga)"
            self.lbl_status.setFullText(msg)
            self.toast.show_msg(msg, 5000)
            QApplication.alert(self)
        self.refresh_queue_ui()

    def open_output(self):
        if self.last_output:
            reveal(self.last_output)
