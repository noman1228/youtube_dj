# EncoreMix 2026 — dual-deck Python mixer
Because VisualBasic is DEAD and I like shit my way.
A working first-phase desktop DJ application with:

- Two independent Qt Multimedia audio decks using Qt's FFmpeg backend
- A left playlist and a right playlist
- Separate YouTube / YouTube Music search window
- Search result thumbnails, metadata, descriptions, and direct **Add Left / Add Right** actions
- Equal-power crossfader
- Automatic transition when the dominant deck reaches 10 seconds remaining
- Configurable 2–10 second fade time
- Automatic advancement of the ended deck to its next playlist track
- Local audio-file support
- Persistent playlists and mixer settings
- An independent third karaoke video deck with YouTube-only search, a manual queue, and detachable projector output

## Windows requirements

1. **Python 3.11 or newer, 64-bit**
2. A current JavaScript runtime is strongly recommended for current YouTube extraction. Node.js 22+ or Deno 2.3+ are suitable for current yt-dlp releases.
3. Internet access

## Fast start

Double-click:

```text
run_windows.bat
```

The script creates a local `.venv`, installs the packages, and launches the application.

Manual launch:

```powershell
cd youtube_dj
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

## How to use

1. Click **SEARCH MUSIC**.
2. Search YouTube, YouTube Music, or both.
3. Add results to the left or right playlist.
4. Double-click a playlist item, or press Play.
5. Move the crossfader manually, or leave **AUTO MIX** enabled.
6. With Auto Mix enabled, the opposite deck starts and the crossfader moves when the dominant deck has 10 seconds remaining.
7. After a deck finishes, it loads the next item in its own playlist and waits for its next turn.

## Important implementation notes

- YouTube stream URLs expire. The application resolves a fresh audio URL whenever a track is loaded.
- YouTube Music search uses `ytmusicapi`, an unofficial client. Normal public search does not require account authentication.
- Streaming availability can change because YouTube changes its site frequently. Keep `yt-dlp` current:

```powershell
python -m pip install --upgrade yt-dlp
```

## Next phase

The karaoke deck is intentionally isolated from the two-deck Auto Mix bus. Future phases can add:

- Singer queue and key-change controls
- BPM/key analysis, beat grids, waveform caching, cue points, loops, and true beat-synced transitions
<img width="1552" height="932" alt="image" src="https://github.com/user-attachments/assets/87137381-bf45-47bb-88a1-44e03c6c9a53" />
<img width="1362" height="913" alt="image" src="https://github.com/user-attachments/assets/c5484ffb-e3d4-4336-9734-fe4b384a6eaa" />
<img width="962" height="572" alt="image" src="https://github.com/user-attachments/assets/5b3d180f-5330-4637-b334-1c0cf7bdead9" />
<img width="1402" height="882" alt="image" src="https://github.com/user-attachments/assets/b4a578dc-e22c-4224-902a-df4307647d08" />


