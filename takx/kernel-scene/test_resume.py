# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('kernel_scene_resume', HERE / 'resume.py')
RESUME = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RESUME)

spec2 = importlib.util.spec_from_file_location('kernel_only', HERE / 'kernel.py')
KERNEL = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(KERNEL)


class ResumeGuards(unittest.TestCase):
    def test_changed_or_extra_snapshot_input_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            old, snapshot = root / 'old', root / 'snapshot'
            old.mkdir(); snapshot.mkdir()
            (old / 'file').write_text('changed')
            (snapshot / 'file').write_text('original')
            manifest = root / 'manifest'
            import json
            manifest.write_text(json.dumps(RESUME.build.inventory(snapshot)))
            with patch.object(RESUME, 'SNAPSHOT_SHA', RESUME.build.native.digest(manifest)):
                with self.assertRaisesRegex(ValueError, 'changed or unknown'):
                    RESUME.verify_snapshot(old, snapshot, manifest)
            self.assertEqual((old / 'file').read_text(), 'changed')

    def test_truncated_relocatable_object_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'file.o'
            header = struct.pack('<16sHHIQQQIHHHHHH', b'\x7fELF\x02\x01'+b'\0'*10,
                                 1,62,1,0,0,64,0,64,0,0,64,1,0)
            section = struct.pack('<IIQQQQIIQQ',0,1,0,0,128,16,0,0,1,0)
            path.write_bytes(header+section+b'x'*16)
            self.assertTrue(RESUME.relocatable(path))
            path.write_bytes((header+section+b'x'*16)[:-1])
            self.assertFalse(RESUME.relocatable(path))

    def test_only_owned_incomplete_and_last_compile_outputs_selected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'partial.o').write_bytes(b'partial')
            (root / 'partial.lo').write_text('libtool')
            (root / 'source.cpp').write_text('unchanged source')
            _, remove = RESUME.object_audit(root, 'cc -c -o ../o/partial.lo partial.cpp ')
            self.assertEqual(set(remove), {'partial.o','partial.lo'})
            self.assertEqual((root / 'source.cpp').read_text(),'unchanged source')
            self.assertTrue((root / 'partial.o').exists())  # Audit never mutates.

    def test_archive_contract_hashes_actual_members_and_rejects_truncation(self):
        import hashlib
        from collections import Counter
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'lib.a'
            payload=b'\x7fELF\x02\x01'+b'actual object bytes'
            header=(b'member.o/'.ljust(16)+b'0'.ljust(12)+b'0'.ljust(6)+b'0'.ljust(6)+
                    b'100644'.ljust(8)+str(len(payload)).encode().ljust(10)+b'`\n')
            data=b'!<arch>\n'+header+payload+(b'\n' if len(payload)%2 else b'')
            p.write_bytes(data)
            self.assertEqual(KERNEL.archive_members(p),Counter([hashlib.sha256(payload).hexdigest()]))
            p.write_bytes(data[:-2])
            with self.assertRaises(ValueError): KERNEL.archive_members(p)

    def test_foreign_provider_and_missing_actual_core_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            library, core, foreign = root/'own.so', root/'assimp.so', root/'foreign.so'
            for path in (library,core,foreign): path.write_bytes(b'fixture')
            text = f'provider={library}\nprovider={core}\n'
            self.assertEqual(len(RESUME.build.runtime_providers(text,library,core)),2)
            with self.assertRaises(ValueError):
                RESUME.build.runtime_providers(text+f'provider={foreign}\n',library,core)
            with self.assertRaises(ValueError):
                RESUME.build.runtime_providers(f'provider={library}\n',library,core)


if __name__ == '__main__':
    unittest.main()
