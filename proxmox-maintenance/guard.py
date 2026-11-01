#!/usr/bin/env python3
"""Transient coordination using real POSIX dpkg locks; no resident service."""
import contextlib,fcntl,json,os,pathlib,signal,subprocess,sys,time
ROOT=pathlib.Path('/var/lib/proxmox-maintenance')
UNITS=['apt-daily.timer','apt-daily-upgrade.timer','apt-daily.service','apt-daily-upgrade.service','unattended-upgrades.service','pve-daily-update.timer','pve-daily-update.service','paperless-import.timer','paperless-import.service']
def boot():return pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()
def cmd(*a):return subprocess.run(a,capture_output=True,text=True,timeout=30)
def save(p,obj):
    t=p.with_suffix('.tmp')
    with t.open('w') as f:json.dump(obj,f);f.flush();os.fsync(f.fileno())
    os.replace(t,p)
    fd=os.open(p.parent,os.O_RDONLY|os.O_DIRECTORY);os.fsync(fd);os.close(fd)
def restore():
    p=ROOT/'quarantine.json'
    if not p.exists():return
    state=json.loads(p.read_text())
    if state['boot']==boot():
        for u,v in state['units'].items():
            if v['mask'] and cmd('systemctl','unmask','--runtime',u).returncode:raise RuntimeError('unmask '+u)
        # Restore ALL dependencies before starting any timer.
        for u,v in state['units'].items():
            if u.endswith('.timer') and v['active'] and cmd('systemctl','start',u).returncode:raise RuntimeError('restore '+u)
    p.unlink()
def prepare(run):
    # APT owns its locks. Only pause the known Paperless scheduling timer.
    p=ROOT/'quarantine.json'
    if p.exists():
        old=json.loads(p.read_text())
        if old.get('strategy')=='timer-stop' and old['boot']==boot() and old.get('complete'):
            app_idle();return
        restore()  # Repairs legacy masks in two passes before new work.
    s={'boot':boot(),'run':run,'units':{},'complete':False,'strategy':'timer-stop'}
    if pathlib.Path('/run/systemd/system').exists():
        u='paperless-import.timer'
        q=cmd('systemctl','show',u,'-p','LoadState','--value')
        if q.returncode:raise RuntimeError('timer state unknown '+u)
        if q.stdout.strip()!='not-found':
            q=cmd('systemctl','show',u,'-p','ActiveState','--value')
            if q.returncode:raise RuntimeError('timer activity unknown '+u)
            active=q.stdout.strip() in ('active','activating','reloading')
            s['units'][u]={'mask':False,'active':active}
            save(p,s)  # Save original state BEFORE stopping, for crash recovery.
            if active and cmd('systemctl','stop',u).returncode:raise RuntimeError('timer stop '+u)
            q=cmd('systemctl','show',u,'-p','ActiveState','--value')
            if q.returncode or q.stdout.strip() not in ('inactive','failed'):raise RuntimeError('timer still active '+u)
    # Never stop a service that is importing. Report failure and let it finish.
    app_idle()
    s['complete']=True;save(p,s)
def app_idle():
    if not pathlib.Path('/run/systemd/system').exists():return
    q=cmd('systemctl','show','paperless-import.service','-p','LoadState','--value')
    if q.returncode:raise RuntimeError('import state unknown')
    if q.stdout.strip()=='not-found':return
    q=cmd('systemctl','show','paperless-import.service','-p','ActiveState','--value')
    if q.returncode or q.stdout.strip() not in ('inactive','failed'):raise BlockingIOError('Paperless import busy')
@contextlib.contextmanager
def gate(paths=None):
    fds=[]
    try:
        for p in paths or ['/var/lib/dpkg/lock-frontend','/var/lib/dpkg/lock','/var/lib/apt/lists/lock']:
            fd=os.open(p,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600);fds.append(fd);fcntl.lockf(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield
    finally:
        for fd in fds:os.close(fd)
def restore_worker():
    # fd8 is inherited from the worker; do not reopen/relock a different fd.
    fdstat=os.fstat(8);pathstat=(ROOT/'worker.lock').stat()
    if (fdstat.st_dev,fdstat.st_ino)!=(pathstat.st_dev,pathstat.st_ino):raise RuntimeError('worker lock mismatch')
    fcntl.flock(8,fcntl.LOCK_EX|fcntl.LOCK_NB)
    restore()
def main():
    os.umask(0o077)
    if ROOT.is_symlink():raise RuntimeError('state symlink')
    ROOT.mkdir(mode=0o700,exist_ok=True)
    if ROOT.stat().st_uid!=0 or ROOT.stat().st_mode&0o022:raise RuntimeError('state permissions')
    mode=sys.argv[1];run=sys.argv[2] if len(sys.argv)>2 else ''
    if mode=='prepare':prepare(run);return
    if mode=='restore-worker':
        restore_worker();return
    if mode=='restore':
        with open(ROOT/'worker.lock','a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            restore()
        return
    if mode=='app-idle':
        state=json.loads((ROOT/'quarantine.json').read_text())
        if state.get('boot')!=boot() or not state.get('complete'):raise RuntimeError('timer coordination incomplete')
        app_idle();return
    if mode=='ready':
        p=ROOT/('ready-'+run);s=json.loads(p.read_text());raw=pathlib.Path('/proc/'+str(s['pid'])+'/cmdline').read_bytes()
        if s['boot']!=boot() or run.encode() not in raw.split(b'\0') or b'hold' not in raw.split(b'\0'):raise RuntimeError('stale guard')
        return
    with open(ROOT/'worker.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if mode in ('hold','shutdown'):prepare(run)
        with gate():
            app_idle()
            if mode=='idle':return
            if mode=='shutdown':
                if cmd('shutdown','-h','now').returncode:raise RuntimeError('shutdown failed')
                time.sleep(300);return
            if mode!='hold':raise ValueError('mode')
            p=ROOT/('ready-'+run);save(p,dict(pid=os.getpid(),boot=boot()))
            signal.signal(signal.SIGTERM,lambda *_:sys.exit(0))
            try:time.sleep(300)
            finally:p.unlink(missing_ok=True)
if __name__=='__main__':
    try:main()
    except Exception as e:print(type(e).__name__+': '+str(e),file=sys.stderr);sys.exit(1)
