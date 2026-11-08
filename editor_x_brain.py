"""Editor-X 2.0: deterministic intent extraction and safe edit proposals.

This module NEVER mutates the timeline. The UI/editor must validate, preview,
and explicitly apply changes. Only assets actually in the local library may be used.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field, asdict

@dataclass
class EditIntent:
    operation: str = "modify_existing"
    activity: str = "unspecified"
    duration_seconds: int | None = None
    intro_seconds: int | None = None
    intro_speed: float | None = None
    music_genre: str | None = None
    music_track: str | None = None
    captions: list[str] = field(default_factory=list)
    smooth_transitions: bool | None = None
    remove_pauses: bool = False
    remove_stagnant: bool = False
    add_scene_captions: bool = False
    preserve_existing: bool = True
    warnings: list[str] = field(default_factory=list)

def parse_instruction(message: str) -> EditIntent:
    s = ' '.join(message.split()); lower=re.sub(r'(\d)-(?=(?:second|minute|sec|min))',r'\1 ',s.lower())
    result=EditIntent()
    command=re.sub(r'["“][^"”]*["”]','',lower)
    if re.search(r'\b(new edit|start over|from scratch|replace (?:the |my )?edit)\b',lower):
        result.operation='replace_existing';result.preserve_existing=False
    if re.search(r'\b(combat|fight|fighting|kills?|battle|shooting)\b',command):result.activity='combat'
    elif re.search(r'\b(explor|chill|scenic|travel|landscape)\w*',command):result.activity='exploration'
    if re.search(r'\b(both|mix|combine)\b',lower) and re.search(r'combat|fight',lower) and re.search(r'explor|chill',lower):result.activity='mixed'
    m=re.search(r'\b(?:about|around|approximately|roughly|\+/-|\+-)?\s*(\d{1,3})\s*(seconds?|secs?|minutes?|mins?)\b',lower)
    if m:result.duration_seconds=int(m.group(1))*(60 if m.group(2).startswith(('min',)) else 1)
    durations=re.findall(r'\b(\d{1,3})\s*(seconds?|secs?|minutes?|mins?)\b',lower)
    if len(durations)>1:
        amount,unit=durations[-1]
        result.duration_seconds=int(amount)*(60 if unit.startswith('min') else 1)
    m=re.search(r'\b(\d{1,3})\s*(?:seconds?|secs?)\s*(?:long\s*)?(?:combat\s*)?intro\b',lower)
    if m:result.intro_seconds=int(m.group(1))
    elif re.search(r'\b(?:\d{1,3})\s*(?:seconds?|secs?)\s+combat\s+intro\b',lower):result.intro_seconds=result.duration_seconds
    elif 'intro' in lower and result.duration_seconds is not None and not re.search(r'\b(main|full|whole)\s+(?:video|edit)\b',lower):
        result.intro_seconds=result.duration_seconds
    m=re.search(r'\b(\d+(?:\.\d+)?)\s*[x×]\s*(?:speed|playback)?\b',lower)
    if m:result.intro_speed=float(m.group(1)) if 'intro' in lower else None
    if re.search(r'\b(rock|metal|ncs|ambient|chill|lofi|electronic)\b',command):
        for genre in ('rock','metal','ncs','ambient','lofi','electronic','chill'):
            if re.search(r'\b'+genre+r'\b',command):result.music_genre=genre;break
    # User quotes are exact data: do not let the language model paraphrase them.
    result.captions=re.findall(r'["“]([^"”]{1,180})["”]',s)
    if re.search(r'\b(captions? explaining|scene captions?|context.aware captions?)\b',lower):result.add_scene_captions=True
    if re.search(r'\b(no|without|remove|disable|avoid)\s+(?:the\s+)?(?:smooth|soft)\s+transitions?\b',lower):result.smooth_transitions=False
    elif re.search(r'\b(smooth\s+(?:out\s+)?(?:the\s+)?transitions?|smoother\s+transitions?|add\s+(?:smooth|soft)\s+transitions?)\b',lower):result.smooth_transitions=True
    elif re.search(r'\bno[,;:. ]+smooth\s+out\s+(?:the\s+)?transitions?\b',lower):result.smooth_transitions=True
    result.remove_pauses=bool(re.search(r'\b(remov\w*|cut\s+out|skip)\b.{0,45}\b(pause|menu|loading)\w*',lower))
    result.remove_stagnant=bool(re.search(r'\b(remov\w*|cut\s+out|skip)\b.{0,45}\b(stagnant|idle|still|boring)\w*',lower))
    if result.duration_seconds and result.duration_seconds>24*3600:result.warnings.append('Requested duration exceeds one day')
    return result

def describe_intent(intent: EditIntent) -> str:
    parts=[]
    if intent.duration_seconds is not None:parts.append(f'{intent.duration_seconds}-second target')
    if intent.activity!='unspecified':parts.append(intent.activity+' footage')
    if intent.intro_seconds is not None:parts.append(f'{intent.intro_seconds}-second intro')
    if intent.intro_speed is not None:parts.append(f'{intent.intro_speed:g}× intro speed')
    if intent.music_genre:parts.append(intent.music_genre+' music (subject to local availability)')
    if intent.smooth_transitions is not None:parts.append('smooth transitions' if intent.smooth_transitions else 'hard cuts')
    if intent.captions:parts.append('exact caption(s): '+', '.join(repr(c) for c in intent.captions))
    if intent.add_scene_captions:parts.append('scene-aware captions after footage analysis')
    if intent.remove_pauses:parts.append('remove pause/loading screens after verification')
    if intent.remove_stagnant:parts.append('remove stagnant sections after verification')
    if not parts:parts=['review the current V1 timeline']
    return ('I can prepare changes to the existing V1 edit: '+', '.join(parts)+'. '
            'I will preserve unrelated edits and verify footage and available music before applying anything. '
            'Select Prepare Edit to analyze and preview the proposed changes.')

def timeline_snapshot(clips):
    """Immutable, compact V1 snapshot; never cache media frames or modify clips."""
    result=[]
    for clip in clips:
        if not isinstance(clip,dict):continue
        result.append({k:clip.get(k) for k in ('path','start','end','speed','volume','track','effects','text') if k in clip})
    return result
