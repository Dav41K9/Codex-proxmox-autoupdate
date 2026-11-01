#!/usr/bin/env python3
"""Build deterministic source ZIP and checksums. Never runs an updater."""
import difflib,hashlib,pathlib,shutil,zipfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
pkg=ROOT/'proxmox-maintenance';dist=ROOT/'dist';dist.mkdir(exist_ok=True)
old=dist/'proxmox-maintenance-v4-reviewed-20261031.zip'
if not old.exists():
    original=dist/'proxmox-maintenance-v4-reviewed.zip'
    if hashlib.sha256(original.read_bytes()).hexdigest()!='ce2daf45c013e5365a473a80184f919d43fc55fc805cd538d34cfc0da9ef5ee4':raise RuntimeError('Missing verified 4.0 archive')
    shutil.copyfile(original,old)
with zipfile.ZipFile(old) as previous:
    oldfiles={pathlib.PurePosixPath(n).name:previous.read(n).decode() for n in previous.namelist() if n.startswith('proxmox-maintenance/') and not n.endswith('/')}
newfiles={p.name:p.read_text() for p in pkg.iterdir() if p.is_file()}
patch=[]
for name in sorted(oldfiles.keys()|newfiles.keys()):
    patch.extend(difflib.unified_diff(oldfiles.get(name,'').splitlines(True),newfiles.get(name,'').splitlines(True),fromfile='reviewed-4.0/'+name if name in oldfiles else '/dev/null',tofile='proxmox-maintenance/'+name if name in newfiles else '/dev/null'))
(ROOT/'diff/reviewed-4.0-to-4.1.diff').write_text(''.join(patch))
files=[ROOT/'README.md',*sorted(p for d in ('proxmox-maintenance','tests','scripts') for p in (ROOT/d).iterdir() if p.is_file()),ROOT/'diff/reviewed-4.0-to-4.1.diff',ROOT/'docs/MESSA-IN-PRODUZIONE-IT.md']
manifest=''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(ROOT).as_posix()+'\n' for p in files)
(dist/'FILES.sha256').write_text(manifest)
target=dist/'proxmox-maintenance-v4.1-reviewed.zip'
with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for path in files:
        info=zipfile.ZipInfo(path.relative_to(ROOT).as_posix(),(2026,11,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16
        z.writestr(info,path.read_bytes())
    info=zipfile.ZipInfo('FILES.sha256',(2026,11,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16;z.writestr(info,manifest.encode())
with zipfile.ZipFile(target) as z:
    assert z.testzip() is None
    for line in z.read('FILES.sha256').decode().splitlines():
        sha,name=line.split('  ',1);assert hashlib.sha256(z.read(name)).hexdigest()==sha
shutil.copyfile(target,dist/'proxmox-maintenance-v4-reviewed.zip')
sums=''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in sorted(dist.glob('*.zip')))
(dist/'SHA256SUMS').write_text(sums)
print('ZIP verified:',target.name,target.stat().st_size,'bytes')
print(sums,end='')
