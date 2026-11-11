"""Audio Extractor - logica: formati, ffmpeg, analisi dei file, copertine, comandi di estrazione.
Nessuna interfaccia qui (a parte QImage/QObject per le miniature e il lavoro in thread)."""
from __future__ import annotations

import base64
import os
import re
import shutil
import struct
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from common import NO_WINDOW

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
            Quality("32 bit PCM", ["-c:a", "pcm_s32le"]),
            Quality("32 bit float", ["-c:a", "pcm_f32le"]),
        ]),
    ], rates=[44100, 48000, 88200, 96000, 192000], note="Audio grezzo per l'editing, fino a 32 bit. Non supporta copertine."),
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
    row: object = None                # QueueRow (interfaccia)
    detail: str = ""                  # dettaglio tecnico dell'errore (copiabile)
    track_sel: int = 0                # traccia scelta nella riga (indice nella lista tracce)
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
        job.error = "Impossibile analizzare il file"
        job.detail = str(e)
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
        job.detail = out.strip()[-3000:]
        if "Invalid data" in out or "moov atom not found" in out or not job.duration:
            job.error = "File non riconosciuto o danneggiato"
        else:
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



def friendly_error(stderr: str, code=None) -> str:
    """Messaggio comprensibile (italiano) per un errore di ffmpeg; il testo originale resta nel dettaglio."""
    t = stderr.lower()
    rules = [
        ("no space left", "Spazio su disco esaurito nella cartella di destinazione."),
        ("permission denied", "Non ho il permesso di scrivere nella cartella di destinazione."),
        ("read-only file system", "La cartella di destinazione e' in sola lettura."),
        ("invalid data found", "Il file e' danneggiato o in un formato non riconosciuto."),
        ("moov atom not found", "Il file video e' incompleto o danneggiato."),
        ("no such file", "File o cartella non trovati: e' stato spostato o eliminato?"),
        ("does not contain any stream", "La traccia scelta non contiene audio utilizzabile."),
        ("codec not currently supported", "Il formato scelto non supporta questa traccia: prova un altro formato."),
        ("could not find tag for codec", "Il formato scelto non supporta questa traccia: prova un altro formato."),
        ("error opening input", "Impossibile aprire il file video."),
    ]
    for key, msg in rules:
        if key in t:
            return msg
    return "ffmpeg non e' riuscito a estrarre l'audio da questo file."


def build_audio_args(src: Path, out: Path, *, fmt: Format, track_index: int, quality_args: list[str],
                     rate: int | None, channels: int | None, cover: Path | None, embed: str | None,
                     meta: Path | None, tmp: Path) -> list[str]:
    """Comando ffmpeg per estrarre una traccia nel formato scelto, con copertina opzionale."""
    args = ["-hide_banner", "-nostdin", "-y", "-i", str(src)]
    maps = ["-map", f"0:{track_index}"]
    meta_src = "0"
    extra: list[str] = []
    if embed in ("id3", "attached") and cover:
        args += ["-i", str(cover)]
        maps += ["-map", "1:0"]
        extra += ["-c:v", "copy", "-disposition:v:0", "attached_pic"]
        if embed == "id3":
            extra += ["-id3v2_version", "3", "-metadata:s:v", "title=Album cover",
                      "-metadata:s:v", "comment=Cover (front)"]
    elif embed == "vorbis" and cover:
        lines = [";FFMETADATA1"]
        if meta and meta.is_file():
            old = meta.read_text(encoding="utf-8", errors="replace").splitlines()
            lines = old if old and old[0].startswith(";FFMETADATA") else lines + old
        lines.insert(1, "METADATA_BLOCK_PICTURE=" + ffmeta_escape(vorbis_picture_block(cover)))
        mfile = tmp / f"metaout_{uuid.uuid4().hex}.txt"
        mfile.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
        args += ["-f", "ffmetadata", "-i", str(mfile)]
        meta_src = "1"
    args += maps + ["-sn", "-dn"] + fmt.codec + quality_args + extra
    if fmt.key == "opus":
        args += ["-ar", "48000"]
    elif rate is not None:
        args += ["-ar", str(rate)]
    if fmt.key != "copy" and channels is not None:
        args += ["-ac", str(channels)]
    args += ["-map_metadata", meta_src, "-map_chapters", "-1", "-progress", "pipe:1", "-nostats", str(out)]
    return args
