# EncoreMix 2026 — dual-deck Python mixer
Because VisualBasic is DEAD and I like shit my way.
A working first-phase desktop DJ application with:

- Two independent Qt Multimedia audio decks using Qt's FFmpeg backend
- A left playlist and a right playlist
- Separate YouTube / YouTube Music search window
- Search result thumbnails, metadata, descriptions, and direct **Add Left / Add Right** actions
- Equal-power crossfader
- Background-prepared waveforms on both decks with playheads, click/drag seeking, and live audio fallback
- Automatic transition when the dominant deck reaches 10 seconds remaining
- Optional beat-matched Auto Mix with silent incoming-deck analysis, harmonic tempo normalization, phase alignment, and fades driven by 1–8 complete bars
- Configurable 2–10 second fade time for timed mode and beat-analysis fallback
- Automatic advancement of the ended deck to its next playlist track
- Local audio-file support
- Persistent playlists and mixer settings
- An independent third karaoke video deck with YouTube-only search, a manual queue, and detachable projector output
- Reciprocal remotes: control the selected main deck from Karaoke, or karaoke playback, fades, and queue selection from the main mixer

## Desktop requirements

1. **Python 3.11 or newer, 64-bit**
2. A JavaScript runtime for YouTube extraction. Setup installs **Deno inside `.venv`** automatically; no separate system installation or `PATH` change is needed. EncoreMix also supports an existing **Node.js 22+** installation. See [yt-dlp's runtime setup guide](https://github.com/yt-dlp/yt-dlp/wiki/EJS) for details.
3. Internet access

Windows, macOS, and Linux use the same Python launcher. Install Python for your
machine's architecture and create a fresh environment on each machine; do not copy
`.venv` between computers. Linux also needs a working desktop/audio stack and
[Qt's platform libraries](https://doc.qt.io/qt-6/linux-requirements.html).
Availability of PySide6 and Deno wheels limits supported OS/CPU combinations;
setup stops if a required package cannot be installed.

## Fast start

Double-click:

```text
run_windows.bat
```

The script creates a local `.venv`, installs the packages, updates `yt-dlp` and its
matching YouTube challenge scripts and Deno runtime, and launches the application. Other packages
are updated only when needed to satisfy `requirements.txt`.

On macOS or Linux, run `python3 run.py`. On Windows, `python run.py` is also
available. Both install into `.venv` and check package consistency before launch.

Playback explicitly uses Qt's FFmpeg backend supplied with PySide6. A separate
VLC installation, FFmpeg command-line executable, or Windows Store HEVC extension
is not part of setup. HEVC playback needs a decoder, not an encoder.
Startup checks registered H.264, HEVC, VP9, AV1 and common audio decoders, an audio output device,
and a working YouTube JavaScript runtime before opening the mixer.

- `python run.py --repair`: reinstall the required packages and playback libraries.
- `python run.py --check`: set up the environment and report readiness without playback.
- `python run.py --software-video`: use CPU video decoding for laptops with GPU driver issues.
- `.venv\Scripts\python.exe main.py --check`: offline Windows readiness check;
  use `.venv/bin/python main.py --check` on macOS/Linux.

Software decoding can use more CPU, particularly for 4K video. This switch uses
[Qt's FFmpeg configuration](https://doc.qt.io/qt-6/advanced-ffmpeg-configuration.html).
Capability checks cannot prove that every codec profile, driver, projector, or
remote stream works. Verify a representative karaoke track on each target machine
before a show. System libraries and drivers are not installed automatically;
Linux deployments may need matching FFmpeg shared libraries as described in
[Qt Multimedia deployment](https://doc.qt.io/qt-6/qtmultimedia-index.html).

Manual launch:

```powershell
cd youtube_dj
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install --upgrade "yt-dlp[default,deno]"
python main.py
```

## Appearance

Press **Shift+/** (**?**) on the main screen to open Appearance, including while
fullscreen. Choose Midnight, Graphite, or Deep Ocean and customize the left/UI
accent and right deck colors. Changes apply immediately and are saved for the
next launch. **Reset to defaults** restores the original colors.

Use the main screen's **FULL SCREEN** button or **F11** for borderless fullscreen;
**Esc** restores the previous window mode.

## Updating

Close EncoreMix, then run the standalone updater from the project folder:

```powershell
.\.venv\Scripts\python.exe updater.py
```

The updater checks the canonical source repository, installs only fast-forward
updates, installs the packages in `requirements.txt`, and upgrades `yt-dlp` with
its matching YouTube challenge scripts and Deno runtime. It stops without
changing anything when the checkout contains local changes. To check without
installing, use `updater.py --check`; to leave installed packages alone, use
`updater.py --skip-dependencies`.

When setting up a laptop, use the same application source and let
`run_windows.bat` create a separate `.venv` on that machine, including Deno.
If YouTube tracks stop early or fail to start, run `run_windows.bat` again
to refresh the extractor, challenge scripts, and runtime before retrying.

The minimum supported `yt-dlp` version is **2026.8.19**. That release
[removed the old Android VR client from its defaults](https://github.com/yt-dlp/yt-dlp/releases/tag/2026.08.19).
Older extractors can resolve song metadata yet return audio URLs that YouTube
rejects with HTTP 403.

## How to use

1. Click **SEARCH MUSIC**.
2. Search YouTube, YouTube Music, or both.
3. Add results to the left or right playlist.
4. Double-click a playlist item, or press Play.
5. Move the crossfader manually, or leave **AUTO MIX** enabled.
6. With Auto Mix enabled, the opposite deck starts near the end of the dominant track; preparation begins earlier when Beat Match needs more bars.
7. After a deck finishes, it loads the next item in its own playlist and waits for its next turn.
8. Use **MAIN MIX REMOTE** in the karaoke window to choose a side, adjust its volume, pause/resume it, or move the main crossfader.
9. Use **KARAOKE REMOTE** on the main mixer to pause/resume karaoke, set its volume, or fade it in/out over the selected duration.
10. The karaoke queue is mirrored in **KARAOKE REMOTE**. Double-click an entry there to jump directly to it.
11. Leave **BEAT MATCH** enabled and choose **FADE BARS** for a beat-driven Auto Mix. Disable it to expose **FADE SECONDS** and use only the original timed crossfade.

## Random related-song searches

In the music search window, **SIMILAR TO LEFT** and **SIMILAR TO RIGHT** each
use their deck's current loaded YouTube/YouTube Music track. Each click finds up to
10 distinct random recommendations from that song's YouTube Music radio, excluding
the seed, tracks already in that deck's queue, and the previous displayed results.
Add recommendations using the usual deck buttons; searching does not change playback.

Radio recommendations supply musical similarity. Available release years and
view counts favor songs from a similar era and popularity range, but these
fields are often missing, so matching is approximate. Local files are not
supported as seeds. A paused track can also be used.

## Waveforms

Waveforms are analyzed silently as loaded and next-up audio becomes available. A single
low-priority helper process uses Qt's existing decoder, keeping analysis outside the UI
and playback processes. It reuses prepared downloads and local files; it does not download
the entire playlist. Each song is analyzed as it reaches the existing preloader.
Compact waveforms are cached across sessions in the application's cache directory
(up to 1,000 tracks). Local-file changes invalidate their cached waveform. If analysis
fails, the waveform continues to build during playback as before. No additional software
installation is required. Beat detection still uses the playing deck's audio independently.

## Beat-matched Auto Mix

When **BEAT MATCH** is enabled, EncoreMix prepares the incoming deck before the audible crossfade:

1. The incoming deck plays silently long enough to estimate its BPM and beat phase.
2. Its tempo is normalized against the active deck, including half-time and double-time BPM relationships.
3. Playback is paused, aligned to the outgoing beat grid, and restarted silently to settle the phase.
4. The deck is unmuted on a beat boundary and the equal-power crossfade advances for the selected number of complete bars.
5. On the final beat, the outgoing deck is fully muted and the incoming deck returns to its original tempo (1.0x playback speed).

The incoming playback rate is set once while the deck is muted and remains fixed for the entire audible mix. EncoreMix does not repeatedly retune the player during the crossfade; frequent playback-rate changes can cause underruns, choppy audio, or decoder glitches. Phase drift is measured for the on-screen status but does not mutate playback speed while both decks are audible.

If either deck does not produce a confident beat estimate, Auto Mix safely falls back to the configured **FADE SECONDS** value.

## Important implementation notes

- YouTube stream URLs expire. The application resolves a fresh audio URL whenever a track is loaded.
- Karaoke selects the highest available resolution supported by its combined-stream or HLS playback path, without a 720p cap. When YouTube only offers separate HLS renditions, it narrows their shared master playlist to one video rendition at the highest available resolution and its matching audio before opening the player. This avoids defaulting to a low-quality track and probing every available resolution at startup. Playback errors or five seconds without progress during a karaoke song trigger an automatic step down to the next available resolution, preserving the playback position. HLS quality changes reuse the resolved playlist; a brief buffering pause may occur. Each new song starts at maximum quality. Missing-format errors are reported once instead of repeatedly reconnecting.
- Auto Mix uses the full duration resolved by `yt-dlp`; temporary Qt/FFmpeg segment durations cannot trigger an early transition.
- Waveform and beat metering are sampled at a bounded rate to keep dual-deck playback responsive on lower-power systems.
- If a remote stream socket drops, ends before the known song duration, or makes no playback progress for 20 seconds, playback re-resolves the URL and retries up to three times from the interrupted position. A failed stream does not advance the queue; Pause and Stop cancel the playback timeout.
- YouTube Music search uses `ytmusicapi`, an unofficial client. Normal public search does not require account authentication.
- Streaming availability can change because YouTube changes its site frequently. Keep `yt-dlp` current:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade "yt-dlp[default,deno]"
```

## Next phase

The karaoke deck is intentionally isolated from the two-deck Auto Mix bus. Future phases can add:

- Singer queue and key-change controls
- Key analysis, persistent beat-grid editing, waveform caching, cue points, loops, and transition previewing
<img width="1552" height="932" alt="image" src="https://github.com/user-attachments/assets/87137381-bf45-47bb-88a1-44e03c6c9a53" />
<img width="1362" height="913" alt="image" src="https://github.com/user-attachments/assets/c5484ffb-e3d4-4336-9734-fe4b384a6eaa" />
<img width="962" height="572" alt="image" src="https://github.com/user-attachments/assets/5b3d180f-5330-4637-b334-1c0cf7bdead9" />
<img width="1402" height="882" alt="image" src="https://github.com/user-attachments/assets/b4a578dc-e22c-4224-902a-df4307647d08" />


