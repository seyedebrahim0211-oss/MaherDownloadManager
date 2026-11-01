"""Local HTTP integration tests for byte ranges, persistence, and fallback."""
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import json
import sys
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from download_engine import DownloadManager,sanitize_name,category_for

CONTENT=bytes(((i*37+i//31)%251) for i in range(2*1024*1024+61))

class Handler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-Length',str(len(CONTENT)))
        self.send_header('ETag','"maher-test-v1"')
        self.end_headers()

    def do_GET(self):
        if self.path.startswith('/range') and self.headers.get('Range'):
            import re
            match=re.fullmatch(r'bytes=(\d+)-(\d+)',self.headers['Range'])
            if match:
                start,end=map(int,match.groups())
                if 0<=start<=end<len(CONTENT):
                    self.send_response(206)
                    self.send_header('Content-Length',str(end-start+1))
                    self.send_header('Content-Range',f'bytes {start}-{end}/{len(CONTENT)}')
                    self.send_header('Accept-Ranges','bytes')
                    self.send_header('ETag','"maher-test-v1"')
                    self.end_headers()
                    try:self.wfile.write(CONTENT[start:end+1])
                    except (BrokenPipeError,ConnectionResetError):pass
                    return
        self.send_response(200)
        self.send_header('Content-Length',str(len(CONTENT)))
        self.end_headers()
        try:self.wfile.write(CONTENT)
        except (BrokenPipeError,ConnectionResetError):pass

    def log_message(self,*args):pass


def waitfor(fn,seconds=15):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        if fn():return
        time.sleep(.04)
    raise AssertionError('Timed out')

class DownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.port=cls.server.server_address[1]
        cls.thread=Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close()

    def setUp(self):
        self.temp=TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.manager=DownloadManager(self.root/'state',connections=4,parallel=1)

    def tearDown(self):
        self.manager.shutdown()
        self.temp.cleanup()

    def test_multisegment_integrity_and_duplicate(self):
        url=f'http://127.0.0.1:{self.port}/range'
        job=self.manager.add(url,filename='example.zip',directory=str(self.root/'files'))
        waitfor(lambda:job.status in ('done','error'))
        self.assertEqual(job.status,'done',job.error)
        self.assertEqual(len(job.segments),4)
        self.assertEqual(job.dest.read_bytes(),CONTENT)
        with self.assertRaises(ValueError):self.manager.add(url)
        self.assertEqual(job.category,'فشرده')

    def test_nonrange_fallback_integrity(self):
        url=f'http://127.0.0.1:{self.port}/no-range'
        j=self.manager.add(url,filename='test.bin',directory=str(self.root/'files'))
        waitfor(lambda:j.status in ('done','error'))
        self.assertEqual(j.status,'done',j.error)
        self.assertFalse(j.ranged)
        self.assertEqual(j.dest.read_bytes(),CONTENT)

    def test_pause_and_persist_then_resume(self):
        url=f'http://127.0.0.1:{self.port}/range-pausable'
        j=self.manager.add(url,filename='paused.dat',directory=str(self.root/'files'),limit_kbps=256)
        waitfor(lambda:j.downloaded>50000,8)
        self.manager.pause(j.id)
        waitfor(lambda:not j._worker,8)
        offset=j.downloaded
        self.assertGreater(offset,0)
        self.manager.shutdown()
        self.manager=DownloadManager(self.root/'state',connections=4,parallel=1)
        reloaded=self.manager.find(j.id)
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded.downloaded,offset)
        self.assertEqual(reloaded.status,'paused')
        reloaded.limit_kbps=0
        self.manager.resume(reloaded.id)
        waitfor(lambda:reloaded.status in ('done','error'),15)
        self.assertEqual(reloaded.status,'done',reloaded.error)
        self.assertEqual(reloaded.dest.read_bytes(),CONTENT)

    def test_filename_protection(self):
        self.assertEqual(sanitize_name('..\\..\\CON.zip'),'_CON.zip')
        self.assertEqual(sanitize_name('my:file?.pdf'),'my_file_.pdf')
        self.assertEqual(category_for('whatever.mp4'),'ویدیو')

if __name__=='__main__':unittest.main()
