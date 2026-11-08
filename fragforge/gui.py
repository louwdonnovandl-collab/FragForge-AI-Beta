"""Windows/Linux desktop GUI; requires tkinter and FFmpeg."""
import json
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from .core import probe, render, suggest_highlights

class Editor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('FragForge AI v0.4 | Gaming Video Editor')
        self.geometry('900x600');self.configure(bg='#10131c')
        self.clips=[]
        style=ttk.Style(self);style.theme_use('clam')
        style.configure('TFrame',background='#10131c');style.configure('TLabel',background='#10131c',foreground='#dce5f5')
        style.configure('TButton',padding=8)
        header=ttk.Frame(self);header.pack(fill='x',padx=18,pady=16)
        ttk.Label(header,text='FRAGFORGE  v0.4',font=('Arial',22,'bold')).pack(side='left')
        ttk.Button(header,text='Add gaming clips',command=self.add).pack(side='right')
        self.list=tk.Listbox(self,bg='#1b2130',fg='#dce5f5',selectbackground='#1b9c9b',height=14)
        self.list.pack(fill='both',expand=True,padx=18,pady=8)
        bar=ttk.Frame(self);bar.pack(fill='x',padx=18)
        for label,action in [('Remove',self.remove),('Move up',lambda:self.move(-1)),('Move down',lambda:self.move(1)),('Find scene highlights',self.highlights),('Save project',self.save),('Load project',self.load)]:
            ttk.Button(bar,text=label,command=action).pack(side='left',padx=2)
        options=ttk.Frame(self);options.pack(fill='x',padx=18,pady=16)
        self.res=tk.StringVar(value='1080p');self.fps=tk.StringVar(value='60');self.transition=tk.StringVar(value='0.35')
        for label,var,choices in [('Resolution',self.res,['720p','1080p','1440p','4k']),('FPS',self.fps,['30','60','120']),('Crossfade (seconds)',self.transition,['0','0.2','0.35','0.5','1'])]:
            ttk.Label(options,text=label).pack(side='left',padx=5)
            ttk.Combobox(options,textvariable=var,values=choices,width=8).pack(side='left',padx=5)
        ttk.Button(self,text='RENDER MP4',command=self.export).pack(pady=8)
        self.status=tk.StringVar(value='Ready. Add clips to begin.')
        ttk.Label(self,textvariable=self.status).pack(pady=12)
    def refresh(self):
        self.list.delete(0,'end')
        for i,c in enumerate(self.clips):self.list.insert('end',f"{i+1:02d}  {c['path']}  [{c['start']:.2f}s - {c['end']:.2f}s]")
    def add(self):
        for path in filedialog.askopenfilenames(filetypes=[('Video','*.mp4 *.mov *.mkv *.webm *.avi'),('All','*.*')]):
            try:
                meta=probe(path);self.clips.append({'path':path,'start':0,'end':meta['duration']})
            except Exception as e:messagebox.showerror('Import failed',str(e))
        self.refresh()
    def remove(self):
        sel=self.list.curselection()
        if sel:self.clips.pop(sel[0]);self.refresh()
    def move(self,d):
        sel=self.list.curselection()
        if sel:
            i=sel[0];j=i+d
            if 0<=j<len(self.clips):self.clips[i],self.clips[j]=self.clips[j],self.clips[i];self.refresh();self.list.selection_set(j)
    def save(self):
        path=filedialog.asksaveasfilename(defaultextension='.json',filetypes=[('FragForge project','*.json')])
        if path:open(path,'w',encoding='utf-8').write(json.dumps({'clips':self.clips},indent=2))
    def load(self):
        path=filedialog.askopenfilename(filetypes=[('FragForge project','*.json')])
        if path:
            try:self.clips=json.load(open(path,encoding='utf-8'))['clips'];self.refresh()
            except Exception as e:messagebox.showerror('Load failed',str(e))
    def highlights(self):
        sel=self.list.curselection()
        if not sel:return messagebox.showinfo('Select clip','Select a clip first.')
        def job():
            try:
                marks=suggest_highlights(self.clips[sel[0]]['path'])
                self.after(0,lambda:messagebox.showinfo('Scene-change suggestions',', '.join(map(str,marks[:60])) or 'No scene changes found'))
            except Exception as e:self.after(0,lambda:messagebox.showerror('Analysis failed',str(e)))
        threading.Thread(target=job,daemon=True).start()
    def export(self):
        if not self.clips:return messagebox.showinfo('No clips','Add clips first.')
        path=filedialog.asksaveasfilename(defaultextension='.mp4',filetypes=[('MP4 video','*.mp4')])
        if not path:return
        try:
            transition=float(self.transition.get());fps=int(self.fps.get());width,height={'720p':(1280,720),'1080p':(1920,1080),'1440p':(2560,1440),'4k':(3840,2160)}[self.res.get()]
        except Exception as e:return messagebox.showerror('Invalid options',str(e))
        self.status.set('Rendering...')
        def job():
            try:
                result=render([dict(c) for c in self.clips],path,transition=transition,fps=fps,width=width,height=height)
                self.after(0,lambda:(self.status.set('Render complete'),messagebox.showinfo('Success',f"Saved {path}\n{result['duration']:.2f}s")))
            except Exception as e:self.after(0,lambda:(self.status.set('Render failed'),messagebox.showerror('Render failed',str(e))))
        threading.Thread(target=job,daemon=True).start()

def main():Editor().mainloop()
if __name__=='__main__':main()
