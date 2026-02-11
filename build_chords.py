#!/usr/bin/env python3
"""
Scans the Lyrics folder for chord files (.odt/.doc/.docx), converts them to text
using textutil, parses chord-above-lyrics format into ChordPro notation, and
generates chord_songs.js for the chord viewer app.

Merge behavior (default): preserves songs already in chord_songs.js (which may
have manual edits) and only adds newly discovered songs from Word docs.

Use --force to reimport all songs from scratch, discarding any manual edits.
Use --force-song "Title" to reimport a single song by title.
"""

import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime

LYRICS_DIR = "/Users/johnhobbs/Desktop/Church/Lyrics"
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chord_songs.js")

# Matches a single chord token like C, Am, G#m7, Dsus4, F#/C#, Eb, Bbar, Am7, Cmaj7, etc.
CHORD_TOKEN_RE = re.compile(
    r'^[A-G][#b]?(m(?:aj)?|min|dim|aug|sus[24]?|add\d+)?\d*(\/(([A-G][#b]?)))?$'
)

# Section label pattern: [Verse 1], [Chorus], [Bridge], etc.
SECTION_LABEL_RE = re.compile(r'^\[([^\]]+)\]\s*$')

# Pattern for section labels that may have extra text after (like [chorus x2])
SECTION_LABEL_LOOSE_RE = re.compile(r'^\[([^\]]+)\]')

# Unbracketed section labels like "Verse 1", "Chorus", "Bridge", "Intro",
# "Repeat Chorus", "Final Chorus", "Chorus Repeat", etc.
UNBRACKETED_SECTION_RE = re.compile(
    r'^(Repeat\s+|Final\s+)?'
    r'(Intro|Verse|Chorus|Bridge|Tag|Outro|Pre[\s-]?Chorus|Interlude|Turn|Instrumental|Ending|Vamp)'
    r'(\s+\d+)?(\s+(Repeat|x\d+))?\s*$',
    re.IGNORECASE
)

# Inline ChordPro bracket pattern: [C], [Am7], [G/B], etc. embedded in lyrics
INLINE_CHORDPRO_RE = re.compile(
    r'\[([A-G][#b]?(?:m(?:aj)?|min|dim|aug|sus[24]?|add\d+)?\d*(?:/[A-G][#b]?)?)\]'
)

NOTES_SHARP = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
NOTES_FLAT = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B']

# Map any note name to its semitone index
NOTE_TO_INDEX = {}
for i, n in enumerate(NOTES_SHARP):
    NOTE_TO_INDEX[n] = i
for i, n in enumerate(NOTES_FLAT):
    NOTE_TO_INDEX[n] = i


def normalize_line_breaks(text):
    text = text.replace('\u2028', '\n')
    text = text.replace('\u2029', '\n')
    text = text.replace('\r\n', '\n')
    text = text.replace('\r', '\n')
    return text


def is_chord_token(token):
    """Check if a single whitespace-delimited token is a chord."""
    # Handle "Xbar" notation (barre chord)
    if token.endswith('bar') and len(token) > 3:
        token = token[:-3]
    # Handle "X7bar" etc.
    if token.endswith('bar'):
        token = token[:-3]
    return bool(CHORD_TOKEN_RE.match(token))


def is_chord_line(line):
    """Determine if a line consists primarily of chord tokens."""
    trimmed = line.strip()
    if not trimmed:
        return False
    # Collapse "X bar" into "Xbar"
    collapsed = re.sub(r'\b([A-G][#b]?(?:m|maj|min|dim|aug|sus[24]?|add\d+|\d+)?)\s*bar\b', r'\1', trimmed)
    tokens = collapsed.split()
    if not tokens:
        return False
    chord_count = sum(1 for t in tokens if is_chord_token(t))
    return chord_count > 0 and chord_count >= len(tokens) * 0.6


def has_inline_chordpro(line):
    """Check if a line contains inline ChordPro notation like [C]word [G]word."""
    matches = INLINE_CHORDPRO_RE.findall(line)
    if len(matches) < 1:
        return False
    # Must also have some non-bracket text (lyrics) to distinguish from section labels
    stripped = INLINE_CHORDPRO_RE.sub('', line).strip()
    # Allow chord-only lines in ChordPro too (like "[C] [G] [F]")
    return len(matches) >= 1 and (len(stripped) > 0 or len(matches) >= 2)


def is_chord_file(lines):
    """Determine if a file is a chord chart (>15% of non-empty lines are chord lines
    or contain inline ChordPro notation)."""
    non_empty = [l for l in lines if l.strip()]
    if not non_empty:
        return False
    chord_lines = sum(1 for l in non_empty if is_chord_line(l) or has_inline_chordpro(l))
    return chord_lines / len(non_empty) > 0.15


def expand_tabs(line, tab_width=4):
    """Expand tabs to spaces. Uses tab_width=4 which better approximates
    Word's proportional font tab stops than the standard 8."""
    result = []
    col = 0
    for ch in line:
        if ch == '\t':
            spaces = tab_width - (col % tab_width)
            result.append(' ' * spaces)
            col += spaces
        else:
            result.append(ch)
            col += 1
    return ''.join(result)


def extract_chords_with_positions(chord_line):
    """Extract chords and their character positions from a chord-only line.
    Returns list of (position, chord_string) tuples.
    Tabs are expanded first so positions match visual columns."""
    # Expand tabs and collapse "X bar" / "Xbar" notation
    expanded = expand_tabs(chord_line)
    collapsed = re.sub(r'\b([A-G][#b]?(?:m|maj|min|dim|aug|sus[24]?|add\d+|\d+)?)\s*bar\b', r'\1', expanded)
    chords = []
    i = 0
    while i < len(collapsed):
        if collapsed[i] == ' ':
            i += 1
            continue
        # Find the end of this token
        j = i
        while j < len(collapsed) and collapsed[j] != ' ':
            j += 1
        token = collapsed[i:j]
        # Check for period/comma at end (punctuation artifacts)
        token = token.rstrip('.,;:')
        if token and is_chord_token(token):
            chords.append((i, token))
        i = j
    return chords


def snap_to_word_boundary(pos, lyric):
    """Snap a chord position to the nearest word start in the lyric line.

    Word docs and textutil conversion can shift character positions, so we snap
    chords to the nearest word boundary. The algorithm considers both the current
    word start and the next word start, preferring whichever is closer.
    """
    if pos >= len(lyric):
        return pos

    # If we're already at a word start (space before, or position 0), keep it
    if pos == 0 or lyric[pos - 1] == ' ':
        return pos

    # We're in the middle of a word. Find the start of this word.
    word_start = pos
    while word_start > 0 and lyric[word_start - 1] != ' ':
        word_start -= 1

    # Also find the start of the next word
    next_word = pos
    while next_word < len(lyric) and lyric[next_word] != ' ':
        next_word += 1
    while next_word < len(lyric) and lyric[next_word] == ' ':
        next_word += 1

    dist_back = pos - word_start
    dist_fwd = next_word - pos if next_word < len(lyric) else 999

    # If we're deep into a word (more than half its length past the start),
    # prefer snapping forward to the next word
    word_end = pos
    while word_end < len(lyric) and lyric[word_end] != ' ':
        word_end += 1
    word_len = word_end - word_start

    if word_len > 0 and dist_back > word_len * 0.5 and dist_fwd < 999:
        return next_word

    # Otherwise snap to whichever word start is closer
    if dist_fwd <= dist_back:
        return next_word
    else:
        return word_start


def merge_chord_and_lyric_lines(chord_line, lyric_line):
    """Merge a chord line with its corresponding lyric line into ChordPro format.
    Both lines are tab-expanded so chord positions align with lyric characters.
    Chord positions are snapped to the nearest word boundary to compensate for
    proportional vs monospace font differences."""
    chords = extract_chords_with_positions(chord_line)
    if not chords:
        return lyric_line.strip()

    lyric = expand_tabs(lyric_line).rstrip()
    # Pad lyric to at least the length needed
    max_pos = max(pos for pos, _ in chords)
    if len(lyric) <= max_pos:
        lyric = lyric.ljust(max_pos + 1)

    # Snap each chord to nearest word boundary, then insert right-to-left
    snapped = [(snap_to_word_boundary(pos, lyric), chord) for pos, chord in chords]

    # Deduplicate positions (if two chords snapped to same spot, keep both in order)
    result = lyric
    for pos, chord in reversed(snapped):
        insert_pos = min(pos, len(result))
        result = result[:insert_pos] + f'[{chord}]' + result[insert_pos:]

    # Clean up: remove excess whitespace before trailing chords
    # e.g. "[G]Thee       [C]" → "[G]Thee [C]"
    result = re.sub(r'\s{2,}(\[[^\]]+\])\s*$', r' \1', result)
    # Also collapse internal runs of spaces to single space (but keep chord markers)
    result = re.sub(r'(\]) {2,}', r'] ', result)

    return result.strip()


def is_date_header(line):
    return bool(re.match(r'^\s*Sunday\b', line, re.IGNORECASE))


def clean_filename(filename):
    name = re.sub(r'\.(odt|docx?|pages)$', '', filename, flags=re.IGNORECASE)
    # Remove common suffixes
    name = re.sub(r'\s*-?\s*[Cc]hords?\s*$', '', name)
    name = re.sub(r'[-_]+', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def detect_key(sections):
    """Detect the key from the most common chord root in the song."""
    root_counts = Counter()
    for section in sections:
        for line in section['lines']:
            for match in re.finditer(r'\[([A-G][#b]?)', line):
                root = match.group(1)
                if root in NOTE_TO_INDEX:
                    root_counts[root] += 1
    if root_counts:
        return root_counts.most_common(1)[0][0]
    return 'C'


def parse_section_label(line):
    """If line is a section label like [Verse 1], return (type, label). Else None.
    Also recognizes unbracketed labels like 'Chorus', 'Verse 1', 'Bridge', etc."""
    trimmed = line.strip()
    m = SECTION_LABEL_RE.match(trimmed)
    if m:
        # Exact bracket match — but reject if the bracket content is a chord name
        # e.g. [Am7] is a chord, not a section label
        bracket_content = m.group(1).strip()
        if is_chord_token(bracket_content) or is_chord_token(bracket_content.rstrip('.,;:')):
            return None
    if not m:
        # Also check for loose labels like [chorus x2] or [bridge]
        m = SECTION_LABEL_LOOSE_RE.match(trimmed)
        if not m:
            # Check for unbracketed section labels
            um = UNBRACKETED_SECTION_RE.match(trimmed)
            if um:
                label = trimmed
                label_lower = label.lower()
                if 'verse' in label_lower:
                    return ('verse', label)
                elif 'chorus' in label_lower or 'repeat' in label_lower:
                    return ('chorus', label)
                elif 'bridge' in label_lower:
                    return ('bridge', label)
                elif 'tag' in label_lower:
                    return ('tag', label)
                elif 'intro' in label_lower:
                    return ('intro', label)
                elif 'outro' in label_lower or 'ending' in label_lower:
                    return ('outro', label)
                elif 'pre' in label_lower:
                    return ('pre-chorus', label)
                elif 'interlude' in label_lower or 'turn' in label_lower or 'instrumental' in label_lower or 'vamp' in label_lower:
                    return ('section', label)
                else:
                    return ('section', label)
            return None
        # If the bracket content is a chord name, this is inline ChordPro, not a section label
        bracket_content = m.group(1).strip()
        if is_chord_token(bracket_content) or is_chord_token(bracket_content.rstrip('.,;:')):
            return None
        # Only accept if the rest of the line after the bracket is short
        rest = trimmed[m.end():].strip()
        if len(rest) > 10:
            return None

    label = m.group(1).strip()
    label_lower = label.lower()

    if 'verse' in label_lower:
        return ('verse', label)
    elif 'chorus' in label_lower:
        return ('chorus', label)
    elif 'bridge' in label_lower:
        return ('bridge', label)
    elif 'tag' in label_lower:
        return ('tag', label)
    elif 'intro' in label_lower:
        return ('intro', label)
    elif 'outro' in label_lower:
        return ('outro', label)
    elif 'pre' in label_lower:
        return ('pre-chorus', label)
    else:
        return ('section', label)


def parse_chord_file(text, filename):
    """Parse a chord file's text content into structured ChordPro sections."""
    text = normalize_line_breaks(text)
    raw_lines = text.split('\n')

    if not is_chord_file(raw_lines):
        return None

    # Strip date headers and leading blanks
    start_idx = 0
    for i, line in enumerate(raw_lines):
        trimmed = line.strip()
        if not trimmed:
            start_idx = i + 1
            continue
        if is_date_header(line):
            start_idx = i + 1
            continue
        break

    lines = raw_lines[start_idx:]

    # Extract title from first non-blank, non-section-label line
    # Only accept it as a title if it comes BEFORE any section labels or chord lines
    # (otherwise it's likely a lyric line, not a title)
    title = None
    title_end = 0
    saw_section_or_chord = False
    for i, line in enumerate(lines):
        trimmed = line.strip()
        if not trimmed:
            continue
        if parse_section_label(trimmed):
            saw_section_or_chord = True
            continue
        if is_chord_line(line):
            saw_section_or_chord = True
            continue
        if saw_section_or_chord:
            # This line comes after a section label or chord line — it's lyrics, not a title
            break
        if len(trimmed) < 80:
            title = trimmed
            title_end = i + 1
            break

    if not title:
        title = clean_filename(filename)

    # Skip title line and any immediate blank lines after it
    body_lines = lines[title_end:]
    while body_lines and not body_lines[0].strip():
        body_lines.pop(0)

    # Also skip subtitle-ish lines (date, author, capo)
    while body_lines:
        trimmed = body_lines[0].strip()
        if not trimmed:
            body_lines.pop(0)
            continue
        lower = trimmed.lower()
        if (re.match(r'^(capo|key\s|by\s)', lower) or
            re.match(r'^[A-Z][a-z]+([-\s][A-Z][a-z]+)?\s+\d{4}', trimmed) or  # "May 2025", "May-June 2025"
            re.match(r'^[A-Z]\.\s', trimmed) or  # "J. Hobbs"
            re.match(r'^[A-Z][a-z]+\s+[A-Z][a-z]+$', trimmed) or  # "John Hobbs" (2-word name)
            re.match(r'^\d+[a-z]?$', lower) or  # "1c" (capo shorthand)
            (len(trimmed.split()) <= 4 and not is_chord_line(body_lines[0]) and
             not parse_section_label(trimmed) and
             re.match(r'^[A-Z]', trimmed) and
             any(c.isdigit() for c in trimmed))):  # date-like short lines
            body_lines.pop(0)
            continue
        break

    # Now parse body into sections
    sections = []
    current_section = {'type': 'verse', 'label': '', 'lines': []}
    i = 0

    while i < len(body_lines):
        line = body_lines[i]
        trimmed = line.strip()

        # Empty line
        if not trimmed:
            # Add empty line as section separator
            if current_section['lines']:
                current_section['lines'].append('')
            i += 1
            continue

        # Section label
        section_info = parse_section_label(trimmed)
        if section_info:
            # Save current section if it has content
            if current_section['lines']:
                sections.append(current_section)
            current_section = {
                'type': section_info[0],
                'label': section_info[1],
                'lines': []
            }
            i += 1
            continue

        # Chord line followed by lyric line
        if is_chord_line(line):
            chord_line = line
            # Look ahead for the lyric line
            j = i + 1
            while j < len(body_lines) and not body_lines[j].strip():
                j += 1

            if j < len(body_lines) and not is_chord_line(body_lines[j]) and not parse_section_label(body_lines[j].strip()):
                # Merge chord + lyric
                lyric_line = body_lines[j]
                merged = merge_chord_and_lyric_lines(chord_line, lyric_line)
                current_section['lines'].append(merged)
                i = j + 1
            else:
                # Chord line with no lyric line — chord-only line
                chords = extract_chords_with_positions(chord_line)
                if chords:
                    chord_str = ' '.join(f'[{c}]' for _, c in chords)
                    current_section['lines'].append(chord_str)
                i += 1
            continue

        # Check if line already has inline ChordPro notation [C]word [G]word
        if has_inline_chordpro(line):
            current_section['lines'].append(trimmed)
            i += 1
            continue

        # Regular lyric line (no chords detected above it)
        # Check if it has inline chords (tabs mixed with text)
        inline_chords = extract_inline_chords(line)
        if inline_chords:
            current_section['lines'].append(inline_chords)
        else:
            current_section['lines'].append(trimmed)
        i += 1

    # Save last section
    if current_section['lines']:
        sections.append(current_section)

    # Clean up: trim trailing empty lines and collapse consecutive blanks
    for section in sections:
        while section['lines'] and section['lines'][-1] == '':
            section['lines'].pop()
        while section['lines'] and section['lines'][0] == '':
            section['lines'].pop(0)
        # Collapse consecutive blank lines into single blanks
        cleaned = []
        for line in section['lines']:
            if line == '' and cleaned and cleaned[-1] == '':
                continue
            cleaned.append(line)
        section['lines'] = cleaned

    # Remove empty sections
    sections = [s for s in sections if s['lines']]

    if not sections:
        return None

    key = detect_key(sections)

    return {
        'title': title,
        'key': key,
        'sections': sections
    }


def extract_inline_chords(line):
    """Handle lines that have chords mixed with lyrics via tab separation.
    e.g. 'G  F#/G Bm' at the start followed by lyrics, or chord then tab then lyrics.
    Returns ChordPro line or None if no inline chords found."""
    # Look for pattern: chord(s) followed by tab(s) then lyrics
    # Or lines starting with a chord followed by whitespace and lyrics
    trimmed = line.strip()
    if not trimmed:
        return None

    # Try to find chord tokens at the beginning
    parts = re.split(r'\t+', line, maxsplit=1)
    if len(parts) == 2:
        before_tab = parts[0].strip()
        after_tab = parts[1].strip()
        if before_tab and after_tab:
            # Check if the before-tab part is chords
            collapsed = re.sub(r'\b([A-G][#b]?)\s+bar\b', r'\1', before_tab)
            tokens = collapsed.split()
            chord_count = sum(1 for t in tokens if is_chord_token(t))
            if tokens and chord_count >= len(tokens) * 0.5:
                # Build ChordPro: put all chords at the start of the lyric text
                chords = [t for t in tokens if is_chord_token(t)]
                chord_prefix = ''.join(f'[{c}]' for c in chords)
                return chord_prefix + after_tab

    return None


def load_existing_songs():
    """Load existing songs from chord_songs.js if it exists.
    Returns a list of song dicts, or empty list if file doesn't exist."""
    if not os.path.exists(OUTPUT_FILE):
        return []
    try:
        with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
        # Extract the JSON array from "const CHORD_SONGS = [...];"
        match = re.search(r'const CHORD_SONGS\s*=\s*(\[.*\])\s*;', content, re.DOTALL)
        if match:
            return json.loads(match.group(1))
    except Exception as e:
        print(f"Warning: could not load existing {OUTPUT_FILE}: {e}")
    return []


def normalize_title(title):
    """Normalize a song title for comparison (lowercase, strip whitespace/punctuation)."""
    return re.sub(r'[^a-z0-9]', '', title.lower())


def main():
    # Parse command-line flags
    force_all = '--force' in sys.argv
    force_songs = set()
    for i, arg in enumerate(sys.argv):
        if arg == '--force-song' and i + 1 < len(sys.argv):
            force_songs.add(normalize_title(sys.argv[i + 1]))

    extensions = {'.odt', '.doc', '.docx'}
    files = sorted([
        f for f in os.listdir(LYRICS_DIR)
        if os.path.splitext(f)[1].lower() in extensions and not f.startswith('~$')
    ])

    print(f"Found {len(files)} total song files")

    # Load existing songs (to preserve manual edits)
    existing_songs = [] if force_all else load_existing_songs()
    existing_titles = {normalize_title(s['title']) for s in existing_songs}

    if force_all:
        print("--force: reimporting ALL songs from scratch")
    elif existing_songs:
        print(f"Loaded {len(existing_songs)} existing songs from chord_songs.js")
        if force_songs:
            # Remove force-reimport songs from existing so they get re-parsed
            # Uses substring matching so --force-song "The Vow" matches "The Vow – Cody Carnes"
            kept = []
            for s in existing_songs:
                nt = normalize_title(s['title'])
                matched = any(fs in nt or nt in fs for fs in force_songs)
                if matched:
                    existing_titles.discard(nt)
                    print(f"  --force-song: will reimport \"{s['title']}\"")
                else:
                    kept.append(s)
            existing_songs = kept

    new_songs = []
    skipped = []
    already_existed = 0

    for filename in files:
        filepath = os.path.join(LYRICS_DIR, filename)
        try:
            result = subprocess.run(
                ['textutil', '-convert', 'txt', '-stdout', filepath],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                skipped.append(f"{filename} (conversion error)")
                continue

            song = parse_chord_file(result.stdout, filename)
            if song:
                nt = normalize_title(song['title'])
                # Check for exact or substring match against existing titles
                match_found = nt in existing_titles or any(
                    nt in et or et in nt for et in existing_titles
                )
                if match_found:
                    already_existed += 1
                else:
                    new_songs.append(song)
            else:
                skipped.append(f"{filename} (not a chord file)")
        except Exception as e:
            skipped.append(f"{filename} ({e})")

    # Merge: existing songs (preserved) + newly discovered songs
    all_songs = existing_songs + new_songs
    all_songs.sort(key=lambda s: s['title'].lower())

    output = f"// Generated by build_chords.py — manual edits are preserved on rebuild\n"
    output += f"// Generated: {datetime.now().isoformat()}\n"
    output += f"const CHORD_SONGS = {json.dumps(all_songs, indent=2)};\n"

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(output)

    print(f"\nGenerated {OUTPUT_FILE}")
    print(f"  {len(all_songs)} chord songs total")
    if not force_all and existing_songs:
        print(f"  {len(existing_songs)} songs preserved from existing file")
    if new_songs:
        print(f"  {len(new_songs)} new songs added:")
        for s in new_songs:
            print(f"    + {s['title']}")
    if already_existed:
        print(f"  {already_existed} songs already existed (kept manual edits)")
    if skipped:
        print(f"  {len(skipped)} files skipped:")
        for s in skipped:
            print(f"    - {s}")


if __name__ == '__main__':
    main()
