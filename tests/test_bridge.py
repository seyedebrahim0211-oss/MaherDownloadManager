import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import requests
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from browser_bridge import start_bridge
from download_engine import DownloadManager

class BrowserBridgeTests(unittest.TestCase):
    def test_local_origin_gate_and_pairing(self):
        with TemporaryDirectory() as tmp:
            manager=DownloadManager(Path(tmp)/'state')
            server=start_bridge(manager,0)
            self.assertIsNotNone(server)
            url=f'http://127.0.0.1:{server.server_address[1]}'
            try:
                r=requests.get(url+'/health',timeout=4)
                self.assertEqual(r.status_code,403)
                bad=requests.post(url+'/add',headers={'Origin':'https://evil.example','X-Maher-Token':manager.pairing_token},json={'url':'https://example.com/f.zip'},timeout=4)
                self.assertEqual(bad.status_code,403)
                wrong=requests.post(url+'/add',headers={'Origin':'chrome-extension://testing123','X-Maher-Token':'wrong'},json={'url':'https://example.com/f.zip'},timeout=4)
                self.assertEqual(wrong.status_code,403)
                good=requests.post(url+'/add',headers={'Origin':'chrome-extension://testing123','X-Maher-Token':manager.pairing_token},json={'url':'https://example.com/f.zip'},timeout=4)
                self.assertEqual(good.status_code,200,good.text)
                self.assertEqual(len(manager.jobs),1)
                self.assertEqual(requests.get(url+'/health',headers={'Origin':'moz-extension://browser123','X-Maher-Token':manager.pairing_token},timeout=4).status_code,200)
            finally:
                server.shutdown();server.server_close();manager.shutdown()

if __name__=='__main__':unittest.main()
