#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Fixed completion facts only, for the strict ownership experiment."""
import json
import sys

LIMIT=128*1024
PHASES=frozenset(('New','FailedValidation','InProgress','WaitingForPluginOperations',
                  'WaitingForPluginOperationsPartiallyFailed','FinalizingafterPluginOperations',
                  'Finalizing','Completed','PartiallyFailed','Failed','Deleting'))


def project(value):
    status=value.get('status') if isinstance(value,dict) else None
    if not isinstance(status,dict):raise ValueError('status schema')
    def count(name):
        value=status.get(name,0)
        if type(value) is not int or not 0<=value<=2**31-1:raise ValueError('count schema')
        return value
    phase=status.get('phase')
    return {'phase':phase if isinstance(phase,str) and phase in PHASES else 'other',
            'errors':count('errors'),'warnings':count('warnings'),
            'failure_reason_present':bool(status.get('failureReason'))}


def unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate field')
        result[key]=value
    return result


def main():
    try:
        raw=sys.stdin.buffer.read(LIMIT+1)
        if len(raw)>LIMIT:raise ValueError('input bound')
        result=project(json.loads(raw,object_pairs_hook=unique));result['schema']=1
        clean=(result['phase']=='Completed' and result['errors']==0 and result['warnings']==0 and not result['failure_reason_present'])
        result['clean']=clean
        print(json.dumps(result,sort_keys=True))
        return 0 if clean else 1
    except (ValueError,TypeError,UnicodeError,OverflowError,RecursionError):
        print('{"schema":1,"clean":false,"diagnostic":"invalid-status"}')
        return 2


if __name__=='__main__':raise SystemExit(main())
