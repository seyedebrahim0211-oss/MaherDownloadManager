from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from types import SimpleNamespace
import sys
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from download_engine import DownloadManager
from media_engine import guess_mode, _all_formats_drm

class FakeYoutubeDL:
    def __init__(self,opts):self.opts=opts
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def extract_info(self,url,download):
        if 'drm' in url:
            reason=self.opts['match_filter']({'is_drm':True,'formats':[{'has_drm':True}]},incomplete=False)
            raise ValueError(reason)
        p=Path(self.opts['paths']['home'])/'maher.mp4'
        p.write_bytes(b'test-video-data')
        self.opts['progress_hooks'][0]({'status':'downloading','downloaded_bytes':15,'total_bytes':15,'speed':123})
        return {'title':'A sample','is_drm':False}

class MediaTests(unittest.TestCase):
    def test_detection(self):
        self.assertEqual(guess_mode('https://www.youtube.com/watch?v=abc'),'media')
        self.assertEqual(guess_mode('https://cdn.example.com/movie.m3u8?token=abc'),'media')
        self.assertEqual(guess_mode('https://cdn.example.com/example.zip'),'direct')
        self.assertTrue(_all_formats_drm({'formats':[{'has_drm':True}]}))
        self.assertFalse(_all_formats_drm({'formats':[{'has_drm':True},{'has_drm':False}]}))

    def test_media_integration_and_drm_rejection(self):
        with TemporaryDirectory() as tmp,patch.dict(sys.modules,{'yt_dlp':SimpleNamespace(YoutubeDL=FakeYoutubeDL)}):
            manager=DownloadManager(Path(tmp)/'db')
            try:
                j=manager.add('https://www.youtube.com/watch?v=abc',directory=str(Path(tmp)/'videos'))
                self.assertEqual(j.kind,'media')
                end=time.monotonic()+6
                while j.status not in {'done','error'} and time.monotonic()<end:time.sleep(.04)
                self.assertEqual(j.status,'done',j.error)
                self.assertEqual(j.dest.read_bytes(),b'test-video-data')
                bad=manager.add('https://www.youtube.com/watch?v=drm',directory=str(Path(tmp)/'videos'))
                while bad.status not in {'done','error'} and time.monotonic()<end:time.sleep(.04)
                self.assertEqual(bad.status,'error')
                self.assertIn('DRM',bad.error)
            finally:manager.shutdown()

if __name__=='__main__':unittest.main()
