#!/usr/bin/env python3
"""One-time transition of known Portainer agent; never database rollback."""
import http.client,json,os,pathlib,socket,subprocess,sys,time,urllib.parse
ROOT=pathlib.Path('/var/lib/proxmox-maintenance')
class UnixHTTP(http.client.HTTPConnection):
    def connect(self):self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.settimeout(120);self.sock.connect('/var/run/docker.sock')
def api(method,path,body=None,missing=False):
    conn=UnixHTTP('localhost')
    try:
        conn.request(method,path,json.dumps(body) if body is not None else None,{'Content-Type':'application/json'});r=conn.getresponse();data=r.read()
        if r.status==404 and missing:return None
        if r.status>=300 and r.status!=304:raise RuntimeError('Docker API '+str(r.status))
        return json.loads(data) if data else {}
    finally:conn.close()
def save(p,s):
    t=p.with_suffix('.tmp')
    if p.is_symlink() or t.is_symlink():raise ValueError('journal symlink')
    with t.open('w') as f:json.dump(s,f);f.flush();os.fsync(f.fileno())
    os.replace(t,p)
    fd=os.open(p.parent,os.O_RDONLY|os.O_DIRECTORY);os.fsync(fd);os.close(fd)
def healthy(cid):
    for _ in range(30):
        s=api('GET','/containers/'+cid+'/json')['State']
        if s.get('Running') and s.get('Health',{}).get('Status','healthy')=='healthy':return True
        time.sleep(2)
    return False
def rollback(s,p):
    old=api('GET','/containers/'+s['old']+'/json',missing=True)
    if not old:raise RuntimeError('Original agent missing: keep new, manual recovery')
    new=api('GET','/containers/portainer_agent/json',missing=True)
    if new and new['Id']!=s['old']:
        if (new['Config'].get('Labels') or {}).get('pve-maintenance.migration')!=s['token']:raise RuntimeError('External replacement: leave untouched')
        api('POST','/containers/'+new['Id']+'/stop?t=60');api('DELETE','/containers/'+new['Id'])
    if old['Name']!='/portainer_agent':api('POST','/containers/'+s['old']+'/rename?name=portainer_agent')
    api('POST','/containers/'+s['old']+'/start')
    if not healthy(s['old']):raise RuntimeError('Old agent not healthy after recovery')
    p.unlink(missing_ok=True)
def migrate():
    p=ROOT/'agent-migration.json'
    if p.is_symlink():raise ValueError('journal symlink')
    if p.exists():
        s=json.loads(p.read_text());new=api('GET','/containers/portainer_agent/json',missing=True)
        if s['phase']=='verified' and new and (new['Config'].get('Labels') or {}).get('pve-maintenance.migration')==s['token'] and healthy(new['Id']):
            if api('GET','/containers/'+s['old']+'/json',missing=True):api('DELETE','/containers/'+s['old'])
            p.unlink();return
        rollback(s,p);print('WARN|Agent recuperato dopo interruzione; upgrade rinviato');return
    old=api('GET','/containers/portainer_agent/json',missing=True)
    if not old or not old['State'].get('Running'):return
    cfg=old['Config'];hc=old['HostConfig'];labels=cfg.get('Labels') or {};image=cfg['Image']
    if labels.get('com.docker.compose.project') or image=='portainer/agent:latest':return
    if not (image.startswith('portainer/agent:') or image=='23327631ee89'):raise ValueError('Agent image identity unverified')
    if hc.get('AutoRemove') or hc.get('Links') or hc.get('NetworkMode','default') not in ('default','bridge','host','none'):raise ValueError('Agent configuration not safely reconstructible')
    if hc.get('PublishAllPorts') or any(not b.get('HostPort') or b['HostPort']=='0' for bs in (hc.get('PortBindings') or {}).values() for b in (bs or [])):raise ValueError('Agent dynamic ports')
    mounts=list(hc.get('Mounts') or []);bound={m.get('Target') for m in mounts}
    bound.update(b.split(':')[1] for b in hc.get('Binds') or [] if ':' in b)
    for m in old.get('Mounts',[]):
        if m['Destination'] in bound:continue
        if m['Type']!='volume':raise ValueError('Agent mount cannot be reconstructed')
        mounts.append(dict(Type='volume',Source=m['Name'],Target=m['Destination'],ReadOnly=not m.get('RW',True)))
    if subprocess.run(['docker','pull','portainer/agent:latest'],capture_output=True).returncode:raise RuntimeError('Agent pull failed; old untouched')
    s=dict(old=old['Id'],token=os.environ['RUN_ID'],phase='intent');save(p,s)
    try:
        api('POST','/containers/'+s['old']+'/stop?t=60');api('POST','/containers/'+s['old']+'/rename?name='+urllib.parse.quote('portainer_agent.pve-old-'+s['token'],safe=''))
        newcfg=dict(cfg);newcfg['Image']='portainer/agent:latest';newcfg['Labels']=dict(labels,**{'pve-maintenance.migration':s['token']});newhc=dict(hc)
        if mounts:newhc['Mounts']=mounts
        created=api('POST','/containers/create?name=portainer_agent',dict(newcfg,HostConfig=newhc));s['new']=created['Id'];s['phase']='created';save(p,s)
        api('POST','/containers/'+s['new']+'/start')
        if not healthy(s['new']):raise RuntimeError('New agent not healthy')
        s['phase']='verified';save(p,s);api('DELETE','/containers/'+s['old']);p.unlink();print('NOTE|Agent passato a latest; volumi e configurazione preservati')
    except Exception:
        if s['phase']!='verified':rollback(s,p)
        raise
if __name__=='__main__':
    os.umask(0o077)
    try:
        if os.environ.get('GUEST_ID')=='1000':raise ValueError('Docker forbidden1000')
        migrate()
    except Exception as e:print('FAIL|'+str(e));sys.exit(1)
