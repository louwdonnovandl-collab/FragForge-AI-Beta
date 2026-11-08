"""Offline, explainable selection of user-licensed music files.
Metadata is based on filenames and optional sidecar JSON; this is not acoustic genre recognition.
"""
import json
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
    for key in ('title','genre','mood','license'):
     if isinstance(meta.get(key),str):data[key]=meta[key]
  except (ValueError,OSError):pass
 return data

def scan_library(folder,limit=50):
 root=Path(folder)
 if not root.is_dir():return []
 return [track_metadata(p) for p in sorted(root.iterdir(),key=lambda p:p.name.lower()) if p.is_file() and p.suffix.lower() in EXTENSIONS][:max(0,limit)]

def choose_track(tracks,request):
 items=[track_metadata(x['path'] if isinstance(x,dict) else x) for x in tracks]
 if not items:return None
 request=str(request or '').strip().lower()
 # Explicit title takes priority over genre; avoid silently substituting a different named song.
 for item in items:
  if request and (request==item['title'].lower() or request==item['path'].name.lower()):
   return dict(item,reason='exact title match')
 genre=genre_for_request(request)
 if genre:
  candidates=[x for x in items if x['genre']==genre]
  if candidates:return dict(candidates[0],reason='genre metadata match')
 return dict(items[0],reason='default first track; review before applying')
