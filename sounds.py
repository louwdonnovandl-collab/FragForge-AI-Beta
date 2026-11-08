"""Original synthesized FragForge sound effects; no third-party recordings."""
import sys,shutil,json,re,uuid,hashlib
from pathlib import Path
SOUNDS = [('board_001', 'Vine-Style Deep Boom', 'Meme Impacts'), ('board_002', 'Vine-Style Double Boom', 'Meme Impacts'), ('board_003', 'Metal Pipe Drop', 'Meme Impacts'), ('board_004', 'Dramatic Bass Hit', 'Meme Impacts'), ('board_005', 'Explosion Punch', 'Meme Impacts'), ('board_006', 'Heavy Cinematic Slam', 'Meme Impacts'), ('board_007', 'Cartoon Bonk', 'Meme Impacts'), ('board_008', 'Cartoon Punch', 'Meme Impacts'), ('board_009', 'Glass Break', 'Meme Impacts'), ('board_010', 'Big Door Slam', 'Meme Impacts'), ('board_011', 'Sad Trombone Wah Wah', 'Comedy & Reactions'), ('board_012', 'Ba Dum Tss Rimshot', 'Comedy & Reactions'), ('board_013', 'Wrong Answer Buzzer', 'Comedy & Reactions'), ('board_014', 'Correct Answer Ding', 'Comedy & Reactions'), ('board_015', 'Awkward Crickets', 'Comedy & Reactions'), ('board_016', 'Record Scratch Stop', 'Comedy & Reactions'), ('board_017', 'Airhorn Triple Blast', 'Comedy & Reactions'), ('board_018', 'Comedy Boing', 'Comedy & Reactions'), ('board_019', 'Censor Beep', 'Comedy & Reactions'), ('board_020', 'Game Over Descend', 'Comedy & Reactions'), ('board_021', 'Victory Fanfare', 'Gaming & Streaming'), ('board_022', 'Level Up Arpeggio', 'Gaming & Streaming'), ('board_023', 'Coin Pickup', 'Gaming & Streaming'), ('board_024', 'Headshot Impact', 'Gaming & Streaming'), ('board_025', 'Achievement Unlocked', 'Gaming & Streaming'), ('board_026', 'Countdown Three Beeps', 'Gaming & Streaming'), ('board_027', '8-Bit Power Up', 'Gaming & Streaming'), ('board_028', '8-Bit Fail', 'Gaming & Streaming'), ('board_029', 'Notification Pop', 'Gaming & Streaming'), ('board_030', 'Glitch Error', 'Gaming & Streaming'), ('board_031', 'Fast Transition Whoosh', 'Editing Transitions'), ('board_032', 'Reverse Whoosh Riser', 'Editing Transitions'), ('board_033', 'Bass Drop Transition', 'Editing Transitions'), ('board_034', 'Camera Shutter', 'Editing Transitions'), ('board_035', 'Tape Stop', 'Editing Transitions'), ('board_036', 'White Noise Sweep', 'Editing Transitions'), ('board_037', 'Digital Glitch Cut', 'Editing Transitions'), ('board_038', 'Sparkle Reveal', 'Editing Transitions'), ('board_039', 'Dark Suspense Pulse', 'Background Loops'), ('board_040', 'Retro Arcade Beat', 'Background Loops'), ('board_041', 'Lo-Fi Chill Loop', 'Background Loops'), ('board_042', 'Epic Tension Rhythm', 'Background Loops'), ('board_043', 'Nice! (Original Voice)', 'Meme Reactions'), ('board_044', 'Wow! (Original Voice)', 'Meme Reactions'), ('board_045', 'Lets Go! (Original Voice)', 'Gaming & Streaming'), ('board_046', 'Bruh (Original Voice)', 'Meme Reactions'), ('board_047', 'Oops! (Original Voice)', 'Comedy & Reactions'), ('board_048', 'Oh No! (Original Voice)', 'Meme Reactions'), ('board_049', 'Seriously? (Original Voice)', 'Meme Reactions'), ('board_050', 'GG! (Original Voice)', 'Gaming & Streaming'), ('board_051', 'Crowd Applause (Original)', 'Meme Reactions'), ('board_052', 'Crowd Gasp (Original)', 'Meme Reactions')]

def sound_path(slug):
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
    source=root/'sound_assets'/(slug+'.wav')
    target=Path.home()/'.fragforge'/'sounds'/(slug+'.wav')
    target.parent.mkdir(parents=True,exist_ok=True)
    if not source.is_file():raise FileNotFoundError(f'Bundled sound missing: {source}')
    if not target.exists() or target.stat().st_size != source.stat().st_size or hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(source.read_bytes()).digest():
        shutil.copy2(source,target)
    return str(target)


USER_AUDIO_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac'}

def user_sound_dir():
    directory = Path.home() / '.fragforge' / 'meme_sounds'
    directory.mkdir(parents=True, exist_ok=True)
    return directory

def user_sounds():
    """Return (key, display name, category) entries from local user imports."""
    root = user_sound_dir()
    metadata = root / 'library.json'
    try:
        entries = json.loads(metadata.read_text(encoding='utf-8')) if metadata.exists() else []
    except (OSError, ValueError, TypeError):
        entries = []
    return [(str(e['file']), str(e['name']), 'My Audio') for e in entries
            if isinstance(e, dict) and (root / str(e.get('file', ''))).is_file()
            and Path(str(e.get('file', ''))).name == str(e.get('file', ''))]

def import_user_sound(source):
    """Copy user-provided audio into a persistent library, retaining its descriptive filename."""
    source = Path(source).resolve()
    if not source.is_file() or source.suffix.lower() not in USER_AUDIO_EXTENSIONS:
        raise ValueError('Choose an MP3, WAV, M4A, AAC, OGG or FLAC audio file.')
    root = user_sound_dir()
    safe_name = re.sub(r'[^\w .()\-]+', '_', source.stem, flags=re.UNICODE).strip(' ._-')[:90] or 'Imported sound'
    destination = root / (uuid.uuid4().hex[:12] + source.suffix.lower())
    shutil.copy2(source, destination)
    metadata = root / 'library.json'
    try:
        entries = json.loads(metadata.read_text(encoding='utf-8')) if metadata.exists() else []
        if not isinstance(entries, list): entries = []
    except (OSError, ValueError, TypeError):
        entries = []
    entries.append({'file': destination.name, 'name': safe_name})
    metadata.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding='utf-8')
    return str(destination)

def resolve_sound(key):
    if str(key).startswith('board_'):
        return sound_path(key)
    filename = Path(str(key)).name
    if filename != str(key) or not filename:
        raise ValueError('Invalid sound file')
    path = user_sound_dir() / filename
    if not path.is_file(): raise FileNotFoundError(path)
    return str(path)
