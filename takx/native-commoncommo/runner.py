# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Bound owned command lifetime, output and aggregate files while it runs."""
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import time

def disk_bytes(root):
    total=0
    for path in root.rglob('*'):
        try:info=path.lstat()
        except FileNotFoundError:continue  # normal compiler/install rename or unlink
        if stat.S_ISREG(info.st_mode):total+=info.st_size
    return total

def execute(command,root,label,timeout,env,capture=False,disk_limit=2*1024**3,log_limit=16*1024**2):
    child=None;data=bytearray();count=0;deadline=time.monotonic()+timeout;next_disk=0
    try:
        child=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,env=env,start_new_session=True)
        with (root/(label+'.log')).open('xb') as log,selectors.DefaultSelector() as selector:
            os.set_blocking(child.stdout.fileno(),False);selector.register(child.stdout,selectors.EVENT_READ)
            while selector.get_map() or child.poll() is None:
                now=time.monotonic()
                if now>=deadline:raise ValueError('owned command deadline exceeded')
                if now>=next_disk:
                    if disk_bytes(root)>disk_limit:raise ValueError('owned output quota exceeded')
                    next_disk=now+1
                for key,_ in selector.select(min(deadline-now,0.1)):
                    block=os.read(key.fileobj.fileno(),65536)
                    if not block:selector.unregister(key.fileobj);continue
                    count+=len(block)
                    if count>log_limit:raise ValueError('owned command log quota exceeded')
                    log.write(block)
                    if capture:data.extend(block)
            code=child.wait(timeout=max(0.001,deadline-time.monotonic()))
            if disk_bytes(root)>disk_limit:raise ValueError('owned output quota exceeded')
            if code:raise ValueError('owned command failed; private bounded log retained')
    finally:
        if child is not None:
            try:os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            child.wait();child.stdout.close()
    return bytes(data)
