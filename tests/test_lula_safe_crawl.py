# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Run actual published-and-patched Lula analysis against an in-memory API."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("patch_crawl", ROOT / ".github/lula/patch_crawl.py")
PATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCH)
OFFICIAL = ROOT / ".github/lula/official/crawl-0.9.5.js"

HARNESS = r'''
const vm = require('node:vm');
const crypto = require('node:crypto');
const fs = require('node:fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const events = [];
const contentRefs = [];
const bot = {id:41898282, login:'github-actions[bot]', type:'Bot'};
const prefix = '<!-- LULA_SIGNATURE:v1 -->\n## Lula Compliance Overview\n';
const own = id => ({id,user:bot,body:prefix+'old'});
const comments = [
  own(1), own(2),
  {id:3,user:{id:7,login:'human',type:'User'},body:prefix+'quoted'},
  {id:4,user:{id:8,login:'other[bot]',type:'Bot'},body:prefix+'other'},
  {id:5,user:bot,body:'quoted '+prefix},
  {id:6,user:{...bot,id:9},body:prefix},
  {id:7,user:{...bot,login:'other[bot]'},body:prefix},
  {id:8,user:{...bot,type:'User'},body:prefix},
  own(99), own(100)
];
const block = '<!-- @lulaStart aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa -->\nVALUE\n<!-- @lulaEnd aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa -->';
const expected = {repository:'owner/repo',baseSHA:'b'.repeat(40),headSHA:'a'.repeat(40),changedFiles:1};
let prReads = 0;
const api = {
  pulls:{
    get:async()=>{
      prReads++;
      const data={state:'open',draft:false,changed_files:1,
        head:{ref:'topic',sha:expected.headSHA,repo:{full_name:'owner/repo'}},
        base:{ref:'main',sha:expected.baseSHA}};
      if(input.mode==='race' && prReads>1) data.head.sha='c'.repeat(40);
      if(input.mode==='fork') data.head.repo.full_name='fork/repo';
      if(input.mode==='draft') data.draft=true;
      if(input.mode==='closed') data.state='closed';
      if(input.mode==='other-base') data.base.ref='other';
      if(input.mode==='oversize') data.changed_files=31;
      return {data};
    },
    listFiles:async()=>({data:input.mode==='incomplete'?[]:[{filename:'mapped.xml',status:input.mode==='deleted'?'removed':'modified'}]})
  },
  repos:{getContent:async({ref})=>{
    contentRefs.push(ref);
    if (ref !== expected.baseSHA && ref !== expected.headSHA) throw Error('Non-SHA content reference');
    const side=ref===expected.headSHA?'head':'base';
    events.push('read:'+side);
    if (input.mode==='partial' && side==='head' || input.mode==='deleted') throw Error('API read failed');
    return {data:block.replace('VALUE',side==='head' && input.mode!=='none'?'NEW':'OLD')};
  }},
  issues:{
    createComment:async()=>{
      events.push('create');
      if(input.mode==='create-failure') throw Error('create failed');
      return {data:{id:99,user:input.mode==='wrong-identity'?{...bot,id:7}:bot}};
    },
    listComments:async({page})=>{
      events.push('list:'+page);
      return {data:page===1?comments:[]};
    },
    deleteComment:async({comment_id})=>events.push('delete:'+comment_id)
  }
};
let action;
class Command {
  command(){return this;} description(){return this;} addOption(){return this;}
  action(fn){action=fn;return this;}
}
class Option {choices(){return this;}default(){return this;}}
const context = {fs,createHash:crypto.createHash,Command,Option,
  Octokit:function(){return api;},
  process:{env:{OWNER:'owner',REPO:'repo',PULL_NUMBER:'1',LULA_PREFLIGHT_JSON:JSON.stringify(expected)}},
  console:{log(){},error(){}}
};
// Remove only static dependency imports/exports; all official analysis and the
// actual patched command/cleanup functions execute unchanged in this fixture.
const executable=input.source.replace(/^import .*;\n/gm,'').replace(/export \{[\s\S]*?\};\s*$/,'');
vm.runInNewContext(executable+'\ncrawlCommand();',context);
(async()=>{
  let failed=false;
  try {await action({postMode:input.mode==='review'?'review':'comment'});} catch {failed=true;}
  process.stdout.write(JSON.stringify({failed,events,contentRefs}));
})();
'''


class SafeCrawl(unittest.TestCase):
    def test_fixtures_are_unconditionally_wired_into_read_only_validation(self):
        import yaml
        workflow = yaml.safe_load((ROOT / ".github/workflows/lula.yaml").read_text())
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        job = workflow["jobs"]["mappings"]
        self.assertNotIn("if", job)
        steps = [step for step in job["steps"] if "tests.test_lula_safe_crawl" in step.get("run", "")]
        self.assertEqual(len(steps), 1)
        self.assertNotIn("if", steps[0])

    def run_case(self, mode):
        result = subprocess.run(["node", "-e", HARNESS], input=json.dumps({
            "mode": mode, "source": PATCH.patch_source(OFFICIAL.read_text())}),
            text=True, capture_output=True, check=True, timeout=10)
        return json.loads(result.stdout)

    def test_only_old_own_comments_deleted_after_successful_replacement(self):
        result = self.run_case("changed")
        self.assertFalse(result["failed"])
        self.assertEqual(result["contentRefs"], ["b" * 40, "a" * 40])
        self.assertEqual([e for e in result["events"] if e.startswith("delete:")], ["delete:1", "delete:2"])
        self.assertLess(result["events"].index("create"), result["events"].index("delete:1"))
        self.assertLess(result["events"].index("list:2"), result["events"].index("delete:1"))

    def test_no_findings_has_no_mutation(self):
        result = self.run_case("none")
        self.assertFalse(result["failed"])
        self.assertEqual(result["events"], ["read:base", "read:head"])

    def test_partial_modified_or_deleted_read_never_mutates(self):
        for mode in ["partial", "deleted"]:
            with self.subTest(mode=mode):
                result = self.run_case(mode)
                self.assertTrue(result["failed"])
                self.assertFalse(any(e.startswith(("create", "delete", "list")) for e in result["events"]))

    def test_failed_creation_or_wrong_authenticated_author_never_cleans(self):
        for mode in ["create-failure", "wrong-identity"]:
            with self.subTest(mode=mode):
                result = self.run_case(mode)
                self.assertTrue(result["failed"])
                self.assertIn("create", result["events"])
                self.assertFalse(any(e.startswith(("delete", "list")) for e in result["events"]))

    def test_review_mode_rejected_before_any_api_read(self):
        self.assertEqual(self.run_case("review"), {"failed": True, "events": [], "contentRefs": []})

    def test_changed_or_unsupported_pr_never_mutates(self):
        for mode in ["race", "fork", "draft", "closed", "other-base", "oversize", "incomplete"]:
            with self.subTest(mode=mode):
                result = self.run_case(mode)
                self.assertTrue(result["failed"])
                self.assertFalse(any(e.startswith(("create", "delete", "list")) for e in result["events"]))

    def test_exact_official_input_and_exclusive_output(self):
        self.assertIn(hashlib.sha256(OFFICIAL.read_bytes()).hexdigest(), PATCH.INPUTS)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "official.js"
            output = Path(directory) / "safe.mjs"
            source.write_bytes(OFFICIAL.read_bytes())
            PATCH.prepare(source, output)
            self.assertEqual(output.read_text(), PATCH.patch_source(OFFICIAL.read_text()))
            with self.assertRaises(FileExistsError):
                PATCH.prepare(source, output)
            source.write_text(OFFICIAL.read_text()+"\n")
            with self.assertRaisesRegex(ValueError, "digest"):
                PATCH.prepare(source, Path(directory)/"drift.mjs")
            self.assertFalse((Path(directory)/"drift.mjs").exists())

    def test_wrong_archive_integrity_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "wrong.tgz"
            archive.write_bytes(b"not the official archive")
            with self.assertRaisesRegex(ValueError, "integrity"):
                PATCH.verify_archive(archive)


if __name__ == "__main__":
    unittest.main()
