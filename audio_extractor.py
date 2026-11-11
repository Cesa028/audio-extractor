"""
Audio Extractor 2 — estrae l'audio dai video con ffmpeg, con copertina dal video.
Formati: MP3, AAC, Opus, Ogg Vorbis, AC3, FLAC, WAV, ALAC, copia diretta.
Requisiti (solo per eseguire il sorgente): Python 3.10+, PySide6, ffmpeg.
La versione .exe include già tutto.
"""
from __future__ import annotations

import base64
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

try:
    import PySide6  # noqa: F401
except ImportError:
    _msg = (f"PySide6 non è installato per questo Python:\n{sys.executable}\n\n"
            f"Installalo con:\n\"{sys.executable}\" -m pip install PySide6")
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, _msg, "Audio Extractor", 0x10)
    print(_msg, file=sys.stderr)
    sys.exit(1)

from PySide6.QtCore import (QByteArray, QObject, QProcess, QRectF, QSettings, QSize, Qt,
                            QThread, QTimer, QUrl, Signal)
from PySide6.QtGui import (QColor, QDesktopServices, QIcon, QImage, QPainter, QPainterPath,
                           QPalette, QPen, QPixmap)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QApplication, QButtonGroup, QComboBox, QFileDialog,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSlider,
    QStackedWidget, QVBoxLayout, QWidget,
)

APP_NAME = "Audio Extractor"
APP_VERSION = "2.1"
VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".m4v", ".mpg", ".mpeg",
             ".ts", ".m2ts", ".mts", ".3gp", ".ogv", ".vob", ".mxf", ".divx", ".asf"}
IMAGE_EXT = {".jpg", ".jpeg", ".jfif", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".avif"}
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
ACCENT = "#6366f1"
THUMB_W, THUMB_H = 120, 68

ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><defs>
<linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#6366f1"/>
<stop offset="1" stop-color="#a855f7"/></linearGradient></defs>
<rect x="2" y="2" width="60" height="60" rx="15" fill="url(#g)"/>
<g stroke="#fff" stroke-width="4.5" stroke-linecap="round">
<line x1="15" y1="27" x2="15" y2="37"/><line x1="23.5" y1="19" x2="23.5" y2="45"/>
<line x1="32" y1="23" x2="32" y2="41"/><line x1="40.5" y1="14" x2="40.5" y2="50"/>
<line x1="49" y1="25" x2="49" y2="39"/></g></svg>"""

DROP_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" fill="none" stroke="#7c83f6"
stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
<rect x="5" y="9" width="38" height="30" rx="5"/><path d="M5 17h38M13 9l4 8M23 9l4 8M33 9l4 8"/>
<path d="M24 34v-10M19.5 28.5L24 24l4.5 4.5"/></svg>"""

AUDIO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" fill="none" stroke="#5c6275"
stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">
<path d="M18 34V12l20-4v22"/><circle cx="13" cy="34" r="5"/><circle cx="33" cy="30" r="5"/></svg>"""

ARROW_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M1.5 3.5l3.5 3.5 3.5-3.5"
fill="none" stroke="#8b91a3" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>"""


# --------------------------------------------------------------------------- #
#  Formati
# --------------------------------------------------------------------------- #
@dataclass
class Quality:
    label: str
    args: list[str]
    kbps: int | None = None


@dataclass
class Mode:
    short: str           # etichetta del selettore (CBR / VBR)
    title: str           # titolo del campo qualità
    qualities: list[Quality]
    default: int = 0


@dataclass
class Format:
    key: str
    title: str
    tag: str
    ext: str
    codec: list[str]
    modes: list[Mode]
    rates: list[int] = field(default_factory=list)
    note: str = ""


def cbr(values, default):
    return Mode("CBR", "Bitrate", [Quality(f"{v} kbps", ["-b:a", f"{v}k"], v) for v in values],
                values.index(default))


FORMATS: list[Format] = [
    Format("mp3", "MP3", "Lossy · universale", "mp3", ["-c:a", "libmp3lame"], [
        cbr([64, 96, 128, 160, 192, 224, 256, 320], 320),
        Mode("VBR", "Qualità variabile", [
            Quality(f"V{q}  ·  ~{k} kbps", ["-q:a", str(q)], k)
            for q, k in [(0, 245), (1, 225), (2, 190), (3, 175), (4, 165), (5, 130), (6, 115), (7, 100)]
        ]),
    ], rates=[32000, 44100, 48000], note="Si apre ovunque: auto, telefoni, lettori, browser."),
    Format("aac", "AAC", "Lossy · .m4a", "m4a", ["-c:a", "aac"], [
        cbr([96, 128, 160, 192, 256, 320], 256),
    ], rates=[22050, 32000, 44100, 48000, 96000], note="Più efficiente dell'MP3 a parità di peso. Nativo su Apple."),
    Format("opus", "Opus", "Lossy · efficiente", "opus", ["-c:a", "libopus"], [
        cbr([32, 48, 64, 96, 128, 160, 192, 256], 160),
    ], rates=[], note="Il codec lossy migliore oggi. Lavora sempre a 48 kHz."),
    Format("vorbis", "Vorbis", "Lossy · .ogg", "ogg", ["-c:a", "libvorbis"], [
        Mode("VBR", "Qualità variabile", [
            Quality(f"q{q}  ·  ~{k} kbps", ["-q:a", str(q)], k)
            for q, k in [(3, 112), (4, 128), (5, 160), (6, 192), (7, 224), (8, 256), (9, 320), (10, 500)]
        ], default=3),
    ], rates=[22050, 32000, 44100, 48000], note="Formato aperto, molto usato nei videogiochi."),
    Format("ac3", "AC3", "Lossy · Dolby", "ac3", ["-c:a", "ac3"], [
        cbr([192, 256, 384, 448, 640], 448),
    ], rates=[32000, 44100, 48000], note="Dolby Digital: mantiene il 5.1. Non supporta copertine."),
    Format("flac", "FLAC", "Lossless", "flac", ["-c:a", "flac", "-compression_level", "8"], [
        Mode("—", "Profondità bit", [
            Quality("16 bit", ["-sample_fmt", "s16"]),
            Quality("24 bit", ["-sample_fmt", "s32", "-bits_per_raw_sample", "24"]),
        ]),
    ], rates=[44100, 48000, 88200, 96000, 192000], note="Senza perdita, circa metà del peso di un WAV."),
    Format("wav", "WAV", "Non compresso", "wav", [], [
        Mode("—", "Profondità bit", [
            Quality("16 bit PCM", ["-c:a", "pcm_s16le"]),
            Quality("24 bit PCM", ["-c:a", "pcm_s24le"]),
            Quality("32 bit float", ["-c:a", "pcm_f32le"]),
        ]),
    ], rates=[44100, 48000, 88200, 96000, 192000], note="Audio grezzo per l'editing. Non supporta copertine."),
    Format("alac", "ALAC", "Lossless · Apple", "m4a", ["-c:a", "alac"], [
        Mode("—", "Profondità bit", [
            Quality("16 bit", ["-sample_fmt", "s16p"]),
            Quality("24 bit", ["-sample_fmt", "s32p", "-bits_per_raw_sample", "24"]),
        ]),
    ], rates=[44100, 48000, 88200, 96000, 192000], note="Senza perdita, per iPhone, iTunes e Apple Music."),
    Format("copy", "Originale", "Copia diretta", "", ["-c:a", "copy"], [
        Mode("—", "Qualità", [Quality("Identica alla sorgente", [])]),
    ], rates=[], note="Estrae la traccia così com'è: istantaneo e senza perdita di qualità."),
]
FORMAT_BY_KEY = {f.key: f for f in FORMATS}

COPY_EXT = {"aac": "m4a", "mp3": "mp3", "opus": "opus", "vorbis": "ogg", "flac": "flac", "ac3": "ac3",
            "eac3": "eac3", "alac": "m4a", "dts": "dts", "truehd": "thd", "mp2": "mp2"}
COVER_BY_EXT = {"mp3": "id3", "m4a": "attached", "flac": "attached", "opus": "vorbis", "ogg": "vorbis"}


# --------------------------------------------------------------------------- #
#  ffmpeg
# --------------------------------------------------------------------------- #
def find_ffmpeg() -> str | None:
    here = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    for c in (here / exe, Path(sys.executable).parent / exe,
              Path(r"C:\ffmpeg\ffmpeg.exe"), Path(r"C:\ffmpeg\bin\ffmpeg.exe")):
        if c.is_file():
            return str(c)
    return shutil.which("ffmpeg")


@dataclass
class AudioTrack:
    index: int
    codec: str
    desc: str


@dataclass(eq=False)
class Job:
    path: Path
    duration: float = 0.0
    tracks: list[AudioTrack] = field(default_factory=list)
    has_video: bool = False
    width: int = 0
    height: int = 0
    thumb: Path | None = None
    error: str = ""
    cover_pos: float = 0.2
    aspect: float = 16 / 9       # proporzioni reali del fotogramma (SAR corretto)
    cx: float = 0.5              # centro dell'inquadratura (0..1 sul fotogramma)
    cy: float = 0.5
    zoom: float = 1.0
    output: Path | None = None
    row: "QueueRow | None" = None
    cover_from: "Job | None" = None   # copertina condivisa: presa da un altro video
    image: Path | None = None         # immagine esterna usata al posto del fotogramma
    frame_aspect: float = 16 / 9      # proporzioni del video, ripristinate togliendo l'immagine


def cover_owner(job: Job) -> Job:
    return job.cover_from or job


def cover_source(o: Job) -> tuple[Path, float | None] | None:
    """Da dove prendere la copertina: (file, istante) — istante None per un'immagine."""
    if o.image:
        return o.image, None
    if o.has_video:
        return o.path, min(o.cover_pos * o.duration, max(o.duration - 0.1, 0))
    return None


DUR_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
AUDIO_RE = re.compile(r"Stream #0:(\d+)(?:\[[^\]]*\])?(?:\((\w+)\))?: Audio: ([^\n]+)")
VIDEO_RE = re.compile(r"Stream #0:\d+[^:\n]*: Video: ([^\n]+)")


def run_quiet(args: list[str], timeout=60) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          creationflags=NO_WINDOW, timeout=timeout)


SAR_FIX = "scale='trunc(iw*sar/2)*2':ih,setsar=1"
MAX_ZOOM = 6.0


def crop_rect(aspect: float, square: bool, cx: float, cy: float, zoom: float):
    """Rettangolo di ritaglio normalizzato (x, y, w, h) sul fotogramma, già limitato ai bordi.
    Restituisce anche il centro corretto (cx, cy)."""
    target = 1.0 if square else aspect
    if aspect > target:              # fotogramma più largo dell'inquadratura
        w, h = target / aspect, 1.0
    else:                            # fotogramma più alto (es. 9:16 in quadrato)
        w, h = 1.0, aspect / target
    z = min(max(zoom, 1.0), MAX_ZOOM)
    w, h = w / z, h / z
    cx = min(max(cx, w / 2), 1 - w / 2)
    cy = min(max(cy, h / 2), 1 - h / 2)
    return (cx - w / 2, cy - h / 2, w, h), cx, cy


def cover_filter(job: "Job", square: bool, max_side: int) -> str:
    (x, y, w, h), _, _ = crop_rect(job.aspect, square, job.cx, job.cy, job.zoom)
    vf = SAR_FIX
    if w < 0.9999 or h < 0.9999:
        vf += f",crop=iw*{w:.6f}:ih*{h:.6f}:iw*{x:.6f}:ih*{y:.6f}"
    if square:
        vf += f",scale='min({max_side},iw)':'min({max_side},iw)':flags=lanczos"
    else:
        vf += f",scale='min({max_side},iw)':-2:flags=lanczos"
    return vf


def frame_args(src: Path, t: float | None, vf: str, out: Path, q=2) -> list[str]:
    seek = [] if t is None else ["-ss", f"{max(t, 0):.3f}"]
    # format=yuvj420p: anche PNG/WebP con trasparenza o palette diventano un jpg compatibile
    return ["-hide_banner", "-loglevel", "error", "-y", *seek, "-i", str(src),
            "-frames:v", "1", "-an", "-sn", "-vf", vf + ",format=yuvj420p", "-q:v", str(q),
            "-update", "1", str(out)]


def image_aspect(ffmpeg: str, path: Path) -> float | None:
    """Proporzioni di un'immagine (con SAR) letta da ffmpeg; None se non è un'immagine valida."""
    try:
        out = run_quiet([ffmpeg, "-hide_banner", "-i", str(path)], 15).stderr
    except Exception:  # noqa: BLE001
        return None
    m = re.search(r"Video: .*?, (\d{1,5})x(\d{1,5})(?:\s*\[SAR (\d+):(\d+))?", out)
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    sar = int(m.group(3)) / int(m.group(4)) if m.group(3) and int(m.group(4)) else 1.0
    return (w * (sar or 1.0)) / h if h else None


def probe(ffmpeg: str, path: Path, tmp: Path) -> Job:
    job = Job(path)
    try:
        out = run_quiet([ffmpeg, "-hide_banner", "-i", str(path)], 30).stderr
    except Exception as e:  # noqa: BLE001
        job.error = str(e)
        return job
    if m := DUR_RE.search(out):
        h, mi, s = m.groups()
        job.duration = int(h) * 3600 + int(mi) * 60 + float(s)
    for m in AUDIO_RE.finditer(out):
        idx, lang, info = m.groups()
        codec = info.split()[0].rstrip(",")
        parts = [p.strip() for p in info.split(",")]
        bits = [codec.upper()]
        for p in parts:
            if "Hz" in p:
                try:
                    bits.append(f"{int(p.split()[0]) / 1000:g} kHz")
                except ValueError:
                    bits.append(p)
            elif p in ("mono", "stereo") or p.startswith(("5.1", "7.1", "quad")):
                bits.append(p)
            elif "kb/s" in p:
                bits.append(p.replace(" (default)", "").replace("kb/s", "kbps"))
        if lang and lang != "und":
            bits.insert(0, lang.upper())
        job.tracks.append(AudioTrack(int(idx), codec, "  ·  ".join(bits)))
    for m in VIDEO_RE.finditer(out):
        if "attached pic" in m.group(1):
            continue
        job.has_video = True
        if r := re.search(r"\b(\d{2,5})x(\d{2,5})\b", m.group(1)):
            job.width, job.height = int(r.group(1)), int(r.group(2))
        break
    if not job.tracks:
        job.error = "Nessuna traccia audio"
    if job.has_video:
        thumb = tmp / f"thumb_{uuid.uuid4().hex}.jpg"
        vf = "scale='trunc(iw*sar/2)*2':ih,setsar=1,scale=360:-2"
        for t in (job.duration * 0.2, 0):
            try:
                run_quiet([ffmpeg] + frame_args(path, t, vf, thumb, 4), 30)
            except Exception:  # noqa: BLE001
                pass
            if thumb.is_file() and thumb.stat().st_size:
                job.thumb = thumb
                img = QImage(str(thumb))
                if not img.isNull() and img.height():
                    job.aspect = img.width() / img.height()
                break
        if not job.thumb and job.width and job.height:
            job.aspect = job.width / job.height
    return job


class ProbeWorker(QObject):
    probed = Signal(object)
    finished = Signal()

    def __init__(self, ffmpeg: str, paths: list[Path], tmp: Path):
        super().__init__()
        self.ffmpeg, self.paths, self.tmp = ffmpeg, paths, tmp

    def run(self):
        for p in self.paths:
            self.probed.emit(probe(self.ffmpeg, p, self.tmp))
        self.finished.emit()


def fmt_time(sec: float) -> str:
    sec = int(round(sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_size(mb: float) -> str:
    if mb >= 1024:
        return f"{mb / 1024:.2f} GB"
    return f"{mb:.1f} MB" if mb >= 1 else f"{mb * 1024:.0f} KB"


def unique_path(p: Path) -> Path:
    if not p.exists():
        return p
    i = 1
    while (q := p.with_name(f"{p.stem} ({i}){p.suffix}")).exists():
        i += 1
    return q


def ffmeta_escape(s: str) -> str:
    for ch in "\\=;#\n":
        s = s.replace(ch, "\\" + ch)
    return s


def vorbis_picture_block(jpg: Path) -> str:
    """METADATA_BLOCK_PICTURE (FLAC picture block in base64) per Ogg/Opus."""
    data = jpg.read_bytes()
    img = QImage(str(jpg))
    mime = b"image/jpeg"
    blk = (struct.pack(">II", 3, len(mime)) + mime + struct.pack(">I", 0)
           + struct.pack(">IIII", img.width(), img.height(), 24, 0)
           + struct.pack(">I", len(data)) + data)
    return base64.b64encode(blk).decode("ascii")


# --------------------------------------------------------------------------- #
#  Grafica
# --------------------------------------------------------------------------- #
def dpr() -> float:
    s = QApplication.primaryScreen()
    return s.devicePixelRatio() if s else 1.0


def svg_pixmap(svg: str, w: int, h: int | None = None) -> QPixmap:
    h = h or w
    r = dpr()
    img = QImage(int(w * r), int(h * r), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    QSvgRenderer(QByteArray(svg.encode())).render(p)
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(r)
    return pm


def rounded_cover(src: QPixmap | None, w: int, h: int, radius=8, fill=False) -> QPixmap:
    r = dpr()
    out = QPixmap(int(w * r), int(h * r))
    out.setDevicePixelRatio(r)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
    p.setClipPath(path)
    p.fillRect(QRectF(0, 0, w, h), QColor("#1b1e27"))
    if src and not src.isNull():
        mode = Qt.KeepAspectRatioByExpanding if fill else Qt.KeepAspectRatio
        s = src.scaled(int(w * r), int(h * r), mode, Qt.SmoothTransformation)
        s.setDevicePixelRatio(r)
        sw, sh = s.width() / r, s.height() / r
        p.drawPixmap(QRectF((w - sw) / 2, (h - sh) / 2, sw, sh), s, QRectF(s.rect()))
    else:
        ic = svg_pixmap(AUDIO_SVG, 26)
        p.drawPixmap(int((w - 26) / 2), int((h - 26) / 2), ic)
    p.end()
    return out


def repolish(w: QWidget):
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


STYLE = """
* { font-family: 'Segoe UI Variable Text', 'Segoe UI', sans-serif; font-size: 10pt; color: #e7e9ee; outline: none; }
QMainWindow, #leftPane { background: #0e1015; }
#sidebar { background: #14171f; border-left: 1px solid #222632; }
#sharedBox { background: rgba(99,102,241,0.10); border: 1px solid rgba(99,102,241,0.35); border-radius: 8px; }
#sharedText { color: #c7cbff; font-size: 9pt; }
#sideInner, QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
#actionBar { background: #171a23; border-top: 1px solid #222632; border-left: 1px solid #222632; }

#appTitle { font-size: 16pt; font-weight: 700; }
#appSub { color: #8b91a3; }
#sectionTitle { color: #8b91a3; font-size: 8.5pt; font-weight: 700; letter-spacing: 1.3px; }
#fieldLabel { color: #aeb3c2; font-size: 9pt; }
#hint { color: #7f8597; font-size: 9pt; }
#warn { color: #f5b452; font-size: 9pt; }
#countLabel { color: #8b91a3; font-size: 9pt; }
#summary { color: #aeb3c2; font-size: 9pt; }
#estimate { color: #a5b4fc; font-weight: 700; }
#statusText { color: #8b91a3; font-size: 9pt; }
#divider { background: #222632; min-height: 1px; max-height: 1px; border: none; }

QComboBox, QLineEdit {
    background: #1c2029; border: 1px solid #2b303e; border-radius: 8px; padding: 6px 10px; min-height: 20px;
}
QComboBox:hover, QLineEdit:hover { border-color: #3d4356; }
QComboBox:focus, QLineEdit:focus { border-color: #6366f1; }
QComboBox:disabled, QLineEdit:disabled { color: #5c6275; background: #171a22; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox::down-arrow { image: url(%ARROW%); width: 10px; height: 10px; }
QComboBox QAbstractItemView {
    background: #1c2029; border: 1px solid #2b303e; padding: 4px; selection-background-color: #34378f;
}

QPushButton {
    background: #1c2029; border: 1px solid #2b303e; border-radius: 8px; padding: 7px 14px; color: #dfe2ea;
}
QPushButton:hover { background: #232836; border-color: #3d4356; }
QPushButton:pressed { background: #191c25; }
QPushButton:disabled { color: #555b6c; background: #171a22; border-color: #222632; }
QPushButton#ghost { background: transparent; border-color: transparent; color: #aeb3c2; }
QPushButton#ghost:hover { background: #1c2029; color: #e7e9ee; }
QPushButton#ghost:disabled { color: #4a5060; background: transparent; }
QPushButton#accentSoft { background: rgba(99,102,241,0.14); border: 1px solid rgba(99,102,241,0.45); color: #c7cbff; font-weight: 600; }
QPushButton#accentSoft:hover { background: rgba(99,102,241,0.24); }
QPushButton#primary {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #6366f1, stop:1 #8b5cf6);
    border: none; border-radius: 10px; color: white; font-weight: 700; font-size: 10.5pt; padding: 11px 20px;
}
QPushButton#primary:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #7477f4, stop:1 #9a6ff7); }
QPushButton#primary:disabled { background: #252a3a; color: #6b7187; }
QPushButton#danger { background: rgba(248,113,113,0.12); border: 1px solid rgba(248,113,113,0.4); color: #fca5a5;
    border-radius: 10px; font-weight: 700; padding: 11px 20px; }
QPushButton#danger:hover { background: rgba(248,113,113,0.2); }

QPushButton#seg { background: #1c2029; border: 1px solid #2b303e; border-radius: 0; padding: 6px 10px; color: #aeb3c2; }
QPushButton#seg[pos="first"] { border-top-left-radius: 8px; border-bottom-left-radius: 8px; }
QPushButton#seg[pos="last"] { border-top-right-radius: 8px; border-bottom-right-radius: 8px; }
QPushButton#seg[pos="only"] { border-radius: 8px; }
QPushButton#seg:hover { color: #e7e9ee; }
QPushButton#seg:checked { background: rgba(99,102,241,0.2); border-color: #6366f1; color: #ffffff; font-weight: 600; }
QPushButton#seg:disabled { color: #4a5060; }

QPushButton#rowRemove { background: transparent; border: none; color: #5f6578; font-size: 11pt; padding: 4px 8px; border-radius: 6px; }
QPushButton#rowRemove:hover { color: #f87171; background: rgba(248,113,113,0.12); }
QPushButton#rowRemove:disabled { color: transparent; }

QListWidget#queue { background: transparent; border: none; }
QListWidget#queue::item { background: #151821; border: 1px solid #1f2330; border-radius: 12px; }
QListWidget#queue::item:hover { background: #181b25; border-color: #2a2f3e; }
QListWidget#queue::item:selected { background: #1a1d2b; border: 1px solid #4b4fd0; }
QListWidget#queue[drag="true"] { background: rgba(99,102,241,0.05); border: 2px dashed #6366f1; border-radius: 14px; }
#row { background: transparent; }
#rowTitle { font-weight: 600; font-size: 10.5pt; }
#rowMeta { color: #8b91a3; font-size: 9pt; }
#rowTrack { color: #aeb3c2; font-size: 9pt; }
#rowWarn { color: #f5b452; font-size: 9pt; }
QComboBox#rowCombo { padding: 3px 8px; font-size: 9pt; min-height: 18px; border-radius: 6px; }

#badge { border-radius: 10px; padding: 3px 10px; font-size: 8.5pt; font-weight: 600; color: #aeb3c2; background: #222632; }
#badge[state="run"] { color: #c7cbff; background: rgba(99,102,241,0.18); }
#badge[state="ok"] { color: #4ade80; background: rgba(74,222,128,0.12); }
#badge[state="err"] { color: #f87171; background: rgba(248,113,113,0.12); }
#badge[state="warn"] { color: #f5b452; background: rgba(245,180,82,0.12); }

#dropZone { border: 2px dashed #2b303e; border-radius: 18px; background: #12141b; }
#dropZone[drag="true"] { border-color: #6366f1; background: rgba(99,102,241,0.07); }
#dropTitle { font-size: 14pt; font-weight: 700; }
#dropSub { color: #7f8597; }

QProgressBar { background: #232733; border: none; border-radius: 3px; }
QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #6366f1, stop:1 #a855f7); border-radius: 3px; }
QProgressBar#mini { min-height: 4px; max-height: 4px; border-radius: 2px; }
QProgressBar#mini::chunk { border-radius: 2px; }
QProgressBar#overall { min-height: 6px; max-height: 6px; }

QSlider::groove:horizontal { height: 4px; background: #2b303e; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #6366f1; border-radius: 2px; }
QSlider::handle:horizontal { background: #ffffff; width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; }
QSlider::handle:horizontal:hover { background: #e0e1ff; }
QSlider::sub-page:horizontal:disabled { background: #3a3f50; }
QSlider::handle:horizontal:disabled { background: #555b6c; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #2b303e; border-radius: 3px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #3d4356; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QToolTip { background: #1c2029; color: #e7e9ee; border: 1px solid #2b303e; padding: 6px 8px; }
QMessageBox { background: #14171f; }
"""


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

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._refresh()

    def _refresh(self):
        QLabel.setText(self, self.fontMetrics().elidedText(self._full, self._mode, max(self.width(), 30)))


class Toggle(QAbstractButton):
    def __init__(self, checked=False):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(38, 22)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on, en = self.isChecked(), self.isEnabled()
        track = QColor(ACCENT if on else "#343949")
        if not en:
            track.setAlpha(90)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, 38, 22), 11, 11)
        knob = QColor("#ffffff" if en else "#8b91a3")
        p.setBrush(knob)
        x = 19 if on else 3
        p.drawEllipse(QRectF(x, 3, 16, 16))


class FormatTile(QAbstractButton):
    def __init__(self, fmt: Format):
        super().__init__()
        self.fmt = fmt
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(54)
        self.setToolTip(fmt.note)

    def sizeHint(self):
        return QSize(100, 54)

    def enterEvent(self, e):
        self.update(); super().enterEvent(e)

    def leaveEvent(self, e):
        self.update(); super().leaveEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        on = self.isChecked()
        if on:
            bg, border = QColor(99, 102, 241, 46), QColor(ACCENT)
        elif self.underMouse() and self.isEnabled():
            bg, border = QColor("#21252f"), QColor("#3d4356")
        else:
            bg, border = QColor("#1a1d26"), QColor("#2a2f3c")
        p.setPen(QPen(border, 1.5 if on else 1))
        p.setBrush(bg)
        p.drawRoundedRect(r, 10, 10)
        f = self.font()
        f.setPointSizeF(10.5); f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#ffffff" if on else "#e7e9ee") if self.isEnabled() else QColor("#5c6275"))
        p.drawText(r.adjusted(12, 7, -6, -r.height() / 2), Qt.AlignLeft | Qt.AlignBottom, self.fmt.title)
        f.setPointSizeF(8); f.setBold(False)
        p.setFont(f)
        p.setPen(QColor("#b4b8ff" if on else "#7f8597"))
        p.drawText(r.adjusted(12, r.height() / 2 + 2, -6, -6), Qt.AlignLeft | Qt.AlignTop, self.fmt.tag)


class Segmented(QWidget):
    changed = Signal(int)

    def __init__(self, labels: list[str]):
        super().__init__()
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
            b = QPushButton(text, objectName="seg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.setProperty("pos", "only" if n == 1 else "first" if i == 0 else "last" if i == n - 1 else "mid")
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
        self.setFixedHeight(240)
        self.setMouseTracking(True)
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
        j, pix = self.job, self.pix
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
        p.setPen(QPen(QColor("#232733"), 1))
        p.setBrush(QColor("#0b0d12"))
        p.drawPath(frame)
        if not (self.job and self.pix and not self.pix.isNull()):
            p.setPen(QColor("#5c6275"))
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
        p.fillPath(outside.subtracted(hole), QColor(8, 9, 13, 185))
        p.restore()
        # bordo + griglia dei terzi durante lo spostamento
        if self.dragging:
            p.setPen(QPen(QColor(255, 255, 255, 70), 1))
            for k in (1, 2):
                xk = vp.left() + vp.width() * k / 3
                yk = vp.top() + vp.height() * k / 3
                p.drawLine(int(xk), int(vp.top()), int(xk), int(vp.bottom()))
                p.drawLine(int(vp.left()), int(yk), int(vp.right()), int(yk))
        p.setPen(QPen(QColor(255, 255, 255, 220 if self.isEnabled() else 60), 1.5))
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
            p.fillPath(frame, QColor(14, 16, 21, 150))
        self._paint_loading(p, r)

    def _pill(self, p: QPainter, rect: QRectF, text: str):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 150))
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        p.setPen(QColor("#e7e9ee"))
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
        self.setCursor(Qt.PointingHandCursor)
        v = QVBoxLayout(self)
        v.setAlignment(Qt.AlignCenter)
        v.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(svg_pixmap(DROP_SVG, 64))
        ic.setAlignment(Qt.AlignCenter)
        t = QLabel("Trascina qui i tuoi video", objectName="dropTitle")
        t.setAlignment(Qt.AlignCenter)
        s = QLabel("Anche intere cartelle  ·  MP4, MKV, MOV, AVI, WEBM e molti altri", objectName="dropSub")
        s.setAlignment(Qt.AlignCenter)
        b = QPushButton("Scegli file", objectName="accentSoft")
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(self.clicked.emit)
        v.addWidget(ic); v.addWidget(t); v.addWidget(s); v.addSpacing(8)
        v.addWidget(b, 0, Qt.AlignCenter)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()


class QueueRow(QWidget):
    remove_requested = Signal(object)

    def __init__(self, job: Job):
        super().__init__(objectName="row")
        self.job = job
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 10, 8, 10)
        h.setSpacing(14)

        self.thumb = QLabel()
        self.thumb.setFixedSize(THUMB_W, THUMB_H)
        src = QPixmap(str(job.thumb)) if job.thumb else None
        self.thumb.setPixmap(rounded_cover(src, THUMB_W, THUMB_H, 8, fill=True))
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
            self.track.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            self.track.setMaximumWidth(380)
            v.addWidget(self.track, 0, Qt.AlignLeft)
        elif job.tracks:
            v.addWidget(ElidedLabel("♪  " + job.tracks[0].desc, Qt.ElideRight, objectName="rowTrack"))
        else:
            v.addWidget(QLabel("⚠  " + (job.error or "Nessuna traccia audio"), objectName="rowWarn"))
        h.addLayout(v, 1)

        right = QVBoxLayout()
        right.setSpacing(6)
        right.addStretch()
        self.badge = QLabel(objectName="badge")
        self.badge.setAlignment(Qt.AlignCenter)
        self.bar = QProgressBar(objectName="mini")
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedWidth(120)
        self.bar.hide()
        right.addWidget(self.badge, 0, Qt.AlignRight)
        right.addWidget(self.bar, 0, Qt.AlignRight)
        right.addStretch()
        h.addLayout(right)

        self.btn_rm = QPushButton("✕", objectName="rowRemove")
        self.btn_rm.setCursor(Qt.PointingHandCursor)
        self.btn_rm.setToolTip("Rimuovi dalla coda")
        self.btn_rm.clicked.connect(lambda: self.remove_requested.emit(self.job))
        h.addWidget(self.btn_rm, 0, Qt.AlignVCenter)

        if job.tracks:
            self.set_state("idle", "Pronto")
        else:
            self.set_state("warn", "Saltato")

    def track_index(self) -> int | None:
        if self.track:
            return self.track.currentData()
        return self.job.tracks[0].index if self.job.tracks else None

    def set_state(self, state: str, text: str, tip: str = ""):
        self.badge.setText(text)
        self.badge.setToolTip(tip)
        self.badge.setProperty("state", state)
        repolish(self.badge)
        self.bar.setVisible(state == "run")
        if state != "run":
            self.bar.setValue(0)

    def set_progress(self, frac: float):
        self.bar.setValue(int(frac * 1000))

    def set_busy(self, busy: bool):
        self.btn_rm.setEnabled(not busy)
        if self.track:
            self.track.setEnabled(not busy)


# --------------------------------------------------------------------------- #
#  Finestra principale
# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    def __init__(self, ffmpeg: str, tmp: Path):
        super().__init__()
        self.ffmpeg, self.tmp = ffmpeg, tmp
        self.settings = QSettings("AudioExtractor", os.environ.get("AE_PROFILE", "AudioExtractor"))
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
        self.setWindowIcon(QIcon(svg_pixmap(ICON_SVG, 256)))
        self.setMinimumSize(1060, 680)
        avail = (QApplication.primaryScreen().availableGeometry() if QApplication.primaryScreen() else None)
        w, h = 1380, 752
        if avail:
            w, h = min(w, avail.width() - 20), min(h, avail.height() - 50)
        self.resize(w, h)
        if avail:
            self.move(avail.center().x() - w // 2, avail.center().y() - (h + 30) // 2)
        self.setAcceptDrops(True)

        root = QWidget()
        self.setCentralWidget(root)
        rl = QHBoxLayout(root)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(self.build_left(), 1)
        rl.addWidget(self.build_sidebar())

        self.load_settings()
        self.refresh_queue_ui()

    # ================================================================ layout
    def build_left(self) -> QWidget:
        w = QWidget(objectName="leftPane")
        v = QVBoxLayout(w)
        v.setContentsMargins(28, 22, 22, 18)
        v.setSpacing(16)

        head = QHBoxLayout()
        head.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(svg_pixmap(ICON_SVG, 40))
        head.addWidget(logo)
        tv = QVBoxLayout()
        tv.setSpacing(0)
        tv.addWidget(QLabel(APP_NAME, objectName="appTitle"))
        tv.addWidget(QLabel("Estrai l'audio dai video, con copertina inclusa.", objectName="appSub"))
        head.addLayout(tv)
        head.addStretch()
        self.btn_about = QPushButton("Informazioni", objectName="ghost")
        self.btn_about.setCursor(Qt.PointingHandCursor)
        self.btn_about.clicked.connect(self.show_about)
        head.addWidget(self.btn_about)
        self.btn_add_dir = QPushButton("Aggiungi cartella", objectName="ghost")
        self.btn_add_dir.clicked.connect(self.pick_folder)
        self.btn_add = QPushButton("＋  Aggiungi video", objectName="accentSoft")
        self.btn_add.clicked.connect(self.pick_files)
        for b in (self.btn_add_dir, self.btn_add):
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
        self.list.currentRowChanged.connect(self.on_current_changed)
        self.list.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.stack.addWidget(self.list)
        v.addWidget(self.stack, 1)

        foot = QHBoxLayout()
        self.lbl_count = QLabel("", objectName="countLabel")
        foot.addWidget(self.lbl_count)
        foot.addStretch()
        self.btn_clear_done = QPushButton("Rimuovi completati", objectName="ghost")
        self.btn_clear_done.clicked.connect(self.clear_done)
        self.btn_clear = QPushButton("Svuota coda", objectName="ghost")
        self.btn_clear.clicked.connect(self.clear_list)
        for b in (self.btn_clear_done, self.btn_clear):
            b.setCursor(Qt.PointingHandCursor)
            foot.addWidget(b)
        v.addLayout(foot)
        return w

    def show_about(self):
        base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        lic = base / "licenses"
        box = QMessageBox(self)
        box.setWindowTitle(f"Informazioni su {APP_NAME}")
        box.setIconPixmap(svg_pixmap(ICON_SVG, 56))
        box.setTextFormat(Qt.RichText)
        box.setText(f"<b style='font-size:13pt'>{APP_NAME}</b><br>Versione {APP_VERSION}<br><br>"
                    "© 2026 Cesa028 — software gratuito con licenza MIT.")
        box.setInformativeText(
            "Include componenti open source:<br>"
            "• <a href='https://ffmpeg.org'>FFmpeg</a> — GPL v3 "
            "(<a href='https://github.com/FFmpeg/FFmpeg/tree/469aad3897'>sorgenti</a>)<br>"
            "• <a href='https://www.qt.io'>Qt 6</a> / PySide6 — LGPL v3<br>"
            "• <a href='https://www.python.org'>Python</a> — PSF License<br><br>"
            "I testi completi delle licenze sono nella cartella «licenses» del programma.")
        btn_lic = box.addButton("Apri licenze", QMessageBox.ActionRole) if lic.is_dir() else None
        box.addButton(QMessageBox.Close)
        box.exec()
        if btn_lic is not None and box.clickedButton() is btn_lic:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(lic)))

    def section(self, title: str, lay: QVBoxLayout, right: QWidget | None = None) -> QVBoxLayout:
        if lay.count():
            lay.addSpacing(6)
            d = QFrame(objectName="divider")
            lay.addWidget(d)
            lay.addSpacing(6)
        h = QHBoxLayout()
        h.addWidget(QLabel(title.upper(), objectName="sectionTitle"))
        h.addStretch()
        if right:
            h.addWidget(right)
        lay.addLayout(h)
        body = QVBoxLayout()
        body.setSpacing(8)
        lay.addLayout(body)
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

        scroll = QScrollArea()
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
        self.seg_mode = Segmented(["CBR", "VBR"])
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
        self.btn_image = QPushButton("🖼  Carica immagine…", objectName="ghost")
        self.btn_image.setToolTip("Usa un'immagine dal PC (jpg, png, webp…) al posto del fotogramma del video.\n"
                                  "Puoi anche trascinarla nella finestra.")
        self.btn_image.setCursor(Qt.PointingHandCursor)
        self.btn_image.clicked.connect(self.pick_cover_image)
        body = self.section("Copertina", lay, self.btn_image)
        self.tg_embed = Toggle(True)
        self.tg_embed.toggled.connect(self.on_cover_settings)
        self.row_embed = self.toggle_row("Incorpora nel file audio", self.tg_embed)
        body.addWidget(self.row_embed)
        self.lbl_cover_warn = QLabel("", objectName="warn")
        self.lbl_cover_warn.setWordWrap(True)
        body.addWidget(self.lbl_cover_warn)
        self.tg_jpg = Toggle(False)
        self.tg_jpg.toggled.connect(self.on_cover_settings)
        body.addWidget(self.toggle_row("Salva anche come immagine .jpg", self.tg_jpg))
        self.cover_box = QWidget()
        cb = QVBoxLayout(self.cover_box)
        cb.setContentsMargins(0, 4, 0, 0)
        cb.setSpacing(8)
        self.seg_shape = Segmented(["Quadrata", "Proporzioni originali"])
        self.seg_shape.changed.connect(self.on_cover_settings)
        cb.addWidget(self.seg_shape)
        self.shared_box = QFrame(objectName="sharedBox")
        sb = QHBoxLayout(self.shared_box)
        sb.setContentsMargins(12, 8, 8, 8)
        sb.setSpacing(8)
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
        self.seg_dest = Segmented(["Stessa del video", "Altra cartella"])
        self.seg_dest.changed.connect(self.on_dest_changed)
        body.addWidget(self.seg_dest)
        self.dest_row = QWidget()
        dr = QHBoxLayout(self.dest_row)
        dr.setContentsMargins(0, 0, 0, 0)
        dr.setSpacing(8)
        self.ed_dest = QLineEdit()
        self.ed_dest.setPlaceholderText("Scegli una cartella…")
        self.ed_dest.textChanged.connect(lambda t: self.settings.setValue("dest", t))
        self.btn_dest = QPushButton("Sfoglia")
        self.btn_dest.setCursor(Qt.PointingHandCursor)
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
        self.btn_open = QPushButton("Apri cartella")
        self.btn_open.setCursor(Qt.PointingHandCursor)
        self.btn_open.clicked.connect(self.open_output)
        self.btn_open.setEnabled(False)
        self.btn_start = QPushButton("Estrai audio", objectName="primary")
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.clicked.connect(self.start)
        self.btn_cancel = QPushButton("Annulla", objectName="danger")
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
            if QMessageBox.question(self, APP_NAME, "Estrazione in corso. Vuoi interromperla e uscire?") \
                    != QMessageBox.Yes:
                e.ignore()
                return
            self.cancel()
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
            depth = (16, 24, 32)[min(self.cb_quality.currentIndex(), 2)]
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
            self.lbl_shared.setFullText(f"🔗  Copertina presa da «{j.cover_from.path.name}»")
        o = cover_owner(j) if j else None
        img = bool(o and o.image)
        self.image_box.setVisible(img and not shared)
        if img:
            self.lbl_image.setFullText(f"🖼  Immagine: {o.image.name}")
            self.lbl_image.setToolTip(str(o.image))
        self.frame_box.setVisible(not (o and not o.has_video) and not img)
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
            QMessageBox.information(self, APP_NAME, "Aggiungi prima un video, poi scegli l'immagine di copertina.")
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
            QMessageBox.warning(self, APP_NAME, f"Impossibile leggere l'immagine:\n{path}")
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

    def on_probed(self, job: Job):
        self._probing = max(self._probing - 1, 0)
        if any(j.path == job.path for j in self.jobs):
            self.update_status_idle()
            return
        self.jobs.append(job)
        row = QueueRow(job)
        row.remove_requested.connect(self.remove_job)
        job.row = row
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, max(row.sizeHint().height(), 90)))
        self.list.addItem(item)
        self.list.setItemWidget(item, row)
        if self.list.currentRow() < 0:
            self.list.setCurrentRow(0)
        self.refresh_queue_ui()

    def remove_job(self, job: Job):
        if self.is_running() or job not in self.jobs:
            return
        r = self.jobs.index(job)
        for x in self.jobs:
            if x.cover_from is job:
                x.cover_from = None
        self.list.takeItem(r)
        self.jobs.pop(r)
        self.refresh_queue_ui()
        self.request_preview()

    def clear_list(self):
        if self.is_running():
            return
        self.list.clear()
        self.jobs.clear()
        self.refresh_queue_ui()
        self.request_preview()

    def clear_done(self):
        if self.is_running():
            return
        for j in [j for j in self.jobs if j.output]:
            self.remove_job(j)

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
        target = j.output if j.output and j.output.exists() else j.path
        if os.name == "nt":
            subprocess.Popen(f'explorer /select,"{target}"', creationflags=NO_WINDOW)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.parent)))

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
            QMessageBox.warning(self, APP_NAME, "Scegli la cartella di destinazione.")
            return
        self.queue = [j for j in self.jobs if j.tracks]
        if not self.queue:
            return
        for j in self.jobs:
            if j.tracks:
                j.output = None
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
            job.row.set_state("err", "Errore", str(e))
            self.err_count += 1
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
        f, c = self.fmt, self.ctx
        args = ["-hide_banner", "-nostdin", "-y", "-i", str(job.path)]
        maps = ["-map", f"0:{c.track.index}"]
        meta_src = "0"
        extra: list[str] = []
        if c.embed in ("id3", "attached") and c.cover:
            args += ["-i", str(c.cover)]
            maps += ["-map", "1:0"]
            extra += ["-c:v", "copy", "-disposition:v:0", "attached_pic"]
            if c.embed == "id3":
                extra += ["-id3v2_version", "3", "-metadata:s:v", "title=Album cover",
                          "-metadata:s:v", "comment=Cover (front)"]
        elif c.embed == "vorbis" and c.cover:
            lines = [";FFMETADATA1"]
            if c.meta and c.meta.is_file():
                src = c.meta.read_text(encoding="utf-8", errors="replace").splitlines()
                lines = src if src and src[0].startswith(";FFMETADATA") else lines + src
            lines.insert(1, "METADATA_BLOCK_PICTURE=" + ffmeta_escape(vorbis_picture_block(c.cover)))
            mfile = self.tmp / f"metaout_{uuid.uuid4().hex}.txt"
            mfile.write_text("\n".join(lines) + "\n", encoding="utf-8")
            args += ["-f", "ffmetadata", "-i", str(mfile)]
            meta_src = "1"
        args += maps + ["-sn", "-dn"] + f.codec + self.quality().args + extra
        if f.key == "opus":
            args += ["-ar", "48000"]
        elif (rate := self.cb_rate.currentData()) is not None:
            args += ["-ar", str(rate)]
        if f.key != "copy" and (ch := self.cb_channels.currentData()) is not None:
            args += ["-ac", str(ch)]
        args += ["-map_metadata", meta_src, "-map_chapters", "-1",
                 "-progress", "pipe:1", "-nostats", str(c.out)]
        return args

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
                job.row.set_state("ok", f"✓  {fmt_size(size)}", tip)
            self.ok_count += 1
        else:
            err = [l for l in c.stderr.strip().splitlines() if l.strip()]
            c.out.unlink(missing_ok=True)
            job.row.set_state("err", "Errore", err[-1] if err else f"ffmpeg ha restituito {code}")
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
            if j.tracks and j.output is None and j.row.badge.property("state") not in ("err", "warn"):
                j.row.set_state("idle", "Pronto")
        self.cur = None
        self.queue.clear()
        self.set_busy(False)
        if self.cancelled:
            self.lbl_status.setFullText("Operazione annullata.")
        else:
            self.progress.setValue(1000)
            msg = f"Completato  ·  {self.ok_count} {'file estratto' if self.ok_count == 1 else 'file estratti'}"
            if self.err_count:
                msg += f"  ·  {self.err_count} errori (passa sopra a «Errore» per i dettagli)"
            self.lbl_status.setFullText(msg)
            QApplication.alert(self)
        self.refresh_queue_ui()

    def open_output(self):
        if self.last_output:
            if os.name == "nt" and self.last_output.exists():
                subprocess.Popen(f'explorer /select,"{self.last_output}"', creationflags=NO_WINDOW)
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_output.parent)))


def dark_palette() -> QPalette:
    p = QPalette()
    for role, c in [(QPalette.Window, "#0e1015"), (QPalette.WindowText, "#e7e9ee"),
                    (QPalette.Base, "#1c2029"), (QPalette.AlternateBase, "#151821"),
                    (QPalette.Text, "#e7e9ee"), (QPalette.Button, "#1c2029"),
                    (QPalette.ButtonText, "#e7e9ee"), (QPalette.Highlight, ACCENT),
                    (QPalette.HighlightedText, "#ffffff"), (QPalette.ToolTipBase, "#1c2029"),
                    (QPalette.ToolTipText, "#e7e9ee"), (QPalette.PlaceholderText, "#5c6275")]:
        p.setColor(role, QColor(c))
    return p


def main():
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AudioExtractor.App")
        except Exception:  # noqa: BLE001
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    tmp = Path(tempfile.mkdtemp(prefix="audioextractor_"))
    app.aboutToQuit.connect(lambda: shutil.rmtree(tmp, ignore_errors=True))
    arrow = tmp / "arrow.png"
    svg_pixmap(ARROW_SVG, 10).toImage().save(str(arrow))
    app.setStyleSheet(STYLE.replace("%ARROW%", arrow.as_posix()))
    app.setWindowIcon(QIcon(svg_pixmap(ICON_SVG, 256)))
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        QMessageBox.critical(None, APP_NAME, "ffmpeg non trovato.\nMettilo nel PATH, in C:\\ffmpeg "
                                             "oppure accanto a questo programma.")
        return 1
    w = MainWindow(ffmpeg, tmp)
    w.show()
    if len(sys.argv) > 1:
        w.add_paths([Path(a) for a in sys.argv[1:]])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
