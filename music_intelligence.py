"""Offline, explainable selection of user-licensed music files.
Metadata is based on filenames and optional sidecar JSON; this is not acoustic genre recognition.
"""
import json
import secrets
from pathlib import Path

EXTENSIONS={'.mp3','.wav','.flac','.m4a','.ogg','.aac'}
GENRES={
 'rock_metal': ('rock','metal','heavy','guitar','hardcore','punk'),
 'cinematic_action': ('cinematic','action','battle','trailer','orchestral'),
 'dark_survival': ('dark','survival','horror','zombie','scary','suspense'),
 'chill_exploration': ('chill','ambient','exploration','calm','relax','lofi'),
 'epic_intro': ('epic','intro','opening','heroic','victory'),
}

def genre_for_request(request):
 text=str(request or '').lower()
 scores={genre:sum(1 for word in words if word in text) for genre,words in GENRES.items()}
 best=max(scores,key=scores.get)
 return best if scores[best] else None

def track_metadata(path):
 path=Path(path)
 data={'path':path,'title':path.stem,'genre':genre_for_request(path.stem) or 'unclassified', 'mood':'unspecified'}
 sidecar=path.with_suffix('.json')
 if sidecar.is_file():
  try:
   meta=json.loads(sidecar.read_text(encoding='utf-8'))
   if isinstance(meta,dict):
    for key in ('title','genre','mood','license','version'):
     if isinstance(meta.get(key),str):data[key]=meta[key]
  except (ValueError,OSError):pass
 return data

def scan_library(folder,limit=50):
 root=Path(folder)
 if not root.is_dir():return []
 return [track_metadata(p) for p in sorted(root.rglob('*'),key=lambda p:str(p).lower()) if p.is_file() and p.suffix.lower() in EXTENSIONS][:max(0,limit)]

def choose_track(tracks,request):
 items=[track_metadata(x['path'] if isinstance(x,dict) else x) for x in tracks]
 if not items:return None
 request=str(request or '').strip().lower()
 version='loop' if any(x in request for x in ('loop','looping','short version')) else 'full'
 import re
 cleaned=re.sub(r'\b(full.length|full version|full|looping|loop version|short version|loop|version)\b','',request).strip(' -.,:')
 # Exact title or numbered genre requests; no arbitrary substitution for a named song.
 for item in items:
  if item.get('version')==version and (cleaned==item['title'].lower() or cleaned==item['path'].name.lower() or cleaned==item['path'].stem.lower()):
   return dict(item,reason='exact requested track and version')
 # Named song inside a longer editing instruction takes priority over genre randomization.
 for item in items:
  title=item['title'].lower().strip()
  if item.get('version')==version and len(title)>=5 and title in request:
   return dict(item,reason='named requested song and version')
 genre=genre_for_request(request)
 match=re.search(r'\b(?:track|song|number|#)\s*(\d{1,2})\b',request)
 if genre and match:
  num=int(match.group(1))
  candidates=[x for x in items if x['genre']==genre and x.get('version')==version]
  candidates.sort(key=lambda x:x['path'].name)
  if 1<=num<=len(candidates):return dict(candidates[num-1],reason='requested genre, number and version')
  return None
 if genre and not match:
  candidates=[x for x in items if x['genre']==genre and x.get('version')==version]
  if candidates:return dict(secrets.choice(candidates),reason='random track from requested genre')
 return None
