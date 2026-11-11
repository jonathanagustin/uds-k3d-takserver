# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('cesium_acquire',HERE/'acquire.py')
ACQUIRE=importlib.util.module_from_spec(spec);spec.loader.exec_module(ACQUIRE)


class SourceGuards(unittest.TestCase):
    def test_expansion_budget_precedes_materialization(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);archive=root/'test.tar'
            with tarfile.open(archive,'w') as tar:
                member=tarfile.TarInfo('source/file');member.size=2;tar.addfile(member,io.BytesIO(b'xx'))
            budget={'expanded':ACQUIRE.EXPANDED-1}
            with self.assertRaises(ValueError):ACQUIRE.extract(archive,root/'out',budget)
            self.assertFalse((root/'out').exists())

    def test_pinned_git_blob_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);archive=root/'test.tar'
            with tarfile.open(archive,'w') as tar:
                member=tarfile.TarInfo('source/file');member.size=2;tar.addfile(member,io.BytesIO(b'xx'))
            with self.assertRaises(ValueError):
                ACQUIRE.extract(archive,root/'out',{'expanded':0},{'file':{'sha':'0'*40,'size':2}})

    def test_ktx_exception_refuses_other_targets_and_wrong_license(self):
        for target in ('../LICENSE.md','other.md','LICENSE.md'):
            with self.subTest(target=target),tempfile.TemporaryDirectory() as d:
                root=Path(d);archive=root/'test.tar'
                with tarfile.open(archive,'w') as tar:
                    member=tarfile.TarInfo('source/LICENSE.md');member.size=2;tar.addfile(member,io.BytesIO(b'xx'))
                    member=tarfile.TarInfo('source/NOTICE.md');member.type=tarfile.SYMTYPE;member.linkname=target;tar.addfile(member)
                with self.assertRaises(ValueError):
                    ACQUIRE.extract(archive,root/'out',{'expanded':0},allow_ktx_notice=True)
                self.assertFalse((root/'out').exists())

    def test_exact_zstd_test_links_materialize_without_symlinks(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);links={};archive=root/'zstd.tar'
            wrapper=b'#!/bin/sh\n\nzstdname=$(basename $0)\n\nif [ -z "$EXEC_PREFIX" ]; then\n    "$ZSTD_SYMLINK_DIR/$zstdname" $@\nelse\n    $EXEC_PREFIX "$ZSTD_SYMLINK_DIR/$zstdname" $@\nfi\n'
            with tarfile.open(archive,'w') as tar:
                target=tarfile.TarInfo('source/tests/cli-tests/bin/zstd');target.size=len(wrapper);tar.addfile(target,io.BytesIO(wrapper))
                for name in ('unzstd','zstdcat'):
                    link=tarfile.TarInfo('source/tests/cli-tests/bin/'+name);link.type=tarfile.SYMTYPE;link.linkname='zstd';tar.addfile(link)
            result=ACQUIRE.extract(archive,root/'out',{'expanded':0},allow_zstd_tests=True,source_links=links)
            self.assertEqual(set(links),{'tests/cli-tests/bin/unzstd','tests/cli-tests/bin/zstdcat'})
            for name in links:
                self.assertFalse((root/'out'/name).is_symlink())
                self.assertEqual((root/'out'/name).read_bytes(),(root/'out/tests/cli-tests/bin/zstd').read_bytes())
                self.assertEqual(result[name],links[name]['materialized_postimage'])

    def test_source_links_and_traversal_are_refused(self):
        for name,link in [('source/../outside',False),('source/link',True)]:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as d:
                root=Path(d);archive=root/'test.tar'
                with tarfile.open(archive,'w') as tar:
                    member=tarfile.TarInfo(name)
                    if link:member.type=tarfile.SYMTYPE;member.linkname='/outside';tar.addfile(member)
                    else:member.size=1;tar.addfile(member,io.BytesIO(b'x'))
                with self.assertRaises(ValueError):ACQUIRE.extract(archive,root/'out',{'expanded':0})
                self.assertFalse((root/'out').exists())


if __name__=='__main__':unittest.main()
