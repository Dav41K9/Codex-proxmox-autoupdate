#!/usr/bin/env python3
"""Compose identity, explicit profiles, persisted mounts, standalone Watchtower."""
import base64,hashlib,json,os,pathlib,re,subprocess,sys,time
FAIL=0
AGENT_FAILED=False
ROOT=pathlib.Path('/var/lib/proxmox-maintenance')
def emit(level,msg):
    global FAIL
    FAIL+=level=='FAIL';print(level+'|'+msg.replace('\n',' / '),flush=True)
def docker(*args,cwd=None,env=None):
    p=subprocess.run(['docker',*args],cwd=cwd,env=env,capture_output=True,text=True)
    if p.returncode:
        # Private local log only; never serialize the Compose config/environment.
        for line in p.stderr.splitlines()[-25:]:print('DEBUG|Docker '+args[0]+': '+line,flush=True)
        raise RuntimeError('Docker '+args[0]+' rc='+str(p.returncode)+'; dettagli nel log host')
    return p.stdout+p.stderr if args[0]=='run' else p.stdout

def inspect(cid,key):return json.loads(docker('inspect','--format','{{json '+key+'}}',cid))
def inventory():
    return [dict(id=c,labels=inspect(c,'.Config.Labels') or {},running=inspect(c,'.State.Running')) for c in docker('ps','-aq').split()]
def projects(rows,configured):
    out={}
    for row in rows:
        l=row['labels'];n=l.get('com.docker.compose.project');w=l.get('com.docker.compose.project.working_dir')
        if not n or l.get('com.docker.compose.oneoff','').lower()=='true':continue
        if not w or not pathlib.Path(w).is_absolute():emit('FAIL','Compose directory metadata missing');continue
        files=tuple(f for f in l.get('com.docker.compose.project.config_files','').split(',') if f and pathlib.Path(f).parent!=ROOT/'compose-policy')
        envfiles=tuple(f for f in l.get('com.docker.compose.project.environment_file','').split(',') if f)
        p=out.setdefault((n,w),dict(meta=(files,envfiles),rows=[],bad=False))
        if p['meta']!=(files,envfiles):p['bad']=True
        p['rows'].append(row)
    for w in configured:
        if not any(key[1]==w for key in out):out[('',w)]=dict(meta=((),()),rows=[],bad=False)
    for (n,w),p in out.items():
        if p['rows'] and not any(r['running'] for r in p['rows']):
            peers=[q for (name,wd),q in out.items() if wd==w and name!=n]
            p['skip']=w not in configured or bool(peers)
    return out

def command(name,wd,meta):
    files,envfiles=meta;args=['compose']
    if name:args+=['-p',name]
    if not files:
        for f in ('compose.yaml','compose.yml','docker-compose.yml','docker-compose.yaml'):
            if (pathlib.Path(wd)/f).is_file():files=(str(pathlib.Path(wd)/f),);break
        for f in ('compose.override.yaml','compose.override.yml','docker-compose.override.yml','docker-compose.override.yaml'):
            if (pathlib.Path(wd)/f).is_file():files+= (str(pathlib.Path(wd)/f),);break
    if not files:raise ValueError('Compose file missing')
    for flag,values in (('-f',files),('--env-file',envfiles)):
        for f in values:
            if not pathlib.Path(f).is_absolute() or not pathlib.Path(f).is_file():raise ValueError('Incomplete Compose/env file set')
            args += [flag,f]
    return args

def select(model,rows,web):
    if web:
        chosen=['db','redis','wordpress','nginx']
        if any(n not in model['services'] for n in chosen):raise ValueError('WP services unexpected')
        if any(set(model['services'][n].get('depends_on',{}))-set(chosen) for n in chosen):raise ValueError('pma dependency forbidden')
        return chosen
    running={r['labels'].get('com.docker.compose.service') for r in rows if r['running']}
    return [n for n,v in model['services'].items() if not v.get('profiles') or n in running]
def mounts(model,rows,selected,web):
    if web:
        for service,target,vol in [('db','/var/lib/mysql','wordpress_db12'),('wordpress','/var/www/html','wordpress_wp_data')]:
            valid=False
            for m in model['services'][service].get('volumes',[]):
                v=model.get('volumes',{}).get(m.get('source'),{})
                if m.get('target')==target and v.get('external') and v.get('name',m.get('source'))==vol:valid=True
            if not valid:raise ValueError('WP persistent external volume mismatch')
    for row in rows:
        n=row['labels'].get('com.docker.compose.service')
        if n not in selected:continue
        expected={}
        for m in model['services'][n].get('volumes',[]):
            source=m.get('source')
            if m.get('type')=='volume':source=model.get('volumes',{}).get(source,{}).get('name',source)
            expected[m['target']]=(m.get('type'),source,not m.get('read_only',False))
        for m in inspect(row['id'],'.Mounts'):
            if m['Type'] in ('bind','volume') and expected.get(m['Destination'])!=(m['Type'],m.get('Name') or m.get('Source'),m.get('RW',True)):raise ValueError('Persistent mount change: '+n)
def canonical_repo(repo):
    # Docker Hub aliases identify the same image; never rewrite private registries.
    for prefix in ('docker.io/','index.docker.io/','registry-1.docker.io/'):
        if repo.startswith(prefix):
            repo=repo[len(prefix):]
            break
    if repo.startswith('library/'):repo=repo[len('library/'):]
    return repo

def override(model,name,wd):
    images={}
    for n,v in model['services'].items():
        image=v.get('image','')
        if v.get('build'):continue
        if '@sha256:' in image or image.startswith('sha256:') or re.fullmatch('[0-9a-f]{12,64}',image):emit('WARN',n+': digest/ID immutabile: scegliere un tag aggiornabile');continue
        repo,tag=(image.rsplit(':',1) if ':' in image.rsplit('/',1)[-1] else (image,'latest'));target=None
        key=canonical_repo(repo)
        if key in ('postgres','mariadb','couchdb'):
            m=re.match(r'^(\d+)(?:\.(\d+))?',tag)
            if m:
                target=m[1]+('.'+m[2] if key=='mariadb' and m[2] else '')+('-alpine' if 'alpine' in tag else '')
                emit('NOTE',n+': aggiornamenti automatici nel ramo DB '+target+' ('+key+'); migrazioni major escluse')
            else:emit('NOTE',n+': canale DB mobile esistente mantenuto: '+image)
        elif key in ('redis','nginx'):target='alpine' if 'alpine' in tag else 'latest'
        elif key in ('gotenberg/gotenberg','apache/tika','ghcr.io/paperless-ngx/paperless-ngx'):target='latest'
        if target:
            images[n]={'image':repo+':'+target}
            if image!=repo+':'+target:emit('NOTE',n+': canale automatico '+image+' -> '+repo+':'+target)
        elif re.match(r'\d',tag):emit('WARN',n+': canale numerico senza regola automatica: '+image+'; verificare il ramo desiderato')
    if not images:return None
    p=ROOT/'compose-policy';p.mkdir(mode=0o700,parents=True,exist_ok=True)
    if p.is_symlink() or p.stat().st_uid!=os.geteuid() or p.stat().st_mode&0o022:raise ValueError('unsafe policy directory')
    path=p/(hashlib.sha256((name+'\0'+wd).encode()).hexdigest()+'.json');tmp=path.with_suffix('.tmp')
    if path.is_symlink() or tmp.is_symlink():raise ValueError('policy symlink')
    tmp.write_text(json.dumps({'services':images}));tmp.chmod(0o600);os.replace(tmp,path);return str(path)
def health(names):
    for name in names:
        deadline=time.monotonic()+int(os.environ.get('COMPOSE_WAIT_SECONDS','240'))
        while True:
            try:
                state=inspect(name,'.State')
                if state.get('Running') and state.get('Health',{}).get('Status','none') in ('healthy','none'):
                    if 'Health' not in state:emit('NOTE',name+': running; healthcheck applicativo non configurato')
                    break
            except Exception:pass
            if time.monotonic()>=deadline:emit('FAIL',name+': non pronto/unhealthy');break
            time.sleep(3)
def project(name,wd,p,check=False):
    if p['bad']:raise ValueError('Compose conflicting metadata')
    if p.get('skip'):emit('NOTE',name+': progetto spento non riattivato');return
    args=command(name,wd,p['meta']);env=os.environ.copy();env['COMPOSE_PROFILES']=''
    for k in ('COMPOSE_FILE','COMPOSE_PROJECT_NAME','COMPOSE_ENV_FILES'):env.pop(k,None)
    model=json.loads(docker(*args,'--profile','*','config','--format','json',cwd=wd,env=env));name=model.get('name',name)
    web=os.environ.get('GUEST_ID')=='200' and wd==os.environ.get('WEB_COMPOSE_DIR','/home/3dft/3dft-wordpress')
    chosen=select(model,p['rows'],web)
    if not chosen:return
    mounts(model,p['rows'],chosen,web)
    if not check:
        if any('paperless-ngx/paperless-ngx' in v.get('image','') for v in model['services'].values()):
            q=subprocess.run([sys.executable,str(pathlib.Path(__file__).with_name('guard.py')),'app-idle'],capture_output=True)
            if q.returncode:raise RuntimeError('Paperless rinviato: import inattivo/coordinamento timer non confermati')
        policy=override(model,name,wd)
        if policy:args+=['-f',policy]
        for step in (['config','--quiet'],['pull','--ignore-buildable',*chosen],['build','--pull','--no-cache',*chosen],['up','-d','--wait','--wait-timeout',os.environ.get('COMPOSE_WAIT_SECONDS','240'),*chosen]):
            emit('NOTE',name+': Compose '+step[0]+' in corso')
            docker(*args,*step,cwd=wd,env=env)
    after=[r for r in inventory() if r['labels'].get('com.docker.compose.project')==name and r['labels'].get('com.docker.compose.project.working_dir')==wd]
    present={r['labels'].get('com.docker.compose.service') for r in after if r['running']}
    if set(chosen)-present:emit('FAIL',name+': servizi mancanti '+','.join(sorted(set(chosen)-present)))
    mounts(model,after,chosen,web)
    health([r['id'] for r in after if r['labels'].get('com.docker.compose.service') in chosen])
    if web and {'phpmyadmin','pma'}&present:emit('FAIL','phpMyAdmin attivo: verificare avvio esterno')
def standalone(rows):
    names=[]
    for r in rows:
        if not r['running'] or r['labels'].get('com.docker.compose.project'):continue
        name=inspect(r['id'],'.Name').lstrip('/');image=inspect(r['id'],'.Config.Image')
        if '.pve-old-' in name or (name=='portainer_agent' and AGENT_FAILED):continue
        if name.startswith('pve-wt-'):raise RuntimeError('Watchtower precedente ancora attivo')
        if '@sha256:' in image or image.startswith('sha256:') or re.fullmatch('[0-9a-f]{12,64}',image):emit('WARN',name+': digest/ID immutabile: scegliere un tag aggiornabile');continue
        if re.search(r':\d',image):emit('WARN',name+': standalone su canale numerico '+image+'; Watchtower aggiorna solo questo tag')
        names.append(name)
    if not names:return
    if os.environ.get('STANDALONE_MODE','watchtower')!='watchtower':emit('WARN','Standalone disabilitati');return
    output=docker('run','--pull','always','--rm','--name','pve-wt-'+os.environ['RUN_ID'],'-v','/var/run/docker.sock:/var/run/docker.sock',os.environ.get('WATCHTOWER_IMAGE','ghcr.io/nicholas-fedor/watchtower:latest'),'--log-format','LogFmt','--no-color','--run-once',*names)
    if re.search(r'level=(error|fatal)|"level":"(error|fatal)"',output,re.I):emit('FAIL','Watchtower error log')
    health(names)
def main():
    global AGENT_FAILED
    if os.environ.get('GUEST_ID')=='1000':raise RuntimeError('Docker vietato1000')
    if '--record' in sys.argv:
        names=[inspect(cid,'.Name').lstrip('/') for cid in docker('ps','-q').split()]
        p=ROOT/'worker-status'/(os.environ['RUN_ID']+'.running.json');p.write_text(json.dumps(names));return 0
    rows=inventory();configured=[s for s in base64.b64decode(os.environ.get('COMPOSE_DIRS_B64',''),validate=True).decode().splitlines() if s.strip()]
    check='--health' in sys.argv
    if not check and any(inspect(r['id'],'.Name').startswith('/pve-wt-') for r in rows if r['running']):raise RuntimeError('Watchtower precedente ancora attivo')
    for (name,wd),p in projects(rows,configured).items():
        try:project(name,wd,p,check)
        except Exception as e:emit('FAIL',str(e))
    if check:
        p=ROOT/'worker-status'/(os.environ['RUN_ID'].removesuffix('-health')+'.running.json')
        if p.exists():health(json.loads(p.read_text()))
        else:emit('WARN','Inventario pre-reboot assente')
    else:
        try:
            q=subprocess.run([sys.executable,str(pathlib.Path(__file__).with_name('agent-migrate.py'))],capture_output=True,text=True)
            for line in q.stdout.splitlines():
                if '|' in line:emit(*line.split('|',1))
            if q.returncode:AGENT_FAILED=True;emit('FAIL','Migrazione agent incompleta')
        except Exception as e:AGENT_FAILED=True;emit('FAIL',str(e))
        try:standalone(inventory())
        except Exception as e:emit('FAIL',str(e))
    return bool(FAIL)
if __name__=='__main__':
    os.umask(0o077)
    try:sys.exit(main())
    except Exception as e:emit('FAIL',str(e));sys.exit(1)
