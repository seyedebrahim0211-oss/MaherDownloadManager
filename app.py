"""Maher Download Manager – Persian Windows desktop interface."""
from __future__ import annotations
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from datetime import datetime
from urllib.parse import urlsplit

from download_engine import DownloadManager, STATUS_FA, APP_DIR, human_size
from browser_bridge import start_bridge
from themes import THEMES
from updater import APP_VERSION, find_update, download_verified_update, launch_installer
from release_config import RELEASE_REPOSITORY

C=THEMES['فیروزه‌ای'].copy()
FONT='Segoe UI'

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    def fa(text):
        """Visual RTL shaping for Tk widgets; keep URL and file paths in logical order."""
        value = str(text)
        return get_display(arabic_reshaper.reshape(value), base_dir='R') if any('\u0600' <= ch <= '\u06ff' for ch in value) else value
except ImportError:
    def fa(text): return str(text)



def button(parent, title, command, primary=False, width=None, **kwargs):
    bg=C['accent'] if primary else C['surface2']
    fg='#051721' if primary else C['text']
    b=tk.Button(parent,text=fa(title),command=command,bd=0,relief='flat',
        font=(FONT,10,'bold'),bg=bg,fg=fg,activebackground=C['accentHover'] if primary else C['line'],
        activeforeground=fg,cursor='hand2',padx=16,pady=10,highlightthickness=0,
        width=width,**kwargs)
    return b


def label(parent,text='',size=10,color='text',bold=False,**kwargs):
    return tk.Label(parent,text=fa(text),font=(FONT,size,'bold' if bold else 'normal'),
        fg=C.get(color,color),bg=parent.cget('bg'),**kwargs)


def entry(parent,**kwargs):
    return tk.Entry(parent,bd=0,relief='flat',bg=C['surface2'],fg=C['text'],
        insertbackground=C['text'],font=(FONT,11),highlightthickness=1,
        highlightbackground=C['line'],highlightcolor=C['accent'],**kwargs)


class Dialog(tk.Toplevel):
    def __init__(self,root,title,w=565,h=435):
        super().__init__(root)
        self.title(title);self.configure(bg=C['surface'])
        self.geometry(f'{w}x{h}');self.resizable(False,False)
        self.transient(root);self.grab_set()
        self.center(root)
        self.bind('<Escape>',lambda _:self.destroy())

    def center(self,root):
        self.update_idletasks()
        x=root.winfo_rootx()+(root.winfo_width()-self.winfo_width())//2
        y=root.winfo_rooty()+(root.winfo_height()-self.winfo_height())//2
        self.geometry(f'+{max(0,x)}+{max(0,y)}')


class AddDialog(Dialog):
    def __init__(self,root,initial=''):
        super().__init__(root,'افزودن دانلود جدید',600,530)
        self.app=root
        inner=tk.Frame(self,bg=C['surface'],padx=26,pady=23);inner.pack(fill='both',expand=True)
        label(inner,'دانلود جدید',size=19,bold=True).pack(anchor='e')
        label(inner,'پیوند فایل، ویدیوی YouTube یا جریان HLS',color='muted').pack(anchor='e',pady=(16,5))
        self.url=entry(inner,justify='left');self.url.pack(fill='x',ipady=9)
        self.url.insert(0,initial);self.url.focus_set()
        label(inner,'نوع دانلود',color='muted').pack(anchor='e',pady=(12,5))
        self.kind=ttk.Combobox(inner,values=['تشخیص خودکار','لینک مستقیم','ویدیو / HLS'],state='readonly',font=(FONT,10))
        self.kind.current(0);self.kind.pack(fill='x',ipady=4)
        label(inner,'نام فایل (اختیاری)',color='muted').pack(anchor='e',pady=(12,5))
        self.filename=entry(inner,justify='right');self.filename.pack(fill='x',ipady=7)
        label(inner,'مسیر ذخیره (خالی = دسته‌بندی خودکار)',color='muted').pack(anchor='e',pady=(12,5))
        path_row=tk.Frame(inner,bg=C['surface']);path_row.pack(fill='x')
        button(path_row,'انتخاب پوشه',self.browse).pack(side='left')
        self.directory=entry(path_row,justify='left');self.directory.pack(side='left',fill='x',expand=True,ipady=8,padx=(0,8))
        lim=tk.Frame(inner,bg=C['surface']);lim.pack(fill='x',pady=15)
        label(lim,'کیلوبایت بر ثانیه (۰ = نامحدود)',color='muted').pack(side='right')
        self.speed=entry(lim,justify='center',width=8);self.speed.insert(0,'0');self.speed.pack(side='right',padx=12,ipady=6)
        actions=tk.Frame(inner,bg=C['surface']);actions.pack(fill='x',pady=(0,2))
        button(actions,'شروع دانلود',self.submit,True).pack(side='right')
        button(actions,'انصراف',self.destroy).pack(side='right',padx=8)
        self.bind('<Return>',lambda _:self.submit())

    def browse(self):
        directory=filedialog.askdirectory(parent=self,title='انتخاب مسیر ذخیره')
        if directory:self.directory.delete(0,'end');self.directory.insert(0,directory)

    def submit(self):
        try:
            lim=int(self.speed.get().strip() or 0)
            if not 0<=lim<=1000000:raise ValueError('محدودیت سرعت باید بین صفر و یک میلیون باشد.')
            job=self.app.manager.add(self.url.get(),filename=self.filename.get(),directory=self.directory.get(),limit_kbps=lim,kind=['auto','direct','media'][self.kind.current()])
            self.app.selected=job.id
            self.destroy();self.app.refresh()
        except Exception as e:messagebox.showerror('خطا در افزودن دانلود',str(e),parent=self)


class SettingsDialog(Dialog):
    def __init__(self,root):
        super().__init__(root,'تنظیمات دانلود',580,615)
        self.app=root;m=root.manager
        inner=tk.Frame(self,bg=C['surface'],padx=26,pady=24);inner.pack(fill='both',expand=True)
        label(inner,'تنظیمات',size=20,bold=True).pack(anchor='e')
        label(inner,'تعداد اتصال برای هر فایل (۱ تا ۱۶)',color='muted').pack(anchor='e',pady=(18,6))
        self.connections=entry(inner,justify='center');self.connections.insert(0,str(m.connections));self.connections.pack(fill='x',ipady=7)
        label(inner,'حداکثر دانلود هم‌زمان (۱ تا ۶)',color='muted').pack(anchor='e',pady=(12,6))
        self.parallel=entry(inner,justify='center');self.parallel.insert(0,str(m.parallel));self.parallel.pack(fill='x',ipady=7)
        label(inner,'پوشه پایه دانلودها',color='muted').pack(anchor='e',pady=(12,6))
        line=tk.Frame(inner,bg=C['surface']);line.pack(fill='x')
        button(line,'انتخاب',self.browse).pack(side='left')
        self.directory=entry(line,justify='left');self.directory.insert(0,str(m.default_dir))
        self.directory.pack(side='left',fill='x',expand=True,ipady=8,padx=(0,8))
        label(inner,'پروکسی HTTP(S) بدون اطلاعات ورود (اختیاری)',color='muted').pack(anchor='e',pady=(12,6))
        self.proxy=entry(inner,justify='left');self.proxy.insert(0,m.proxy);self.proxy.pack(fill='x',ipady=7)
        label(inner,'پوسته ایرانی',color='muted').pack(anchor='e',pady=(11,5))
        self.theme=ttk.Combobox(inner,values=list(THEMES),state='readonly',font=(FONT,10))
        self.theme.set(m.theme);self.theme.pack(fill='x',ipady=4)
        label(inner,'مخزن GitHub برای بروزرسانی (owner/repo)',color='muted').pack(anchor='e',pady=(11,5))
        self.repo=entry(inner,justify='left');self.repo.insert(0,m.update_repo or RELEASE_REPOSITORY);self.repo.pack(fill='x',ipady=7)
        button(inner,'ذخیره تنظیمات',self.save,True).pack(side='right',pady=(15,0))

    def browse(self):
        folder=filedialog.askdirectory(parent=self)
        if folder:self.directory.delete(0,'end');self.directory.insert(0,folder)

    def save(self):
        try:
            self.app.manager.configure(connections=int(self.connections.get()),parallel=int(self.parallel.get()),
                default_dir=self.directory.get(),proxy=self.proxy.get().strip(),
                theme=self.theme.get(),update_repo=self.repo.get().strip())
            self.destroy();self.app.apply_theme(self.app.manager.theme)
        except Exception as e:messagebox.showerror('تنظیمات',str(e),parent=self)


try:
    from tkinterdnd2 import TkinterDnD
    Root = TkinterDnD.Tk
except ImportError:
    Root = tk.Tk


class App(Root):
    FILTERS=['همه دانلودها','در حال دانلود','در صف','تکمیل‌شده','متوقف‌شده','خطادار','ویدیو','موسیقی','تصاویر','اسناد','فشرده','سایر']
    def __init__(self):
        super().__init__()
        self.title('ماهر دانلود منیجر | Maher Download Manager')
        self.geometry('1160x750');self.minsize(880,600)
        self.selected=None;self.filter='همه دانلودها';self._dirty=queue.Queue(maxsize=1)
        self._updates=queue.Queue(maxsize=2)
        self.manager=DownloadManager(callback=self._notify)
        C.update(THEMES.get(self.manager.theme,THEMES['فیروزه‌ای']))
        self.configure(bg=C['bg'])
        self.bridge=start_bridge(self.manager)
        self._build_styles();self._build_ui();self._bind_events()
        self.after(150,self._poll);self.protocol('WM_DELETE_WINDOW',self.close)
        self.refresh()
        if self.manager.update_repo or RELEASE_REPOSITORY:self.after(2200,lambda:self.check_update(silent=True))

    def _notify(self):
        try:self._dirty.put_nowait(1)
        except queue.Full:pass

    def _build_styles(self):
        style=ttk.Style(self);style.theme_use('clam')
        style.configure('Maher.Treeview',background=C['surface'],foreground=C['text'],
            fieldbackground=C['surface'],borderwidth=0,rowheight=43,font=(FONT,10))
        style.map('Maher.Treeview',background=[('selected',C['surface2'])],foreground=[('selected',C['accent'])])
        style.configure('Maher.Treeview.Heading',background=C['surface2'],foreground=C['muted'],
            borderwidth=0,relief='flat',font=(FONT,10,'bold'),padding=(10,12))
        style.map('Maher.Treeview.Heading',background=[('active',C['line'])])
        style.configure('Maher.Vertical.TScrollbar',background=C['surface2'],troughcolor=C['surface'])

    def _build_ui(self):
        self.sidebar=tk.Frame(self,bg=C['surface'],width=222)
        self.sidebar.pack(side='right',fill='y');self.sidebar.pack_propagate(False)
        brand=tk.Frame(self.sidebar,bg=C['surface'],padx=16,pady=26);brand.pack(fill='x')
        tk.Label(brand,text='◉',fg=C['accent'],bg=C['surface'],font=(FONT,27,'bold')).pack(side='right',padx=(0,10))
        btxt=tk.Frame(brand,bg=C['surface']);btxt.pack(side='right')
        label(btxt,'ماهر دانلود',15,bold=True).pack(anchor='e')
        label(btxt,'DOWNLOAD MANAGER',8,'muted').pack(anchor='e')
        # Eight-pointed tilework motif: vector-only ornament, no embedded fonts.
        motif=tk.Canvas(self.sidebar,width=190,height=32,bg=C['surface'],highlightthickness=0)
        motif.pack(pady=(0,9))
        for x in (24,72,120,168):
            r=12
            motif.create_polygon(x-r,16,x,16-r,x+r,16,x,16+r,
                outline=C['accent'],fill='',width=1.6)
            motif.create_rectangle(x-8,8,x+8,24,outline=C['line'],width=1)
            motif.create_oval(x-2,14,x+2,18,fill=C['accent'],outline='')
        tk.Frame(self.sidebar,bg=C['line'],height=1).pack(fill='x',padx=15)
        label(self.sidebar,'کتابخانه دانلود',10,'muted',True).pack(anchor='e',padx=22,pady=(22,9))
        self.filter_buttons={}
        emoji={'همه دانلودها':'▦','در حال دانلود':'↓','در صف':'⋯','تکمیل‌شده':'✓','متوقف‌شده':'Ⅱ','خطادار':'!','ویدیو':'▣','موسیقی':'♫','تصاویر':'▧','اسناد':'▤','فشرده':'▱','سایر':'◇'}
        for item in self.FILTERS:
            b=tk.Button(self.sidebar,text=fa(f'{item}    {emoji[item]}'),anchor='e',bd=0,relief='flat',
                padx=20,pady=10,font=(FONT,10),bg=C['surface'],fg=C['muted'],
                activebackground=C['surface2'],activeforeground=C['text'],cursor='hand2',
                command=lambda key=item:self.choose_filter(key))
            b.pack(fill='x',padx=10,pady=1)
            self.filter_buttons[item]=b
        tk.Frame(self.sidebar,bg=C['line'],height=1).pack(fill='x',padx=15,pady=(16,10))
        label(self.sidebar,f'نسخه {APP_VERSION} • پارسی',9,'muted').pack(anchor='e',padx=23)

        self.main=tk.Frame(self,bg=C['bg']);self.main.pack(side='left',fill='both',expand=True)
        header=tk.Frame(self.main,bg=C['bg'],padx=28,pady=21);header.pack(fill='x')
        button(header,'+ افزودن لینک',lambda:AddDialog(self),True).pack(side='right')
        button(header,'⚙ تنظیمات',lambda:SettingsDialog(self)).pack(side='right',padx=(0,9))
        button(header,'◈ پوسته',self.cycle_theme).pack(side='right',padx=(0,9))
        titleblock=tk.Frame(header,bg=C['bg']);titleblock.pack(side='left')
        label(titleblock,'مدیریت دانلودها',23,bold=True).pack(anchor='w')
        label(titleblock,'دانلود سریع، منظم و قابل ادامه',10,'muted').pack(anchor='w',pady=(2,0))

        stats=tk.Frame(self.main,bg=C['bg'],padx=28);stats.pack(fill='x')
        self.cards={}
        for i,(key,title,unit) in enumerate([('total','کل فایل‌ها','فایل'),('running','فعال','دانلود'),('done','تکمیل‌شده','فایل'),('speed','سرعت کل','در ثانیه')]):
            f=tk.Frame(stats,bg=C['surface'],highlightbackground=C['line'],highlightthickness=1)
            f.pack(side='right',fill='both',expand=True,padx=(5 if i else 0,5 if i!=3 else 0),ipady=11)
            label(f,title,10,'muted').pack(anchor='e',padx=17,pady=(4,4))
            count=label(f,'۰',22,bold=True);count.pack(anchor='e',padx=17)
            label(f,unit,9,'muted').pack(anchor='e',padx=17,pady=(0,3))
            self.cards[key]=count

        toolbox=tk.Frame(self.main,bg=C['bg'],padx=28,pady=21);toolbox.pack(fill='x')
        self.search_text=tk.StringVar()
        self.search=entry(toolbox,textvariable=self.search_text,justify='right',width=28)
        self.search.pack(side='right',fill='x',expand=True,ipady=8)
        label(toolbox,'جستجو',10,'muted').pack(side='right',padx=(12,8))
        button(toolbox,'▶ ادامه',self.resume_selected).pack(side='left',padx=(0,5))
        button(toolbox,'Ⅱ توقف',self.pause_selected).pack(side='left',padx=5)
        button(toolbox,'▢ حذف',self.remove_selected).pack(side='left',padx=5)

        bottom=tk.Frame(self.main,bg=C['bg'],padx=28,pady=3);bottom.pack(fill='x',side='bottom')
        self.connection=label(bottom,fa('رابط مرورگر: '+('فعال ✓' if self.bridge else 'درگاه اشغال است')),9,'muted')
        self.connection.pack(side='right')
        button(bottom,'کپی کد اتصال مرورگر',self.copy_pairing).pack(side='right',padx=9)
        button(bottom,'بررسی نسخه جدید',self.check_update).pack(side='left',padx=9)
        button(bottom,'توقف همه',self.manager.pause_all).pack(side='left',padx=(0,4))
        button(bottom,'ادامه همه',self.manager.resume_all).pack(side='left',padx=4)

        details=tk.Frame(self.main,bg=C['surface'],padx=18,pady=11)
        details.pack(side='bottom',fill='x',padx=28,pady=(0,13))
        self.details=label(details,'برای مشاهده جزئیات، یک دانلود را انتخاب کنید.',10,'muted')
        self.details.pack(side='right',fill='x',expand=True,anchor='e')
        button(details,'پوشه فایل',self.open_directory).pack(side='left',padx=3)
        button(details,'باز کردن',self.open_file).pack(side='left',padx=3)

        frame=tk.Frame(self.main,bg=C['surface'],highlightbackground=C['line'],highlightthickness=1)
        frame.pack(fill='both',expand=True,padx=28,pady=(0,12))
        upper=tk.Frame(frame,bg=C['surface']);upper.pack(fill='x',padx=16,pady=14)
        self.section_label=label(upper,'همه دانلودها',12,bold=True);self.section_label.pack(side='right')
        self.count_label=label(upper,'۰ مورد',9,'muted');self.count_label.pack(side='left')
        wrap=tk.Frame(frame,bg=C['surface']);wrap.pack(fill='both',expand=True,padx=9,pady=(0,10))
        # Left-to-right column order ensures filename is nearest the right edge.
        cols=('state','speed','size','percent','filename')
        self.tree=ttk.Treeview(wrap,columns=cols,show='headings',style='Maher.Treeview',selectmode='browse')
        columns={
            'state':('وضعیت',130,'center'),
            'speed':('سرعت',110,'center'),
            'size':('حجم',110,'center'),
            'percent':('پیشرفت',165,'center'),
            'filename':('نام فایل',250,'e'),
        }
        for col,(name,w,anch) in columns.items():
            self.tree.heading(col,text=fa(name),anchor=anch)
            self.tree.column(col,width=w,minwidth=100 if col=='filename' else 85,stretch=col=='filename',anchor=anch)
        sb=ttk.Scrollbar(wrap,orient='vertical',command=self.tree.yview,style='Maher.Vertical.TScrollbar')
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side='right',fill='y');self.tree.pack(side='left',fill='both',expand=True)
        self.tree.tag_configure('done',foreground=C['green'])
        self.tree.tag_configure('error',foreground=C['red'])
        self.tree.tag_configure('paused',foreground=C['warn'])
        self.tree.tag_configure('running',foreground=C['text'])

    def _bind_events(self):
        self.search_text.trace_add('write',lambda *_:self.refresh())
        self.tree.bind('<<TreeviewSelect>>',self.on_select)
        self.tree.bind('<Double-1>',lambda _:self.open_file())
        self.tree.bind('<Button-3>',self.right_click)
        self.bind('<Control-n>',lambda _:AddDialog(self))
        self.bind('<Control-v>',self.clipboard_add)
        try:
            self.drop_target_register('DND_TEXT','DND_FILES')
            self.dnd_bind('<<Drop>>',lambda e:self._on_drop(e.data))
        except (AttributeError,tk.TclError):pass

    def apply_theme(self,theme):
        C.update(THEMES.get(theme,THEMES['فیروزه‌ای']))
        self.configure(bg=C['bg'])
        for child in self.winfo_children():child.destroy()
        self._build_styles();self._build_ui();self._bind_events();self.refresh()

    def cycle_theme(self):
        themes=list(THEMES);index=(themes.index(self.manager.theme)+1)%len(themes) if self.manager.theme in themes else 0
        self.manager.configure(theme=themes[index]);self.apply_theme(themes[index])

    def copy_pairing(self):
        self.clipboard_clear();self.clipboard_append(self.manager.pairing_token)
        messagebox.showinfo('اتصال مرورگر','کد محرمانه اتصال کپی شد. در افزونه مرورگر وارد و ذخیره کنید.',parent=self)

    def check_update(self,silent=False):
        repo=self.manager.update_repo or RELEASE_REPOSITORY
        if not repo:
            if not silent:messagebox.showinfo('بروزرسانی','ابتدا در تنظیمات، آدرس GitHub را به شکل owner/repo وارد کنید.',parent=self)
            return
        def task():
            try:
                update=find_update(repo)
                self._updates.put(('new',update,silent) if update else ('none',None,silent))
            except Exception as exc:self._updates.put(('error',str(exc),silent))
        threading.Thread(target=task,daemon=True).start()

    def _offer_update(self,update):
        if not messagebox.askyesno('نسخه جدید',f"نسخه {update['version']} موجود است. بسته نصب دریافت و اعتبارسنجی شود؟",parent=self):return
        def task():
            try:self._updates.put(('installed',download_verified_update(update),False))
            except Exception as exc:self._updates.put(('error',str(exc),False))
        threading.Thread(target=task,daemon=True).start()

    def _on_drop(self,data):
        data=data.strip().strip('{}')
        if data.startswith(('https://','http://','ftp://')):
            AddDialog(self,data)

    def clipboard_add(self,event=None):
        if isinstance(self.focus_get(),(tk.Entry,ttk.Entry)):return
        try:url=self.clipboard_get().strip()
        except tk.TclError:return
        if url.startswith(('http://','https://','ftp://')):AddDialog(self,url)

    def right_click(self,event):
        row=self.tree.identify_row(event.y)
        if row:self.tree.selection_set(row);self.selected=row;self._update_details()
        menu=tk.Menu(self,tearoff=0,bg=C['surface2'],fg=C['text'],activebackground=C['accent'],activeforeground=C['bg'],bd=0)
        menu.add_command(label=fa('ادامه دانلود'),command=self.resume_selected)
        menu.add_command(label=fa('توقف دانلود'),command=self.pause_selected)
        menu.add_command(label=fa('باز کردن پوشه'),command=self.open_directory)
        menu.add_separator()
        menu.add_command(label=fa('حذف از فهرست'),command=self.remove_selected)
        menu.tk_popup(event.x_root,event.y_root)

    def choose_filter(self,key):
        self.filter=key
        for k,b in self.filter_buttons.items():
            b.configure(bg=C['surface2'] if k==key else C['surface'],fg=C['accent'] if k==key else C['muted'])
        self.refresh()

    def _matches(self,j):
        item=self.filter
        states={'در حال دانلود':'running','در صف':'queued','تکمیل‌شده':'done','متوقف‌شده':'paused','خطادار':'error'}
        if item in states and j['status']!=states[item]:return False
        if item in ('ویدیو','موسیقی','تصاویر','اسناد','فشرده','سایر') and j['category']!=item:return False
        query=self.search_text.get().strip().lower()
        return not query or query in j['filename'].lower() or query in j['url'].lower()

    def _poll(self):
        if not self.winfo_exists():return
        try:self._dirty.get_nowait();self.refresh()
        except queue.Empty:pass
        try:
            event,data,silent=self._updates.get_nowait()
            if event=='error':
                if not silent:messagebox.showerror('بروزرسانی',str(data),parent=self)
            elif event=='none':
                if not silent:messagebox.showinfo('بروزرسانی','آخرین نسخه نصب است.',parent=self)
            elif event=='new':self._offer_update(data)
            elif event=='installed':
                if messagebox.askyesno('نصب بروزرسانی','فایل معتبر دریافت شد. نصب‌کننده اجرا و برنامه بسته شود؟',parent=self):
                    launch_installer(data);self.close();return
        except queue.Empty:pass
        self.after(450,self._poll)

    def refresh(self):
        if not hasattr(self,'tree'):return
        jobs=self.manager.list_jobs()
        visible=[j for j in jobs if self._matches(j)]
        existing=set(self.tree.get_children());ids={j['id'] for j in visible}
        for id in existing-ids:self.tree.delete(id)
        for idx,j in enumerate(visible):
            total=j['total'];pct=min(100,round(100*j['downloaded']/total)) if total else 0
            progress='■'*round(pct/10)+'·'*(10-round(pct/10)) + f'  {pct}%' if total else ('✓ ۱۰۰٪' if j['status']=='done' else human_size(j['downloaded']))
            stat=STATUS_FA.get(j['status'],j['status'])
            if j['status']=='scheduled':stat='زمان‌بندی‌شده'
            values=(fa(stat), human_size(j['speed'])+'/s' if j['status']=='running' else '—',
                    human_size(total) if total else human_size(j['downloaded']),progress,j['filename'])
            if j['id'] not in existing:self.tree.insert('','end',iid=j['id'],values=values,tags=(j['status'],))
            else:self.tree.item(j['id'],values=values,tags=(j['status'],))
            self.tree.move(j['id'],'',idx)
        if self.selected in ids:self.tree.selection_set(self.selected)
        self.cards['total'].configure(text=str(len(jobs)))
        self.cards['running'].configure(text=str(sum(j['status']=='running' for j in jobs)))
        self.cards['done'].configure(text=str(sum(j['status']=='done' for j in jobs)))
        self.cards['speed'].configure(text=human_size(sum(j['speed'] for j in jobs if j['status']=='running')))
        self.section_label.configure(text=fa(self.filter))
        self.count_label.configure(text=fa(f'{len(visible)} مورد'))
        self._update_details()

    def on_select(self,event=None):
        selected=self.tree.selection()
        if selected:self.selected=selected[0]
        self._update_details()

    def _update_details(self):
        j=self.manager.find(self.selected) if self.selected else None
        if j:
            msg=f'{j.filename}   •   {human_size(j.downloaded)} از {human_size(j.total)}'
            if j.error:msg+='   •   '+j.error[:110]
            self.details.configure(text=fa(msg))
        else:self.details.configure(text='برای مشاهده جزئیات، یک دانلود را انتخاب کنید.')

    def pause_selected(self):
        if self.selected:self.manager.pause(self.selected);self.refresh()

    def resume_selected(self):
        if self.selected:self.manager.resume(self.selected);self.refresh()

    def remove_selected(self):
        if not self.selected:return
        j=self.manager.find(self.selected)
        if not j:return
        if j._worker:
            messagebox.showinfo('دانلود فعال','ابتدا دانلود را متوقف کنید و چند لحظه بعد حذف کنید.',parent=self);return
        if not messagebox.askyesno('حذف دانلود',f'«{j.filename}» از فهرست حذف شود؟\nفایل تکمیل‌شده حذف نخواهد شد.',parent=self):return
        try:self.manager.remove(j.id,delete_partial=True);self.selected=None;self.refresh()
        except ValueError as e:messagebox.showerror('خطا',str(e),parent=self)

    def open_directory(self):
        j=self.manager.find(self.selected) if self.selected else None
        if not j:return
        path=Path(j.directory)
        if path.exists():self._open_path(path)
        else:messagebox.showwarning('پوشه یافت نشد',str(path),parent=self)

    def open_file(self):
        j=self.manager.find(self.selected) if self.selected else None
        if not j:return
        if j.status=='done' and j.dest.exists():self._open_path(j.dest)
        else:self.open_directory()

    def _open_path(self,path):
        try:
            if os.name=='nt':os.startfile(str(path))
            elif sys.platform=='darwin':subprocess.Popen(['open',str(path)])
            else:subprocess.Popen(['xdg-open',str(path)])
        except OSError as e:messagebox.showerror('باز کردن فایل',str(e),parent=self)

    def close(self):
        self.manager.shutdown()
        if self.bridge:self.bridge.shutdown();self.bridge.server_close()
        self.destroy()


def main():
    app=App()
    try:
        ico=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'assets'/'maher.ico'
        if ico.exists():app.iconbitmap(str(ico))
    except tk.TclError:pass
    app.mainloop()

if __name__=='__main__':main()
