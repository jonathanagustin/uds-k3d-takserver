# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Locked cached Git/source-archive projection; no checkout mutation or downloads."""
import hashlib
import json
from pathlib import Path,PurePosixPath
import subprocess
import tarfile
from providers import digest,regular
HERE=Path(__file__).resolve().parent

def relative(name):
    p=PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or '\\' in name or not p.parts:raise ValueError('unsafe source path')
    return Path(*p.parts)
def checked(data,entry):
    if len(data)!=entry['bytes'] or hashlib.sha256(data).hexdigest()!=entry['sha256']:raise ValueError('locked source bytes differ')
    if 'git_blob' in entry and hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()!=entry['git_blob']:raise ValueError('source Git blob differs')
def git_blobs(checkout,entries,run,git="git"):
    # Every cached blob goes through the same bounded owned process group.
    # No blocking batch protocol can outlive the profile's aggregate deadline.
    for index,(name,entry) in enumerate(entries.items()):
        if entry['bytes']>16*1024**2:raise ValueError('locked individual source exceeds command output bound')
        data=run([str(git),'--no-lazy-fetch','-C',str(checkout),'cat-file','blob',entry['git_blob']],
                 'source-'+str(index),20)
        checked(data,entry);yield name,data
def project(checkout,output,lock,run,git="git"):
    entries=json.loads((HERE/'native-sources.lock.json').read_text());headers=json.loads((HERE/'gles1-headers.lock.json').read_text())
    combined=entries|headers
    for name,data in git_blobs(checkout,combined,run,git):
        dest=(output/'layout'/relative(name)) if name in entries else (output/'gles1-declarations'/Path(*relative(name).parts[-2:]))
        dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
    for name,entry in lock['patches'].items():
        p=output/'layout'/relative(entry['target'])
        if digest(p)!=entry['before']:raise ValueError('owned patch preimage differs')
        run(['patch','--batch','--fuzz=0','--no-backup-if-mismatch','-p1','-d',str(output/'layout'),'-i',str(HERE/'patches'/name)],'patch-'+name,30)
        if digest(p)!=entry['after']:raise ValueError('owned patch postimage differs')
def gltf_headers(cache,output):
    locks=json.loads((HERE/'gltf-inputs.lock.json').read_text())
    for entry in locks.values():
        archive=regular(cache/entry['sha256']);checked(archive.read_bytes(),entry)
        with tarfile.open(archive) as tar:
            members=tar.getmembers()
            if len(members)!=entry['archive_members']:raise ValueError('GLTF archive member count differs')
            total=0;selected=set();seen=set()
            for m in members:
                path=relative(m.name)
                if m.name in seen or not(m.isfile() or m.isdir()):raise ValueError('duplicate/nonregular GLTF archive input')
                seen.add(m.name)
                if m.name not in entry['selected']:continue
                if not m.isfile():raise ValueError('selected GLTF source not regular')
                data=tar.extractfile(m).read();checked(data,entry['selected'][m.name]);total+=len(data)
                if total>64*1024**2:raise ValueError('selected GLTF expansion limit')
                target=output/'gltf-headers'/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data);selected.add(m.name)
            if selected!=set(entry['selected']):raise ValueError('locked GLTF header absent')
