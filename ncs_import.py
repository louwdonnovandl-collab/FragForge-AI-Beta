"""User-managed NCS song imports. No NCS recordings are distributed with FragForge.

A user downloads recordings from NCS under their own permitted usage, then imports
files into their private library. Metadata and credits are kept alongside tracks.
"""
import json
import shutil
from pathlib import Path

SLOTS = 20
EXTENSIONS = {'.mp3', '.wav', '.flac', '.m4a', '.ogg', '.aac'}

def user_library():
    return Path.home() / 'Music' / 'FragForge' / 'NCS'

def import_track(source, title, artist, credit='', destination=None):
    source = Path(source)
    if not source.is_file() or source.suffix.lower() not in EXTENSIONS:
        raise ValueError('Select a valid local audio file.')
    title, artist = title.strip(), artist.strip()
    if not title or not artist:
        raise ValueError('Song title and artist are required for attribution.')
    root = Path(destination) if destination else user_library()
    root.mkdir(parents=True, exist_ok=True)
    current = [p for p in root.iterdir() if p.suffix.lower() in EXTENSIONS]
    if len(current) >= SLOTS:
        raise ValueError('The 20-track NCS collection is full.')
    target = root / (f'{len(current)+1:02d}_' + source.name)
    if target.exists():
        raise ValueError('A track with this name is already imported.')
    shutil.copy2(source, target)
    target.with_suffix('.json').write_text(json.dumps({
        'title': title, 'artist': artist, 'genre': 'ncs',
        'version': 'full', 'license': 'User-imported; follow NCS usage policy',
        'credit': credit or f'{artist} - {title}\nMusic provided by NoCopyrightSounds\nhttps://ncs.io/',
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    return target
