# Song-Printer — Claude Code Guide

## What This Project Is

Browser-based church worship toolkit with two apps: a Lyrics Printer (3-column print layout) and a Chord Viewer (interactive transposition and editing). Pure HTML/CSS/JS — no server needed.

## Building

```bash
python3 build.py            # → songs.js (lyrics only)
python3 build_chords.py     # → chord_songs.js (with chords)
```

Source directory: `/Users/johnhobbs/Desktop/Church/Lyrics/` (.odt, .doc, .docx files)

Requires macOS (`textutil` for document conversion).

## Key Files

| File | Purpose |
|------|---------|
| `index.html` | Lyrics Printer — search, select, print songs in 3-column landscape layout |
| `chords.html` | Chord Viewer — view/transpose/edit chord charts, download edited versions |
| `build.py` | Converts word docs → `songs.js`. Skips chord-heavy files (<15% chord lines). Uses `textutil`. |
| `build_chords.py` | Converts word docs → `chord_songs.js`. Imports chord-heavy files (>15% chord lines). Supports bracket notation and chord-above-lyrics. Merge by default preserves manual edits. |
| `songs.js` | Auto-generated JSON array of {title, lyrics} objects |
| `chord_songs.js` | Auto-generated JSON array of {title, sections: [{label, lines: [{lyrics, chords}]}]} |

## Chord Format

Two supported input formats:
1. **Inline brackets** (preferred): `[G]Amazing [C]grace`
2. **Chord-above-lyrics**: Chord line with spacing, lyrics line below

## Build Flags

- `python3 build_chords.py --force` — Reimport all songs (discards browser edits saved to chord_songs.js)
- `python3 build_chords.py --force-song "Title"` — Reimport one specific song

## Git Safety Rules

**When adding songs (manually or via skills), follow these rules to avoid accidentally deleting files:**

- **Stage only the file you changed**: use `git add songs.js` or `git add chord_songs.js` — NEVER `git add .` or `git add -A`
- **Never push automatically** — the user pushes manually
- **Verify before committing**: after modifying a data file, confirm it still contains all existing songs before committing

## Notes

- Chord edits in the browser are in-memory only — use Download button to save `chord_songs.js`
- Song title detection: first non-blank, non-date line under 80 chars
- Section labels recognized: Verse, Chorus, Bridge, Intro, Pre-Chorus, Tag, Outro
- Git remote: https://github.com/jwh0007/Song-Printer.git
