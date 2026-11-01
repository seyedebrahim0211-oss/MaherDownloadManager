"""Bilingual desktop asset and shaping invariants (no graphical session required)."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_support import shape
from i18n import tr
from updater import APP_VERSION

ROOT = Path(__file__).resolve().parents[1]

class DesktopUITests(unittest.TestCase):
    def test_persian_visual_forms(self):
        converted = shape('همه دانلودها')
        self.assertTrue(converted)
        self.assertNotEqual(converted, 'همه دانلودها')
        self.assertTrue(any('\uFB50' <= ch <= '\uFEFF' for ch in converted))

    def test_english_not_reordered(self):
        self.assertEqual(shape('Maher Downloader 2.2'), 'Maher Downloader 2.2')

    def test_idm_toolbar_icons(self):
        for icon in ('brand','add','resume','pause','allpause','remove','schedule','folder','settings','update'):
            with self.subTest(icon=icon):
                p = ROOT / 'assets' / 'ui' / (icon + '.png')
                self.assertTrue(p.exists(), str(p))
                self.assertGreater(p.stat().st_size, 100)

    def test_bilingual_menu_and_table_columns(self):
        for key in ('menu_file','menu_downloads','menu_view','menu_tools','menu_help',
                    'toolbar_add','toolbar_schedule','sidebar_categories','added','description','status_summary'):
            self.assertTrue(tr(key,'fa',total=1,active=0,done=1,speed='1 MB'), key)
            self.assertTrue(tr(key,'en',total=1,active=0,done=1,speed='1 MB'), key)

    def test_release_version_and_installer(self):
        self.assertEqual(APP_VERSION,'2.2.1')
        self.assertIn('#define MyAppVersion "2.2.1"',(ROOT/'installer'/'MaherDownloader.iss').read_text(encoding='utf-8'))

if __name__ == '__main__':unittest.main()
