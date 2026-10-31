#!/usr/bin/env python3
"""Future rollout only: invoke under Hermes obsidian-vault skill, never touch CouchDB files."""
import argparse,fcntl,hashlib,json,os,pathlib,re,subprocess,sys
CLI='/home/hermes/obsidian-vault-cli/bin/obsidian-vault'
def vault(*args,data=None):return subprocess.run([CLI,*args],input=data,capture_output=True,timeout=120)
def run(inbox,folder,check=False):
    index=vault('read','Friday/INDEX.md')
    if index.returncode or folder.encode() not in index.stdout:raise ValueError('Canonical folder not confirmed')
    listing=vault('list',folder)
    if listing.returncode:raise ValueError('Vault list failed')
    try:items=json.loads(listing.stdout)
    except ValueError:items=listing.stdout.decode().splitlines()
    if isinstance(items,dict):items=items.get('files',items.get('items'))
    if not isinstance(items,list):raise ValueError('Unverified list format')
    names=set()
    for item in items:
        if isinstance(item,dict):item=item.get('path',item.get('name'))
        if not isinstance(item,str):raise ValueError('Unverified list format')
        item=item.removeprefix(folder+'/')
        if '/' in item or not item.endswith('.md') or item.startswith(('- ','* ')):raise ValueError('Unverified list format')
        names.add(item)
    if check:return
    archive=inbox/'.archived';archive.mkdir(mode=0o700,exist_ok=True)
    if archive.is_symlink():raise ValueError('archive symlink')
    for p in sorted(inbox.glob('*.md')):
        if p.is_symlink() or not re.fullmatch(r'[A-Za-z0-9_-]+\.md',p.name):raise ValueError('report path')
        data=p.read_bytes();target=folder+'/'+p.name;old=vault('read',target)
        if old.returncode==0:
            if old.stdout!=data:raise ValueError('Content conflict; no overwrite')
        elif p.name in names:raise ValueError('Existing note unreadable')
        else:
            q=vault('write',target,data=data)
            if q.returncode:raise ValueError('Write failed')
        q=vault('read',target)
        if q.returncode or q.stdout!=data:raise ValueError('Readback mismatch')
        dest=archive/p.name
        if dest.is_symlink() or (dest.exists() and dest.read_bytes()!=data):raise ValueError('Archive collision')
        os.replace(p,dest)
        fd=os.open(archive,os.O_DIRECTORY);os.fsync(fd);os.close(fd)
    for p in sorted(archive.glob('*.md'),reverse=True)[10:]:p.unlink()
def main():
    p=argparse.ArgumentParser();p.add_argument('--inbox',type=pathlib.Path,default=pathlib.Path('/home/hermes/maintenance-reports'));p.add_argument('--check-only',action='store_true');a=p.parse_args()
    if os.geteuid()==0:raise ValueError('Run as hermes')
    if a.inbox.is_symlink():raise ValueError('inbox symlink')
    with open('/var/lib/proxmox-maintenance-import/import.lock','rb') as f:
        fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        marker=pathlib.Path('/var/lib/proxmox-maintenance-import/maintenance.active')
        if marker.exists() and marker.read_text().splitlines()[0]==pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip():return 75
        run(a.inbox,'Friday/Reports',a.check_only)
    return 0
if __name__=='__main__':
    os.umask(0o077)
    try:sys.exit(main())
    except BlockingIOError:sys.exit(75)
    except Exception as e:print(type(e).__name__+': '+str(e),file=sys.stderr);sys.exit(1)
