# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline exact-cleanup request guards; never cluster/data deletion."""
import base64
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock,patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('retained',ROOT/'tests/workload-identities/retained_state.py')
R=importlib.util.module_from_spec(spec);spec.loader.exec_module(R)

class RetainedStateGuards(unittest.TestCase):
    def secret(self,name='takserver-keystore'):
        return {'kind':'Secret','metadata':{'name':name,'namespace':'takserver','uid':'original','resourceVersion':'7','annotations':{'helm.sh/hook-delete-policy':'before-hook-creation'}},'data':{'CAPASS':'Zml4dHVyZQ=='}}
    def driver(self,obj):
        client={'clusters':[{'cluster':{'server':'https://127.0.0.1:6443','certificate-authority-data':'Zml4dHVyZQ=='}}],
                'users':[{'user':{'client-certificate-data':'Zml4dHVyZQ==','client-key-data':'Zml4dHVyZQ=='}}]}
        return SimpleNamespace(guard=lambda:None,core_unchanged=lambda:None,
            get=lambda *a,**k:{'items':[]},kube=lambda *a:'{}' if a[1]=='namespace' else json.dumps(obj),command=lambda argv:json.dumps(client))
    def test_delete_sends_actual_uid_and_resourceversion_preconditions(self):
        obj=self.secret();rec=R.resource_record(obj);driver=self.driver(obj);opener=MagicMock();opener.open.return_value.__enter__.return_value.status=200
        with patch.object(R.ssl,'create_default_context',return_value=MagicMock()),patch.object(R.urllib.request,'build_opener',return_value=opener):R.conditional_delete(driver,rec)
        request=opener.open.call_args.args[0]
        self.assertEqual(request.get_method(),'DELETE');self.assertEqual(request.full_url,'https://127.0.0.1:6443/api/v1/namespaces/takserver/secrets/takserver-keystore')
        self.assertEqual(json.loads(request.data)['preconditions'],{'uid':'original','resourceVersion':'7'})
    def test_changed_uid_or_resourceversion_refuses_before_client_or_http(self):
        for field in ('uid','resourceVersion'):
            obj=self.secret();rec=R.resource_record(obj);obj['metadata'][field]='replacement';driver=self.driver(obj)
            driver.command=lambda argv:self.fail('client configuration must not be read')
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'identity/metadata'):R.conditional_delete(driver,rec)
    def test_foreign_scope_unknown_secret_and_unproven_pvc_refuse(self):
        for rec in [{'namespace':'kube-system','kind':'Secret','name':'takserver-keystore'},
                    {'namespace':'takserver','kind':'Secret','name':'foreign'},
                    {'namespace':'takserver','kind':'PersistentVolumeClaim','name':'data-foreign'}]:
            with self.subTest(rec=rec),self.assertRaisesRegex(ValueError,'outside exact'):R.conditional_delete(None,rec)
    def test_live_consumer_refuses_retained_data_cleanup(self):
        obj=self.secret();driver=self.driver(obj);driver.get=lambda *a,**k:{'items':[{'metadata':{'name':'live'}}]}
        driver.command=lambda argv:self.fail('must not construct delete client with live consumers')
        with self.assertRaisesRegex(ValueError,'still has consumers'):R.conditional_delete(driver,R.resource_record(obj))
    def test_only_known_recreated_hook_can_change_uid_with_stable_data(self):
        for name,recreated in [('takserver-keystore',True),('database',False)]:
            obj=self.secret(name);rec=R.resource_record(obj);rec.update(dataSHA256=R.sha(obj['data']),recreatedHook=recreated)
            obj['metadata']['uid']='new-hook';driver=SimpleNamespace(get=lambda *a,**k:obj)
            with patch.object(R,'hooks',return_value={}):
                if recreated:R.verify(driver,{'source':{},'records':[rec]})
                else:
                    with self.assertRaisesRegex(ValueError,'replaced'):R.verify(driver,{'source':{},'records':[rec]})
    def test_changed_hook_password_is_not_accepted_as_recreation(self):
        obj=self.secret();rec=R.resource_record(obj);rec.update(dataSHA256=R.sha(obj['data']),recreatedHook=True);obj['data']['CAPASS']='Y2hhbmdlZA=='
        with patch.object(R,'hooks',return_value={}),self.assertRaisesRegex(ValueError,'credential/certificate'):
            R.verify(SimpleNamespace(get=lambda *a,**k:obj),{'source':{},'records':[rec]})
