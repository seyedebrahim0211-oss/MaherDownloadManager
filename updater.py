"""Opt-in verified GitHub Releases installer updates, without silent execution."""
from __future__ import annotations

from pathlib import Path
import hashlib
import re
import subprocess
import tempfile
import requests

APP_VERSION = '2.0.0'
REPO_RE = re.compile(r'^[A-Za-z\d_.-]+/[A-Za-z\d_.-]+$')
SETUP_NAME = 'MaherDownloader-Setup.exe'


def _version_tuple(version):
    parts = re.findall(r'\d+', version or '')
    return tuple((int(n) for n in parts[:3])) if parts else (0,0,0)


def find_update(repository, current=APP_VERSION, session=requests):
    if not REPO_RE.fullmatch(repository):
        raise ValueError('نشانی مخزن باید مانند owner/repo باشد.')
    url=f'https://api.github.com/repos/{repository}/releases/latest'
    r=session.get(url,headers={'Accept':'application/vnd.github+json','User-Agent':'MaherDownloader-Updater'},timeout=(8,18))
    r.raise_for_status()
    data=r.json()
    version=data.get('tag_name','').lstrip('vV')
    if _version_tuple(version)<=_version_tuple(current):
        return None
    assets={a.get('name'):a.get('browser_download_url') for a in data.get('assets',[])}
    if not assets.get(SETUP_NAME) or not assets.get(SETUP_NAME+'.sha256'):
        raise ValueError('نسخه جدید فایل نصب یا هش SHA-256 معتبر ندارد.')
    if not (assets[SETUP_NAME].startswith('https://') and assets[SETUP_NAME+'.sha256'].startswith('https://')):
        raise ValueError('فقط دریافت امن HTTPS برای نصب‌کننده مجاز است.')
    return {'version':version,'url':assets[SETUP_NAME], 'checksum_url':assets[SETUP_NAME+'.sha256'],
            'release_url':data.get('html_url','')}


def download_verified_update(update, directory=None, session=requests):
    """Checks SHA-256 of downloaded EXE before offering execution."""
    destination=Path(directory or Path(tempfile.gettempdir())/'MaherDownloaderUpdate')
    destination.mkdir(parents=True,exist_ok=True)
    hash_response=session.get(update['checksum_url'],timeout=(8,20))
    hash_response.raise_for_status()
    expected=hash_response.text.strip().split()[0].lower()
    if not re.fullmatch(r'[a-f0-9]{64}',expected):
        raise ValueError('هش فایل به‌روزرسانی نامعتبر است.')
    target=destination/SETUP_NAME
    tmp=destination/(SETUP_NAME+'.download')
    h=hashlib.sha256();size=0
    try:
        with session.get(update['url'],stream=True,timeout=(12,40)) as response:
            response.raise_for_status()
            with tmp.open('wb') as fp:
                for part in response.iter_content(chunk_size=1024*256):
                    if not part:continue
                    size+=len(part)
                    if size>800*1024*1024:raise ValueError('حجم نصب‌کننده بیش از حد مجاز است.')
                    fp.write(part);h.update(part)
        if not size or h.hexdigest()!=expected:
            raise ValueError('یکپارچگی SHA-256 بسته نصب تأیید نشد.')
        tmp.replace(target)
        return target
    finally:
        tmp.unlink(missing_ok=True)


def launch_installer(path):
    path=Path(path)
    if path.name!=SETUP_NAME or not path.is_file():
        raise ValueError('مسیر نصب‌کننده نامعتبر است.')
    return subprocess.Popen([str(path),'/NORESTART'],close_fds=True)
