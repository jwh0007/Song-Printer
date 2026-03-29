#!/usr/bin/env python3
"""
Scans the Lyrics folder, extracts text from .odt/.doc/.docx files using textutil,
and generates songs.js with structured song data for the Song Printer HTML app.
"""

import json
import os
import re
import subprocess
import sys

LYRICS_DIR = "/Users/johnhobbs/Desktop/Church/Lyrics"
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "songs.js")

CHORD_TOKEN_RE = re.compile(
    r'^[A-G][#b]?(m|maj|min|dim|aug|sus[24]?|add\d+|\d+|bar)?(\/[A-G][#b]?)?$'
)

def is_chord_line(line):
    trimmed = line.strip()
    if not trimmed:
        return False
    # Collapse "X bar" into "Xbar" before tokenizing (alternate chord notation)
    collapsed = re.sub(r'\b([A-G][#b]?)\s+bar\b', r'\1bar', trimmed)
    tokens = collapsed.split()
    chord_count = sum(1 for t in tokens if CHORD_TOKEN_RE.match(t))
    return chord_count > 0 and chord_count >= len(tokens) * 0.6

def is_chord_file(lines):
    non_empty = [l for l in lines if l.strip()]
    if not non_empty:
        return False
    chord_lines = sum(1 for l in non_empty if is_chord_line(l))
    return chord_lines / len(non_empty) > 0.15

def is_date_header(line):
    return bool(re.match(r'^\s*Sunday\b', line, re.IGNORECASE))

def clean_filename(filename):
    name = re.sub(r'\.(odt|docx?|pages)$', '', filename, flags=re.IGNORECASE)
    name = re.sub(r'[-_]+', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name

def extract_title(lines, filename):
    for line in lines:
        trimmed = line.strip()
        if not trimmed:
            continue
        if is_date_header(line):
            continue
        if 0 < len(trimmed) < 80:
            return trimmed
        break
    return clean_filename(filename)

def normalize_line_breaks(text):
    """Replace Unicode line separators and paragraph separators with newlines."""
    text = text.replace('\u2028', '\n')  # Line Separator
    text = text.replace('\u2029', '\n')  # Paragraph Separator
    text = text.replace('\r\n', '\n')
    text = text.replace('\r', '\n')
    return text

def parse_song(text, filename):
    text = normalize_line_breaks(text)
    raw_lines = text.split('\n')

    if is_chord_file(raw_lines):
        return None

    # Strip date headers and leading blank lines
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

    content_lines = raw_lines[start_idx:]

    title = extract_title(content_lines, filename)

    # Skip the title line in body
    body_start = 0
    for i, line in enumerate(content_lines):
        trimmed = line.strip()
        if not trimmed:
            body_start = i + 1
            continue
        if trimmed == title:
            body_start = i + 1
            break
        break

    body_lines = content_lines[body_start:]
    parsed = []

    for line in body_lines:
        indent = 0
        j = 0
        # Count leading tabs
        while j < len(line) and line[j] == '\t':
            indent += 1
            j += 1
        # If no tabs, check for leading spaces
        if indent == 0:
            spaces = 0
            while j < len(line) and line[j] == ' ':
                spaces += 1
                j += 1
            if spaces >= 8:
                indent = 2
            elif spaces >= 4:
                indent = 1

        text_content = line.strip()

        # Skip bracket-only labels like [bridge]
        if re.match(r'^\[.*\]$', text_content):
            continue

        parsed.append({"indent": indent, "text": text_content})

    # Trim leading and trailing empty lines
    while parsed and parsed[0]["text"] == "":
        parsed.pop(0)
    while parsed and parsed[-1]["text"] == "":
        parsed.pop()

    return {"title": title, "lines": parsed}

def main():
    extensions = {'.odt', '.doc', '.docx'}
    files = sorted([
        f for f in os.listdir(LYRICS_DIR)
        if os.path.splitext(f)[1].lower() in extensions
        and not f.startswith('~$')
        and not re.search(r'chords?', os.path.splitext(f)[0], re.IGNORECASE)
    ])

    # Also gather chord files that were filtered out, for the skip report
    chord_name_files = sorted([
        f for f in os.listdir(LYRICS_DIR)
        if os.path.splitext(f)[1].lower() in extensions
        and not f.startswith('~$')
        and re.search(r'chords?', os.path.splitext(f)[0], re.IGNORECASE)
    ])

    print(f"Found {len(files)} lyric files ({len(chord_name_files)} chord files skipped by name)")

    songs = []
    skipped = [f"{f} (chord file by name)" for f in chord_name_files]

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

            song = parse_song(result.stdout, filename)
            if song:
                songs.append(song)
            else:
                skipped.append(f"{filename} (chord file)")
        except Exception as e:
            skipped.append(f"{filename} ({e})")

    songs.sort(key=lambda s: s['title'].lower())

    from datetime import datetime
    output = f"// Auto-generated by build.py — do not edit manually\n"
    output += f"// Generated: {datetime.now().isoformat()}\n"
    output += f"const SONGS = {json.dumps(songs, indent=2)};\n"

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(output)

    print(f"\nGenerated {OUTPUT_FILE}")
    print(f"  {len(songs)} songs included")
    if skipped:
        print(f"  {len(skipped)} files skipped:")
        for s in skipped:
            print(f"    - {s}")

if __name__ == '__main__':
    main()
