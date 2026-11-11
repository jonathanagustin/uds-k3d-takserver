# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
from pathlib import Path
import os
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('normalizer', HERE / 'normalize_la.py')
NORMALIZER = importlib.util.module_from_spec(spec)
spec.loader.exec_module(NORMALIZER)


class NormalizerControls(unittest.TestCase):
    def test_lf_is_byte_and_timestamp_identical(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'library.la'
            data = b"# library.la - a libtool library file\ndlname=''\n"
            p.write_bytes(data)
            before = p.stat()
            NORMALIZER.normalize(p)
            self.assertEqual(p.read_bytes(), data)
            self.assertEqual(p.stat().st_mtime_ns, before.st_mtime_ns)

    def test_actual_crlf_is_converted_without_other_text_changes(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'library.la'
            data = b"# library.la - a libtool library file\r\ndlname=''\r\n"
            p.write_bytes(data)
            NORMALIZER.normalize(p)
            self.assertEqual(p.read_bytes(), data.replace(b'\r\n', b'\n'))

    def test_binary_bare_cr_symlink_and_fifo_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for bad in (b'\x7fELF\x00', b'# libtool library file\nbinary=\x00', b'# libtool library file\rbare'):
                p = root / 'library.la'
                p.write_bytes(bad)
                with self.assertRaises((ValueError,UnicodeError)):
                    NORMALIZER.normalize(p)
                self.assertEqual(p.read_bytes(), bad)
            alias = root / 'alias.la'
            alias.symlink_to(p)
            with self.assertRaises(OSError):
                NORMALIZER.normalize(alias)
            fifo = root / 'pipe.la'
            os.mkfifo(fifo)
            with self.assertRaises(ValueError):
                NORMALIZER.normalize(fifo)


if __name__ == '__main__':
    unittest.main()
