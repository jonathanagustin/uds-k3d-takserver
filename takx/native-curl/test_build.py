# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import time
import unittest
SPEC=importlib.util.spec_from_file_location('core_curl',Path(__file__).with_name('build.py'))
B=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(B)
class Guards(unittest.TestCase):
    def test_archive_refuses_links_and_traversal_before_output(self):
        for kind in ('link','traversal','duplicate'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as d:
                root=Path(d);archive=root/'x.tar'
                with tarfile.open(archive,'w') as tar:
                    item=tarfile.TarInfo('src/../outside' if kind=='traversal' else 'src/file')
                    if kind=='link':item.type=tarfile.SYMTYPE;item.linkname='/outside';tar.addfile(item)
                    else:
                        item.size=2;tar.addfile(item,io.BytesIO(b'xx'))
                        if kind=='duplicate':tar.addfile(item,io.BytesIO(b'xx'))
                lock={'bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'expanded_bytes':4 if kind=='duplicate' else 2}
                with self.assertRaises(ValueError):B.extract(archive,root/'out',lock)
                self.assertFalse((root/'out').exists())
    def test_owned_timeout_retains_diagnostic(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            with self.assertRaisesRegex(ValueError,'deadline'):
                B.execute([sys.executable,'-c','import time;print("retained",flush=True);time.sleep(5)'],root,'timeout',time.monotonic()+.2,dict(os.environ))
            self.assertIn(b'retained',(root/'timeout.log').read_bytes())
    def test_live_quota_survives_closed_stream_and_log_quota(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);code='import os,time;from pathlib import Path;os.close(1);os.close(2);Path('+repr(str(root/'payload'))+').write_bytes(b"x"*2048);time.sleep(5)'
            start=time.monotonic()
            with self.assertRaisesRegex(ValueError,'output bound'):
                B.execute([sys.executable,'-c',code],root,'disk',start+4,dict(os.environ),disk_limit=1024)
            self.assertLess(time.monotonic()-start,3)
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'log bound'):
                B.execute([sys.executable,'-c','print("x"*2000)'],Path(d),'log',time.monotonic()+2,dict(os.environ),log_limit=100)
    def test_disk_scan_does_not_follow_links(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'regular').write_bytes(b'123');(root/'link').symlink_to('/etc/hosts')
            self.assertEqual(B.disk(root),3)
if __name__=='__main__':unittest.main()
