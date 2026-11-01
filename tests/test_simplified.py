import contextlib,fcntl,importlib.util,io,json,os,pathlib,subprocess,sys,tempfile,unittest
from unittest.mock import patch
import test_reconstruction as common
Base=common.Base;guard=common.guard;store=common.store;SRC=common.SRC

class TimerPolicy(Base):
    def mock_system(self,active=True,import_busy=False):
        calls=[];timer={'state':'active' if active else 'inactive'}
        def cmd(*a):
            calls.append(a)
            if a[1]=='show':
                value='loaded' if 'LoadState' in a else timer['state'] if a[2].endswith('.timer') else 'active' if import_busy else 'inactive'
                return subprocess.CompletedProcess(a,0,value+'\n','')
            if a[1]=='stop':timer['state']='inactive'
            if a[1]=='start':timer['state']='active'
            return subprocess.CompletedProcess(a,0,'','')
        return cmd,calls,timer
    def test_custom_paperless_stops_timer_only_without_mask(self):
        cmd,calls,timer=self.mock_system()
        with patch.object(guard,'ROOT',self.p),patch.object(guard,'cmd',cmd),patch.object(pathlib.Path,'exists',lambda p: str(p)=='/run/systemd/system' or os.path.exists(p)):
            guard.prepare('test');state=json.loads((self.p/'quarantine.json').read_text());self.assertTrue(state['complete']);self.assertEqual(timer['state'],'inactive');guard.restore()
        self.assertEqual(timer['state'],'active');self.assertFalse(any('mask' in a or 'unmask' in a for a in calls));self.assertEqual([a[2] for a in calls if a[1]=='stop'],['paperless-import.timer'])
    def test_preexisting_inactive_timer_stays_inactive(self):
        cmd,calls,timer=self.mock_system(False)
        with patch.object(guard,'ROOT',self.p),patch.object(guard,'cmd',cmd),patch.object(pathlib.Path,'exists',lambda p: str(p)=='/run/systemd/system' or os.path.exists(p)):
            guard.prepare('test');guard.restore()
        self.assertEqual(timer['state'],'inactive');self.assertFalse(any(a[1] in ('stop','start','mask') for a in calls))
    def test_import_busy_is_never_stopped_and_timer_can_be_restored(self):
        cmd,calls,timer=self.mock_system(import_busy=True)
        with patch.object(guard,'ROOT',self.p),patch.object(guard,'cmd',cmd),patch.object(pathlib.Path,'exists',lambda p: str(p)=='/run/systemd/system' or os.path.exists(p)):
            self.assertRaises(BlockingIOError,guard.prepare,'test');guard.restore()
        self.assertTrue(all(not (a[1]=='stop' and a[2].endswith('.service')) for a in calls));self.assertEqual(timer['state'],'active')
    def test_host_without_paperless_does_not_touch_apt_timers(self):
        def cmd(*a):return subprocess.CompletedProcess(a,0,'not-found\n','')
        with patch.object(guard,'ROOT',self.p),patch.object(guard,'cmd',side_effect=cmd) as calls,patch.object(pathlib.Path,'exists',lambda p: str(p)=='/run/systemd/system' or os.path.exists(p)):
            guard.prepare('test');guard.restore()
        self.assertFalse(any(a.args[1] in ('mask','stop','start','unmask') for a in calls.call_args_list))

class WebAndRecovery(Base):
    run_functions=common.BashFlows.run_functions
    def test_homepage_both_checks_pass_and_login_not_used(self):
        out,tr=self.run_functions('WEB_HTTP_HOST=example.invalid;remote(){ echo "REMOTE $*" >>"$FIX/trace";echo 200; };curl(){ echo "CURL $*" >>"$FIX/trace";echo 200; };web_health')
        self.assertIn('https://example.invalid/',tr);self.assertIn('http://127.0.0.1:8080/',tr);self.assertNotIn('wp-login',tr);self.assertNotIn('ACTION',tr)
    def test_public_failure_not_hidden_by_local_success(self):
        out,tr=self.run_functions('WEB_HTTP_HOST=example.invalid;remote(){ echo 200; };curl(){ echo 503; };web_health')
        self.assertIn('locale=200 pubblico=503',tr);self.assertIn('ACTION',tr)
    def test_guest_boot_wait_accepts_degraded_but_not_starting(self):
        out,tr=self.run_functions('remote(){ if [[ ! -e "$FIX/seen" ]];then touch "$FIX/seen";echo starting;else echo degraded;return 1;fi; };wait_guest 200;event NOTE test ready')
        self.assertIn('ready',tr)
    def test_guest_boot_wait_failure_is_not_false_ready(self):
        out,tr=self.run_functions('remote(){ echo starting; };if wait_guest 200;then event FAIL test false-ready;else event NOTE test timeout;fi')
        self.assertIn('timeout',tr);self.assertNotIn('false-ready',tr)
    def test_history_does_not_replay_old_updates(self):
        out,tr=self.run_functions("parse 'LXC 101 recupero' $'RUN|old\\nNOTE|Agent passed latest\\nFAIL|old failure\\nCOMPLETE|failures=1 warnings=0' old 1;event NOTE test parsed;echo complete=$STATUS_COMPLETE")
        self.assertNotIn('Agent passed latest',tr);self.assertNotIn('old failure',tr);self.assertIn('complete=1',out)
    def test_running_guest_restores_timer_even_if_import_busy(self):
        out,tr=self.run_functions('state(){ echo running; };remote(){ echo "REMOTE $*" >>"$FIX/trace";[[ ${*: -1} != idle ]]; };restore_guest 106 running 0')
        self.assertIn('guard.py restore',tr);self.assertNotIn('guard.py idle',tr)

class Installer(Base):
    def fixture(self,conflict=1):
        root=self.p/'root';pkg=self.p/'pkg';mock=self.p/'bin';pkg.mkdir();mock.mkdir();(root/'etc').mkdir(parents=True);(root/'var/lock').mkdir(parents=True);(root/'var/log').mkdir();(root/'etc/cron.d').mkdir();(root/'etc/logrotate.d').mkdir()
        for p in SRC.iterdir():
            if p.is_file():(pkg/p.name).write_bytes(p.read_bytes())
        (pkg/'audit-schedulers.py').write_text('import sys\nprint("scanner fixture")\nsys.exit('+str(conflict)+')\n')
        cfg=root/'etc/update-guests.conf';cfg.write_text('DRY_RUN=0\nSEND_TELEGRAM=1\nTELEGRAM_BOT_TOKEN=DUMMY\nTELEGRAM_CHAT_ID=DUMMY\n');cfg.chmod(0o600)
        for n in ('pct','ssh','ping','findmnt','chown'):
            f=mock/n;f.write_text('#!/bin/sh\nexit 0\n');f.chmod(0o700)
        f=mock/'timedatectl';f.write_text('#!/bin/sh\necho Europe/Zurich\n');f.chmod(0o700)
        s=(pkg/'install.sh').read_text()
        for pre in ('/usr/local','/var/lock','/var/backups','/var/log','/etc'):s=s.replace(pre,str(root)+pre)
        s=s.replace('export PATH='+str(root)+'/usr/local/sbin:'+str(root)+'/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin','export PATH='+str(mock)+':/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin')
        s=s.replace('EUID==0','EUID=='+str(os.geteuid())).replace('$(stat -c %u "$config") == 0','$(stat -c %u "$config") == '+str(os.geteuid())).replace(' -o root -g root','')
        (pkg/'install.sh').write_text(s);return root,pkg
    def test_check_makes_no_installation_even_with_scheduler_warning(self):
        root,pkg=self.fixture();q=subprocess.run(['bash',str(pkg/'install.sh'),'--check'],capture_output=True,text=True);self.assertEqual(q.returncode,0,q.stderr);self.assertFalse((root/'usr/local/sbin').exists())
    def test_install_allowed_with_scheduler_warning_no_cron(self):
        root,pkg=self.fixture();q=subprocess.run(['bash',str(pkg/'install.sh'),'--install'],capture_output=True,text=True);self.assertEqual(q.returncode,0,q.stderr);self.assertTrue((root/'usr/local/sbin/maintenance-recover.sh').exists());self.assertFalse((root/'etc/cron.d/pve-maintenance').exists())
    def test_enable_cron_conflict_refused_before_mutations(self):
        root,pkg=self.fixture();q=subprocess.run(['bash',str(pkg/'install.sh'),'--enable-cron'],capture_output=True,text=True);self.assertNotEqual(q.returncode,0);self.assertFalse((root/'usr/local/sbin').exists())
    def test_enable_cron_has_only_two_scheduled_jobs(self):
        root,pkg=self.fixture(0);q=subprocess.run(['bash',str(pkg/'install.sh'),'--enable-cron'],capture_output=True,text=True);self.assertEqual(q.returncode,0,q.stderr);content=(root/'etc/cron.d/pve-maintenance').read_text();self.assertEqual(content.count('--scheduled'),2)

class ScopeAndScheduling(Base):
    def recovery(self,scope):
        src=(SRC/'coordinator.sh').read_text();part=src[src.index('declare -A BLOCKED=()'):src.index('node_ready=0;node_owned=0')]
        script='''set -uo pipefail
SCOPE=$1;RUN_ID=test;DIR=/unused;STATE=/unused
store(){ case "$1" in pending) printf '200|old|running|0|worker\\n101|old|running|0|worker\\n106|old|running|0|worker\\n';;esac; }
event(){ echo "EVENT $*"; }
state(){ echo stopped; }
restore_guest(){ echo "RESTORE $1"; }
'''+part
        return subprocess.run(['bash','-c',script,'bash',scope],capture_output=True,text=True,timeout=10)
    def test_wordpress_recovers_only_200(self):
        q=self.recovery('wordpress');self.assertEqual(q.returncode,0,q.stderr);self.assertIn('RESTORE 200',q.stdout);self.assertNotIn('RESTORE 101',q.stdout);self.assertNotIn('RESTORE 106',q.stdout)
    def test_general_recovers_all_pending_guests(self):
        q=self.recovery('proxmox');self.assertEqual(q.returncode,0,q.stderr)
        for id in ('200','101','106'):self.assertIn('RESTORE '+id,q.stdout)
    def scheduling(self,scheduled,run):
        src=(SRC/'coordinator.sh').read_text();part=src[src.index('[[ ! -L /var/lock/update-guests.lock ]]'):src.index('CLAIMED=1;trap')].replace('/var/lock/update-guests.lock',str(self.p/'lock'))
        script='''set -uo pipefail
SCOPE=wordpress;SCHEDULED=$1;RUN_ID=$2;RETRY=0
store(){ python3 "$TEST_SRC/state.py" "$TEST_ROOT/state" "$@"; }
telegram(){ echo "TELEGRAM $*"; }
'''+part
        return subprocess.run(['bash','-c',script,'bash',str(scheduled),run],env=dict(os.environ,TEST_ROOT=str(self.p),TEST_SRC=str(SRC)),capture_output=True,text=True,timeout=10)
    def test_manual_runs_same_day_do_not_require_retry(self):
        for run in ('manual1','manual2'):
            q=self.scheduling(0,run);self.assertEqual(q.returncode,0,q.stderr);self.assertNotIn('duplicato evitato',q.stdout)
        import sqlite3
        with sqlite3.connect(self.p/'state/state.sqlite') as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM runs').fetchone()[0],2)
    def test_cron_runs_same_day_are_deduplicated(self):
        self.scheduling(1,'cron1');q=self.scheduling(1,'cron2');self.assertEqual(q.returncode,0);self.assertIn('duplicato evitato',q.stdout)
    def test_manual_busy_lock_returns_without_starting_work(self):
        with (self.p/'lock').open('w') as f:
            fcntl.flock(f,fcntl.LOCK_EX);q=self.scheduling(0,'busy')
        self.assertEqual(q.returncode,75);self.assertFalse((self.p/'state').exists())

class WorkerLock(Base):
    def test_restore_worker_uses_inherited_descriptor(self):
        code='''import os,sys,pathlib,fcntl,importlib.util
spec=importlib.util.spec_from_file_location('guard',sys.argv[1]);g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g);g.ROOT=pathlib.Path(sys.argv[2])
f=open(g.ROOT/'worker.lock','a');os.dup2(f.fileno(),8);fcntl.flock(8,fcntl.LOCK_EX|fcntl.LOCK_NB)
g.restore_worker();print('RESTORED')
'''
        q=subprocess.run([sys.executable,'-c',code,str(SRC/'guard.py'),str(self.p)],capture_output=True,text=True,timeout=10);self.assertEqual(q.returncode,0,q.stderr);self.assertIn('RESTORED',q.stdout)

class RecoveryUtility(Base):
    def test_repair_does_not_invoke_update_or_power_commands(self):
        root=self.p/'root';pkg=self.p/'pkg';mock=self.p/'bin';pkg.mkdir();mock.mkdir();(root/'etc').mkdir(parents=True);(root/'var/lock').mkdir(parents=True)
        (root/'etc/update-guests.conf').write_text('UPDATE_NODE2=1\nNODE2_IP=example.invalid\nVM_SSH_TARGETS=()\n')
        for name in ('guard.py','maintenance-recover.sh'):(pkg/name).write_bytes((SRC/name).read_bytes())
        trace=self.p/'trace'
        pct=mock/'pct';pct.write_text('''#!/usr/bin/env bash
printf 'pct %s\\n' "$*" >>"$TRACE"
if [[ "$1" == list ]];then printf 'VMID Status Name\\n200 running web\\n101 stopped other\\n';fi
exit 0
''');pct.chmod(0o700)
        ssh=mock/'ssh';ssh.write_text('#!/bin/sh\nprintf "ssh %s\\n" "$*" >>"$TRACE"\nexit 0\n');ssh.chmod(0o700)
        s=(pkg/'maintenance-recover.sh').read_text().replace('/etc/update-guests.conf',str(root/'etc/update-guests.conf')).replace('/var/lock/update-guests.lock',str(root/'var/lock/update-guests.lock')).replace('/var/lib/proxmox-maintenance',str(root/'var/lib/proxmox-maintenance'))
        s=s.replace('export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin','export PATH='+str(mock)+':/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin').replace('EUID==0','EUID=='+str(os.geteuid())).replace('$(stat -c %u "$CONFIG") == 0','$(stat -c %u "$CONFIG") == '+str(os.geteuid()))
        (pkg/'maintenance-recover.sh').write_text(s)
        q=subprocess.run(['bash',str(pkg/'maintenance-recover.sh')],env=dict(os.environ,TRACE=str(trace)),capture_output=True,text=True,timeout=10)
        self.assertEqual(q.returncode,0,q.stderr);tr=trace.read_text();self.assertIn(' restore',tr);self.assertNotIn('pct exec 101',tr)
        for bad in ('apt-get ','docker ','wakeonlan ','pct start ','pct reboot ','pct shutdown ','shutdown -h'):self.assertNotIn(bad,tr)
