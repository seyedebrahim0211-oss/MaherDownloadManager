"""Maher Download Manager download core.

Supports HTTP(S) segmented transfer and validated resume, sequential non-range
fallback, FTP streaming, atomic metadata persistence and an optional rate cap.
Only user-supplied, directly accessible download URLs are supported.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Event, RLock, Thread
from urllib.parse import urlsplit, unquote
import json
import math
import os
import re
import shutil
import time
import uuid
import secrets
import urllib.request

import requests

APP_DIR = Path(os.environ.get('LOCALAPPDATA') or Path.home() / '.maher_downloader') / 'MaherDownloader'
ALLOWED_SCHEMES = {'http', 'https', 'ftp'}
EXT_CATEGORIES = {
    'ویدیو': {'.mp4','.mkv','.mov','.avi','.webm','.wmv','.flv','.m4v','.ts'},
    'موسیقی': {'.mp3','.wav','.flac','.aac','.ogg','.m4a','.wma'},
    'تصاویر': {'.jpg','.jpeg','.png','.gif','.webp','.bmp','.svg','.tiff'},
    'اسناد': {'.pdf','.doc','.docx','.xls','.xlsx','.ppt','.pptx','.txt','.csv','.epub'},
    'فشرده': {'.zip','.rar','.7z','.tar','.gz','.iso','.msi','.exe'},
}
STATUS_FA = {'queued':'در صف','running':'در حال دانلود','paused':'متوقف','done':'تکمیل‌شده','error':'خطا','scheduled':'زمان‌بندی‌شده'}


def sanitize_name(value: str) -> str:
    """Produce a safe Windows filename and never honor paths supplied by remote sites."""
    value = unquote(value or '').replace('\\','/').split('/')[-1]
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value).strip(' .')
    if value.split('.')[0].upper() in {'CON','PRN','AUX','NUL', *[f'COM{i}' for i in range(1,10)], *[f'LPT{i}' for i in range(1,10)]}:
        value = '_' + value
    return (value[:180].rstrip(' .') or f'download-{uuid.uuid4().hex[:8]}.bin')


def category_for(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return next((key for key, vals in EXT_CATEGORIES.items() if suffix in vals), 'سایر')


def human_size(num: int | float | None) -> str:
    if num is None or num < 0: return 'نامشخص'
    v=float(num)
    for unit in ('B','KB','MB','GB','TB'):
        if v<1024 or unit=='TB':return f'{v:.0f} {unit}' if unit=='B' else f'{v:.1f} {unit}'
        v/=1024
    return '—'


@dataclass
class DownloadJob:
    url: str
    filename: str
    directory: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    category: str = 'سایر'
    status: str = 'queued'
    total: int = 0
    downloaded: int = 0
    segments: list[dict] = field(default_factory=list)
    etag: str = ''
    modified: str = ''
    ranged: bool = False
    limit_kbps: int = 0
    added_at: str = field(default_factory=lambda:datetime.now().isoformat(timespec='seconds'))
    scheduled_at: str = ''
    error: str = ''
    kind: str = 'direct'
    speed: float = 0.0
    _stop: Event = field(default_factory=Event, repr=False, compare=False)
    _worker: bool = field(default=False, repr=False, compare=False)
    _last_bytes: int = field(default=0, repr=False, compare=False)
    _last_tick: float = field(default_factory=time.monotonic, repr=False, compare=False)

    def snapshot(self) -> dict:
        fields=('id','url','filename','directory','category','status','total','downloaded','segments',
                'etag','modified','ranged','limit_kbps','added_at','scheduled_at','error','kind')
        return {field: getattr(self,field) for field in fields}

    @property
    def dest(self) -> Path: return Path(self.directory) / self.filename

    @property
    def part(self) -> Path: return self.dest.with_name(self.dest.name + '.maher.part')


class Paused(Exception): pass


class DownloadManager:
    def __init__(self, app_dir: Path | str = APP_DIR, *, connections: int = 6, parallel: int = 2, callback=None):
        self.app_dir = Path(app_dir)
        self.app_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.app_dir / 'downloads.json'
        self.default_dir = Path.home() / 'Downloads'
        self.connections = max(1,min(int(connections),16))
        self.parallel = max(1,min(int(parallel),6))
        self.proxy = ''
        self.theme = 'نگار ایرانی'
        self.update_repo = ''
        self.language = 'fa'
        self.auto_check_updates = True
        self.auto_download_updates = True
        self.last_update_check = ''
        self.pairing_token = secrets.token_hex(24)
        self.callback = callback or (lambda:None)
        self.jobs: list[DownloadJob] = []
        self.lock=RLock()
        self._stop=Event()
        self._load()
        if not self.db_path.exists(): self.save()
        self.scheduler=Thread(target=self._schedule_loop, daemon=True, name='maher-scheduler')
        self.scheduler.start()

    def configure(self, *, connections=None, parallel=None, default_dir=None, proxy=None, theme=None, update_repo=None, language=None, auto_check_updates=None, auto_download_updates=None, last_update_check=None):
        with self.lock:
            if connections is not None: self.connections=max(1,min(16,int(connections)))
            if parallel is not None:self.parallel=max(1,min(6,int(parallel)))
            if default_dir is not None:self.default_dir=Path(default_dir).expanduser()
            if proxy is not None:
                if '@' in urlsplit(proxy).netloc: raise ValueError('پروکسی دارای رمز عبور ذخیره نمی‌شود.')
                if proxy and urlsplit(proxy).scheme not in {'http','https'}:raise ValueError('نشانی پروکسی نامعتبر است.')
                self.proxy=proxy
            if theme is not None:
                from themes import THEMES
                if theme not in THEMES:raise ValueError('پوسته نامعتبر است.')
                self.theme=theme
            if update_repo is not None:
                from updater import REPO_RE
                if update_repo and not REPO_RE.fullmatch(update_repo):raise ValueError('نشانی مخزن GitHub معتبر نیست.')
                self.update_repo=update_repo
            if language is not None:
                if language not in {'fa','en'}:raise ValueError('Unsupported language.')
                self.language=language
            if auto_check_updates is not None:self.auto_check_updates=bool(auto_check_updates)
            if auto_download_updates is not None:self.auto_download_updates=bool(auto_download_updates)
            if last_update_check is not None:self.last_update_check=str(last_update_check)
            self.save()
        self._notify()

    def _load(self):
        if not self.db_path.exists():return
        try:
            data=json.loads(self.db_path.read_text(encoding='utf-8'))
            settings=data.get('settings',{})
            self.connections=max(1,min(16,int(settings.get('connections', self.connections))))
            self.parallel=max(1,min(6,int(settings.get('parallel', self.parallel))))
            self.default_dir=Path(settings.get('default_dir',str(self.default_dir)))
            self.proxy=settings.get('proxy','')
            self.theme=settings.get('theme','فیروزه‌ای')
            self.update_repo=settings.get('update_repo','')
            self.language=settings.get('language','fa') if settings.get('language','fa') in {'fa','en'} else 'fa'
            self.auto_check_updates=bool(settings.get('auto_check_updates',True))
            self.auto_download_updates=bool(settings.get('auto_download_updates',True))
            self.last_update_check=settings.get('last_update_check','')
            self.pairing_token=settings.get('pairing_token') or self.pairing_token
            allowed=set(DownloadJob.__dataclass_fields__)-{'_stop','_worker','_last_bytes','_last_tick','speed'}
            for raw in data.get('jobs',[]):
                job=DownloadJob(**{k:v for k,v in raw.items() if k in allowed})
                if job.status=='running':job.status='paused'
                if job.status=='queued' and not job.scheduled_at:job.status='paused'
                self.jobs.append(job)
        except (ValueError,TypeError,KeyError,OSError):
            # Preserve the damaged metadata rather than silently replacing it.
            try:shutil.copy2(self.db_path, self.db_path.with_suffix('.corrupt.json'))
            except OSError:pass

    def save(self):
        with self.lock:
            payload={'version':1,'settings':{'connections':self.connections,'parallel':self.parallel,
                'default_dir':str(self.default_dir),'proxy':self.proxy,'theme':self.theme,
                'update_repo':self.update_repo,'pairing_token':self.pairing_token,
                'language':self.language,'auto_check_updates':self.auto_check_updates,
                'auto_download_updates':self.auto_download_updates,'last_update_check':self.last_update_check},'jobs':[j.snapshot() for j in self.jobs]}
            tmp=self.db_path.with_suffix('.json.tmp')
            tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2), encoding='utf-8')
            os.replace(tmp,self.db_path)

    def _notify(self):
        try:self.callback()
        except Exception:pass

    def list_jobs(self):
        with self.lock:
            return [dict(j.snapshot(),speed=j.speed,active=j._worker) for j in self.jobs]

    def find(self, id):
        with self.lock:return next((job for job in self.jobs if job.id==id),None)

    def add(self, url: str, *, filename='', directory='', limit_kbps=0, scheduled_at='', kind='auto') -> DownloadJob:
        url=url.strip()
        parsed=urlsplit(url)
        if parsed.scheme.lower() not in ALLOWED_SCHEMES or not parsed.hostname:
            raise ValueError('فقط پیوندهای مستقیم HTTP، HTTPS و FTP پذیرفته می‌شوند.')
        if parsed.username or parsed.password:
            raise ValueError('پیوند شامل نام کاربری یا گذرواژه پذیرفته نمی‌شود.')
        from media_engine import guess_mode
        if kind == 'auto':kind = guess_mode(url)
        if kind not in {'direct','media'}:raise ValueError('نوع دانلود نامعتبر است.')
        with self.lock:
            for old in self.jobs:
                if old.url==url and old.status!='error':
                    raise ValueError('این پیوند قبلاً به فهرست دانلود اضافه شده است.')
            name=sanitize_name(filename or (('video-' + uuid.uuid4().hex[:8] + '.mp4') if kind=='media' else parsed.path.split('/')[-1]))
            folder=Path(directory).expanduser() if directory else self.default_dir / category_for(name)
            job=DownloadJob(url=url,filename=name,directory=str(folder),category=('ویدیو' if kind=='media' else category_for(name)),kind=kind,
                limit_kbps=max(0,int(limit_kbps)),scheduled_at=scheduled_at,status='scheduled' if scheduled_at else 'queued')
            if job.dest.exists() or job.part.exists() or any(j.dest==job.dest for j in self.jobs):
                stem=job.dest.stem;suffix=job.dest.suffix
                for i in range(1,10001):
                    name=sanitize_name(f'{stem} ({i}){suffix}')
                    candidate=Path(job.directory)/name
                    if not candidate.exists() and not candidate.with_name(name+'.maher.part').exists() and all(j.dest!=candidate for j in self.jobs):
                        job.filename=name;break
            self.jobs.insert(0,job)
            self.save()
        self._notify()
        return job

    def pause(self, id):
        with self.lock:
            job=self.find(id)
            if job and job.status in {'running','queued','scheduled'}:
                job.status='paused';job._stop.set();job.speed=0
                self.save()
        self._notify()

    def resume(self,id):
        with self.lock:
            job=self.find(id)
            if job and job.status in {'paused','error','scheduled'} and not job._worker:
                job._stop.clear();job.error='';job.scheduled_at='';job.status='queued'
                self.save()
        self._notify()

    def pause_all(self):
        for job in self.list_jobs():self.pause(job['id'])

    def resume_all(self):
        for job in self.list_jobs():self.resume(job['id'])

    def remove(self,id,delete_partial=False):
        with self.lock:
            j=self.find(id)
            if not j:return
            if j._worker:raise ValueError('ابتدا دانلود را متوقف کنید و منتظر خروج آن از حالت فعال بمانید.')
            self.jobs.remove(j)
            if delete_partial:
                try:j.part.unlink(missing_ok=True)
                except OSError:pass
            self.save()
        self._notify()

    def _schedule_loop(self):
        last_save=time.monotonic()
        while not self._stop.wait(0.25):
            with self.lock:
                now=datetime.now()
                for j in self.jobs:
                    if j.status=='scheduled':
                        try:
                            if datetime.fromisoformat(j.scheduled_at)<=now:j.status='queued'
                        except ValueError:j.status='paused'
                running=sum(1 for j in self.jobs if j._worker)
                for j in reversed(self.jobs):
                    if running>=self.parallel:break
                    if j.status=='queued' and not j._worker:
                        j._worker=True;j._stop.clear();j.status='running'
                        j._last_bytes=j.downloaded;j._last_tick=time.monotonic();j.speed=0.0
                        Thread(target=self._run_job,args=(j,),daemon=True,name='download-'+j.id[:7]).start()
                        running+=1
                t=time.monotonic()
                for j in self.jobs:
                    if j.status=='running':
                        delta=max(t-j._last_tick,0.01)
                        # Smoothed approximately over 1s, using instantaneous differences.
                        if delta>=0.8:
                            j.speed=max(0.0,(j.downloaded-j._last_bytes)/delta)
                            j._last_bytes=j.downloaded;j._last_tick=t
                if t-last_save>1.5:
                    try:self.save()
                    except OSError:pass
                    last_save=t
            self._notify()

    def _requests(self):
        s=requests.Session()
        s.trust_env=not bool(self.proxy)
        if self.proxy:s.proxies={'http':self.proxy,'https':self.proxy}
        s.headers.update({'User-Agent':'MaherDownloadManager/1.0','Accept-Encoding':'identity'})
        return s

    def _probe(self,job):
        if urlsplit(job.url).scheme=='ftp':return (0, False, '', '')
        total=0;etag='';modified=''
        with self._requests() as s:
            try:
                r=s.head(job.url,allow_redirects=True,timeout=(8,18))
                if r.ok:
                    total=int(r.headers.get('Content-Length') or 0)
                    etag=r.headers.get('ETag','');modified=r.headers.get('Last-Modified','')
                r.close()
            except requests.RequestException:pass
            # A real 206 test is essential: Accept-Ranges alone cannot be trusted.
            r=s.get(job.url,headers={'Range':'bytes=0-0'},allow_redirects=True,stream=True,timeout=(10,25))
            try:
                r.raise_for_status()
                cr=r.headers.get('Content-Range','')
                match=re.match(r'bytes\s+0-0/(\d+)',cr,re.I)
                ranged=(r.status_code==206 and bool(match))
                if ranged:total=int(match.group(1))
                elif not total:total=int(r.headers.get('Content-Length') or 0)
                etag=r.headers.get('ETag') or etag
                modified=r.headers.get('Last-Modified') or modified
            finally:r.close()
        return total,ranged,etag,modified

    def _prepare(self,j,total,ranged,etag,modified):
        with self.lock:
            must_reset = bool(j.segments) and (
                (j.total and total and j.total!=total) or
                (j.etag and etag and j.etag!=etag) or
                (j.modified and modified and j.modified!=modified) or
                (not ranged) or
                (not j.part.exists()) or
                (ranged and total and j.part.exists() and j.part.stat().st_size != total) or
                any(not (0 <= p.get('start',-1) <= p.get('offset',-2) <= p.get('end',-3)+1) for p in j.segments)
            )
            if must_reset:
                j.segments=[];j.downloaded=0
            j.total=total;j.ranged=ranged;j.etag=etag;j.modified=modified
            if ranged and total:
                if not j.segments:
                    n=min(self.connections,max(1,math.ceil(total/(512*1024))))
                    span=math.ceil(total/n)
                    j.segments=[{'start':start,'end':min(start+span-1,total-1),'offset':start}
                                for start in range(0,total,span)]
                j.downloaded=sum(s['offset']-s['start'] for s in j.segments)
            else:
                j.segments=[{'start':0,'end':total-1 if total else -1,'offset':0}]
                j.downloaded=0
            j.directory and Path(j.directory).mkdir(parents=True,exist_ok=True)
            # Never alter an already completed file; unique destination is chosen on addition.
            if not (ranged and total and j.part.exists() and not must_reset):
                with j.part.open('wb') as f:
                    if ranged and total:f.truncate(total)
            self.save()

    def _run_job(self,j):
        try:
            if j._stop.is_set() or j.status!='running':raise Paused()
            if j.kind=='media':
                from media_engine import download_media
                download_media(j,self.lock,self.proxy)
                if j._stop.is_set() or j.status!='running':raise Paused()
                with self.lock:
                    j.status='done';j.speed=0;j.error='';self.save()
                return
            total,ranged,etag,modified=self._probe(j)
            if j._stop.is_set() or j.status!='running':raise Paused()
            self._prepare(j,total,ranged,etag,modified)
            if ranged and total:
                remaining=[s for s in j.segments if s['offset']<=s['end']]
                limiter=_RateLimit(j)
                if remaining:
                    with ThreadPoolExecutor(max_workers=len(remaining)) as pool:
                        futures=[pool.submit(self._download_part,j,s,limiter) for s in remaining]
                        for future in as_completed(futures):
                            try:future.result()
                            except Exception:
                                j._stop.set()
                                raise
            elif urlsplit(j.url).scheme=='ftp':
                self._download_ftp(j,_RateLimit(j))
            else:
                self._download_stream(j,_RateLimit(j))
            if j._stop.is_set() or j.status!='running':raise Paused()
            with self.lock:
                if j.total and j.downloaded!=j.total:raise OSError('اندازه فایل دریافتی با اندازه اعلام‌شده مطابقت ندارد.')
                if j.dest.exists():raise OSError('فایل مقصد از قبل وجود دارد؛ از بازنویسی خودکار جلوگیری شد.')
                os.replace(j.part,j.dest)
                j.status='done';j.speed=0;j.error=''
                self.save()
        except Paused:
            with self.lock:
                if j.status=='running':j.status='paused'
                j.speed=0;self.save()
        except Exception as exc:
            with self.lock:
                if j.status=='paused':j.error=''
                else:j.status='error';j.error=str(exc)[:350]
                j.speed=0;self.save()
        finally:
            with self.lock:
                j._worker=False
                self.save()
            self._notify()

    def _download_part(self,j,seg,limiter):
        if j._stop.is_set():raise Paused()
        start=seg['offset'];end=seg['end']
        headers={'Range':f'bytes={start}-{end}'}
        if j.etag and not j.etag.startswith('W/'):headers['If-Range']=j.etag
        elif j.modified:headers['If-Range']=j.modified
        with self._requests() as session:
            with session.get(j.url,headers=headers,stream=True,timeout=(10,25)) as r:
                if r.status_code!=206:raise OSError('سرور ادامه دانلود چندبخشی را نپذیرفت؛ دوباره امتحان کنید.')
                content_range=r.headers.get('Content-Range','')
                if not content_range.lower().startswith(f'bytes {start}-{end}/'):
                    raise OSError('پاسخ بخش دانلود از محدوده درخواست‌شده متفاوت است.')
                with j.part.open('r+b',buffering=0) as f:
                    f.seek(start);offset=start
                    for chunk in r.iter_content(chunk_size=64*1024):
                        if j._stop.is_set():raise Paused()
                        if not chunk:continue
                        if len(chunk)>end-offset+1:raise OSError('حجم بخش دریافتی بیشتر از مقدار مورد انتظار است.')
                        limiter.wait(len(chunk),j._stop)
                        if j._stop.is_set():raise Paused()
                        f.write(chunk)
                        offset+=len(chunk)
                        with self.lock:
                            seg['offset']=offset;j.downloaded+=len(chunk)
                    if offset!=end+1:raise OSError('بخشی از فایل ناقص دریافت شد.')

    def _download_stream(self,j,limiter):
        with self._requests() as session:
            with session.get(j.url,stream=True,timeout=(10,25)) as r:
                r.raise_for_status()
                with j.part.open('wb',buffering=0) as f:
                    for chunk in r.iter_content(chunk_size=64*1024):
                        if j._stop.is_set():raise Paused()
                        if not chunk:continue
                        limiter.wait(len(chunk),j._stop)
                        if j._stop.is_set():raise Paused()
                        f.write(chunk)
                        with self.lock:j.downloaded+=len(chunk)

    def _download_ftp(self,j,limiter):
        # FTP is streamed. Some FTP servers support REST; universal safe resume is not guaranteed.
        with urllib.request.urlopen(j.url,timeout=25) as resp:
            with j.part.open('wb',buffering=0) as f:
                while True:
                    if j._stop.is_set():raise Paused()
                    chunk=resp.read(64*1024)
                    if not chunk:break
                    limiter.wait(len(chunk),j._stop)
                    if j._stop.is_set():raise Paused()
                    f.write(chunk)
                    with self.lock:j.downloaded+=len(chunk)

    def shutdown(self):
        self._stop.set()
        with self.lock:
            for j in self.jobs:
                if j.status=='running':j.status='paused';j._stop.set()
            self.save()
        self.scheduler.join(timeout=2)
        deadline=time.monotonic()+5
        while any(j._worker for j in self.jobs) and time.monotonic()<deadline:
            time.sleep(0.08)
        self.save()


class _RateLimit:
    def __init__(self, job):
        self.job = job
        self.lock = RLock()
        self.next_at = time.monotonic()

    def wait(self, n, stop):
        if self.job.limit_kbps <= 0:
            return
        with self.lock:
            rate = max(self.job.limit_kbps * 1024, 1024)
            now = time.monotonic()
            slot = max(now, self.next_at)
            self.next_at = slot + n / rate
        remaining = max(0, slot - time.monotonic())
        while remaining > 0:
            if stop.wait(min(remaining, 0.1)):
                raise Paused()
            remaining = max(0, slot - time.monotonic())
