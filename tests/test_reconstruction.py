import base64,contextlib,fcntl,importlib.util,io,json,os,pathlib,subprocess,sys,tempfile,time,unittest
from unittest.mock import patch
SRC=pathlib.Path(__file__).resolve().parents[1]/'proxmox-maintenance'
def mod(name):
    spec=importlib.util.spec_from_file_location(name,SRC/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
store=mod('state');guard=mod('guard');dm=mod('docker-maint');agent=mod('agent-migrate');imp=mod('hermes-import-reports');scan=mod('audit-schedulers')
class Base(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.p=pathlib.Path(self.tmp.name);dm.FAIL=0;dm.AGENT_FAILED=False
    def tearDown(self):self.tmp.cleanup()
class Ledger(Base):
    def db(self):
        s=store.Store(self.p/'state');self.addCleanup(s.db.close);s.begin('run','proxmox','today',False);return s
    def test_dedup_and_explicit_retry(self):
        s=self.db();self.assertFalse(s.begin('dup','proxmox','today',False));self.assertTrue(s.begin('retry','proxmox','today',True));self.assertTrue(s.begin('web','wordpress','today',False))
    def test_action_is_failure(self):
        s=self.db();s.event('run','ACTION','LXC103','Ancora acceso; intervento');status,name=s.finish('run');self.assertEqual(status,'FAIL');self.assertIn('Ancora acceso',(s.root/'outbox'/name).read_text())
    def test_report_idempotent(self):
        s=self.db();self.assertEqual(s.finish('run'),s.finish('run'));self.assertEqual(len(list((s.root/'outbox').iterdir())),1)
    def test_crash_between_freeze_and_file_write_recovers(self):
        s=self.db();s.event('run','WARN','test','original')
        with patch.object(store,'atomic',side_effect=OSError('injected disk error')):self.assertRaises(OSError,s.finish,'run')
        s.event('run','FAIL','recovery','late event')
        status,name=s.finish('run');self.assertEqual(status,'WARN');self.assertIn('original',(s.root/'outbox'/name).read_text());self.assertEqual(s.finish('run'),(status,name))
    def test_cache_ten_pending_never_deleted(self):
        s=self.db();s.finish('run')
        for n in range(12):s.begin('test'+str(n),'web',str(n),False);s.finish('test'+str(n))
        self.assertEqual(len(list((s.root/'reports').glob('*.md'))),10);self.assertEqual(len(list((s.root/'outbox').glob('*.md'))),13);self.assertTrue((s.root/'latest.md').exists())
    def test_state_symlink_rejected(self):
        p=self.p/'link';p.symlink_to(self.p/'x');self.assertRaises(ValueError,store.Store,p)
    def test_atomic_destination_symlink_rejected(self):
        p=self.p/'link';p.symlink_to(self.p/'x');self.assertRaises(ValueError,store.atomic,p,b'x')
    def test_nas_unmounted_keeps_outbox(self):
        s=self.db();_,name=s.finish('run')
        with patch.object(store.subprocess,'run',side_effect=RuntimeError('missing')):self.assertRaises(RuntimeError,s.archive,self.p/'nas')
        self.assertTrue((s.root/'outbox'/name).exists());self.assertFalse((self.p/'nas').exists())
    def test_nas_readback_receipt_retry_and_retention(self):
        s=self.db();_,name=s.finish('run');mount=self.p/'nas';mount.mkdir()
        result=subprocess.CompletedProcess([],0,json.dumps({'filesystems':[{'target':str(mount),'fstype':'nfs4'}]}),'')
        with patch.object(store.subprocess,'run',return_value=result):
            s.archive(mount);s.archive(mount);self.assertFalse((s.root/'outbox'/name).exists());self.assertTrue((s.root/'receipts'/(name+'.json')).exists())
            dest=mount/'proxmox-maintenance/reports';(dest/'unrelated.md').write_text('keep');s.db.execute('UPDATE archives SET created=0');s.db.commit();s.archive(mount);self.assertFalse((dest/name).exists());self.assertTrue((dest/'unrelated.md').exists())
    def test_expired_report_payload_removed_from_ledger(self):
        s=self.db();_,name=s.finish('run');s.db.execute('UPDATE archives SET created=?',(time.time()-61*86400,));s.db.commit();mount=self.p/'nas';mount.mkdir();q=subprocess.CompletedProcess([],0,json.dumps({'filesystems':[{'target':str(mount),'fstype':'nfs4'}]}),'')
        with patch.object(store.subprocess,'run',return_value=q):s.archive(mount)
        self.assertIsNone(s.db.execute('SELECT payload FROM finalizations').fetchone());self.assertFalse((s.root/'reports'/name).exists())
    def test_nas_collision_keeps_local(self):
        s=self.db();_,name=s.finish('run');mount=self.p/'nas';dest=mount/'proxmox-maintenance/reports';dest.mkdir(parents=True,mode=0o700);dest.parent.chmod(0o700);(dest/name).write_text('other')
        q=subprocess.CompletedProcess([],0,json.dumps({'filesystems':[{'target':str(mount),'fstype':'nfs4'}]}),'')
        with patch.object(store.subprocess,'run',return_value=q):self.assertRaises(ValueError,s.archive,mount)
        self.assertTrue((s.root/'outbox'/name).exists())
    def test_summary_groups_counts_and_prioritizes_manual_action(self):
        s=self.db()
        for n in range(100):s.event('run','NOTE','host','OK step '+str(n))
        s.event('run','FAIL','LXC 200','worker error');s.event('run','ACTION','LXC 200','Timer restore failed');s.event('run','WARN','LXC 101','no healthcheck')
        msg=s.summary('run');self.assertIn('OK 1 | ❌ FAIL 1 | WARN 1',msg);self.assertIn('INTERVENTO',msg);self.assertNotIn('OK step',msg);self.assertLess(len(msg),700)
class Locks(Base):
    def test_real_posix_package_lock_blocks_guard(self):
        p=self.p/'lock';q=subprocess.Popen([sys.executable,'-c','import fcntl,sys;f=open(sys.argv[1],"w");fcntl.lockf(f,fcntl.LOCK_EX);print("ready",flush=True);sys.stdin.read()',str(p)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        try:
            self.assertEqual(q.stdout.readline().strip(),'ready')
            with self.assertRaises(BlockingIOError):
                with guard.gate([p]):pass
        finally:q.communicate('',timeout=5)
        with guard.gate([p]):pass
    def test_package_symlink_rejected(self):
        p=self.p/'lock';p.symlink_to(self.p/'target')
        with self.assertRaises(OSError):
            with guard.gate([p]):pass
    def test_restore_only_owned_masks_and_active_timers(self):
        state={'boot':guard.boot(),'units':{'apt-daily.timer':{'mask':True,'active':True},'other.service':{'mask':False,'active':True}}};(self.p/'quarantine.json').write_text(json.dumps(state));calls=[]
        def cmd(*args):calls.append(args);return subprocess.CompletedProcess(args,0,'','')
        with patch.object(guard,'ROOT',self.p),patch.object(guard,'cmd',cmd):guard.restore()
        self.assertIn(('systemctl','start','apt-daily.timer'),calls);self.assertFalse(any('other.service' in c for c in calls))
    def test_after_reboot_old_masks_not_restored(self):
        (self.p/'quarantine.json').write_text(json.dumps({'boot':'old','units':{}}))
        with patch.object(guard,'ROOT',self.p),patch.object(guard,'cmd') as cmd:guard.restore();cmd.assert_not_called()
    def test_unmask_dependencies_before_starting_any_timer(self):
        state={'boot':guard.boot(),'units':{'apt-daily.timer':{'mask':True,'active':True},'apt-daily.service':{'mask':True,'active':False}}};(self.p/'quarantine.json').write_text(json.dumps(state));masked={'apt-daily.timer','apt-daily.service'};calls=[]
        def cmd(*a):
            calls.append(a)
            if a[1]=='unmask':masked.discard(a[-1])
            return subprocess.CompletedProcess(a,1 if a[1]=='start' and masked else 0,'','')
        with patch.object(guard,'ROOT',self.p),patch.object(guard,'cmd',cmd):guard.restore()
        self.assertFalse((self.p/'quarantine.json').exists());self.assertEqual(calls[-1],('systemctl','start','apt-daily.timer'))
    def test_failed_unmask_does_not_start_timers_or_delete_journal(self):
        state={'boot':guard.boot(),'units':{'apt-daily.timer':{'mask':True,'active':True},'apt-daily.service':{'mask':True,'active':False}}};(self.p/'quarantine.json').write_text(json.dumps(state));calls=[]
        def cmd(*a):calls.append(a);return subprocess.CompletedProcess(a,1 if a[-1].endswith('.service') else 0,'','')
        with patch.object(guard,'ROOT',self.p),patch.object(guard,'cmd',cmd):self.assertRaises(RuntimeError,guard.restore)
        self.assertTrue((self.p/'quarantine.json').exists());self.assertFalse(any(a[1]=='start' for a in calls))
class Compose(Base):
    def test_missing_override_blocks_project(self):
        f=self.p/'compose.yml';f.touch();self.assertRaises(ValueError,dm.command,'custom',str(self.p),((str(f),str(self.p/'missing')),()))
    def test_project_and_env_identity(self):
        f=self.p/'compose.yml';e=self.p/'env file';f.touch();e.touch();self.assertEqual(dm.command('custom',str(self.p),((str(f),),(str(e),))),['compose','-p','custom','-f',str(f),'--env-file',str(e)])
    def test_profiles_wp_off_other_active_preserved(self):
        model={'services':{n:{} for n in ('db','redis','wordpress','nginx')}};model['services'].update(phpmyadmin={'profiles':['pma']},optional={'profiles':['extra']});rows=[dict(labels={'com.docker.compose.service':'optional'},running=True)]
        self.assertNotIn('phpmyadmin',dm.select(model,rows,True));self.assertIn('optional',dm.select(model,rows,False))
    def test_wp_dependency_pma_rejected(self):
        model={'services':{n:{} for n in ('db','redis','wordpress','nginx')}};model['services']['wordpress']['depends_on']={'phpmyadmin':{}};self.assertRaises(ValueError,dm.select,model,[],True)
    def test_persistent_mount_change_rejected(self):
        model={'services':{'db':{'volumes':[dict(type='volume',source='db',target='/data')]}},'volumes':{'db':{'name':'correct'}}};row=dict(id='id',labels={'com.docker.compose.service':'db'})
        with patch.object(dm,'inspect',return_value=[dict(Type='volume',Name='wrong',Destination='/data',RW=True)]):self.assertRaises(ValueError,dm.mounts,model,[row],['db'],False)
    def test_database_branch_and_secret_free_override(self):
        model={'services':{'db':{'image':'mariadb:12.3.1'},'pg':{'image':'postgres:18.1'},'web':{'image':'wordpress:fpm-soap','build':{ 'context':'.'}}}}
        with patch.object(dm,'ROOT',self.p):name=dm.override(model,'p','/app')
        data=json.loads(pathlib.Path(name).read_text())['services'];self.assertEqual(data['db']['image'],'mariadb:12.3');self.assertEqual(data['pg']['image'],'postgres:18');self.assertNotIn('web',data)
    def test_stopped_old_project_not_revived(self):
        common={'com.docker.compose.project.working_dir':'/app'};rows=[dict(labels=dict(common,**{'com.docker.compose.project':'old'}),running=False),dict(labels=dict(common,**{'com.docker.compose.project':'new'}),running=True)]
        self.assertTrue(dm.projects(rows,['/app'])[('old','/app')]['skip'])
    def test_hermes_defense_no_inventory(self):
        with patch.dict(os.environ,GUEST_ID='1000'),patch.object(dm,'inventory') as inventory:self.assertRaises(RuntimeError,dm.main);inventory.assert_not_called()
    def test_unhealthy_fails(self):
        with patch.dict(os.environ,COMPOSE_WAIT_SECONDS='0'),patch.object(dm,'inspect',return_value={'Running':True,'Health':{'Status':'unhealthy'}}):dm.health(['c'])
        self.assertEqual(dm.FAIL,1)
    def test_running_without_health_is_note(self):
        buf=io.StringIO()
        with contextlib.redirect_stdout(buf),patch.object(dm,'inspect',return_value={'Running':True}):dm.health(['c'])
        self.assertIn('NOTE|',buf.getvalue());self.assertNotIn('WARN|',buf.getvalue());self.assertEqual(dm.FAIL,0)
    def test_project_failure_continues_next(self):
        calls=[]
        def project(n,*args):calls.append(n);raise RuntimeError('injected')
        with patch.dict(os.environ,GUEST_ID='101',COMPOSE_DIRS_B64='',RUN_ID='test'),patch.object(sys,'argv',['helper','--health']),patch.object(dm,'inventory',return_value=[]),patch.object(dm,'projects',return_value={('a','/a'):{},('b','/b'):{}}),patch.object(dm,'project',project):dm.main()
        self.assertEqual(calls,['a','b'])
    def test_watchtower_only_standalone_names(self):
        rows=[{'id':'compose','running':True,'labels':{'com.docker.compose.project':'project'}},{'id':'plain','running':True,'labels':{}},{'id':'stopped','running':False,'labels':{}}];calls=[]
        def inspect(cid,key):return '/plain' if key=='.Name' else 'rustdesk/rustdesk-server:latest'
        with patch.object(dm,'inspect',inspect),patch.object(dm,'docker',side_effect=lambda *a,**kw:calls.append(a) or ''),patch.object(dm,'health'),patch.dict(os.environ,RUN_ID='test',STANDALONE_MODE='watchtower'):dm.standalone(rows)
        self.assertEqual(calls[0][-1],'plain');self.assertNotIn('compose',calls[0]);self.assertNotIn('stopped',calls[0])
    def test_watchtower_stderr_is_not_discarded(self):
        with patch.object(dm.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'','level=error failed')):self.assertIn('level=error',dm.docker('run','helper'))
class Import(Base):
    def exercise(self,existing=None,fail=False):
        name='20261031-test_wordpress.md';(self.p/name).write_bytes(b'report');remote={} if existing is None else {'Friday/Reports/'+name:existing};calls=[]
        def vault(*args,data=None):
            calls.append(args)
            if args==('read','Friday/INDEX.md'):return subprocess.CompletedProcess([],0,b'Friday/Reports')
            if args[0]=='list':return subprocess.CompletedProcess([],0,json.dumps(list(remote)).encode())
            if args[0]=='read':return subprocess.CompletedProcess([],0 if args[1] in remote else 1,remote.get(args[1],b''))
            if fail:return subprocess.CompletedProcess([],1,b'')
            remote[args[1]]=data;return subprocess.CompletedProcess([],0,b'')
        with patch.object(imp,'vault',vault):imp.run(self.p,'Friday/Reports')
        return name,calls
    def test_write_readback_archive(self):
        name,calls=self.exercise();self.assertTrue((self.p/'.archived'/name).exists());self.assertEqual(sum(c[0]=='write' for c in calls),1)
    def test_existing_equal_not_rewritten(self):
        _,calls=self.exercise(b'report');self.assertFalse(any(c[0]=='write' for c in calls))
    def test_conflict_never_overwrites(self):self.assertRaises(ValueError,self.exercise,b'other')
    def test_failed_write_retains_inbox(self):
        self.assertRaises(ValueError,self.exercise,None,True);self.assertTrue(list(self.p.glob('*.md')))
class Worker(Base):
    def run_worker(self,guest,mode,apt=0,hermes=0,lock_once=False):
        s=(SRC/'pve-guest-worker.sh').read_text().replace('/var/lib/proxmox-maintenance',str(self.p/'state')).replace('/var/tmp/',str(self.p)+'/').replace('/home/hermes/.local/bin/hermes',str(self.p/'hermes')).replace(' -o root -g root','').replace('== 0 && -z $(find','== "$EUID" && -z $(find')
        (self.p/'worker.sh').write_text(s);(self.p/'hermes').touch();(self.p/'hermes').chmod(0o700)
        script=r'''apt-get(){ echo "APT $*" >>"$TRACE";if [[ "$LOCK_ONCE" == 1 && "$*" == *update && ! -e "$FIX/lock-seen" ]];then touch "$FIX/lock-seen";echo 'Could not get lock /var/lib/apt/lists/lock';return 100;fi;return "$APT_RC"; }
sleep(){ :; }
timeout(){ shift 2;"$@"; }
dpkg-query(){ printf 'libc6\t1\n'; }
python3(){ echo "HELPER $*" >>"$TRACE";return 0; }
docker(){ echo "DOCKER $*" >>"$TRACE";return 0; }
su(){ echo HERMES_FINISHED >>"$TRACE";return "$HERMES_RC"; }
id(){ [[ ${1:-} != hermes ]] || return 0;command id "$@"; }
export -f sleep apt-get timeout dpkg-query python3 docker su id
bash "$FIX/worker.sh"
'''
        env=dict(os.environ,FIX=str(self.p),TRACE=str(self.p/'trace'),RUN_ID='test',KIND='lxc',GUEST_ID=guest,MODE=mode,APT_RC=str(apt),HERMES_RC=str(hermes),LOCK_ONCE=str(int(lock_once)))
        q=subprocess.run(['bash','-c',script],capture_output=True,text=True,env=env,timeout=10)
        status=self.p/'state/worker-status/test.status';self.assertTrue(status.exists(),q.stderr);return q,(self.p/'trace').read_text(),status.read_text()
    def test_apt_fail_still_docker_and_nonzero(self):
        q,tr,s=self.run_worker('101','full',apt=100);self.assertEqual(q.returncode,1,q.stderr);self.assertIn('docker-maint.py',tr);self.assertNotIn('full-upgrade',tr);self.assertIn('COMPLETE|failures=',s)
    def test_hermes_failed_waited_reboot_zero_docker(self):
        q,tr,s=self.run_worker('1000','full',hermes=7);self.assertEqual(q.returncode,1,q.stderr);self.assertIn('HERMES_FINISHED',tr);self.assertNotIn('DOCKER',tr);self.assertNotIn('docker-maint',tr);self.assertIn('REBOOT|',s)
    def test_apt_index_lock_is_retried_without_killing_a_transaction(self):
        q,tr,s=self.run_worker('200','apt',lock_once=True);self.assertEqual(q.returncode,0,q.stderr);self.assertEqual(sum(line.startswith('APT ') and line.endswith(' update') for line in tr.splitlines()),2);self.assertIn('full-upgrade',tr)
    def test_night_no_apt(self):
        q,tr,s=self.run_worker('200','docker');self.assertEqual(q.returncode,0,q.stderr);self.assertNotIn('APT ',tr);self.assertIn('docker-maint.py',tr)
    def test_morning_no_docker_update(self):
        q,tr,s=self.run_worker('200','apt');self.assertEqual(q.returncode,0,q.stderr);self.assertIn('full-upgrade',tr);self.assertNotIn('image prune',tr);self.assertEqual(sum('docker-maint.py' in line for line in tr.splitlines()),1);self.assertIn('--record',tr)
class BashFlows(Base):
    def run_functions(self,body):
        s=(SRC/'coordinator.sh').read_text();s=s[s.index('store(){'):s.index('\nfor bin in')]
        pre='set -uo pipefail\nRUN_ID=test;STATE="$FIX/state";DIR="$FIX/lib";LOG="$FIX/log";SCOPE=wordpress;SNAPSHOT_SKIP_IDS=(106);CREATE_SNAPSHOTS=1;STOP_LXC_STARTED_BY_SCRIPT=1;\n'
        fake='\nstore(){ echo "STORE $*" >>"$FIX/trace"; };event(){ echo "$*" >>"$FIX/trace"; };deploy(){ :; };sleep(){ :; };\n'
        q=subprocess.run(['bash','-c',pre+s+fake+body],env=dict(os.environ,FIX=str(self.p)),text=True,capture_output=True,timeout=10);self.assertEqual(q.returncode,0,q.stderr);return q.stdout,(self.p/'trace').read_text()
    def test_status_wrong_run_not_complete(self):
        out,tr=self.run_functions("parse guest $'RUN|wrong\nCOMPLETE|failures=0 warnings=0';echo complete=$STATUS_COMPLETE");self.assertIn('complete=0',out)
    def test_status_trailing_content_rejected(self):
        out,tr=self.run_functions("parse guest $'RUN|test\nCOMPLETE|failures=0 warnings=0\nNOTE|late';echo complete=$STATUS_COMPLETE");self.assertIn('complete=0',out)
    def test_busy_guest_left_on_action(self):
        out,tr=self.run_functions('state(){ echo running; };remote(){ return 1; };restore_guest 103 stopped 1 || true');self.assertIn('INTERVENTO MANUALE',tr);self.assertIn('Rimane acceso',tr)
    def test_originally_running_not_shutdown(self):
        out,tr=self.run_functions('state(){ echo running; };remote(){ :; };power(){ echo POWER >>"$FIX/trace"; };restore_guest 101 running 0');self.assertNotIn('POWER',tr)
    def test_temporarily_started_restored(self):
        out,tr=self.run_functions('state(){ echo running; };remote(){ :; };power(){ echo "POWER $*" >>"$FIX/trace"; };restore_guest 103 stopped 1');self.assertIn('POWER 103 shutdown',tr)
    def test_snapshot_200_retains_two_plus_three(self):
        out,tr=self.run_functions('pct(){ echo "PCT $*" >>"$FIX/trace";if [[ "$1" == listsnapshot ]];then for n in 01 02 03 04 05;do printf "pre-update-202610%s-000000\\npre-web-update-202610%s-000000\\n" "$n" "$n";done;fi; };snapshots cleanup 200;snapshots create 106')
        self.assertEqual(sum('PCT delsnapshot' in line for line in tr.splitlines()),5);self.assertNotIn('PCT snapshot 106',tr)
    def test_http_down_action(self):
        out,tr=self.run_functions('WEB_HTTP_HOST=example.invalid;remote(){ echo 503; };web_health');self.assertIn('Check homepage fallito',tr)
    def test_node_ping_only_is_online(self):
        out,tr=self.run_functions('ping(){ return 0; };remote(){ return 1; };if node_online example.invalid;then event NOTE node online;fi');self.assertIn('online',tr)
    def test_node_ssh_only_is_online(self):
        out,tr=self.run_functions('ping(){ return 1; };remote(){ return 0; };if node_online example.invalid;then event NOTE node online;fi');self.assertIn('online',tr)
    def test_node_both_negative_is_offline(self):
        out,tr=self.run_functions('ping(){ return 1; };remote(){ return 1; };if node_online example.invalid;then event FAIL node online;else event NOTE node offline;fi');self.assertIn('offline',tr)
    def test_telegram_api_false_is_failure(self):
        out,tr=self.run_functions("SEND_TELEGRAM=1;NO_TELEGRAM=0;TELEGRAM_BOT_TOKEN=DUMMY;TELEGRAM_CHAT_ID=DUMMY;curl(){ echo '{\"ok\":false}'; };if telegram hello;then event FAIL test accepted;else event NOTE test rejected;fi");self.assertIn('rejected',tr)
    def test_telegram_unicode_chunks(self):
        out,tr=self.run_functions("SEND_TELEGRAM=1;NO_TELEGRAM=0;TELEGRAM_BOT_TOKEN=DUMMY;TELEGRAM_CHAT_ID=DUMMY;curl(){ echo CALLED >>\"$FIX/trace\";echo '{\"ok\":true}'; };msg=$(python3 -c 'print(\"è\"*3601)');telegram \"$msg\";event NOTE test end");self.assertEqual(tr.count('CALLED'),3)
class Agent(Base):
    def exercise(self,failure=None):
        import copy
        calls=[];failed=False
        old=dict(Id='old',Name='/portainer_agent',State={'Running':True},Config={'Image':'23327631ee89','Env':['DUMMY=unchanged'],'Labels':{}},HostConfig={'NetworkMode':'host','Binds':['/var/run/docker.sock:/var/run/docker.sock']},Mounts=[{'Type':'volume','Name':'retained','Destination':'/data','RW':True}])
        objects={'old':old}
        def api(method,path,body=None,missing=False):
            nonlocal failed
            calls.append((method,path,copy.deepcopy(body)))
            if failure and failure in path and method!='GET' and not failed:failed=True;raise RuntimeError('injected')
            if '/create?' in path:
                objects['new']=dict(Id='new',Name='/portainer_agent',State={'Running':False},Config={k:v for k,v in body.items() if k!='HostConfig'},HostConfig=body['HostConfig']);return {'Id':'new'}
            cid=path.split('/')[2];obj=objects.get(cid)
            if cid=='portainer_agent':obj=next((v for v in objects.values() if v['Name']=='/portainer_agent'),None)
            if method=='GET':return copy.deepcopy(obj)
            if not obj:raise RuntimeError('missing')
            if method=='DELETE':del objects[obj['Id']];return {}
            if '/stop?' in path:obj['State']['Running']=False
            elif '/start' in path:obj['State']['Running']=True
            elif '/rename?' in path:obj['Name']='/'+path.split('name=')[1]
            return {}
        with patch.object(agent,'ROOT',self.p),patch.object(agent,'api',api),patch.object(agent.subprocess,'run',return_value=subprocess.CompletedProcess([],0)),patch.object(agent.time,'sleep'),patch.dict(os.environ,RUN_ID='test'):
            if failure:self.assertRaises(RuntimeError,agent.migrate)
            else:agent.migrate()
        return objects,calls
    def test_agent_volume_and_configuration_preserved(self):
        objects,calls=self.exercise();self.assertNotIn('old',objects);self.assertEqual(objects['new']['Config']['Env'],['DUMMY=unchanged']);self.assertEqual(objects['new']['HostConfig']['Mounts'][0]['Source'],'retained');self.assertFalse(any('v=true' in p for m,p,b in calls))
    def test_create_failure_rolls_back_only_agent(self):
        objects,calls=self.exercise('/create?');self.assertEqual(objects['old']['Name'],'/portainer_agent');self.assertTrue(objects['old']['State']['Running']);self.assertNotIn('new',objects)
    def test_start_failure_restores_old_agent(self):
        objects,calls=self.exercise('/new/start');self.assertTrue(objects['old']['State']['Running']);self.assertNotIn('new',objects)
    def test_stop_failure_keeps_old(self):
        objects,calls=self.exercise('/old/stop');self.assertTrue(objects['old']['State']['Running']);self.assertNotIn('new',objects)
    def test_rename_failure_restores_old(self):
        objects,calls=self.exercise('/old/rename');self.assertTrue(objects['old']['State']['Running']);self.assertEqual(objects['old']['Name'],'/portainer_agent')
    def test_external_replacement_never_deleted(self):
        def api(method,path,body=None,missing=False):return {'Id':'old','Name':'/backup'} if '/old/' in path else {'Id':'external','Config':{'Labels':{}}}
        with patch.object(agent,'api',api):self.assertRaises(RuntimeError,agent.rollback,dict(old='old',token='test'),self.p/'journal')
class Scanner(Base):
    def test_only_positions_no_command_values(self):
        p=self.p/'cron';p.write_text('0 5 * * * root /usr/local/sbin/update-web.sh DUMMY_VALUE\n');self.assertEqual(scan.scan(p),[str(p)+':1'])
if __name__=='__main__':unittest.main(verbosity=2)
