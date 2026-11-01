"""Maher Download Manager: bilingual Windows desktop UI with verified in-app updates."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
import queue
import subprocess
import sys
import webbrowser
from urllib.parse import urlsplit
from datetime import timedelta
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, font as tkfont

from browser_bridge import start_bridge
from download_engine import DownloadManager, human_size
from i18n import LANGUAGES, FILTER_KEYS, CATEGORY_KEYS, STATUS_KEYS, tr, localize_error
from release_config import RELEASE_REPOSITORY
from themes import THEMES, THEME_LABELS
from updater import APP_VERSION, find_update, download_verified_update, launch_installer
from update_policy import is_update_check_due

from rtl_support import shape

try:
    from tkinterdnd2 import TkinterDnD
    Root = TkinterDnD.Tk
except ImportError:
    Root = tk.Tk

PALETTE = THEMES['فیروزه‌ای'].copy()
FONT = 'Segoe UI'


def choose_font(root, language):
    available = set(tkfont.families(root))
    candidates = (['Vazirmatn','Vazir','Tahoma','Noto Sans Arabic','Segoe UI'] if language == 'fa'
                  else ['Segoe UI','Arial','Tahoma'])
    return next((name for name in candidates if name in available), 'TkDefaultFont')


def widget_label(parent, text, *, size=10, color='text', bold=False, **kwargs):
    return tk.Label(parent, text=shape(text), bg=parent.cget('bg'), fg=PALETTE.get(color,color),
                    font=(FONT,size,'bold' if bold else 'normal'), **kwargs)


def widget_button(parent, text, command, *, primary=False, **kwargs):
    fg=PALETTE.get('buttonText', '#071D20') if primary else PALETTE['text']
    return tk.Button(parent, text=shape(text), command=command, bg=PALETTE['accent'] if primary else PALETTE['surface2'],
                     fg=fg, activebackground=PALETTE['accentHover'] if primary else PALETTE['line'],
                     activeforeground=fg, bd=0, relief='flat', cursor='hand2', highlightthickness=0,
                     padx=13, pady=9, font=(FONT,10,'bold'), **kwargs)


def widget_entry(parent, **kwargs):
    return tk.Entry(parent, bg=PALETTE['surface2'], fg=PALETTE['text'], insertbackground=PALETTE['text'],
                    highlightbackground=PALETTE['line'], highlightcolor=PALETTE['accent'],
                    highlightthickness=1, bd=0, relief='flat', font=(FONT,11), **kwargs)


class Dialog(tk.Toplevel):
    def __init__(self, app, title, width, height):
        super().__init__(app)
        self.app=app
        self.title(app.t(title))
        self.configure(bg=PALETTE['surface'])
        self.geometry(f'{width}x{height}')
        self.minsize(width,height)
        self.transient(app)
        self.grab_set()
        self.bind('<Escape>',lambda _:self.destroy())
        self.update_idletasks()
        x=app.winfo_rootx()+max(0,(app.winfo_width()-width)//2)
        y=app.winfo_rooty()+max(0,(app.winfo_height()-height)//2)
        self.geometry(f'+{x}+{y}')

    def caption(self, parent, key, pady=(11,5)):
        widget_label(parent,self.app.t(key),color='muted').pack(anchor=self.app.anchor,pady=pady)


class AddDialog(Dialog):
    def __init__(self,app,initial='',scheduled=False):
        super().__init__(app,'new',610,620 if scheduled else 560)
        p=tk.Frame(self,bg=PALETTE['surface'],padx=26,pady=20);p.pack(fill='both',expand=True)
        widget_label(p,app.t('download_new'),size=20,bold=True).pack(anchor=app.anchor)
        self.caption(p,'url_hint',pady=(14,5))
        self.url=widget_entry(p,justify='left');self.url.pack(fill='x',ipady=8);self.url.insert(0,initial)
        self.caption(p,'type')
        self.kind=ttk.Combobox(p,values=[app.t(k) for k in ('auto_detect','direct','media')],state='readonly',font=(FONT,10))
        self.kind.current(0);self.kind.pack(fill='x')
        self.caption(p,'filename_opt')
        self.filename=widget_entry(p,justify='left');self.filename.pack(fill='x',ipady=6)
        self.caption(p,'folder_auto')
        row=tk.Frame(p,bg=PALETTE['surface']);row.pack(fill='x')
        widget_button(row,app.t('browse'),self.browse).pack(side=app.trailing)
        self.directory=widget_entry(row,justify='left');self.directory.pack(side=app.trailing,fill='x',expand=True,ipady=7,padx=8)
        self.caption(p,'speed_cap')
        self.speed=widget_entry(p,justify='center');self.speed.insert(0,'0');self.speed.pack(fill='x',ipady=6)
        self.scheduled=scheduled
        if scheduled:
            self.caption(p,'schedule_at')
            self.schedule_value=widget_entry(p,justify='left')
            self.schedule_value.insert(0,(datetime.now()+timedelta(hours=1)).strftime('%Y-%m-%d %H:%M'))
            self.schedule_value.pack(fill='x',ipady=6)
        row=tk.Frame(p,bg=PALETTE['surface']);row.pack(fill='x',pady=(18,0))
        widget_button(row,app.t('start'),self.submit,primary=True).pack(side=app.leading,padx=(0,8))
        widget_button(row,app.t('cancel'),self.destroy).pack(side=app.leading)
        self.bind('<Return>',lambda _:self.submit());self.url.focus_set()

    def browse(self):
        result=filedialog.askdirectory(parent=self)
        if result:self.directory.delete(0,'end');self.directory.insert(0,result)

    def submit(self):
        try:
            limit=int(self.speed.get().strip() or '0')
            if not 0<=limit<=1000000:raise ValueError(self.app.t('speed_invalid'))
            kind=('auto','direct','media')[self.kind.current()]
            scheduled_at=''
            if self.scheduled:
                scheduled_time=datetime.fromisoformat(self.schedule_value.get().strip())
                if scheduled_time<=datetime.now():raise ValueError(self.app.t('schedule_future'))
                scheduled_at=scheduled_time.isoformat(timespec='seconds')
            job=self.app.manager.add(self.url.get(),filename=self.filename.get(),directory=self.directory.get(),limit_kbps=limit,kind=kind,scheduled_at=scheduled_at)
            self.app.selected=job.id
            self.destroy();self.app.refresh()
        except Exception as exc:
            messagebox.showerror(self.app.t('add_error'),localize_error(exc,self.app.manager.language),parent=self)


class SettingsDialog(Dialog):
    def __init__(self,app):
        super().__init__(app,'settings_title',655,690)
        m=app.manager
        footer=tk.Frame(self,bg=PALETTE['surface'],padx=25,pady=9)
        footer.pack(side='bottom',fill='x')
        scroll_frame=tk.Frame(self,bg=PALETTE['surface'])
        scroll_frame.pack(fill='both',expand=True)
        canvas=tk.Canvas(scroll_frame,bg=PALETTE['surface'],highlightthickness=0)
        scrollbar=ttk.Scrollbar(scroll_frame,orient='vertical',command=canvas.yview)
        scrollbar.pack(side='right',fill='y')
        canvas.pack(side='left',fill='both',expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        outer=tk.Frame(canvas,bg=PALETTE['surface'],padx=25,pady=17)
        window=canvas.create_window((0,0),window=outer,anchor='nw')
        outer.bind('<Configure>',lambda _:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(window,width=e.width))
        self.bind('<MouseWheel>',lambda e:canvas.yview_scroll(-1 if e.delta>0 else 1,'units'))
        widget_button(footer,app.t('save_settings'),self.save,primary=True).pack(side=app.leading)
        widget_label(outer,app.t('settings'),size=20,bold=True).pack(anchor=app.anchor)
        self.caption(outer,'language',pady=(13,4))
        self.language=ttk.Combobox(outer,values=list(LANGUAGES.values()),state='readonly',font=(FONT,10))
        self.language.set(LANGUAGES[m.language]);self.language.pack(fill='x')
        self.caption(outer,'theme')
        self.theme=ttk.Combobox(outer,values=[THEME_LABELS[k][app.manager.language] for k in THEMES],state='readonly',font=(FONT,10))
        self.theme.set(THEME_LABELS[m.theme][app.manager.language]);self.theme.pack(fill='x')
        sample=tk.Canvas(outer,width=240,height=28,bg=PALETTE['surface'],highlightthickness=0)
        sample.pack(fill='x',pady=(7,0));self.sample=sample
        self.theme.bind('<<ComboboxSelected>>',self.preview_palette);self.preview_palette()
        self.caption(outer,'connections')
        self.connections=widget_entry(outer,justify='center');self.connections.insert(0,str(m.connections));self.connections.pack(fill='x',ipady=6)
        self.caption(outer,'parallel')
        self.parallel=widget_entry(outer,justify='center');self.parallel.insert(0,str(m.parallel));self.parallel.pack(fill='x',ipady=6)
        self.caption(outer,'base_dir')
        row=tk.Frame(outer,bg=PALETTE['surface']);row.pack(fill='x')
        widget_button(row,app.t('browse'),self.browse).pack(side=app.trailing)
        self.directory=widget_entry(row,justify='left');self.directory.insert(0,str(m.default_dir))
        self.directory.pack(side=app.trailing,fill='x',expand=True,ipady=6,padx=8)
        self.caption(outer,'proxy')
        self.proxy=widget_entry(outer,justify='left');self.proxy.insert(0,m.proxy);self.proxy.pack(fill='x',ipady=6)
        self.caption(outer,'repo')
        self.repo=widget_entry(outer,justify='left');self.repo.insert(0,m.update_repo or RELEASE_REPOSITORY)
        self.repo.pack(fill='x',ipady=6)
        self.check_updates=tk.BooleanVar(value=m.auto_check_updates)
        self.download_updates=tk.BooleanVar(value=m.auto_download_updates)
        for key,var in [('auto_check',self.check_updates),('auto_download',self.download_updates)]:
            tk.Checkbutton(outer,text=shape(app.t(key)),variable=var, bg=PALETTE['surface'],
                fg=PALETTE['text'],selectcolor=PALETTE['surface2'],activebackground=PALETTE['surface'],
                activeforeground=PALETTE['text'],font=(FONT,10),anchor=app.anchor).pack(fill='x',pady=(10,0))

    def preview_palette(self,event=None):
        colors=THEMES.get(self.chosen_theme(),PALETTE)
        self.sample.delete('all');self.sample.update_idletasks()
        width=max(self.sample.winfo_width(),240);keys=('bg','surface','surface2','line','accent','blue','green','red')
        for i,key in enumerate(keys):
            self.sample.create_rectangle(i*width/len(keys),0,(i+1)*width/len(keys)+1,28,fill=colors[key],outline='')

    def chosen_theme(self):
        return next((k for k,v in THEME_LABELS.items() if v[self.app.manager.language]==self.theme.get()),self.app.manager.theme)

    def browse(self):
        p=filedialog.askdirectory(parent=self)
        if p:self.directory.delete(0,'end');self.directory.insert(0,p)

    def save(self):
        try:
            lang=next(k for k,v in LANGUAGES.items() if v==self.language.get())
            self.app.manager.configure(connections=int(self.connections.get()),parallel=int(self.parallel.get()),
                default_dir=self.directory.get(),proxy=self.proxy.get().strip(),
                theme=self.chosen_theme(),language=lang,update_repo=self.repo.get().strip(),
                auto_check_updates=self.check_updates.get(),auto_download_updates=self.download_updates.get())
            self.destroy();self.app.rebuild()
        except (ValueError,StopIteration) as exc:
            messagebox.showerror(self.app.t('settings'),localize_error(exc,self.app.manager.language),parent=self)


class App(Root):
    def __init__(self):
        super().__init__()
        self.manager=DownloadManager(callback=self._notify)
        self.selected=None;self.filter='all'
        self._dirty=queue.Queue(maxsize=1)
        self._updates=queue.Queue()
        self._update_busy=False
        self._ready_update=None
        self._pending_update=None
        self._checked_this_run=False
        self.bridge=start_bridge(self.manager)
        self.geometry('1320x800');self.minsize(1020,610)
        self.sort_by='added_at';self.sort_reverse=True;self.show_sidebar=True
        self._icon_cache={}
        self.rebuild()
        self.after(180,self._poll)
        self.after(2500,self._automatic_update_check)
        self.after(60*60*1000,self._scheduled_check)
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.bind('<Control-n>',lambda _:AddDialog(self))
        self.bind('<Control-v>',self.clipboard_add)
        self.bind('<Control-f>',lambda _:self.focus_search())
        self.bind('<Delete>',lambda _:self.remove_selected())
        self.bind('<F5>',lambda _:self.refresh())
        try:
            self.drop_target_register('DND_TEXT','DND_FILES')
            self.dnd_bind('<<Drop>>',lambda event:self._on_drop(event.data))
        except (AttributeError,tk.TclError):pass

    def t(self,key,**kwargs):return tr(key,self.manager.language,**kwargs)

    @property
    def rtl(self):return self.manager.language=='fa'
    @property
    def leading(self):return 'right' if self.rtl else 'left'
    @property
    def trailing(self):return 'left' if self.rtl else 'right'
    @property
    def anchor(self):return 'e' if self.rtl else 'w'

    def _notify(self):
        try:self._dirty.put_nowait(1)
        except queue.Full:pass

    def _styles(self):
        style=ttk.Style(self);style.theme_use('clam')
        style.configure('Maher.Treeview',background=PALETTE['surface'],foreground=PALETTE['text'],
                        fieldbackground=PALETTE['surface'],borderwidth=0,rowheight=31,font=(FONT,10))
        style.configure('Maher.Treeview.Heading',background=PALETTE['surface2'],foreground=PALETTE['text'],
                        relief='flat',borderwidth=0,font=(FONT,10,'bold'),padding=(9,10))
        style.map('Maher.Treeview',background=[('selected',PALETTE['surface2'])],foreground=[('selected',PALETTE['accent'])])
        style.map('Maher.Treeview.Heading',background=[('active',PALETTE['line'])])
        style.configure('Library.Treeview',background=PALETTE['surface'],foreground=PALETTE['text'],
                        fieldbackground=PALETTE['surface'],borderwidth=0,rowheight=34,font=(FONT,10))
        style.map('Library.Treeview',background=[('selected',PALETTE['surface2'])],foreground=[('selected',PALETTE['accent'])])
        style.configure('Library.Treeview.Heading',background=PALETTE['surface'],foreground=PALETTE['muted'],borderwidth=0)
        style.configure('Maher.TCombobox',fieldbackground=PALETTE['surface2'],background=PALETTE['surface2'],foreground=PALETTE['text'])

    def rebuild(self):
        global FONT
        FONT=choose_font(self,self.manager.language)
        PALETTE.update(THEMES.get(self.manager.theme,THEMES['فیروزه‌ای']))
        self.title(self.t('app_title')+'  ·  '+APP_VERSION)
        self.configure(bg=PALETTE['bg'])
        old_query=self.search_var.get() if hasattr(self,'search_var') else ''
        for child in self.winfo_children():child.destroy()
        self._styles()
        self._draw_layout()
        self.search_var.set(old_query)
        self.refresh()

    def _motif(self,parent,height=38):
        canvas=tk.Canvas(parent,height=height,bg=PALETTE['surface'],highlightthickness=0)
        canvas.pack(fill='x',pady=(0,10))
        def paint(event):
            canvas.delete('all')
            width=event.width
            count=max(1,int(width//42))
            for i in range(count):
                x=(i+0.5)*width/count;y=height/2;r=10
                canvas.create_polygon(x,y-r,x+r,y,x,y+r,x-r,y,outline=PALETTE['accent'],fill='',width=1.4)
                canvas.create_rectangle(x-7,y-7,x+7,y+7,outline=PALETTE['line'])
                canvas.create_oval(x-2,y-2,x+2,y+2,fill=PALETTE['accent'],outline='')
        canvas.bind('<Configure>',paint)

    def _image(self,name):
        if name in self._icon_cache:return self._icon_cache[name]
        path=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'assets'/'ui'/(name+'.png')
        if not path.exists():return None
        icon=tk.PhotoImage(master=self,file=str(path))
        self._icon_cache[name]=icon
        return icon

    def _menu(self):
        menubar=tk.Menu(self,tearoff=0)
        menus=[('menu_file',[('new',lambda:AddDialog(self)),('schedule',self.schedule_download),
                             ('menu_exit',self.close)]),
               ('menu_downloads',[('resume',self.resume_selected),('pause',self.pause_selected),
                                  ('resume_all',self.manager.resume_all),('pause_all',self.manager.pause_all),
                                  ('remove',self.remove_selected),('open_folder',self.open_directory)]),
               ('menu_view',[('menu_toggle_sidebar',self.toggle_sidebar),('theme_button',self.cycle_theme),
                             ('menu_language',self.toggle_language)]),
               ('menu_tools',[('settings_button',lambda:SettingsDialog(self)),('update_check',self.check_update),
                              ('copy_pair',self.copy_pairing)]),
               ('menu_help',[('menu_about',self.about)])]
        for label,entries in menus:
            menu=tk.Menu(menubar,tearoff=0,bg=PALETTE['surface'],fg=PALETTE['text'],
                         activebackground=PALETTE['accent'],activeforeground=PALETTE.get('buttonText','#071D20'))
            for text_key,func in entries:menu.add_command(label=shape(self.t(text_key)),command=func)
            menubar.add_cascade(label=shape(self.t(label)),menu=menu)
        self.config(menu=menubar)

    def _toolbar_button(self,frame,icon,key,command,*,accent=False):
        background=PALETTE['surface2'] if accent else PALETTE['surface']
        tile=tk.Frame(frame,bg=background,width=88,height=80,cursor='hand2')
        tile.pack(side=self.leading,padx=2,pady=6)
        tile.pack_propagate(False)
        image=self._image(icon)
        pic=tk.Label(tile,image=image,bg=background,cursor='hand2')
        pic.pack(pady=(10,4))
        caption=tk.Label(tile,text=shape(self.t(key)),fg=PALETTE['text'] if accent else PALETTE['muted'],
                 bg=background,font=(FONT,9,'bold'),cursor='hand2')
        caption.pack()
        def click(_):command()
        def color(active):
            bg=PALETTE['surface2'] if active else background
            for w in (tile,pic,caption):w.configure(bg=bg)
            caption.configure(fg=PALETTE['accent'] if active else PALETTE['text'] if accent else PALETTE['muted'])
        for w in (tile,pic,caption):
            w.bind('<Button-1>',click)
            w.bind('<Enter>',lambda _:color(True))
            w.bind('<Leave>',lambda _:color(False))
        return tile

    def _draw_layout(self):
        self._menu()
        # Narrow Persian ornament line; the toolbar remains dominant like classic IDM.
        band=tk.Frame(self,bg=PALETTE['surface'],height=54)
        band.pack(side='top',fill='x')
        band.pack_propagate(False)
        identity=tk.Frame(band,bg=PALETTE['surface'])
        identity.pack(side=self.leading,padx=20)
        icon=self._image('brand')
        tk.Label(identity,image=icon,bg=PALETTE['surface']).pack(side=self.leading,padx=(0,8))
        name=tk.Frame(identity,bg=PALETTE['surface']);name.pack(side=self.leading,pady=7)
        widget_label(name,self.t('brand'),size=13,bold=True).pack(anchor=self.anchor)
        widget_label(name,self.t('tagline'),size=9,color='muted').pack(anchor=self.anchor)
        flag=tk.Frame(band,bg=PALETTE['surface']);flag.pack(side=self.trailing,padx=18)
        widget_button(flag,self.t('toolbar_language'),self.toggle_language).pack(side=self.trailing,padx=3)
        widget_button(flag,self.t('theme_button'),self.cycle_theme).pack(side=self.trailing,padx=3)
        widget_label(flag,'v'+APP_VERSION,size=9,color='muted').pack(side=self.trailing,padx=9)
        line=tk.Canvas(self,height=10,bg=PALETTE['surface2'],highlightthickness=0)
        line.pack(side='top',fill='x')
        def paint(event):
            line.delete('all')
            w=event.width
            line.create_rectangle(0,0,w,10,fill=PALETTE['surface2'],outline='')
            for x in range(0,w,24):
                line.create_polygon(x+6,1,x+11,5,x+6,9,x+1,5,fill='',outline=PALETTE['accent'])
                line.create_line(x+11,5,x+19,5,fill=PALETTE['line'])
        line.bind('<Configure>',paint)
        toolbar=tk.Frame(self,bg=PALETTE['surface'],padx=10,pady=1)
        toolbar.pack(side='top',fill='x')
        operations=[('add','toolbar_add',lambda:AddDialog(self)),('resume','toolbar_resume',self.resume_selected),
                    ('pause','toolbar_pause',self.pause_selected),('allpause','pause_all',self.manager.pause_all),
                    ('remove','toolbar_remove',self.remove_selected),('schedule','toolbar_schedule',self.schedule_download),
                    ('folder','toolbar_folder',self.open_directory),('settings','toolbar_settings',lambda:SettingsDialog(self)),
                    ('update','toolbar_update',self.check_update)]
        for i,(icon,label,command) in enumerate(operations):
            if i in (1,5,7):
                tk.Frame(toolbar,bg=PALETTE['line'],width=1,height=55).pack(side=self.leading,padx=7)
            self._toolbar_button(toolbar,icon,label,command,accent=(i==0))
        # Keep an actionable update control in sync with the verified updater.
        self.update_button=widget_button(toolbar,self.t('update_check'),self.check_update)
        # Shown only if an update is available; the toolbar icon handles manual checks.
        # Layout stays compact and avoids duplicate update actions.
        body=tk.Frame(self,bg=PALETTE['bg'])
        body.pack(fill='both',expand=True)
        self.sidebar=tk.Frame(body,bg=PALETTE['surface'],width=225)
        self.sidebar.pack(side=self.leading,fill='y',padx=(0,1));self.sidebar.pack_propagate(False)
        widget_label(self.sidebar,self.t('library'),size=10,color='muted',bold=True).pack(anchor=self.anchor,padx=14,pady=(19,12))
        categories=tk.Frame(self.sidebar,bg=PALETTE['surface'])
        categories.pack(fill='both',expand=True,padx=7)
        self.sidebar_tree=ttk.Treeview(categories,show='tree',selectmode='browse',style='Library.Treeview',height=15)
        self.sidebar_tree.pack(fill='both',expand=True)
        self.library_nodes={}
        self.library_nodes['all']=self.sidebar_tree.insert('','end',text=shape(self.t('all')),image=self._image('cat-all'),open=True)
        status_root=self.sidebar_tree.insert('','end',text=shape(self.t('sidebar_statuses')),image=self._image('cat-folder'),open=True)
        for key in ('active','queued','done','paused','failed'):
            self.library_nodes[key]=self.sidebar_tree.insert(status_root,'end',text=shape(self.t(key)),image=self._image('cat-'+key))
        kinds_root=self.sidebar_tree.insert('','end',text=shape(self.t('sidebar_categories')),image=self._image('cat-folder'),open=True)
        for key in ('video','music','images','documents','archives','other'):
            self.library_nodes[key]=self.sidebar_tree.insert(kinds_root,'end',text=shape(self.t(key)),image=self._image('cat-'+key))
        self.sidebar_tree.bind('<<TreeviewSelect>>',self._tree_filter)
        self._selecting_filter=False
        divider=tk.Frame(self.sidebar,bg=PALETTE['line'],height=1);divider.pack(fill='x',padx=12)
        widget_label(self.sidebar,self.t('sidebar_tip'),size=9,color='muted',wraplength=187,justify='right' if self.rtl else 'left').pack(anchor=self.anchor,padx=14,pady=(12,16))
        if not self.show_sidebar:self.sidebar.pack_forget()
        panel=tk.Frame(body,bg=PALETTE['bg']);panel.pack(side=self.trailing,fill='both',expand=True)
        bar=tk.Frame(panel,bg=PALETTE['bg'],padx=18,pady=11)
        bar.pack(fill='x')
        self.section_label=widget_label(bar,self.t('all'),size=14,bold=True)
        self.section_label.pack(side=self.leading)
        self.count_label=widget_label(bar,self.t('items',count=0),size=9,color='muted')
        self.count_label.pack(side=self.leading,padx=11)
        self.search_var=tk.StringVar()
        search_box=tk.Frame(bar,bg=PALETTE['surface2'],highlightthickness=1,highlightbackground=PALETTE['line'])
        search_box.pack(side=self.trailing,fill='x')
        widget_label(search_box,'⌕',size=15,color='accent').pack(side=self.leading,padx=(9,3))
        self.search_entry=widget_entry(search_box,textvariable=self.search_var,width=29,
                                       justify='right' if self.rtl else 'left')
        self.search_entry.pack(side=self.leading,ipady=6,padx=5)
        self.search_var.trace_add('write',lambda *_:self.refresh())
        tablebox=tk.Frame(panel,bg=PALETTE['surface'],highlightbackground=PALETTE['line'],highlightthickness=1)
        tablebox.pack(fill='both',expand=True,padx=15,pady=(0,7))
        # Compact 7-column IDM-style file list with sort support and alternating rows.
        cols=('description','added','state','speed','progress','size','name') if self.rtl else ('name','size','progress','speed','state','added','description')
        self.tree=ttk.Treeview(tablebox,columns=cols,show='headings',selectmode='browse',style='Maher.Treeview')
        sizes={'name':310,'size':96,'progress':125,'speed':98,'state':123,'added':116,'description':170}
        for col in cols:
            self.tree.heading(col,text=shape(self.t(col)),command=lambda k=col:self.sort_downloads(k),anchor=self.anchor if col=='name' else 'center')
            self.tree.column(col,width=sizes[col],minwidth=78,stretch=col in ('name','description'),anchor=self.anchor if col in ('name','description') else 'center')
        scrolly=ttk.Scrollbar(tablebox,orient='vertical',command=self.tree.yview)
        scrollx=ttk.Scrollbar(tablebox,orient='horizontal',command=self.tree.xview)
        self.tree.configure(yscrollcommand=scrolly.set,xscrollcommand=scrollx.set)
        scrolly.pack(side='right',fill='y');scrollx.pack(side='bottom',fill='x')
        self.tree.pack(side='left',fill='both',expand=True)
        self.tree.tag_configure('even',background=PALETTE['surface'])
        self.tree.tag_configure('odd',background=PALETTE['surface2'])
        self.tree.bind('<<TreeviewSelect>>',self.on_select)
        self.tree.bind('<Double-1>',lambda _:self.open_file())
        self.tree.bind('<Button-3>',self.right_click)
        preview=tk.Frame(panel,bg=PALETTE['surface'],padx=13,pady=8)
        preview.pack(fill='x',padx=15,pady=(0,6))
        self.details=widget_label(preview,self.t('select_hint'),size=9,color='muted')
        self.details.pack(side=self.leading,fill='x',expand=True)
        widget_button(preview,self.t('open_folder'),self.open_directory).pack(side=self.trailing,padx=3)
        widget_button(preview,self.t('open_file'),self.open_file).pack(side=self.trailing,padx=3)
        status=tk.Frame(self,bg=PALETTE['surface2'],padx=15,pady=6)
        status.pack(side='bottom',fill='x')
        self.status_summary=widget_label(status,'',size=9,color='muted')
        self.status_summary.pack(side=self.leading)
        self.browser_status=widget_label(status,self.t('browser_on' if self.bridge else 'browser_off'),size=9,color='muted')
        self.browser_status.pack(side=self.trailing,padx=8)
        widget_button(status,self.t('copy_pair'),self.copy_pairing).pack(side=self.trailing,padx=4)
        self.update_status=widget_label(status,'',size=9,color='accent')
        self.update_status.pack(side=self.trailing,padx=6)
        if self._pending_update:
            self.update_status.configure(text=shape(self.t('update_available_status',version=self._pending_update['version'])))
            self.update_button.configure(text=shape(self.t('update_download_btn')),command=self.download_pending_update)
            self.update_button.pack(side=self.trailing,padx=6,pady=19)
        if self._ready_update:
            self.update_status.configure(text=shape(self.t('update_ready',version=self._ready_update[0]['version'])))
            self.update_button.configure(text=shape(self.t('update_ready_btn')),command=self.install_ready_update)
            self.update_button.pack(side=self.trailing,padx=6,pady=19)

    def _tree_filter(self,event=None):
        if self._selecting_filter:return
        ids=self.sidebar_tree.selection()
        if not ids:return
        for key,widget_id in self.library_nodes.items():
            if ids[0]==widget_id:
                self.filter=key
                self.refresh()
                break

    def toggle_sidebar(self):
        self.show_sidebar=not self.show_sidebar
        self.rebuild()

    def toggle_language(self):
        self.manager.configure(language='en' if self.rtl else 'fa')
        self.rebuild()

    def focus_search(self):
        self.search_entry.focus_set()
        self.search_entry.selection_range(0,'end')

    def schedule_download(self):
        AddDialog(self,scheduled=True)

    def about(self):
        messagebox.showinfo(self.t('menu_about'),self.t('about_text',version=APP_VERSION),parent=self)

    def sort_downloads(self,key):
        alias={'added':'added_at','name':'filename','size':'total','progress':'downloaded','state':'status','speed':'speed','description':'url'}
        field=alias.get(key,'added_at')
        if self.sort_by==field:self.sort_reverse=not self.sort_reverse
        else:self.sort_by=field;self.sort_reverse=field in ('added_at','total','downloaded','speed')
        self.refresh()

    def choose_filter(self,key):
        self.filter=key
        if key in self.library_nodes:
            self._selecting_filter=True
            self.sidebar_tree.selection_set(self.library_nodes[key])
            self._selecting_filter=False
        self.refresh()

    def cycle_theme(self):
        themes=list(THEMES)
        i=themes.index(self.manager.theme) if self.manager.theme in themes else -1
        self.manager.configure(theme=themes[(i+1)%len(themes)])
        self.rebuild()

    def _matches(self,job):
        status={'active':'running','queued':'queued','done':'done','paused':'paused','failed':'error'}
        if self.filter in status and job['status']!=status[self.filter]:return False
        if self.filter in CATEGORY_KEYS.values() and CATEGORY_KEYS.get(job['category'])!=self.filter:return False
        q=self.search_var.get().lower().strip()
        return not q or q in job['filename'].lower() or q in job['url'].lower()

    def refresh(self):
        if not hasattr(self,'tree') or not self.tree.winfo_exists():return
        jobs=self.manager.list_jobs()
        visible=[j for j in jobs if self._matches(j)]
        def sort_value(job):
            value=job.get(self.sort_by,'')
            return value.lower() if isinstance(value,str) else (value if value is not None else -1)
        visible.sort(key=sort_value,reverse=self.sort_reverse)
        existing=set(self.tree.get_children());ids={j['id'] for j in visible}
        for job_id in existing-ids:self.tree.delete(job_id)
        for index,j in enumerate(visible):
            total=j['total'];pct=min(100,round(100*j['downloaded']/total)) if total else (100 if j['status']=='done' else 0)
            progress=('━'*round(pct/10)+'┄'*(10-round(pct/10))+f' {pct}%') if total or j['status']=='done' else '—'
            host=urlsplit(j['url']).hostname or ''
            date=(j.get('added_at') or '')[:16].replace('T',' ')
            status=shape(self.t(STATUS_KEYS.get(j['status'],'status_error')))
            row={'state':status,'speed':human_size(j['speed'])+'/s' if j['status']=='running' else '—',
                 'size':human_size(total or j['downloaded']), 'progress':progress,
                 'name':shape(j['filename']), 'added':date,'description':host}
            values=[row[col] for col in self.tree['columns']]
            if j['id'] not in existing:self.tree.insert('','end',iid=j['id'],values=values,tags=('even' if index%2==0 else 'odd',))
            else:self.tree.item(j['id'],values=values,tags=('even' if index%2==0 else 'odd',))
            self.tree.move(j['id'],'',index)
        if self.selected in ids:self.tree.selection_set(self.selected)
        counts={'all':len(jobs)}
        for key in ('active','queued','done','paused','failed'):
            target={'active':'running','failed':'error'}.get(key,key)
            counts[key]=sum(j['status']==target for j in jobs)
        for key in ('video','music','images','documents','archives','other'):
            counts[key]=sum(CATEGORY_KEYS.get(j['category'])==key for j in jobs)
        for key,node in self.library_nodes.items():
            label=f'{self.t(key)}   {counts[key]}'
            self.sidebar_tree.item(node,text=shape(label))
        wanted=self.library_nodes.get(self.filter)
        if wanted and self.sidebar_tree.selection()!= (wanted,):
            self._selecting_filter=True
            self.sidebar_tree.selection_set(wanted)
            self._selecting_filter=False
        self.section_label.configure(text=shape(self.t(self.filter)))
        self.count_label.configure(text=shape(self.t('items',count=len(visible))))
        active=counts['active'];speed=sum(j['speed'] for j in jobs if j['status']=='running')
        self.status_summary.configure(text=shape(self.t('status_summary',total=len(jobs),active=active,done=counts['done'],speed=human_size(speed))))
        self._update_details()

    def on_select(self,event=None):
        selected=self.tree.selection()
        if selected:self.selected=selected[0]
        self._update_details()

    def _update_details(self):
        j=self.manager.find(self.selected) if self.selected else None
        if j:
            text=self.t('status_detail',name=j.filename,done=human_size(j.downloaded),total=human_size(j.total))
            if j.error:text+='  •  '+j.error[:80]
            self.details.configure(text=shape(text))
        else:self.details.configure(text=shape(self.t('select_hint')))

    def resume_selected(self):
        if self.selected:self.manager.resume(self.selected);self.refresh()

    def pause_selected(self):
        if self.selected:self.manager.pause(self.selected);self.refresh()

    def remove_selected(self):
        if not self.selected:return
        j=self.manager.find(self.selected)
        if not j:return
        if j._worker:
            messagebox.showinfo(self.t('active_download'),self.t('pause_to_delete'),parent=self);return
        if not messagebox.askyesno(self.t('remove_title'),self.t('remove_confirm',name=j.filename),parent=self):return
        try:self.manager.remove(j.id,delete_partial=True);self.selected=None;self.refresh()
        except ValueError as exc:messagebox.showerror(self.t('error'),localize_error(exc,self.manager.language),parent=self)

    def open_directory(self):
        j=self.manager.find(self.selected) if self.selected else None
        if not j:return
        path=Path(j.directory)
        if path.exists():self._open_path(path)
        else:messagebox.showwarning(self.t('missing_folder'),str(path),parent=self)

    def open_file(self):
        j=self.manager.find(self.selected) if self.selected else None
        if not j:return
        self._open_path(j.dest if j.status=='done' and j.dest.exists() else Path(j.directory))

    def _open_path(self,path):
        try:
            if os.name=='nt':os.startfile(str(path))
            elif sys.platform=='darwin':subprocess.Popen(['open',str(path)])
            else:subprocess.Popen(['xdg-open',str(path)])
        except OSError as exc:messagebox.showerror(self.t('open_error'),str(exc),parent=self)

    def right_click(self,event):
        row=self.tree.identify_row(event.y)
        if not row:return
        self.tree.selection_set(row);self.selected=row
        menu=tk.Menu(self,tearoff=0,bg=PALETTE['surface2'],fg=PALETTE['text'],
                     activebackground=PALETTE['accent'],activeforeground=PALETTE.get('buttonText','#081A1D'))
        for key,action in [('menu_resume',self.resume_selected),('menu_pause',self.pause_selected),
                           ('menu_folder',self.open_directory),('menu_copy_url',self.copy_url),('menu_open_url',self.open_url),('menu_remove',self.remove_selected)]:
            menu.add_command(label=shape(self.t(key)),command=action)
        try:menu.tk_popup(event.x_root,event.y_root)
        finally:menu.grab_release()

    def copy_url(self):
        job=self.manager.find(self.selected) if self.selected else None
        if job:self.clipboard_clear();self.clipboard_append(job.url)

    def open_url(self):
        job=self.manager.find(self.selected) if self.selected else None
        if job and urlsplit(job.url).scheme in ('http','https'):webbrowser.open(job.url)

    def _on_drop(self,data):
        s=data.strip().strip('{}')
        if s.startswith(('https://','http://','ftp://')):AddDialog(self,s)

    def clipboard_add(self,event=None):
        if isinstance(self.focus_get(),(tk.Entry,ttk.Entry)):return
        try:s=self.clipboard_get().strip()
        except tk.TclError:return
        if s.startswith(('https://','http://','ftp://')):AddDialog(self,s)

    def copy_pairing(self):
        if self.bridge is None:
            messagebox.showerror(self.t('pair_title'),self.t('pair_port_busy'),parent=self)
            return
        self.clipboard_clear()
        self.clipboard_append(self.manager.pairing_token)
        self.update_idletasks()
        messagebox.showinfo(self.t('pair_title'),self.t('pair_copied'),parent=self)

    def _scheduled_check(self):
        self._automatic_update_check()
        if self.winfo_exists():self.after(60*60*1000,self._scheduled_check)

    def _automatic_update_check(self):
        if not self.manager.auto_check_updates or self._update_busy or self._ready_update:return
        if is_update_check_due(self.manager.last_update_check):
            self.check_update(automatic=True)

    def check_update(self,automatic=False):
        if self._update_busy:return
        repo=self.manager.update_repo or RELEASE_REPOSITORY
        if not repo:
            if not automatic:messagebox.showinfo(self.t('update_title'),self.t('update_repo_missing'),parent=self)
            return
        if self._ready_update and not automatic:
            self.install_ready_update();return
        if self._pending_update and not automatic:
            self.download_pending_update();return
        self._update_busy=True
        self.update_status.configure(text=shape(self.t('update_checking')))
        def task():
            try:
                result=find_update(repo)
                self._updates.put(('found',result,automatic))
            except Exception as exc:self._updates.put(('error',str(exc),automatic))
        threading.Thread(target=task,daemon=True,name='maher-update-check').start()

    def download_pending_update(self):
        if not self._pending_update:return
        self._update_busy=True
        self._start_update_download(self._pending_update,False)
        self._pending_update=None

    def _start_update_download(self,update,automatic):
        self.update_status.configure(text=shape(self.t('update_downloading')))
        def task():
            try:self._updates.put(('ready',(update,download_verified_update(update)),automatic))
            except Exception as exc:self._updates.put(('error',str(exc),automatic))
        threading.Thread(target=task,daemon=True,name='maher-update-download').start()

    def install_ready_update(self):
        if not self._ready_update:return self.check_update()
        update,path=self._ready_update
        if os.name!='nt':
            messagebox.showwarning(self.t('update_title'),self.t('updating_not_windows'),parent=self);return
        if not messagebox.askyesno(self.t('update_title'),self.t('update_verified'),parent=self):return
        try:launch_installer(path)
        except Exception as exc:
            messagebox.showerror(self.t('update_install_error'),localize_error(exc,self.manager.language),parent=self);return
        self.close()

    def _poll(self):
        if not self.winfo_exists():return
        try:self._dirty.get_nowait();self.refresh()
        except queue.Empty:pass
        for _ in range(8):
            try:event,data,automatic=self._updates.get_nowait()
            except queue.Empty:break
            if event=='error':
                self._update_busy=False
                if automatic:self.manager.configure(last_update_check=datetime.now(timezone.utc).isoformat())
                self.update_status.configure(text='')
                if not automatic:messagebox.showerror(self.t('update_failed'),localize_error(Exception(data),self.manager.language),parent=self)
            elif event=='found':
                self.manager.configure(last_update_check=datetime.now(timezone.utc).isoformat())
                if not data:
                    self._update_busy=False
                    self.update_status.configure(text=shape(self.t('update_latest')))
                    self.update_button.pack_forget()
                    if not automatic:messagebox.showinfo(self.t('update_title'),self.t('update_latest'),parent=self)
                elif automatic and self.manager.auto_download_updates:
                    self._start_update_download(data,True)
                elif not automatic and messagebox.askyesno(self.t('update_title'),self.t('update_available',version=data['version']),parent=self):
                    self._start_update_download(data,False)
                else:
                    self._update_busy=False
                    self.update_status.configure(text=shape(self.t('update_available_status',version=data['version'])))
                    self._pending_update=data
                    self.update_button.configure(text=shape(self.t('update_download_btn')),command=self.download_pending_update)
                    self.update_button.pack(side=self.trailing,padx=6,pady=19)
            elif event=='ready':
                self._update_busy=False
                self._ready_update=data
                self._pending_update=None
                self.update_status.configure(text=shape(self.t('update_ready',version=data[0]['version'])))
                self.update_button.configure(text=shape(self.t('update_ready_btn')),command=self.install_ready_update)
                self.update_button.pack(side=self.trailing,padx=6,pady=19)
                if not automatic:self.install_ready_update()
        self.after(450,self._poll)

    def close(self):
        self.manager.shutdown()
        if self.bridge:
            try:self.bridge.shutdown();self.bridge.server_close()
            except Exception:pass
        self.destroy()


def main():
    app=App()
    try:
        base=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))
        icon=base/'assets'/'maher.ico'
        if icon.exists():app.iconbitmap(str(icon))
    except tk.TclError:pass
    app.mainloop()


if __name__=='__main__':main()
