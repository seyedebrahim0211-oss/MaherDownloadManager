from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime, timezone, timedelta
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from i18n import tr, TRANSLATIONS, localize_error, FILTER_KEYS, STATUS_KEYS
from themes import THEMES, THEME_LABELS
from update_policy import is_update_check_due
from download_engine import DownloadManager

class I18NSettingsTests(unittest.TestCase):
    def test_all_translations(self):
        for key, pair in TRANSLATIONS.items():
            self.assertEqual(len(pair),2,key)
            self.assertTrue(tr(key,'fa',version='2.1.0',count=2,name='x',done='2 MB',total='5 MB',active=2,speed='4 MB'),key)
            self.assertTrue(tr(key,'en',version='2.1.0',count=2,name='x',done='2 MB',total='5 MB',active=2,speed='4 MB'),key)
        for key in FILTER_KEYS+list(STATUS_KEYS.values()):
            self.assertIn(key,TRANSLATIONS)
        self.assertEqual(set(THEME_LABELS),set(THEMES))
        self.assertEqual(len(set(x['en'] for x in THEME_LABELS.values())),4)
        self.assertIn('already',localize_error(ValueError('این پیوند قبلاً به فهرست دانلود اضافه شده است.'),'en'))

    def test_settings_persist_without_changing_download_categories(self):
        with TemporaryDirectory() as folder:
            m=DownloadManager(app_dir=folder)
            m.configure(language='en',theme='نگار ایرانی',auto_check_updates=False,auto_download_updates=False,
                        last_update_check='2026-11-01T10:00:00+00:00')
            token=m.pairing_token
            m.shutdown()
            m2=DownloadManager(app_dir=folder)
            self.assertEqual(m2.language,'en')
            self.assertEqual(m2.theme,'نگار ایرانی')
            self.assertFalse(m2.auto_check_updates)
            self.assertFalse(m2.auto_download_updates)
            self.assertEqual(m2.pairing_token,token)
            self.assertTrue(m2.last_update_check.startswith('2026-11-01'))
            with self.assertRaises(ValueError):m2.configure(language='xx')
            m2.shutdown()

    def test_update_check_schedule(self):
        now=datetime(2026,11,1,12,0,tzinfo=timezone.utc)
        self.assertTrue(is_update_check_due('',now=now))
        self.assertFalse(is_update_check_due((now-timedelta(hours=23)).isoformat(),now=now))
        self.assertTrue(is_update_check_due((now-timedelta(hours=24)).isoformat(),now=now))
        self.assertTrue(is_update_check_due('invalid',now=now))

if __name__=='__main__':unittest.main()
