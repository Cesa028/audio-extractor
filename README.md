# Audio Extractor

**Estrai l'audio dai tuoi video in pochi clic, con la copertina già incorporata.**

Audio Extractor è un'applicazione per Windows 10/11 (64 bit) con interfaccia moderna, tema chiaro e scuro (segue quello di Windows). Trascini i video nella coda, scegli formato e qualità e ottieni file audio pronti da ascoltare, con una copertina ricavata dal fotogramma del video (o da un'immagine a tua scelta). Il lavoro di conversione è affidato a [FFmpeg](https://ffmpeg.org), incluso nell'installer.

![Licenza MIT](https://img.shields.io/badge/licenza-MIT-green) ![Piattaforma](https://img.shields.io/badge/piattaforma-Windows%2010%2F11-blue) ![Python](https://img.shields.io/badge/Python-3.10%2B-yellow)

---

## Indice

- [Download](#download)
- [Funzionalità](#funzionalità)
- [Formati supportati](#formati-supportati)
- [Come si usa](#come-si-usa)
- [Eseguire dal codice sorgente](#eseguire-dal-codice-sorgente)
- [Creare l'installer](#creare-linstaller)
- [Struttura del progetto](#struttura-del-progetto)
- [Licenza e componenti di terze parti](#licenza-e-componenti-di-terze-parti)
- [English summary](#english-summary)

---

## Download

L'installer per Windows è disponibile nella sezione **[Releases](../../releases/latest)**: scarica `AudioExtractor-Setup-2.2.1.exe` ed eseguilo. L'installazione non richiede i diritti di amministratore (è comunque possibile installare per tutti gli utenti) e include già FFmpeg: non serve installare altro.

## Funzionalità

- **Coda di conversione**: aggiungi più video, anche con il trascinamento, e convertili in un'unica operazione.
- **Molti formati audio**, sia compressi (MP3, AAC, Opus, Vorbis, AC3) sia senza perdita (FLAC, WAV, ALAC), più la **copia diretta** della traccia originale senza ricodifica.
- **Qualità regolabile**: bitrate costante (CBR) o qualità variabile (VBR), profondità di bit per i formati lossless e frequenza di campionamento.
- **Canali**: mantieni quelli originali oppure converti in stereo o mono.
- **Copertina incorporata**:
  - ricavata da un fotogramma del video, scelto con un cursore;
  - oppure presa da un'immagine esterna (JPG, PNG, WebP, BMP, GIF, TIFF, AVIF);
  - ritaglio personalizzabile con anteprima, anche in forma quadrata;
  - possibilità di applicare la stessa immagine a tutti i video in coda o di personalizzare la copertina di un singolo video.
- **Miniature** dei video nella coda, con avanzamento per ogni file.
- **Tema chiaro e scuro**: di default segue Windows, si cambia dal vivo con il pulsante nell'intestazione e la scelta viene ricordata (contrasto dei testi verificato in entrambi i temi).
- **Tastiera e accessibilità**: tutto raggiungibile con Tab, focus sempre visibile, nomi accessibili per i lettori di schermo, scorciatoie (vedi sotto).
- **Finestra che ricorda** posizione e dimensione, sezioni del pannello comprimibili, messaggi non invasivi e errori in italiano con dettagli copiabili (log in `%APPDATA%\AudioExtractor`).

## Formati supportati

| Formato | Tipo | Estensione | Note |
|---|---|---|---|
| MP3 | Lossy | `.mp3` | Compatibile con qualsiasi dispositivo |
| AAC | Lossy | `.m4a` | Più efficiente dell'MP3, nativo su Apple |
| Opus | Lossy | `.opus` | Ottimo rapporto qualità/peso, lavora a 48 kHz |
| Vorbis | Lossy | `.ogg` | Formato aperto, diffuso nei videogiochi |
| AC3 | Lossy | `.ac3` | Dolby Digital, mantiene il 5.1 (senza copertina) |
| FLAC | Lossless | `.flac` | Compressione senza perdita (16 o 24 bit) |
| WAV | Lossless | `.wav` | PCM non compresso (16, 24, 32 bit PCM o 32 bit float) |
| ALAC | Lossless | `.m4a` | Apple Lossless (16 o 24 bit) |
| Copia diretta | — | varia | Estrae la traccia senza ricodificarla |

**Video in ingresso:** MP4, MKV, MOV, AVI, WebM, FLV, WMV, M4V, MPG/MPEG, TS, M2TS, MTS, 3GP, OGV, VOB, MXF, DIVX, ASF.

## Come si usa

1. Avvia **Audio Extractor** e trascina i video nella coda (oppure usa il pulsante di aggiunta).
2. Scegli il **formato** di uscita e, nel pannello delle impostazioni, bitrate o qualità, frequenza di campionamento e canali.
3. Nella sezione **Copertina** decidi se incorporarla, da quale fotogramma ricavarla o se usare un'immagine tua.
4. Avvia la conversione: i file audio vengono creati e puoi seguirne l'avanzamento nella coda.

## Scorciatoie

| Tasti | Azione |
|---|---|
| `Ctrl+O` | Aggiungi video |
| `Ctrl+Maiusc+O` | Aggiungi cartella |
| `Ctrl+Invio` | Estrai audio |
| `Esc` | Annulla l'estrazione in corso |
| `Canc` | Rimuovi dalla coda i video selezionati |
| `Ctrl+Z` | Annulla l'ultima rimozione dalla coda |
| `F1` | Informazioni, licenza e componenti di terze parti |
| Frecce | Cambiano formato / segmento selezionato; nell'anteprima spostano l'inquadratura (`+` `-` zoom, `Home` centra) |

## Eseguire dal codice sorgente

Requisiti: **Python 3.10 o superiore**, **PySide6** e **FFmpeg** raggiungibile dal `PATH`.

```bat
pip install PySide6
python audio_extractor.py
```

In alternativa puoi avviare `Audio Extractor.pyw`, che apre l'applicazione senza finestra di console.

## Creare l'installer

Servono PyInstaller, PySide6 e [Inno Setup 6](https://jrsoftware.org/isinfo.php).

```bat
pip install pyinstaller PySide6
python build.py             :: crea dist\AudioExtractor-Setup-<versione>.exe
python build.py --portable  :: crea dist\AudioExtractor.exe (file unico)
```

Lo script genera l'icona, compila l'applicazione con PyInstaller, include FFmpeg e i testi delle licenze e infine produce l'installer con lo script `installer/AudioExtractor.iss`.

## Struttura del progetto

```
AudioExtractor/
├─ audio_extractor.py      punto di ingresso (avvio, tema, gestione errori)
├─ Audio Extractor.pyw     avvio senza console
├─ common.py               costanti, percorsi, log, utilità
├─ theme.py                design token, palette scura/chiara, foglio di stile
├─ icons.py                icone SVG tematizzate e icona dell'app
├─ engine.py               formati, ffmpeg, analisi dei file, copertine, comandi
├─ widgets.py              componenti dell'interfaccia (tile, toggle, anteprima, righe coda…)
├─ dialogs.py              Informazioni, visualizzatore licenze, dettaglio errori
├─ ui.py                   finestra principale (coda, estrazione, scorciatoie)
├─ build.py                build dell'eseguibile e dell'installer
├─ installer/              script Inno Setup e pagina della licenza
├─ licenses/               testi delle licenze dei componenti di terze parti
└─ LICENSE.txt             licenza MIT del progetto
```

## Licenza e componenti di terze parti

Il codice di Audio Extractor è rilasciato con licenza **MIT** (vedi [`LICENSE.txt`](LICENSE.txt)), © 2026 Cesa028.

L'installer include software di terze parti, ciascuno con la propria licenza:

- **FFmpeg** (GPL-3.0), eseguito come programma esterno e distribuito senza modifiche;
- **Qt 6 / PySide6** (LGPL-3.0), collegato dinamicamente;
- **Python** (PSF License).

L'elenco completo, con versioni e riferimenti ai sorgenti, è in [`licenses/THIRD-PARTY-NOTICES.txt`](licenses/THIRD-PARTY-NOTICES.txt).

---

## English summary

**Audio Extractor** is a Windows 10/11 (64-bit) desktop app that extracts the audio track from video files and embeds cover art taken from a video frame or from your own image. It supports MP3, AAC, Opus, Vorbis, AC3, FLAC, WAV, ALAC and lossless stream copy, with adjustable bitrate/quality, sample rate and channel layout. The installer bundles FFmpeg. To run from source: Python 3.10+, `pip install PySide6`, FFmpeg in `PATH`, then `python audio_extractor.py`. Released under the MIT license.
