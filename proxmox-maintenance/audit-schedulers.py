#!/usr/bin/env python3
"""Print positions only; never print commands, environment or credential values."""
import pathlib,re,subprocess,sys
PAT=re.compile(r'update-proxmox-guests|update-web\.sh|pve-guest-worker|coordinator\.sh')
def scan(p,depth=0):
    try:
        if p.stat().st_size>1048576:return []
        lines=p.read_text(errors='replace').splitlines()
    except OSError:return []
    found=[]
    for i,line in enumerate(lines,1):
        if line.lstrip().startswith('#'):continue
        if PAT.search(line):found.append(f'{p}:{i}')
        elif depth<2:
            for item in re.findall(r'/(?:usr/local/(?:bin|sbin)|root|opt)/[A-Za-z0-9_./-]+',line):
                if scan(pathlib.Path(item),depth+1):found.append(f'{p}:{i} (wrapper)')
    return found
def main():
    paths=[pathlib.Path('/etc/crontab')]
    for root in ('/etc/cron.d','/etc/cron.hourly','/etc/cron.daily','/etc/cron.weekly','/etc/cron.monthly','/var/spool/cron/crontabs','/etc/systemd/system','/usr/local/lib/systemd/system'):
        paths.extend(p for p in pathlib.Path(root).rglob('*') if p.is_file())
    allow='--allow-managed' in sys.argv
    found=[]
    for p in paths:
        if allow and str(p)=='/etc/cron.d/pve-maintenance':continue
        found+=scan(p)
    q=subprocess.run(['systemctl','list-timers','--all','--full','--no-legend','--plain'],capture_output=True,text=True)
    if q.returncode:print('UNVERIFIED systemd timers');return 2
    for unit in set(re.findall(r'\b[\w@.-]+\.service\b',q.stdout)):
        q=subprocess.run(['systemctl','show',unit,'-p','FragmentPath','--value'],capture_output=True,text=True)
        if q.returncode or not q.stdout.strip():print('UNVERIFIED timer service');return 2
        found+=scan(pathlib.Path(q.stdout.strip()))
    for f in sorted(set(found)):print('CONFLICT '+f)
    if not found:print('Nessun conflitto rilevato; wrapper arbitrari/esterni richiedono verifica manuale.')
    return bool(found)
if __name__=='__main__':sys.exit(main())
