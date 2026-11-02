#!/usr/bin/env python3
import datetime,fcntl,hashlib,json,os,pathlib,re,sqlite3,subprocess,sys,tempfile,time

def atomic(p,data):
    if p.is_symlink():raise ValueError('symlink')
    fd,tmp=tempfile.mkstemp(dir=p.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(tmp,p)
        fd=os.open(p.parent,os.O_RDONLY|os.O_DIRECTORY);os.fsync(fd);os.close(fd)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
def private(p):
    for ancestor in [p,*p.parents]:
        if ancestor.is_symlink():raise ValueError('directory symlink')
    p.mkdir(mode=0o700,parents=True,exist_ok=True)
    if p.stat().st_uid!=os.geteuid() or p.stat().st_mode&0o022:raise ValueError('unsafe state permissions')
class Store:
    def __init__(self,root):
        self.root=pathlib.Path(root);private(self.root)
        for d in ('outbox','reports','receipts'):private(self.root/d)
        if (self.root/'state.sqlite').is_symlink():raise ValueError('database symlink')
        self.db=sqlite3.connect(self.root/'state.sqlite');self.db.executescript('''PRAGMA journal_mode=WAL;PRAGMA synchronous=FULL;
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,scope TEXT,day TEXT,finished INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS events(run TEXT,level TEXT,target TEXT,msg TEXT);
CREATE TABLE IF NOT EXISTS guests(id TEXT PRIMARY KEY,owner TEXT,initial TEXT,owned INTEGER,phase TEXT);
CREATE TABLE IF NOT EXISTS nodes(run TEXT PRIMARY KEY,ip TEXT,phase TEXT);
CREATE TABLE IF NOT EXISTS finalizations(run TEXT PRIMARY KEY,payload BLOB,status TEXT,created REAL);
CREATE TABLE IF NOT EXISTS archives(name TEXT PRIMARY KEY,sha TEXT,created REAL,done INTEGER DEFAULT 0);
''')
    def begin(self,run,scope,day,retry):
        if not re.fullmatch('[A-Za-z0-9_-]+',run):raise ValueError('run')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if not retry and self.db.execute('SELECT 1 FROM runs WHERE scope=? AND day=?',(scope,day)).fetchone():return False
            self.db.execute('INSERT INTO runs(id,scope,day) VALUES(?,?,?)',(run,scope,day));return True
    def event(self,run,level,target,msg):
        if level not in ('NOTE','WARN','FAIL','REBOOT','ACTION'):raise ValueError('level')
        with self.db:
            if not self.db.execute('SELECT 1 FROM finalizations WHERE run=?',(run,)).fetchone():self.db.execute('INSERT INTO events VALUES(?,?,?,?)',(run,level,target,msg))
    def finish(self,run):
        scope=self.db.execute('SELECT scope FROM runs WHERE id=?',(run,)).fetchone()[0]
        rows=list(self.db.execute('SELECT level,target,msg FROM events WHERE run=?',(run,)))
        status='FAIL' if any(r[0] in ('FAIL','ACTION') for r in rows) else 'WARN' if any(r[0]=='WARN' for r in rows) else 'OK'
        name=run+'_'+scope+'.md';payload=(f'# Manutenzione {scope}\n\nRun: {run}\nEsito manutenzione: **{status}**\n\n'+'\n'.join('- **'+l+' '+t.replace('\n',' ')+':** '+m.replace('\n',' / ') for l,t,m in rows)+'\n\nTrasporto NAS/Telegram: ricevute e delivery.log separati. HTTP200 non certifica checkout.\n').encode()
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO finalizations VALUES(?,?,?,?)',(run,payload,status,time.time()))
        payload,status,created=self.db.execute('SELECT payload,status,created FROM finalizations WHERE run=?',(run,)).fetchone()
        existing=self.db.execute('SELECT sha FROM archives WHERE name=?',(name,)).fetchone()
        if not existing:
            path=self.root/'outbox'/name
            if path.exists() and path.read_bytes()!=payload:raise ValueError('immutable report collision')
            atomic(path,payload);atomic(self.root/'reports'/name,payload)
            with self.db:
                self.db.execute('INSERT INTO archives VALUES(?,?,?,0)',(name,hashlib.sha256(payload).hexdigest(),created));self.db.execute('UPDATE runs SET finished=1 WHERE id=?',(run,))
            cached=sorted((self.root/'reports').glob('*.md'),reverse=True)
            for p in cached[10:]:p.unlink()
            link=self.root/'latest.md';temp=self.root/'.latest.tmp';temp.unlink(missing_ok=True);temp.symlink_to('reports/'+cached[0].name);os.replace(temp,link)
        return status,name
    def summary(self,run):
        def target_name(value):
            value=' '.join(value.split())
            match=re.fullmatch(r'lxc\s+(\d+)(.*)',value,re.I)
            if match:return 'LXC '+match[1]+match[2]
            if re.match(r'^(node2|nodo2)(\s|$)',value,re.I):return 'Nodo 2'
            if value.lower()=='host':return 'Host'
            return value
        rows=[(level,target_name(target),' '.join(msg.split())) for level,target,msg in
              self.db.execute('SELECT level,target,msg FROM events WHERE run=? ORDER BY rowid',(run,))]
        rank={'NOTE':0,'REBOOT':0,'WARN':1,'FAIL':2,'ACTION':3}
        groups={}
        for level,target,msg in rows:
            groups[target]=max(groups.get(target,0),rank[level])
        counts=[sum(v==0 for v in groups.values()),sum(v>=2 for v in groups.values()),sum(v==1 for v in groups.values())]
        lines=[f'✅ OK {counts[0]} | ❌ FAIL {counts[1]} | WARN {counts[2]} (target)']
        issues=list(dict.fromkeys((level,target,msg) for level,target,msg in rows if rank[level]>0))
        issues.sort(key=lambda row:-rank[row[0]])
        for level,target,msg in issues[:6]:
            label='INTERVENTO' if level=='ACTION' else level
            lines.append(label+' '+target[:48]+': '+msg[:120])
        if len(issues)>6:lines.append(f'Altri {len(issues)-6} avvisi/errori nel report.')
        power=[msg for level,target,msg in rows if level=='NOTE' and target=='Nodo 2' and
               ('Gia acceso' in msg or 'Aggiornato e spento' in msg)]
        if power:lines.append('Nodo 2: '+power[-1][:120])
        reboots={}
        for level,target,msg in rows:
            if level=='REBOOT':
                reboots[target]=reboots.get(target,False) or 'Reboot completo verificato' in msg
        if reboots:
            lines.append('Reboot: '+', '.join(t+(' verificato' if done else 'richiesto') for t,done in sorted(reboots.items()))[:160])
        lines.append('Dettagli nel report host; esito consegna NAS separato.')
        return '\n'.join(lines)
    def archive(self,mount):
        fd=os.open(self.root/'archive.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            q=subprocess.run(['findmnt','-J','-M',str(mount),'-o','TARGET,FSTYPE'],capture_output=True,text=True,check=True,timeout=10)
            entries=json.loads(q.stdout)['filesystems']
            if len(entries)!=1 or entries[0]['target']!=str(mount) or entries[0]['fstype'] not in ('nfs','nfs4'):raise ValueError('NAS not mounted exactly')
            dest=pathlib.Path(mount)/'proxmox-maintenance'/'reports'
            for p in (dest.parent,dest):
                if p.is_symlink():raise ValueError('NAS symlink')
                p.mkdir(mode=0o700,exist_ok=True)
                if p.stat().st_mode&0o077:raise ValueError('NAS subdirectory must be private0700')
            for name,sha,created,done in list(self.db.execute('SELECT * FROM archives')):
                target=dest/name;source=self.root/'outbox'/name
                if not done:
                    data=source.read_bytes()
                    if hashlib.sha256(data).hexdigest()!=sha:raise ValueError('outbox checksum')
                    if target.is_symlink() or (target.exists() and target.read_bytes()!=data):raise ValueError('NAS collision')
                    atomic(target,data)
                    if hashlib.sha256(target.read_bytes()).hexdigest()!=sha:raise ValueError('NAS readback')
                    atomic(self.root/'receipts'/(name+'.json'),json.dumps(dict(sha256=sha,archived=time.time())).encode())
                    with self.db:self.db.execute('UPDATE archives SET done=1 WHERE name=?',(name,))
                    source.unlink()
                else:source.unlink(missing_ok=True)
                if created<time.time()-60*86400 and target.exists() and not target.is_symlink():target.unlink()
            expired=list(self.db.execute("SELECT f.run,a.name FROM finalizations f JOIN runs r ON r.id=f.run JOIN archives a ON a.name=r.id||'_'||r.scope||'.md' WHERE a.done=1 AND a.created<?",(time.time()-60*86400,)))
            for run,name in expired:
                (self.root/'reports'/name).unlink(missing_ok=True)
                with self.db:
                    self.db.execute('DELETE FROM events WHERE run=?',(run,));self.db.execute('DELETE FROM finalizations WHERE run=?',(run,))
            cached=sorted((self.root/'reports').glob('*.md'),reverse=True)
            link=self.root/'latest.md'
            if cached:
                temp=self.root/'.latest.tmp';temp.unlink(missing_ok=True);temp.symlink_to('reports/'+cached[0].name);os.replace(temp,link)
            else:link.unlink(missing_ok=True)
        finally:os.close(fd)
def main():
    os.umask(0o077);s=Store(sys.argv[1]);cmd=sys.argv[2];a=sys.argv[3:]
    if cmd=='begin':return 0 if s.begin(*a[:3],a[3]=='1') else 75
    if cmd=='event':s.event(*a)
    elif cmd=='guest':
        with s.db:s.db.execute('INSERT OR REPLACE INTO guests VALUES(?,?,?,?,?)',a)
    elif cmd=='node':
        with s.db:s.db.execute('INSERT OR REPLACE INTO nodes VALUES(?,?,?)',a)
    elif cmd=='nodes':
        for row in s.db.execute("SELECT run,ip FROM nodes WHERE phase NOT IN ('closed','manual')"):print('|'.join(row))
    elif cmd=='close':
        with s.db:s.db.execute('DELETE FROM guests WHERE id=?',a)
    elif cmd=='pending':
        for r in s.db.execute('SELECT * FROM guests'):print('|'.join(map(str,r)))
    elif cmd=='unfinished':
        for (r,) in s.db.execute('SELECT id FROM runs WHERE finished=0 AND id!=? AND scope=?',a):print(r)
    elif cmd=='finish':print('|'.join(s.finish(a[0])))
    elif cmd=='summary':print(s.summary(a[0]))
    elif cmd=='alert':
        for level,target,msg in s.db.execute("SELECT level,target,msg FROM events WHERE run=? AND level!='NOTE' ORDER BY CASE level WHEN 'ACTION' THEN 0 WHEN 'FAIL' THEN 1 ELSE 2 END",a):print(level+' '+target+': '+msg)
    elif cmd=='archive':s.archive(a[0])
    else:raise ValueError('command')
    return 0
if __name__=='__main__':
    try:sys.exit(main())
    except Exception as e:print(type(e).__name__+': '+str(e),file=sys.stderr);sys.exit(1)
