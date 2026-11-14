# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
import json
import copy
import importlib.util
from pathlib import Path
import os
import subprocess
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
HELPER=ROOT/'.github/scripts/velero-clean-completion.py'

def server_inventory():
    def meta(name,uid,kind=None,parent=None):
        value={'namespace':'velero','name':name,'uid':uid}
        if kind:value['ownerReferences']=[{'apiVersion':'apps/v1','kind':kind,'uid':parent,'controller':True}]
        return value
    return {'items':[
        {'kind':'Deployment','metadata':meta('velero','deployment')},
        {'kind':'ReplicaSet','metadata':meta('velero-rs','replica','Deployment','deployment')},
        {'kind':'Pod','metadata':meta('node-agent-first','agent','DaemonSet','agent-parent'),
         'status':{'phase':'Running'},'spec':{'containers':[{'name':'node-agent'}]}},
        {'kind':'Pod','metadata':meta('velero-server','server','ReplicaSet','replica'),
         'status':{'phase':'Running'},'spec':{'containers':[{'name':'velero'}]}}]}


class CleanCompletion(unittest.TestCase):
    def test_server_selection_follows_uids_not_overlapping_deployment_selector(self):
        spec=importlib.util.spec_from_file_location('server_pod',ROOT/'.github/scripts/velero-server-pod.py')
        helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
        fixture=server_inventory()
        self.assertEqual(helper.select(fixture),'velero-server')
        for mutate in (lambda v:v['items'].append(copy.deepcopy(v['items'][-1])),
                       lambda v:v['items'][1]['metadata']['ownerReferences'][0].update(uid='replacement'),
                       lambda v:v['items'][-1]['metadata'].update(deletionTimestamp='now'),
                       lambda v:v['items'][-1]['spec']['containers'][0].update(name='node-agent'),
                       lambda v:v['items'][-1]['metadata'].update(namespace='foreign'),
                       lambda v:v['items'][-1]['status'].update(phase='Pending')):
            bad=copy.deepcopy(fixture);mutate(bad)
            with self.assertRaises(ValueError):helper.select(bad)

    def test_server_selection_rejects_malformed_input_without_echoing_bodies(self):
        for data in ('PRIVATE_BODY','x'*(1024*1024+1),json.dumps({'items':[],'private':'PRIVATE_BODY'})):
            result=subprocess.run([sys.executable,str(ROOT/'.github/scripts/velero-server-pod.py')],input=data,
                                  capture_output=True,text=True,check=False)
            self.assertEqual(result.returncode,2)
            self.assertEqual(result.stderr,'Velero server pod selection unavailable\n')
            self.assertEqual(result.stdout,'')

    def test_failed_details_commands_keep_redacted_stderr(self):
        script=(ROOT/'tests/backup-restore.sh').read_text()
        start=script.index('velero_details() {');end=script.index('\n}\n',start)+3
        setup=r'''set -euo pipefail
k() {
  case "$*" in
    get\ deployment,replicaset,pod*) printf '%s' "$SERVER_INVENTORY" ;;
    *describe*) [[ "$*" == "exec -n velero pod/velero-server -c velero -- /velero "* ]] || return 77; echo 'describe transport failed password=PRIVATE_SENTINEL' >&2; return 1 ;;
    *backup\ logs*|*restore\ logs*) [[ "$*" == "exec -n velero pod/velero-server -c velero -- /velero "* ]] || return 77; echo "${LOG_PREFIX}logs transport failed password=PRIVATE_SENTINEL" >&2; return 1 ;;
    *) return 0 ;;
  esac
}
'''
        for verb in ('backup','restore'):
            for prefix in ('','level=error '):
                with self.subTest(verb=verb,prefix=prefix):
                    result=subprocess.run(['bash','-c',setup+script[start:end]+f'\nvelero_details {verb}.velero.io reviewed-{verb}'],
                                          env={**os.environ,'root':str(ROOT),'LOG_PREFIX':prefix,'SERVER_INVENTORY':json.dumps(server_inventory())},capture_output=True,text=True,check=False)
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertIn('describe transport failed password=[REDACTED]',result.stderr)
                    self.assertIn(prefix+'logs transport failed password=[REDACTED]',result.stderr)
                    self.assertIn('velero describe command or redaction failed',result.stderr)
                    self.assertIn('velero logs command or redaction failed',result.stderr)
                    self.assertNotIn('PRIVATE_SENTINEL',result.stdout+result.stderr)

    def test_real_helper_projects_only_fixed_status_facts(self):
        cases=[({'phase':'Completed'},0),({'phase':'Completed','warnings':2},1),
               ({'phase':'PartiallyFailed'},1),({'phase':'Completed','errors':1},1),
               ({'phase':'Completed','failureReason':'PRIVATE_PASSWORD'},1),
               ({'phase':'PRIVATE_PHASE'},1),({'phase':'Completed','errors':True},2)]
        for status,code in cases:
            with self.subTest(status=status):
                result=subprocess.run([sys.executable,str(HELPER)],input=json.dumps({'status':status,'metadata':{'name':'PRIVATE_NAME'}}),capture_output=True,text=True,check=False)
                self.assertEqual(result.returncode,code);self.assertNotIn('PRIVATE',result.stdout+result.stderr)
                value=json.loads(result.stdout);self.assertEqual(value['schema'],1)
        duplicate=subprocess.run([sys.executable,str(HELPER)],input=b'{"status":{"phase":"Failed","phase":"Completed"}}',capture_output=True,check=False)
        self.assertEqual(duplicate.returncode,2)
        oversized=subprocess.run([sys.executable,str(HELPER)],input=b'x'*(128*1024+1),capture_output=True,check=False)
        self.assertEqual(oversized.returncode,2)

    def test_real_wait_gate_keeps_default_and_runs_details_for_strict_warning(self):
        script=(ROOT/'tests/backup-restore.sh').read_text();start=script.index('wait_phase() {');end=script.index('\n}\n',start)+3
        function=script[start:end]
        setup='''set -euo pipefail
k() { case "$*" in *jsonpath*) echo Completed ;; *) printf '%s' "$FIXTURE" ;; esac; }
say() { :; }
velero_details() { echo DETAILS; }
'''
        for strict,warnings,expected,details in [('false',2,0,False),('true',0,0,False),('true',2,1,True)]:
            with self.subTest(strict=strict,warnings=warnings):
                env={**os.environ,'root':str(ROOT),'REQUIRE_CLEAN_BACKUP_RESTORE':strict,'FIXTURE':json.dumps({'status':{'phase':'Completed','warnings':warnings}})}
                result=subprocess.run(['bash','-c',setup+function+'\nwait_phase backup.velero.io reviewed-backup 1'],env=env,capture_output=True,text=True,check=False)
                self.assertEqual(result.returncode,expected,result.stderr);self.assertEqual('DETAILS' in result.stdout,details)

if __name__=='__main__':unittest.main()
