from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import Mock
import hashlib
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from updater import find_update,download_verified_update,APP_VERSION

class FakeResponse:
    def __init__(self, data=None, body=b''):
        self._data=data;self.content=body;self.text=body.decode('ascii','ignore')
    def json(self):return self._data
    def raise_for_status(self):pass
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def iter_content(self,chunk_size):yield self.content

class UpdaterTests(unittest.TestCase):
    def test_github_version_and_assets(self):
        session=Mock()
        session.get.return_value=FakeResponse({'tag_name':'v2.2.0','html_url':'https://github.com/u/r/releases/tag/v2.1.0','assets':[
            {'name':'MaherDownloader-Setup.exe','browser_download_url':'https://cdn.example/setup'},
            {'name':'MaherDownloader-Setup.exe.sha256','browser_download_url':'https://cdn.example/sha'}]})
        result=find_update('u/r',session=session)
        self.assertEqual(result['version'],'2.2.0')
        self.assertIsNone(find_update('u/r',current='2.2.0',session=session))
        with self.assertRaises(ValueError):find_update('u/r/../../bad',session=session)

    def test_sha256_verified(self):
        content=b'MZ' + b'\0'*250
        sha=hashlib.sha256(content).hexdigest()
        session=Mock()
        session.get.side_effect=[FakeResponse(body=sha.encode()),FakeResponse(body=content)]
        with TemporaryDirectory() as tmp:
            dest=download_verified_update({'checksum_url':'https://x/sha','url':'https://x/installer'},tmp,session=session)
            self.assertEqual(dest.read_bytes(),content)
            session.get.side_effect=[FakeResponse(body=b'0'*64),FakeResponse(body=content)]
            with self.assertRaises(ValueError):download_verified_update({'checksum_url':'https://x/sha','url':'https://x/installer'},tmp,session=session)

if __name__=='__main__':unittest.main()
