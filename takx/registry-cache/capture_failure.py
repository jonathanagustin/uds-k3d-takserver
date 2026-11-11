#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Export only complete, bounded, whole-stream-redacted native command logs."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import draco as local

HERE = Path(__file__).resolve().parent
MAX_LOG = 16*1024**2
MAX_TOTAL = 32*1024**2


def capture(root, output):
    if (output.exists() or output.is_symlink() or
            any(p.is_symlink() for p in [root,*root.parents])):
        raise ValueError('ordinary input and new sanitized output required')
    output.mkdir(parents=True)
    total, records = 0, []
    # Only logs emitted by producer.run, not arbitrary recursive source/build files.
    for scope in (root, root/'build'):
        if not scope.exists(): continue
        if scope.is_symlink(): raise ValueError('log scope symlink refused')
        statuses = sorted(scope.glob('*.status.json'))
        if len(statuses)>96: raise ValueError('too many native command logs')
        for path in statuses:
            name = path.name.removesuffix('.status.json')
            if not re.fullmatch('[a-z0-9-]+', name): raise ValueError('invalid native log name')
            status = local.load(path)
            log = scope/(name+'.log')
            record = {'scope':str(scope.relative_to(root)),'name':name,'exported':False}
            records.append(record)
            local.regular(log, scope)
            if (status.get('schema')!='uds-native-command-log-v1' or
                    status.get('complete') is not True or type(status.get('returncode')) is not int or
                    not 0<=status.get('bytes',-1)<=MAX_LOG or
                    status['bytes']!=log.stat().st_size or status.get('sha256')!=local.file_sha(log)):
                continue
            if total+status['bytes']>MAX_TOTAL: continue
            # Never filter/tail before redaction, and never expose raw stderr if
            # the sanitizer refuses the complete stream (NUL/non-UTF8 included).
            result = subprocess.run([sys.executable,str(local.ROOT/'.github/scripts/redact-logs.py'),
                                     '--stdout',str(log)],capture_output=True,timeout=30)
            if (result.returncode or len(result.stdout)>MAX_LOG or
                    total+len(result.stdout)>MAX_TOTAL): continue
            local.regular(log, scope)
            if log.stat().st_size!=status['bytes'] or local.file_sha(log)!=status['sha256']: continue
            target = output/((scope.name if scope!=root else 'host')+'-'+name+'.log')
            target.write_bytes(result.stdout)
            total += len(result.stdout)
            record.update(exported=True,returncode=status['returncode'],
                          sanitized_sha256=local.sha(result.stdout),bytes=len(result.stdout))
    (output/'index.json').write_bytes(local.canonical({'schema':'uds-native-failure-logs-v1',
                                                      'logs':records,'qualification':False}))
    print(f'Native diagnostics: exported {sum(r["exported"] for r in records)} complete redacted logs')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try: capture(args.input,args.output)
    except (OSError,ValueError,subprocess.SubprocessError):
        print('Native diagnostics omitted: capture or complete-stream redaction failed',file=sys.stderr)
        raise SystemExit(1) from None
