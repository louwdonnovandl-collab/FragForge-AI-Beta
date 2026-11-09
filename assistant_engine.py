"""Offline, deterministic editing instruction interpreter. No remote services."""
import re

_DURATION_TOKEN = re.compile(
    r'\b(\d{1,4}(?:[.,]\d+)?)\s*[- ]?\s*'
    r'(seconds?|secs?|minutes?|mins?|min\b)\b', re.I)


def extract_output_duration(text):
    """Prefer total video runtime over intro, transition and end-fade timings."""
    t = str(text or '').lower().replace('×', 'x')
    candidates = []
    for match in _DURATION_TOKEN.finditer(t):
        before = t[max(0,match.start()-90):match.start()]
        after = t[match.end():match.end()+75]
        # This number belongs to a transition, fade, intro or combat padding.
        if re.match(
            r'\s*(?:(?:smooth|scene[- ]to[- ]scene|final|ending|audio|black)\s+)?'
            r'(?:crossfades?|dissolves?|transitions?|fades?|fade[- ]outs?|'
            r'intro|pre[- ]?roll|before|after)\b', after):
            continue
        if re.search(
            r'\b(?:fade|crossfade|transition|dissolve|intro|before|after|last)\s*'
            r'(?:(?:to|from|of|for|over|during|the)\s*){0,3}$',
            before[-55:]):
            continue
        seconds = float(match.group(1).replace(',', '.'))
        if match.group(2).startswith('min'):
            seconds *= 60.
        score = 0
        if re.match(
            r'\s*(?:[- ]?\s*(?:long\s+)?(?:video|montage|edit|clip|reel|'
            r'highlight|gaming\s+highlight)|target|runtime|duration)\b',
            after):
            score += 10
        if re.search(
            r'\b(?:target|duration|runtime|length|total|exactly|'
            r'video|montage|output|export|create|make|build|edit)\b',
            before[-75:]):
            score += 4
        candidates.append((score, -match.start(), seconds))
    return max(1., min(10800., max(candidates)[2])) if candidates else 0.


def interpret_request(text):
    """Extract explicit user constraints without LLM changes to numeric input."""
    t = text.lower().replace('×', 'x')
    intro = re.search(r'(?:intro|opening)[^\n.]{0,65}?(\d{1,2})\s*(?:seconds?|secs?|s\b)', t)
    intro_alt = re.search(r'(\d{1,2})\s*(?:seconds?|secs?|s\b)[^\n.]{0,40}?(?:intro|opening)', t)
    intro_seconds = min(20, int((intro or intro_alt).group(1))) if (intro or intro_alt) else (10 if re.search(r'\b(intro|opening)\b', t) else 0)
    target_seconds = extract_output_duration(text)
    speed_match = re.search(r'\b(?:sped\s*up|speed(?:\s*up)?|playback)(?:\s*(?:to|at|by))?\s*(\d+(?:[.,]\d+)?)\s*(?:x\b|times\b)?', t) or re.search(r'\b(\d+(?:[.,]\d+)?)\s*(?:x\b|times\b)', t)
    requested_speed = max(.25,min(8.,float(speed_match.group(1).replace(',','.')))) if speed_match else 1.
    highlight = bool(re.search(r'\b(highlights?|montage|shorts?|reels?|tiktok|clips?)\b',t))
    focus_kills = bool(re.search(r'\b(kills?|zombies?|takedowns?|combat|fights?|multikills?)\b',t))
    focus_loot = bool(re.search(r'\b(loot|looting|inventory|supplies|containers?)\b',t))
    # Negation must be resolved before positive keyword detection: "do not add music"
    # contains "music" but is explicitly NOT a music request.
    no_music = bool(re.search(r"\b(?:no|without|avoid|skip|exclude|don't|do not|never)\s+(?:(?:add|insert|include|use|play|select|any|background|random)\s+){0,4}(?:music|songs?|soundtrack|background (?:music|track)|audio track)\b",t))
    no_sfx = bool(re.search(r"\b(?:no|without|avoid|skip|exclude|don't|do not|never)\s+(?:(?:add|insert|include|use|play|any|random|extra)\s+){0,4}(?:sound effects?|sfx|boom|whoosh|sound cues?)\b",t))
    no_sounds = no_music or no_sfx or bool(re.search(r'\b(no|without|avoid)\s+(?:random\s+)?(?:sound|audio|boom|sfx|music)',t))
    no_fx = bool(re.search(r'\b(no|without|avoid)\s+(?:visual\s+)?(?:effects?|fx|zooms?)',t))
    music = not no_music and not no_sounds and bool(re.search(r'\b(?:add|insert|include|use|play|select|choose|put|with|background)\b[^.!?\n]{0,60}\b(?:music|songs?|soundtrack|background track)\b|\b(?:music|song|soundtrack)\s*:',t))
    return {
        'mode':'highlight' if highlight or (target_seconds and target_seconds <= 180) else 'longform',
        'target_seconds':target_seconds,
        'target_minutes':target_seconds/60 if target_seconds else 0,
        'remove_stagnant':not bool(re.search(r'\bkeep\s+(?:all\s+)?loading screens',t)),
        'speedup':not bool(re.search(r'\b(no|without|avoid)\s+(?:speed.?up|fast forward)',t)),
        'effects':not no_fx and bool(re.search(r'\b(effects?|zoom|flash|shake|cinematic|visual|fx)\b',t)),
        'sounds':not no_sfx and not no_sounds and bool(re.search(r'\b(?:add|insert|include|use|play)\b[^.!?\n]{0,50}\b(?:sound effects?|sfx|whoosh|impact cues?)\b',t)),
        'music':music,
        'captions':bool(re.search(r'\b(captions?|subtitles?|on.screen text)\b',t)),
        'intro_seconds':intro_seconds,
        'requested_speed':requested_speed,
        'explicit_speed':bool(speed_match),
        'focus_kills':focus_kills,
        'focus_loot':focus_loot,
        'fade_transition':bool(re.search(r'\b(?:fades?|crossfades?|transitions?|dissolves?)\b',t)),
        'crossfade_seconds':0.5,
        'end_fade_seconds':1.0,
        'combat_first':bool(focus_kills and (highlight or target_seconds and target_seconds<=180)),
        'max_noncombat_opening_seconds':3.0,
        'no_music':no_music,
        'original':text.strip(),
    }

def describe_plan(p):
    yes=lambda v:'Requested' if v else 'Not requested'
    lines=[
        'EDIT TYPE: '+('Short highlight montage' if p['mode']=='highlight' else 'Preserve long-form gameplay'),
        'Stagnant/loading-screen removal: '+('Keep footage' if not p['remove_stagnant'] else 'Analyze and suggest cuts'),
        f"Playback speed: {p['requested_speed']:g}× {'(explicitly requested)' if p.get('explicit_speed') else '(automatic pacing default)'}",
        'Visual effects: '+yes(p['effects']),
        'Sound effects: '+yes(p['sounds']),
        'Background music: '+('NO MUSIC (explicit request)' if p.get('no_music') else ('Requested' if p.get('music') else 'Not requested')),
        'Captions/subtitles: '+yes(p['captions']),
        'Target output duration: '+(f"{p.get('target_seconds',0):g} seconds" if p.get('target_seconds') else 'Automatic') ,
        'Create intro: '+(str(p['intro_seconds'])+' seconds' if p['intro_seconds'] else 'Not requested'),
        'Focus on kills: '+yes(p.get('focus_kills',False)),
        'Opening: '+('prioritize possible combat within first 3 seconds; do not claim a verified kill' if p.get('combat_first') else 'chronological/general footage'),
        'Focus on looting: '+yes(p.get('focus_loot',False)),
        f"Export-only transitions: {p.get('crossfade_seconds',0.5):g}s crossfade between approved cuts",
        f"Final fade: {p.get('end_fade_seconds',1):g}s fade to black and silence",
        '',
        'SUPPORTED NOW: scene/motion analysis, long-form cuts, 2× pacing, fades, short-montage effects and soundboard.',
        'NOT YET AUTOMATED: speech transcription, semantic gameplay events, context-sensitive long-form effects, image-generated intros.',
        'NEXT: Open Auto Edit, inspect the settings and analysis results, then approve changes.',
    ]
    return '\n'.join(lines)


def task_queue(plan):
    """Explicit request-to-capability mapping. Never label unsupported work as done."""
    tasks=[]
    def add(label, supported, detail):tasks.append({'label':label,'supported':supported,'detail':detail})
    if plan.get('focus_kills'):add('Find and prioritize zombie kills',False,'Requires Project Zomboid event recognition; not yet available')
    if plan.get('focus_loot'):add('Find and prioritize looting',False,'Requires inventory/loot event recognition; not yet available')
    if plan.get('intro_seconds'):add(f"Assemble {plan['intro_seconds']}-second action-candidate intro",True,'Uses activity candidates; verify kills manually')
    if plan.get('target_seconds'):add(f"Target {plan['target_seconds']:g} seconds",True,'Activity-based selection with an approximate duration target')
    if plan.get('remove_stagnant'):add('Remove stagnant/loading footage',True,'Available in current Auto Edit analysis')
    if plan.get('speedup'):add('Speed up low-activity footage',plan.get('mode')=='longform','Available for long-form at 2×')
    if plan.get('effects'):add('Place visual effects at candidate action cuts',True,'Automatic placement is not kill-aware')
    if plan.get('music'):add('Add background music',True,'Auto-select bundled music by requested genre; confirm actual export audio')
    if plan.get('sounds'):add('Place built-in sound cues at candidate cuts',True,'Bundled original rock tracks are separate from transition sound effects')
    if plan.get('fade_transition'):add('Fade into gameplay',True,'Short clip fades are supported; exact intro-to-main transition needs intro assembly')
    if plan.get('captions'):add('Generate captions',False,'Speech transcription is not yet integrated')
    return tasks

def task_report(plan):
    tasks=task_queue(plan)
    if not tasks:return 'No actionable tasks detected. Describe the edits you want.'
    return '\n'.join(('READY' if t['supported'] else 'NOT IMPLEMENTED')+' | '+t['label']+' — '+t['detail'] for t in tasks)
