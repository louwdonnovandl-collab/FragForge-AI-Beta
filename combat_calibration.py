"""Eli scene-recognition benchmark helpers.

A known combat timestamp only controls WHERE Eli samples more frames.
It is never promoted to a detected combat label on its own.
"""
import re


def parse_reference_timecode(value, source_end):
    """Accept MM:SS or HH:MM:SS. Empty input disables calibration."""
    value=str(value or '').strip()
    if not value:
        return None
    if not re.fullmatch(r'\d+(?::[0-5]\d){1,2}',value):
        raise ValueError('Reference must be MM:SS or HH:MM:SS (example 14:49).')
    parts=[int(part) for part in value.split(':')]
    total=0
    for part in parts:
        total=total*60+part
    if not 0<=total<float(source_end):
        raise ValueError('Reference combat timestamp is outside the source recording.')
    return float(total)


def calibration_sample_times(reference, source_end, max_samples=12):
    """Local 1.5-second cadence, ±9 to +12 seconds, within a firm budget."""
    if reference is None or max_samples<=0:
        return []
    end=float(source_end)
    offsets=[-9.,-7.5,-6.,-4.5,-3.,-1.5,0.,1.5,3.,4.5,6.,7.5,9.,10.5,12.]
    within=[round(max(0.,min(end-.2,float(reference)+delta)),2)
            for delta in offsets if 0<=float(reference)+delta<end]
    within=sorted(set(within),key=lambda t:(abs(t-float(reference)),t))
    return sorted(within[:int(max_samples)])


def calibration_report(samples, reference, radius=13.):
    """Grounded summary, never a fabricated combat event or verification."""
    if reference is None:
        return {'enabled':False,'sampled_frames':0,'combat_frames':0,
                'has_repeated_combat':False,'reference_seconds':None}
    near=[sample for sample in samples
          if abs(float(sample.get('time',-9999))-float(reference))<=radius]
    hits=sorted(float(sample['time']) for sample in near
                if sample.get('event')=='combat'
                and float(sample.get('confidence',0))>=.65)
    repeated=any(0<later-earlier<=5.5
                 for earlier,later in zip(hits,hits[1:]))
    return {'enabled':True,'reference_seconds':round(float(reference),2),
            'sampled_frames':len(near),'combat_frames':len(hits),
            'has_repeated_combat':repeated}
