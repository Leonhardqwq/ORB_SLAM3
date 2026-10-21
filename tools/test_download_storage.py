import tempfile
import unittest
from pathlib import Path
from fetch_euroc_member import ensure_storage_budget

class DownloadStorageTests(unittest.TestCase):
    def test_accounts_for_preceding_archive_and_extraction(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'first.zip').write_bytes(b'x'*40)
            (p/'first').mkdir();(p/'first/image.png').write_bytes(b'x'*60)
            ensure_storage_budget(p,50,150)
            with self.assertRaisesRegex(ValueError,'exceeded'):
                ensure_storage_budget(p,51,150)
            self.assertEqual((p/'first.zip').stat().st_size,40)
    def test_optional_and_invalid_limits(self):
        with tempfile.TemporaryDirectory() as d:
            ensure_storage_budget(d,100,None)
            for addition,budget in [(1,0),(1,-1),(-1,100)]:
                with self.subTest(addition=addition,budget=budget),self.assertRaises(ValueError):
                    ensure_storage_budget(d,addition,budget)

if __name__=='__main__':unittest.main()
