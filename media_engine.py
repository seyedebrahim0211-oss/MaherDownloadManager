"""Download public/authorized video pages and unprotected HLS via yt-dlp.

No DRM circumvention, cookies extraction, or protected-content decryption.
The app keeps a private, resumable per-job yt-dlp workspace, then atomically
moves the finished output to a user-controlled download directory.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit
import re
import shutil

from download_engine import Paused, sanitize_name

MEDIA_HOSTS = ('youtube.com', 'youtu.be', 'youtube-nocookie.com', 'm.youtube.com', 'music.youtube.com')


def guess_mode(url: str) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or '').lower()
    if host in MEDIA_HOSTS or host.endswith('.youtube.com') or host.endswith('.youtube-nocookie.com'):
        return 'media'
    if parsed.path.lower().endswith(('.m3u8', '.mpd')):
        return 'media'
    return 'direct'


def _ffmpeg_location():
    try:
        import imageio_ffmpeg
        path = imageio_ffmpeg.get_ffmpeg_exe()
        if Path(path).exists():
            return path
    except Exception:
        pass
    return shutil.which('ffmpeg')


def get_media_info(url: str) -> dict:
    """Metadata-only probe. Never download protected media here."""
    import yt_dlp
    with yt_dlp.YoutubeDL({'quiet': True, 'noplaylist': True, 'skip_download': True,
                            'ignoreerrors': False}) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise RuntimeError('اطلاعات ویدیو دریافت نشد.')
    return {'title': info.get('title', ''), 'duration': info.get('duration'),
            'webpage_url': info.get('webpage_url', url),
            'drm': bool(info.get('is_drm', False) or _all_formats_drm(info))}


def _all_formats_drm(info):
    fmts = info.get('formats') or []
    return bool(fmts) and all(f.get('has_drm') for f in fmts)


def download_media(job, lock, proxy=""):
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError('موتور رسانه yt-dlp نصب نشده است. requirements.txt را نصب کنید.') from exc
    if job._stop.is_set():
        raise Paused()
    temp = Path(job.directory) / ('.maher-media-' + job.id)
    temp.mkdir(parents=True, exist_ok=True)
    ffmpeg = _ffmpeg_location()
    format_selector = 'bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b' if ffmpeg else 'b[ext=mp4]/b'
    previous = [0]

    def hook(d):
        if job._stop.is_set():
            raise Paused()
        if d.get('status') != 'downloading':
            return
        downloaded = int(d.get('downloaded_bytes') or 0)
        estimated = int(d.get('total_bytes') or d.get('total_bytes_estimate') or 0)
        with lock:
            # yt-dlp may download video and audio separately; progress can reset.
            # A fresh format resets its progress instead of producing invalid >100%.
            if downloaded < previous[0]:
                previous[0] = 0
            job.downloaded = downloaded
            job.total = estimated
            job.speed = float(d.get('speed') or 0)
            previous[0] = downloaded

    def protect(info, *, incomplete=False):
        if job._stop.is_set():
            raise Paused()
        if info.get('is_drm') or _all_formats_drm(info):
            return 'این ویدیو با DRM محافظت می‌شود و قابل دریافت با این برنامه نیست.'
        return None

    options = {
        'paths': {'home': str(temp)},
        'outtmpl': {'default': 'maher.%(ext)s'},
        'format': format_selector,
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'continuedl': True,
        'retries': 5,
        'fragment_retries': 5,
        'concurrent_fragment_downloads': 4,
        'ignoreerrors': False,
        'progress_hooks': [hook],
        'match_filter': protect,
        'overwrites': False,
        'restrictfilenames': True,
        'windowsfilenames': True,
        'allow_unplayable_formats': False,
    }
    if proxy:
        options['proxy'] = proxy
    bundled_deno = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'assets' / 'bin' / 'deno.exe'
    if bundled_deno.is_file():
        options['js_runtimes'] = {'deno': {'path': str(bundled_deno)}}
    if ffmpeg:
        options['ffmpeg_location'] = ffmpeg
    if job.limit_kbps:
        options['ratelimit'] = job.limit_kbps * 1024

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(job.url, download=True)
            if not info:
                raise OSError('رسانه دریافت نشد یا محتوای DRM دارد.')
            if info.get('is_drm') or _all_formats_drm(info):
                raise OSError('محتوای DRM قابل دانلود نیست.')
    except Exception as exc:
        if job._stop.is_set():
            raise Paused() from exc
        raise
    if job._stop.is_set():
        raise Paused()
    # Only files created in our fixed job workspace are eligible.
    outputs = [f for f in temp.iterdir() if f.is_file() and not f.name.endswith(('.part','.ytdl','.temp'))]
    if not outputs:
        raise OSError('فایل خروجی رسانه یافت نشد؛ ممکن است FFmpeg مورد نیاز باشد.')
    winner = max(outputs, key=lambda p: p.stat().st_size)
    final_name = sanitize_name(Path(job.filename).stem + winner.suffix)
    final = Path(job.directory) / final_name
    if final.exists():
        final_name = sanitize_name(Path(job.filename).stem + '-' + job.id[:8] + winner.suffix)
        final = Path(job.directory) / final_name
    if final.exists():
        raise FileExistsError('فایل مقصد از قبل وجود دارد.')
    os.replace(winner, final)
    with lock:
        job.filename = final_name
        job.category = 'ویدیو'
        job.total = final.stat().st_size
        job.downloaded = job.total
    # Only delete temp files after a successful move; retain parts on pause/error.
    shutil.rmtree(temp, ignore_errors=True)
