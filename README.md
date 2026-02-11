# Song Printer & Chord Viewer

Two browser-based tools for church worship: a **lyrics printer** (`index.html`) and a **chord chart viewer** (`chords.html`). Both run as local HTML files — no server needed.

---

## Chord Viewer (`chords.html`)

A browser app for viewing, transposing, editing, and printing chord charts. Chords are displayed above the lyrics in blue.

### Opening

Open `chords.html` directly in your browser (double-click or `File > Open`). Song data is loaded from `chord_songs.js` in the same folder.

### Viewing Songs

- **Search**: Start typing a song name in the search box. An autocomplete dropdown appears — click a result or use arrow keys + Enter.
- **Transpose**: Use the **+/-** buttons next to the key display, or press **Arrow Up / Arrow Down** on your keyboard. The displayed key updates automatically.
- **Font size**: Use the **A+ / A-** buttons to adjust text size.
- **Print**: Click **Print** for a clean printout. Controls are hidden, and the current transposition is preserved in the printout.

### Editing Chords

Click the **Edit** button (turns red, labeled "Done" while editing). In edit mode:

- **Move a chord**: Click a blue chord name to pick it up (it highlights yellow), then click any letter in the lyrics to place it there. You can move chords between lines.
- **Add a new chord**: Type a chord name (e.g. `Am`, `F#m7`) in the "New chord" input box. It turns yellow when ready. Then click any letter to place it. The input stays filled so you can place the same chord multiple times.
- **Delete a chord**: Pick up a chord (click it), then click the red "delete zone" at the bottom.
- **Undo**: Click **Undo** or press **Ctrl+Z** (Cmd+Z on Mac). Supports up to 50 undo steps.
- **Cancel**: Press **Escape** to drop a picked-up chord or clear the new chord input.

Click **Done** when finished editing.

### Saving Your Edits

Click **Download** to save a new `chord_songs.js` file. This downloads to your browser's default download location. **You must manually replace** the `chord_songs.js` file in the Song-Printer folder with the downloaded one for your edits to persist.

> **Important**: Edits only live in the browser's memory until you download. If you refresh the page or select a different song without downloading, your changes to the previous song are kept in memory for that session but will be lost if you close the tab.

---

## Building `chord_songs.js` from Word Documents

The `build_chords.py` script scans the Lyrics folder for Word docs (.odt/.doc/.docx) that contain chord charts, converts them to ChordPro format, and generates `chord_songs.js`.

### What Gets Imported

The script looks at all song files in the Lyrics folder and identifies **chord files** — files where more than 15% of non-empty lines are chord lines (like `G  C  Am  D`). Lyrics-only files are skipped. The chord-above-lyrics format from Word docs is automatically merged so that chords sit above the correct syllables.

### What Does NOT Get Imported

- **Lyrics-only files** (no chord lines detected) — these are used by the Song Printer (`index.html`) instead
- **.pages files** — macOS textutil can't reliably convert these
- **Temp/lock files** (filenames starting with `~$`)

### Writing Chord Files for Import

Follow these guidelines when creating or editing Word documents so the build script imports them correctly.

#### Use Courier (Monospace) Font

**Strongly recommended:** Set your entire document to **Courier** or another monospace font (Courier New, Menlo, etc.). The build script converts documents to plain text, so the font itself doesn't affect parsing — but with a monospace font, each character takes the same width. This means the chord positions you see in Word will match exactly where they land in the viewer. With proportional fonts (like Times or Arial), chords may look aligned in Word but end up shifted after import.

#### Chord Placement — Two Formats

The build script supports two ways to write chords. You can mix both styles in the same file.

**Option A: Inline Bracket Notation (Recommended)**

Write chords in square brackets directly in the lyric text, right before the syllable where the chord is played:

```
[G]Amazing [C]grace how [Am]sweet the [D]sound
```

This is the most reliable format because chord positions are exact — there's no column alignment to worry about. The brackets tell the parser exactly where each chord belongs.

For chord-only lines (intros, interludes, etc.), just put the chords in brackets:

```
[C] [G] [F]
```

**Option B: Chord-Above-Lyrics Format**

Write chords on their own line directly above the lyrics, using spaces to position each chord above the syllable where it should be played:

```
G            C         Am        D
Amazing grace how sweet the sound
```

This format works but depends on column alignment. Use **Courier font** and **spaces (not tabs)** for best results. The importer snaps chords to the nearest word boundary to compensate for small alignment shifts, but it can't always guess the right word if positions are off by several characters.

> **Tip**: If a song imports with chords on the wrong words, the easiest fix is to either (1) rewrite it using inline bracket notation, or (2) fix the chord positions using the Edit mode in the chord viewer.

#### Supported Chord Names

Standard chord names are recognized, including:

- Basic: `C`, `D`, `Em`, `G`, `A`, `Bb`
- Sharps/flats: `F#`, `Eb`, `C#`, `Ab`
- Extended: `Am7`, `Cmaj7`, `D7`, `G9`, `Fmaj7`, `F2`
- Suspended: `Dsus4`, `Asus2`
- Other: `Gdim`, `Eaug`, `Cadd9`
- Slash chords: `G/B`, `D/F#`, `C/E`, `Csus/D`

#### Section Labels

Use labels on their own line to mark sections. Bracketed labels are recommended:

```
[Verse 1]
[Chorus]
[Bridge]
```

Unbracketed labels are also recognized:

```
Verse 1
Chorus
Bridge
Intro
Interlude
```

These become section headers in the viewer. If no labels are present, the script uses indentation to guess sections.

#### Song Title

The first non-blank, non-date line in the file becomes the song title (must be under 80 characters and appear before any chords or section labels). If your file starts with a section label like `[Intro]` or a chord line, the title is taken from the filename instead. Make sure the song title is the very first line of the document.

#### Chord Detection Threshold

A file is identified as a chord file (and imported by `build_chords.py`) when more than 15% of its non-empty lines are chord lines or contain inline bracket notation. Files below this threshold are treated as lyrics-only and handled by `build.py` instead.

#### Complete Example (Inline Bracket Notation)

```
Amazing Grace

[Verse 1]
[G]Amazing [C]grace how [G]sweet the sound
That [G]saved a [Em]wretch like [D]me
[G]I once was [C]lost but [G]now am found
Was [G]blind but [D]now I [G]see

[Verse 2]
[G]'Twas grace that [C]taught my [G]heart to fear
And [G]grace my [Em]fears re[D]lieved
```

### Running the Build

```bash
python3 build_chords.py
```

### Merge Behavior (Default)

By default, the build script **preserves your manual edits**. It works like this:

1. Loads the existing `chord_songs.js` (if it exists)
2. Scans the Lyrics folder for chord files
3. **Keeps** all songs already in `chord_songs.js` exactly as they are
4. **Adds** only newly discovered songs that aren't already in the file

This means you can safely re-run `build_chords.py` after adding new Word docs to the Lyrics folder without losing any chord edits you've made through the viewer.

### Force Reimport

If you want to start fresh or reimport a specific song from its Word doc (discarding manual edits for that song):

```bash
# Reimport everything from scratch (discards ALL manual edits)
python3 build_chords.py --force

# Reimport just one song (all other songs keep their edits)
python3 build_chords.py --force-song "As The Deer"
```

Song title matching is case-insensitive and ignores punctuation.

---

## Lyrics Printer (`index.html`)

A browser app for viewing and printing song lyrics (without chords) in a 3-column landscape layout. Uses `songs.js` generated by `build.py`.

### Building `songs.js`

```bash
python3 build.py
```

This scans the same Lyrics folder but imports the **lyrics-only** files (the opposite of what `build_chords.py` imports).

---

## File Overview

| File | Description |
|------|-------------|
| `chords.html` | Chord chart viewer/editor (open in browser) |
| `chord_songs.js` | Auto-generated chord song data (ChordPro format) |
| `build_chords.py` | Generates `chord_songs.js` from Word docs |
| `index.html` | Lyrics printer (open in browser) |
| `songs.js` | Auto-generated lyrics data |
| `build.py` | Generates `songs.js` from Word docs |

## Requirements

- **macOS** (uses `textutil` for document conversion)
- **Python 3** for the build scripts
- Any modern browser to view the HTML tools
- Song files in `/Users/johnhobbs/Desktop/Church/Lyrics/` (.odt, .doc, or .docx)
