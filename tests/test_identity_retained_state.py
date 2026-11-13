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
    def record(self,obj):
        rec=R.resource_record(obj);rec['origin']={'sourceFilesSHA256':R.source_files(),**{key:'a'*64 for key in ('storedHooksSHA256','sourceGeneratorJobSHA256','keystoreHookSHA256')}};return rec
    def driver(self,obj):
        client={'clusters':[{'cluster':{'server':'https://127.0.0.1:6443','certificate-authority-data':'Zml4dHVyZQ=='}}],
                'users':[{'user':{'client-certificate-data':'Zml4dHVyZQ==','client-key-data':'Zml4dHVyZQ=='}}]}
        return SimpleNamespace(guard=lambda:None,core_unchanged=lambda:None,
            get=lambda *a,**k:{'items':[]},kube=lambda *a:'{}' if a[1]=='namespace' else json.dumps(obj),command=lambda argv:json.dumps(client))
    def test_delete_sends_actual_uid_and_resourceversion_preconditions(self):
        obj=self.secret();rec=self.record(obj);driver=self.driver(obj);opener=MagicMock();opener.open.return_value.__enter__.return_value.status=200
        with patch.object(R.ssl,'create_default_context',return_value=MagicMock()),patch.object(R.urllib.request,'build_opener',return_value=opener):R.conditional_delete(driver,rec)
        request=opener.open.call_args.args[0]
        self.assertEqual(request.get_method(),'DELETE');self.assertEqual(request.full_url,'https://127.0.0.1:6443/api/v1/namespaces/takserver/secrets/takserver-keystore')
        self.assertEqual(json.loads(request.data)['preconditions'],{'uid':'original','resourceVersion':'7'})
    def test_changed_uid_or_resourceversion_refuses_before_client_or_http(self):
        for field in ('uid','resourceVersion'):
            obj=self.secret();rec=self.record(obj);obj['metadata'][field]='replacement';driver=self.driver(obj)
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
        with self.assertRaisesRegex(ValueError,'still has consumers'):R.conditional_delete(driver,self.record(obj))
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

    def test_startup_cleanup_requires_literal_source_checkpoint(self):
        obj={'kind':'ConfigMap','metadata':{'name':'takserver-startup','namespace':'takserver','uid':'startup','resourceVersion':'1','annotations':{'uds.dev/tak-startup':'complete'}},'data':{'ready':'true'}}
        R.startup_map(obj);self.assertTrue(R.cleanup_allowed(R.resource_record(obj)))
        for mutate in [lambda x:x['data'].update(private='foreign'),lambda x:x['metadata']['annotations'].update({'uds.dev/tak-startup':'other'}),lambda x:x.update(binaryData={'other':'payload'})]:
            altered=copy.deepcopy(obj);mutate(altered)
            with self.assertRaisesRegex(ValueError,'literal source'):R.startup_map(altered)

    def trust(self,name='istio-ca-root-cert'):
        source={'kind':'ConfigMap','metadata':{'name':name,'namespace':'istio-system','uid':'core-map','resourceVersion':'1'},'data':{'root-cert.pem':'public authority'}}
        obj={'kind':'ConfigMap','metadata':{'name':name,'namespace':'takserver','uid':'app-map','resourceVersion':'2','labels':{'istio.io/config':'true'}},'data':{'root-cert.pem':'public authority'}}
        driver=SimpleNamespace(get=lambda *a,**k:source)
        return obj,source,driver

    def test_core_trust_is_preserved_only_with_bound_uid_data_and_source(self):
        obj,source,driver=self.trust();rec=R.trust_binding(driver,obj)
        obj['metadata']['resourceVersion']='3'  # A harmless controller observation update.
        self.assertTrue(R.preserved_trust(driver,obj,[rec]))
        for mutate in [lambda x:x['metadata'].update(uid='replacement'),lambda x:x['data'].update({'root-cert.pem':'different'}),lambda x:x['metadata']['labels'].update({'istio.io/config':'false'})]:
            changed=copy.deepcopy(obj);mutate(changed)
            with self.assertRaises(ValueError):R.preserved_trust(driver,changed,[rec])
        source['metadata']['uid']='different-core'
        with self.assertRaisesRegex(ValueError,'Core trust authority'):R.preserved_trust(driver,obj,[rec])

    def test_trust_name_cannot_mask_extra_payload_or_wrong_source_marker(self):
        obj,source,driver=self.trust()
        for mutate in [lambda x:x['data'].update(other='private payload'),lambda x:x['metadata']['labels'].clear(),lambda x:x.update(binaryData={'private':'payload'})]:
            changed=copy.deepcopy(obj);mutate(changed)
            with self.assertRaises(ValueError):R.trust_binding(driver,changed)
        with self.assertRaises(ValueError):R.preserved_trust(driver,obj,[])

    def test_operator_bundle_requires_actual_application_package_owner(self):
        source={'metadata':{'uid':'core-bundle'},'data':{'extra.pem':'public bundle'}}
        obj={'kind':'ConfigMap','metadata':{'name':'uds-trust-bundle','namespace':'takserver','uid':'bundle','resourceVersion':'3','labels':{'uds/package':'takserver','uds/ca-bundle':'true'},'ownerReferences':[{'kind':'Package','uid':'app-package'}]},'data':{'ca-bundle.pem':'public bundle'}}
        driver=SimpleNamespace(get=lambda kind,*a,**k:({'metadata':{'uid':'app-package'}} if kind=='package' else source))
        rec=R.trust_binding(driver,obj);self.assertEqual(rec['sourceUID'],'core-bundle')
        obj['metadata']['ownerReferences'][0]['uid']='foreign'
        with self.assertRaisesRegex(ValueError,'Package owner'):R.trust_binding(driver,obj)

    def test_cloudtak_admin_copy_and_enrollment_cache_keep_exact_source_scope(self):
        parents={'configmap':{'binaryData':{'ca.pem':'ca','admin.pem':'cert'}},'secret':{'data':{'CAPASS':'pass'}}}
        driver=SimpleNamespace(get=lambda kind,*a,**k:parents[kind],kube=lambda *a:json.dumps({'data':{'admin.key':'key'}}))
        obj={'kind':'Secret','metadata':{'name':'cloudtak-tak-admin','namespace':'cloudtak','labels':{'app.kubernetes.io/part-of':'cloudtak'}},'data':{'ca.pem':'ca','admin.pem':'cert','admin.key':'key','CAPASS':'pass'}}
        self.assertTrue(R.generated_secret(driver,obj));self.assertTrue(R.cleanup_allowed({'namespace':'cloudtak','kind':'Secret','name':'cloudtak-tak-admin'}))
        obj['data']['CAPASS']='other'
        with self.assertRaisesRegex(ValueError,'source credentials'):R.generated_secret(driver,obj)
        enrollment={'metadata':{'name':'takclient-enrollment','namespace':'takserver','labels':{'app.kubernetes.io/managed-by':'takserver-oidc'}},'data':{}}
        self.assertTrue(R.generated_secret(None,enrollment))
        with self.assertRaisesRegex(ValueError,'active client'):
            R.generated_secret(SimpleNamespace(get=lambda *a,**k:{'items':[{'metadata':{'name':'active'}}]}),enrollment,cleanup=True)
        enrollment['metadata']['labels'].clear()
        with self.assertRaisesRegex(ValueError,'source label'):R.generated_secret(None,enrollment)

    def test_unbound_or_changed_source_origin_refuses_before_delete_client(self):
        obj=self.secret();driver=self.driver(obj);driver.command=lambda *a:self.fail('delete client must not be read')
        with self.assertRaisesRegex(ValueError,'bound source origin'):R.conditional_delete(driver,R.resource_record(obj))
        rec=self.record(obj);rec['origin']['sourceFilesSHA256']={}
        with self.assertRaisesRegex(ValueError,'bound source origin'):R.conditional_delete(driver,rec)
