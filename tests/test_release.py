import re
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from updater import APP_VERSION
from release_config import RELEASE_REPOSITORY

class ReleaseConfigurationTests(unittest.TestCase):
    def test_release_version_matches_installer(self):
        path=Path(__file__).resolve().parents[1]/'installer'/'MaherDownloader.iss'
        content=path.read_text(encoding='utf-8')
        version=re.search(r'#define MyAppVersion "([^\"]+)"',content)
        self.assertIsNotNone(version)
        self.assertEqual(version.group(1),APP_VERSION)
        self.assertRegex(RELEASE_REPOSITORY,r'^[\w.-]+/[\w.-]+$')
if __name__=='__main__':unittest.main()
