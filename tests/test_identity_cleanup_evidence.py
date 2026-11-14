# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Private cleanup inventory rejects unrelated bodies and ambiguous records."""
import copy
import unittest
from tests.test_package_identity_driver import P

class ConsumerEvidence(unittest.TestCase):
    def fixture(self):
        return {'schema':1,'consumers':[{'kind':'Pod','namespace':'takserver','name':'remaining',
            'uid':'bound-uid','resourceVersion':'123','deleting':True,'phase':'Succeeded',
            'owners':[{'apiVersion':'batch/v1','kind':'Job','name':'hook','uid':'job-uid'}]}]}

    def test_terminal_and_deleting_pods_remain_consumers(self):
        value=self.fixture()
        self.assertEqual(P.R.validate_consumer_failure(value),value)
        driver=type('Driver',(),{'kube':lambda *_:'present',
            'get':lambda _,kind,namespace:{'items':[{'kind':'Pod','metadata':{
                'name':'remaining','namespace':namespace,'uid':'bound-uid','resourceVersion':'123',
                'deletionTimestamp':'now','annotations':{'private':'never exported'}},
                'status':{'phase':'Succeeded'},'spec':{'containers':[{'env':['private']}]}}]
                if kind=='pods' else []}})()
        result=P.R.consumer_failure(driver)
        self.assertEqual(len(result['consumers']),2)
        self.assertNotIn('private',str(result))
        with self.assertRaisesRegex(ValueError,'still has consumers'):P.R.consumers_gone(driver)

    def test_reject_empty_foreign_duplicate_and_payload_fields(self):
        mutations=[lambda v:v.update(consumers=[]),
            lambda v:v['consumers'][0].update(namespace='istio-system'),
            lambda v:v['consumers'].append(copy.deepcopy(v['consumers'][0])),
            lambda v:v['consumers'][0].update(spec={}),
            lambda v:v['consumers'][0]['owners'][0].update(secret='private'),
            lambda v:v['consumers'][0].update(phase='arbitrary'),
            lambda v:v['consumers'][0].update(uid='x'*254),
            lambda v:v.update(schema=True)]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                value=self.fixture();mutate(value)
                with self.assertRaises(ValueError):P.R.validate_consumer_failure(value)
