import argparse
import json
from .core import probe, render, suggest_highlights

def main():
    p=argparse.ArgumentParser(description='FragForge AI v0.4 video editor')
    sub=p.add_subparsers(dest='action',required=True)
    info=sub.add_parser('info');info.add_argument('file')
    hi=sub.add_parser('highlights');hi.add_argument('file');hi.add_argument('--threshold',type=float,default=.35)
    edit=sub.add_parser('render');edit.add_argument('project',help='JSON project file');edit.add_argument('output')
    edit.add_argument('--transition',type=float,default=.35)
    edit.add_argument('--fps',type=int,choices=[30,60,120],default=60)
    edit.add_argument('--resolution',choices=['720p','1080p','1440p','4k'],default='1080p')
    edit.add_argument('--crf',type=int,default=20)
    args=p.parse_args()
    if args.action=='info': result=probe(args.file)
    elif args.action=='highlights': result=suggest_highlights(args.file,args.threshold)
    else:
        from pathlib import Path
        file=Path(args.project).resolve()
        project=json.loads(file.read_text(encoding='utf-8'))
        clips=project['clips']
        for c in clips:
            src=Path(c['path'])
            if not src.is_absolute(): c['path']=str(file.parent/src)
        sizes={'720p':(1280,720),'1080p':(1920,1080),'1440p':(2560,1440),'4k':(3840,2160)}
        w,h=sizes[args.resolution]
        result=render(clips,args.output,transition=args.transition,fps=args.fps,width=w,height=h,crf=args.crf)
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
