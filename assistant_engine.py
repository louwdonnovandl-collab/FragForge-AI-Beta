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
    intro = re.search(r'\bintro\b[^\n.]{0,65}?(\d{1,2})\s*(?:seconds?|secs?|s\b)', t)
    intro_alt = re.search(r'(\d{1,2})\s*(?:seconds?|secs?|s\b)[^\n.]{0,40}?\bintro\b', t)
    intro_seconds = min(20, int((intro or intro_alt).group(1))) if (intro or intro_alt) else (10 if re.search(r'\bintro\b', t) else 0)
    target_seconds = extract_output_duration(text)
    # Match all familiar multiplier expressions: "speed x2", "speed 2x",
    # "2x speed", "playback at 2 times" and "x2 playback". A bare
    # duration like "60 seconds" must never be mistaken for a speed.
    speed_match = (
        re.search(r'\b(?:sped\s*up|speed(?:\s*up)?|playback(?:\s*speed)?)'
                  r'(?:\s*(?:to|at|by|of|:|=))?\s*x?\s*(\d+(?:[.,]\d+)?)'
                  r'\s*(?:x\b|times\b)?', t)
        or re.search(r'\b(\d+(?:[.,]\d+)?)\s*(?:x\b|times\b)'
                     r'(?:\s+(?:speed|playback))?', t)
        or re.search(r'\bx\s*(\d+(?:[.,]\d+)?)'
                     r'(?:\s+(?:speed|playback))?\b', t)
    )
    requested_speed = max(.25,min(8.,float(speed_match.group(1).replace(',','.')))) if speed_match else 1.
    highlight = bool(re.search(r'\b(highlights?|montage|shorts?|reels?|tiktok|clips?)\b',t))
    focus_kills = bool(re.search(r'\b(kills?|zombies?|takedowns?|combat|fights?|fighting|multikills?)\b',t))
    focus_loot = bool(re.search(r'\b(loot|looting|inventory|supplies|containers?)\b',t))
    # Negation must be resolved before positive keyword detection: "do not add music"
    # contains "music" but is explicitly NOT a music request.
    no_music = bool(re.search(r"\b(?:no|without|avoid|skip|exclude|don't|do not|never)\s+(?:(?:add|insert|include|use|play|select|any|background|random)\s+){0,4}(?:music|songs?|soundtrack|background (?:music|track)|audio track)\b",t))
    no_sfx = bool(re.search(r"\b(?:no|without|avoid|skip|exclude|don't|do not|never)\s+(?:(?:add|insert|include|use|play|any|random|extra)\s+){0,4}(?:sound effects?|sfx|boom|whoosh|sound cues?)\b",t))
    no_sounds = no_music or no_sfx or bool(re.search(r'\b(no|without|avoid)\s+(?:random\s+)?(?:sound|audio|boom|sfx|music)',t))
    no_fx = bool(re.search(r'\b(no|without|avoid)\s+(?:visual\s+)?(?:effects?|fx|zooms?)',t))
    music = not no_music and not no_sounds and bool(re.search(r'\b(?:add|insert|include|use|play|select|choose|put|with|background)\b[^.!?\n]{0,60}\b(?:music|songs?|soundtrack|background track)\b|\b(?:music|song|soundtrack)\s*:',t))
    # "Prioritize combat" is a ranking instruction, not "combat only".
    # Only an EXPLICIT exclusive instruction may reject supporting gameplay.
    exclusive_request=bool(re.search(
        r'\b(?:only|exclusively|just|nothing but)\s+(?:actual\s+)?'
        r'(?:combat|fighting|fights?|kills?|zombie attacks?)\b'
        r'|\b(?:combat|fighting|fights?|kills?)\s+only\b'
        r'|\b(?:no|without)\s+(?:any\s+)?(?:noncombat|filler|supporting footage)\b',t))
    # A negated mention of "combat only" is NOT an exclusive editing request.
    # Example: "Prioritize does not mean combat only. Include normal gameplay".
    denied_exclusivity=bool(re.search(
        r'\b(?:not|never|isn.t|doesn.t|does\s+not|do\s+not|is\s+not)\s+'
        r'(?:(?:\w+)[\s-]+){0,5}'
        r'(?:combat[\s-]+only|only\s+combat|exclusively\s+combat)\b',t))
    supports_other_gameplay=bool(re.search(
        r'\b(?:include|allow|add|use|mix\s+in)\s+'
        r'(?:\w+\s+){0,4}'
        r'(?:normal|general|noncombat|supporting|other)\s+'
        r'(?:\w+\s+){0,3}(?:gameplay|footage|scenes|clips)\b',t))
    combat_only=exclusive_request and not (
        denied_exclusivity or supports_other_gameplay)
    priority_combat=bool(focus_kills and re.search(
        r'\b(?:prioriti[sz]e|focus|mostly|emphasi[sz]e|highlight|feature|mainly)\b',t))
    # Prioritising footage is a selection/ranking preference, NOT a request
    # to rearrange time. Only clear, affirmative placement instructions may
    # make combat the opening. Keep this separate from combat_only.
    opening_patterns=(
        r'\b(?:start|begin|open|lead)\s+'
        r'(?:(?:the|my|this|our|video|edit|montage)\s+){0,4}'
        r'(?:with|on)\s+(?:(?:a|the|best|strongest|short|quick|good|'
        r'exciting)\s+){0,3}(?:combat|fight(?:ing)?|kills?|action|battle)\b',
        r'\b(?:put|place|move|show|feature|use)\b[^.!?\n]{0,85}?'
        r'\b(?:combat|fight(?:ing)?|kills?|action|battle)\b'
        r'[^.!?\n]{0,65}?\b(?:at|in|near|within)\s+(?:the\s+)?'
        r'(?:very\s+)?(?:start|beginning|opening|first\s+\d+\s+seconds?)\b',
        r'\b(?:combat|fight(?:ing)?|kills?|action|battle)\s+first\b',
        r'\b(?:combat|fight(?:ing)?|kills?|action|battle)\s+'
        r'(?:at\s+the\s+)?(?:start|beginning|opening)\b',
        r'\b(?:first\s+\d+\s+seconds?|opening|intro)\b'
        r'[^.!?\n]{0,55}?\b(?:combat|fight(?:ing)?|kills?|action|battle)\b',
        r'\b(?:combat|fight(?:ing)?|kills?|action|battle)\b'
        r'[^.!?\n]{0,55}?\bwithin\s+the\s+first\s+\d+\s+seconds?\b',
    )
    combat_opening=bool(focus_kills and any(
        re.search(pattern,t) for pattern in opening_patterns))
    # "add fades" means scene-to-scene crossfades in a montage. A request
    # solely for an ending fade remains independent (not a scene crossfade).
    transition_keyword=bool(re.search(
        r'\b(?:cross[- ]?fades?|dissolves?|transitions?|ripple|turbulence|'
        r'wipes?|slides?)\b',t))
    scene_fades=bool(re.search(
        r'\b(?:add|apply|use|insert|include|make|put|smooth)\b'
        r'[^.!?\n]{0,55}?\bfades?\b'
        r'|\bfades?\b[^.!?\n]{0,55}?\b(?:between|scenes?|clips?|cuts?)\b'
        r'|\b(?:between|at|on)\s+(?:every\s+|each\s+|the\s+)?'
        r'(?:scenes?|clips?|cuts?)\s+fades?\b',t))
    end_only=bool(re.search(
        r'\b(?:final|ending|end)\s+fades?\b'
        r'|\bfade\s+(?:out\s+)?(?:the\s+)?video\s+to\s+black\b'
        r'|\bfade\s+to\s+black\b',t))
    negative_fades=bool(re.search(
        r"\b(?:no|without|avoid|skip|never|don't|do not)\s+"
        r"(?:(?:add|apply|use|insert|any|scene|smooth|cross)\s+){0,3}"
        r"(?:fades?|cross[- ]?fades?|transitions?)\b",t))
    transitions_explicit=(transition_keyword or (scene_fades and not
                          (end_only and not re.search(r'\b(?:between|scenes?|cuts?)\b',t)))) and not negative_fades
    style=('radial' if 'ripple' in t else
           'pixelize' if 'turbulence' in t else 'fade')
    seconds=0.5
    # "ripple transition between cuts at 1 second fades" belongs to
    # the transition length; it is not the total output duration.
    transition_time=(re.search(
        r'(?:transition|cross[- ]?fade|ripple|wipe|dissolve)'
        r'[^.!?\n]{0,55}?\b(\d+(?:[.,]\d+)?)\s*(?:seconds?|secs?|s\b)',t)
        or re.search(
        r'\b(\d+(?:[.,]\d+)?)\s*(?:seconds?|secs?|s\b)'
        r'\s*(?:cross[- ]?fades?|transitions?|fades?|dissolves?)\b',t))
    if transition_time and transitions_explicit:
        seconds=max(.25,min(3.,float(transition_time.group(1).replace(',','.'))))
    explicit_end=bool(re.search(
        r'\b(?:fade\s+(?:the\s+)?(?:video\s+)?to\s+black|'
        r'(?:final|ending|end)\s+fade(?:[- ]out)?|fade\s+out\s+at\s+the\s+end)\b',t))
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
        'fade_transition':transitions_explicit,
        'explicit_crossfade':transitions_explicit,
        'transition_style':style,
        'crossfade_seconds':seconds,
        'explicit_end_fade':explicit_end,
        'end_fade_seconds':1.0,
        'combat_only':combat_only,
        'combat_priority':priority_combat,
        'combat_first':combat_opening,
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
        'Combat policy: '+('Combat ONLY (explicit requirement)' if p.get('combat_only')
                           else 'Combat prioritized throughout; supporting gameplay allowed' if p.get('focus_kills')
                           else 'General gameplay'),
        'Opening: '+('prioritize possible combat within first 3 seconds; do not claim a verified kill' if p.get('combat_first') else 'source order preserved unless a different opening was explicitly requested'),
        'Focus on looting: '+yes(p.get('focus_loot',False)),
        ('Export transitions: '+p.get('transition_style','fade')
         +f" ({p.get('crossfade_seconds',0.5):g}s) — requested"
         if p.get('explicit_crossfade') else
         'Export transitions: Not requested (can be added in Transitions)'),
        ('Final fade: '+f"{p.get('end_fade_seconds',1):g}s requested"
         if p.get('explicit_end_fade') else 'Final fade: Not requested'),
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
