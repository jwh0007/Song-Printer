# CLAUDE.md — Song Printer

## Project Overview

Song Printer is a lightweight web application for church music ministries that generates print-ready, three-column landscape layouts of song lyrics. It runs entirely in the browser with no server backend.

## Architecture

```
Source Documents (.odt/.doc/.docx)
        │
        ▼
   build.py  ──►  songs.js (auto-generated song database)
                       │
                       ▼
                  index.html (single-page app: HTML + CSS + JS)
                       │
                       ▼
                  Browser / Print
```

- **build.py** — Python 3 build script that extracts lyrics from document files using macOS `textutil` and generates `songs.js`
- **songs.js** — Auto-generated JavaScript file containing a `const SONGS` array of song objects. Do not edit manually.
- **index.html** — Monolithic single-page application with embedded CSS and vanilla JavaScript (no frameworks)

## File Inventory

| File | Size | Purpose |
|------|------|---------|
| `build.py` | ~190 lines | Offline build script (Python 3, macOS only) |
| `index.html` | ~760 lines | Complete browser UI (HTML + CSS + JS) |
| `songs.js` | ~7,200 lines | Generated song database (68 songs) |

## Development Workflow

### Running the App

Open `index.html` directly in a browser (file:// protocol works). No build step or dev server is required for the frontend.

### Regenerating the Song Database

```bash
python3 build.py
```

**Requirements:**
- Python 3 (stdlib only, no pip packages)
- macOS with `textutil` command available
- Song documents in the configured `LYRICS_DIR` path (currently hardcoded to `/Users/johnhobbs/Desktop/Church/Lyrics`)

**What it does:**
1. Scans `LYRICS_DIR` for `.odt`, `.doc`, `.docx` files
2. Converts each to text via `textutil -convert txt -stdout`
3. Filters out chord-only files (>15% chord lines)
4. Parses titles, indentation, and line structure
5. Writes sorted results to `songs.js`

### Testing

There is no automated test suite. Manual testing is done by opening `index.html` in a browser and verifying search, layout, editing, and print behavior.

### Linting / Formatting

No linting or formatting tools are configured. Follow existing code style (see conventions below).

### CI/CD

None configured. No GitHub Actions or other automation.

## Code Conventions

### JavaScript (in index.html)

- All app code is wrapped in a single IIFE to avoid polluting the global scope
- Only `SONGS` is exposed globally (from `songs.js`)
- **Naming:** camelCase for functions and variables, UPPER_CASE for constants
- **DOM:** Uses `data-*` attributes (`data-song-idx`, `data-line-idx`, `data-field`) for linking DOM elements back to data
- **Events:** addEventListener with event delegation via `e.target.closest()`
- **Rendering:** String-based HTML construction with `innerHTML`
- **No frameworks or libraries** — everything is vanilla JS

### Python (build.py)

- **Naming:** snake_case for functions and variables, UPPER_CASE for module-level constants
- Standard library only — no external packages
- Error handling via try/except with skip reporting

### HTML/CSS

- **IDs/classes:** kebab-case
- **Print layout:** 10in x 7.5in pages, 3-column CSS columns, landscape orientation
- **Print CSS:** `@media print` rules hide controls and remove decorative styling
- **Font sizes tested:** 11, 10.5, 10, 9.5, 9pt (largest that fits is chosen automatically)

## Key Application Features

- **Song search:** Real-time autocomplete matching against `SONGS` array with word-boundary matching
- **Auto-sizing:** Tests font sizes from largest to smallest, picks the biggest that fits on one page (or splits across two pages at 9pt)
- **Inline editing:** `contenteditable` on song titles and lines, with change tracking (green highlight)
- **Save edits:** Serializes modified `SONGS` array to clipboard or file download
- **Date prefill:** Auto-calculates next Sunday for the page title
- **Print:** Native `window.print()` with print-optimized CSS

## Data Format (songs.js)

```javascript
const SONGS = [
  {
    "title": "Song Title",
    "lines": [
      {"indent": 0, "text": "First line of lyrics"},
      {"indent": 1, "text": "Indented line (chorus, etc.)"},
      {"indent": 0, "text": ""},   // blank line = verse separator
      {"indent": 0, "text": "Next verse line"}
    ]
  }
];
```

- `indent`: 0 = no indent, 1 = one level (4+ spaces or 1 tab), 2 = two levels (8+ spaces or 2 tabs)
- Empty `text` with `indent: 0` represents blank separator lines
- Songs are sorted alphabetically by title
- Bracket-only labels like `[bridge]` are stripped during build

## Important Notes for AI Assistants

- **`songs.js` is auto-generated.** Do not edit it directly. Changes to song data should go through `build.py` or the in-app editor.
- **`index.html` is a single monolithic file.** All CSS, HTML, and JavaScript live together. There is no module system or bundling.
- **macOS dependency:** `build.py` requires the macOS-specific `textutil` command. It will not run on Linux or Windows without modification.
- **Hardcoded paths:** `LYRICS_DIR` in `build.py` points to a specific local directory. This needs to be updated for different environments.
- **No `.gitignore`** exists in the repository.
- **No package.json** or Node.js tooling. This is not an npm project.
