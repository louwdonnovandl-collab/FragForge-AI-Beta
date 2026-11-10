"""Export-backed Eli transition palette.

These map to FFmpeg xfade presets. Radial and pixelize approximate the
requested ripple/turbulence aesthetics; they are not fluid simulations.
"""
TRANSITION_STYLES = {
    'fade': 'Opacity Crossfade',
    'dissolve': 'Soft Dissolve',
    'fadeblack': 'Fade Through Black',
    'fadewhite': 'Fade Through White',
    'wipeleft': 'Wipe Left',
    'wiperight': 'Wipe Right',
    'slideleft': 'Slide Left',
    'slideright': 'Slide Right',
    'radial': 'Radial Reveal (ripple-like)',
    'pixelize': 'Pixel Turbulence',
}


def scene_cut_indices(clips):
    """Return V1 pair indexes (1-based next-clip indexes) for actual scene cuts.

    Clip joins from the same file at the same source timestamp and speed
    are continuous and intentionally get no transition.
    """
    import os
    ordered=sorted(
        (c for c in clips if c.get('track')=='V1' and c.get('kind')!='effect'),
        key=lambda c:float(c.get('at',0.)))
    cuts=[]
    for index,(before,after) in enumerate(zip(ordered,ordered[1:]),1):
        duration=(float(before['end'])-float(before['start'])) / max(.01,float(before.get('speed',1.)))
        if abs(float(after.get('at',0))-float(before.get('at',0))-duration)>.04:
            raise ValueError('V1 contains a gap or overlap. Fix the timeline before using Eli transitions.')
        same_file=(os.path.normcase(os.path.abspath(str(before['path'])))
                   ==os.path.normcase(os.path.abspath(str(after['path']))))
        continuous=(same_file
                    and abs(float(before['end'])-float(after['start']))<=.05
                    and abs(float(before.get('speed',1.))-float(after.get('speed',1.)))<=.0001)
        if not continuous:
            cuts.append(index)
    return ordered,cuts


def plan_montage_transitions(clips, selected_styles=(), seconds=.5,
                             manual_boundaries=None, rng=None,
                             fade_ending=None):
    """Plan transitions WITHOUT modifying clips or rescanning source footage.

    No chosen style => randomize from ten presets. Default boundaries => all
    real timeline cuts. Manual selections affect only named boundaries.
    Every selected cut is validated against the chosen duration BEFORE apply.
    """
    import random
    from media import eli_transition_profile

    seconds=float(seconds)
    if not .25<=seconds<=3.:
        raise ValueError('Transition duration must be 0.25 to 3 seconds.')
    unknown=set(selected_styles)-set(TRANSITION_STYLES)
    if unknown:
        raise ValueError('Unknown transition styles: '+', '.join(sorted(unknown)))
    planned=[dict(c) for c in clips]
    ordered,cuts=scene_cut_indices(planned)
    if len(ordered)<2 or not cuts:
        raise ValueError('No separate V1 scenes found. Add at least two different scene clips.')
    chosen=set(cuts) if manual_boundaries is None else set(int(i) for i in manual_boundaries)
    if not chosen:
        raise ValueError('Select at least one boundary or enable automatic detection.')
    if chosen-set(cuts):
        raise ValueError('Some selected boundaries are continuous footage or not valid cuts.')

    available=tuple(selected_styles) if selected_styles else tuple(TRANSITION_STYLES)
    generator=rng if rng is not None else random.SystemRandom()
    # The caller must be able to see EXACTLY what Eli selected.
    report=[]
    for index,c in enumerate(ordered):
        c['eli_auto_montage']=True
        c['fade']=0.
        c['crossfade_seconds']=float(c.get('crossfade_seconds',seconds))
        c['transition']=str(c.get('transition','fade')).lower()
        if index==0:
            c['crossfade_seconds']=seconds
            c['transition']='fade'
            continue
        if index not in cuts:
            c['transition']='cut'
            c['crossfade_seconds']=0.
            continue
        if index in chosen:
            c['transition']=generator.choice(available)
            c['crossfade_seconds']=seconds
        elif c['transition'] not in TRANSITION_STYLES:
            c['transition']='cut'
            c['crossfade_seconds']=0.
        # An unselected boundary retains its existing valid styling.
        policy=eli_transition_profile(ordered[index-1],c)
        report.append({
            'boundary':index,
            'output_seconds':round(float(c['at']),3),
            'style':TRANSITION_STYLES.get(c['transition'],'Cut'),
            'duration':round(float(policy['overlap']),3),
            'applied_now':index in chosen,
        })

    if fade_ending is None:
        last_fade=bool(ordered[-1].get('eli_end_fade'))
    else:
        last_fade=bool(fade_ending)
    for c in ordered:
        c['eli_end_fade']=False
    ordered[-1]['eli_end_fade']=last_fade
    return planned,report
