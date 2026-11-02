"""Regression tests for actionable alerts. No live Proxmox/Docker/SSH calls."""
import contextlib, importlib.util, io, json, os, pathlib, subprocess, tempfile, unittest
from unittest.mock import patch

SRC=pathlib.Path(os.environ.get('PVE_MAINT_TEST_SRC',str(pathlib.Path(__file__).resolve().parents[1]/'proxmox-maintenance')))
def module(name):
    spec=importlib.util.spec_from_file_location(name,SRC/(name+'.py'))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
dm=module('docker-maint');state=module('state')

class Alerts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=pathlib.Path(self.tmp.name);dm.FAIL=0

    def policy(self,images):
        output=io.StringIO()
        with patch.object(dm,'ROOT',self.root),contextlib.redirect_stdout(output):
            path=dm.override({'services':{k:{'image':v} for k,v in images.items()}},'p','/app')
        return (json.loads(pathlib.Path(path).read_text())['services'] if path else {}),output.getvalue()

    def test_hub_names_apply_mobile_policy(self):
        images={'redis':'docker.io/library/redis:8','gotenberg':'docker.io/gotenberg/gotenberg:8.25'}
        policy,out=self.policy(images)
        self.assertEqual(policy['redis']['image'],'docker.io/library/redis:latest')
        self.assertEqual(policy['gotenberg']['image'],'docker.io/gotenberg/gotenberg:latest')
        self.assertNotIn('WARN|',out)

    def test_database_patch_pins_broaden_only_inside_allowed_branch(self):
        policy,out=self.policy({'pg':'docker.io/library/postgres:18.1','db':'mariadb:12.3.1'})
        self.assertEqual(policy['pg']['image'],'docker.io/library/postgres:18')
        self.assertEqual(policy['db']['image'],'mariadb:12.3')
        self.assertNotIn('WARN|',out)

    def test_existing_mobile_database_is_information(self):
        policy,out=self.policy({'db':'couchdb:latest'})
        self.assertEqual(policy,{})
        self.assertIn('NOTE|',out);self.assertNotIn('WARN|',out)

    def test_private_registry_is_not_mistaken_for_docker_hub(self):
        policy,out=self.policy({'db':'registry.example:5000/library/postgres:18'})
        self.assertEqual(policy,{})
        self.assertIn('WARN|',out)

    def test_immutable_image_is_still_actionable(self):
        policy,out=self.policy({'app':'example/app@sha256:'+'a'*64})
        self.assertEqual(policy,{})
        self.assertIn('WARN|',out);self.assertIn('tag aggiornabile',out)

    def test_running_without_probe_is_note_not_warning(self):
        out=io.StringIO()
        with patch.object(dm,'inspect',return_value={'Running':True}),contextlib.redirect_stdout(out):
            dm.health(['app'])
        self.assertIn('NOTE|',out.getvalue());self.assertNotIn('WARN|',out.getvalue());self.assertEqual(dm.FAIL,0)

    def test_unhealthy_remains_a_failure(self):
        with patch.object(dm,'inspect',return_value={'Running':True,'Health':{'Status':'unhealthy'}}),patch.dict(os.environ,COMPOSE_WAIT_SECONDS='0'),contextlib.redirect_stdout(io.StringIO()):
            dm.health(['app'])
        self.assertEqual(dm.FAIL,1)

    def ledger(self):
        s=state.Store(self.root/'ledger');self.addCleanup(s.db.close)
        s.begin('test','proxmox','today',False);return s

    def test_summary_canonicalizes_targets_and_reports_warn_reason(self):
        s=self.ledger()
        s.event('test','NOTE','LXC 106','begin')
        s.event('test','WARN','lxc 106','Snapshot fallito')
        s.event('test','NOTE','node2 root@10.99.0.2','APT OK')
        s.event('test','NOTE','nodo2','Gia acceso: non verra spento')
        text=s.summary('test')
        self.assertIn('OK 1 | ❌ FAIL 0 | WARN 1',text)
        self.assertIn('WARN LXC 106: Snapshot fallito',text)
        self.assertIn('Nodo 2: Gia acceso: non verra spento',text)

    def test_summary_prioritizes_action_and_deduplicates_events(self):
        s=self.ledger()
        for _ in range(3):s.event('test','WARN','lxc 106','Snapshot fallito')
        s.event('test','FAIL','LXC 101','APT update fallito')
        s.event('test','ACTION','LXC 200','Guest rimasto acceso')
        text=s.summary('test')
        self.assertLess(text.index('INTERVENTO LXC 200'),text.index('FAIL LXC 101'))
        self.assertLess(text.index('FAIL LXC 101'),text.index('WARN LXC 106'))
        self.assertEqual(text.count('Snapshot fallito'),1)

    def test_summary_bounds_large_alerts_and_keeps_overflow_count(self):
        s=self.ledger()
        for i in range(20):s.event('test','WARN','target'+str(i),'x'*1000)
        text=s.summary('test')
        self.assertLess(len(text),1800);self.assertIn('Altri 14 avvisi/errori',text)

    def test_reboot_request_and_completion_are_one_verified_target(self):
        s=self.ledger()
        s.event('test','REBOOT','lxc 1000','Hermes richiede reboot')
        s.event('test','REBOOT','LXC 1000','Reboot completo verificato da boot_id')
        text=s.summary('test')
        self.assertIn('Reboot: LXC 1000 verificato',text)
        self.assertNotIn('richiesto',text)

    def test_expected_conditions_leave_report_ok(self):
        s=self.ledger()
        s.event('test','NOTE','lxc 200','running; healthcheck non configurato')
        s.event('test','NOTE','lxc 106','canale DB mobile esistente')
        status,_=s.finish('test')
        self.assertEqual(status,'OK')

    def hermes(self,scenario):
        source=(SRC/'pve-guest-worker.sh').read_text()
        function=source.split('hermes_health() {',1)[1].split('\ndocker_phase()',1)[0]
        harness=r'''
set -u
tick=0
fail(){ printf 'FAIL:%s\n' "$*"; }
note(){ printf 'NOTE:%s\n' "$*"; }
sleep(){ tick=$((tick+1)); }
systemctl(){
    if [[ "$1" == is-active ]];then
        [[ "$SCENARIO" != inactive ]] || return 1
        [[ "$SCENARIO" != delayed || "$tick" -ge 2 ]] || return 1
        [[ "$SCENARIO" != drops || "$tick" -lt 3 ]] || return 1
        return 0
    fi
    if [[ "$SCENARIO" == unreadable ]];then return 1;fi
    if [[ "$SCENARIO" == empty ]];then return 0;fi
    count=0
    [[ "$SCENARIO" != restarts || "$tick" -lt 3 ]] || count=1
    printf 'MainPID=42\nNRestarts=%s\nExecMainStartTimestampMonotonic=123\n' "$count"
}
'''
        q=subprocess.run(['bash','-c',harness+'\nhermes_health() {'+function+'\nhermes_health'],env=dict(os.environ,SCENARIO=scenario),capture_output=True,text=True,timeout=10)
        self.assertEqual(q.returncode,0,q.stderr);return q.stdout

    def test_hermes_stable_service_is_note(self):
        self.assertNotIn('FAIL:',self.hermes('stable'))

    def test_hermes_boot_delay_is_allowed(self):
        out=self.hermes('delayed');self.assertIn('stabile per 20',out);self.assertNotIn('FAIL:',out)

    def test_hermes_restart_loop_fails(self):
        self.assertIn('FAIL:Dashboard Hermes riavviata',self.hermes('restarts'))

    def test_hermes_drops_after_active_fails(self):
        self.assertIn('FAIL:Dashboard Hermes non stabile',self.hermes('drops'))

    def test_hermes_unreadable_state_fails(self):
        self.assertIn('FAIL:',self.hermes('unreadable'))

    def test_hermes_missing_state_fails(self):
        self.assertIn('FAIL:',self.hermes('empty'))

    def test_hermes_never_ready_fails(self):
        self.assertIn('FAIL:Dashboard Hermes non pronta',self.hermes('inactive'))

if __name__=='__main__':unittest.main()
