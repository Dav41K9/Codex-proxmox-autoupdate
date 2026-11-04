"""NAS ACL mode tests: temporary files and mocked mount inspection only."""
import contextlib,importlib.util,json,os,pathlib,subprocess,sys,tempfile,time,unittest
from unittest.mock import patch
SRC=pathlib.Path(os.environ.get('PVE_MAINT_TEST_SRC',str(pathlib.Path(__file__).resolve().parents[1]/'proxmox-maintenance')))
spec=importlib.util.spec_from_file_location('nas_state',SRC/'state.py')
state=importlib.util.module_from_spec(spec);spec.loader.exec_module(state)

class NasAcl(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=pathlib.Path(self.tmp.name)
        self.store=state.Store(self.root/'local');self.addCleanup(self.store.db.close)
        self.store.begin('run','proxmox','2026-11-04',False)
        _,self.name=self.store.finish('run')
        self.mount=self.root/'nas';self.dest=self.mount/'proxmox-maintenance'/'reports'
        self.dest.mkdir(parents=True);self.dest.chmod(0o777);self.dest.parent.chmod(0o777)
        self.mount_result=subprocess.CompletedProcess([],0,json.dumps({'filesystems':[{'target':str(self.mount),'fstype':'nfs4'}]}),'')
        self.outbox=self.store.root/'outbox'/self.name
    def archive(self,mode='server-acl'):
        with patch.object(state.subprocess,'run',return_value=self.mount_result):
            self.store.archive(self.mount,mode)

    def test_private_default_still_rejects_shared_permissions(self):
        with patch.object(state.subprocess,'run',return_value=self.mount_result):
            with self.assertRaisesRegex(ValueError,'permissions 777'):
                self.store.archive(self.mount)
        self.assertTrue(self.outbox.exists())
        self.assertEqual(self.dest.stat().st_mode&0o777,0o777)

    def test_acl_mode_archives_without_rewriting_permissions(self):
        expected=self.outbox.read_bytes()
        self.archive()
        self.assertEqual((self.dest/self.name).read_bytes(),expected)
        self.assertFalse(self.outbox.exists())
        for p in (self.dest,self.dest.parent):self.assertEqual(p.stat().st_mode&0o777,0o777)
        receipt=json.loads((self.store.root/'receipts'/(self.name+'.json')).read_text())
        self.assertEqual(receipt['permission_mode'],'server-acl')
        self.archive()

    def test_unknown_mode_fails_before_copy(self):
        with self.assertRaisesRegex(ValueError,'Invalid NAS permission mode'):self.archive('off')
        self.assertTrue(self.outbox.exists())

    def test_acl_mode_still_requires_exact_nfs_mount(self):
        for target,fstype in [(str(self.root),'nfs4'),(str(self.mount),'ext4')]:
            q=subprocess.CompletedProcess([],0,json.dumps({'filesystems':[{'target':target,'fstype':fstype}]}),'')
            with self.subTest(target=target,fstype=fstype),patch.object(state.subprocess,'run',return_value=q):
                with self.assertRaisesRegex(ValueError,'NAS not mounted exactly'):self.store.archive(self.mount,'server-acl')
        self.assertTrue(self.outbox.exists())

    def test_acl_mode_rejects_directory_symlink(self):
        self.dest.rmdir();self.dest.symlink_to(self.root)
        with self.assertRaisesRegex(ValueError,'NAS symlink'):self.archive()
        self.assertTrue(self.outbox.exists())

    def test_acl_mode_rejects_file_symlink_and_preserves_target(self):
        target=self.root/'keep';target.write_text('keep')
        (self.dest/self.name).symlink_to(target)
        with self.assertRaisesRegex(ValueError,'NAS collision'):self.archive()
        self.assertEqual(target.read_text(),'keep');self.assertTrue(self.outbox.exists())

    def test_acl_mode_rejects_report_collision(self):
        (self.dest/self.name).write_text('different')
        with self.assertRaisesRegex(ValueError,'NAS collision'):self.archive()
        self.assertEqual((self.dest/self.name).read_text(),'different');self.assertTrue(self.outbox.exists())

    def test_acl_mode_checks_readback_before_receipt(self):
        with patch.object(state,'atomic',side_effect=lambda p,data:p.write_bytes(b'corrupted')):
            with self.assertRaisesRegex(ValueError,'NAS readback'):self.archive()
        self.assertTrue(self.outbox.exists())
        self.assertFalse((self.store.root/'receipts'/(self.name+'.json')).exists())

    def test_write_failure_keeps_outbox(self):
        with patch.object(state,'atomic',side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):self.archive()
        self.assertTrue(self.outbox.exists())

    def test_acl_mode_retention_only_deletes_managed_old_report(self):
        self.store.db.execute('UPDATE archives SET created=?',(time.time()-61*86400,));self.store.db.commit()
        (self.dest/'unrelated.md').write_text('keep')
        self.archive()
        self.assertFalse((self.dest/self.name).exists())
        self.assertEqual((self.dest/'unrelated.md').read_text(),'keep')

    def test_coordinator_passes_configured_mode_and_defaults_private(self):
        source=(SRC/'coordinator.sh').read_text()
        function='finish(){'+source.split('finish(){',1)[1].split('\non_exit(){',1)[0]
        harness=r'''
set -u
STATE=$FIX
RUN_ID=run
SCOPE=proxmox
NAS_MOUNT=/unused
SEND_TELEGRAM=0
NO_TELEGRAM=0
store(){
  case "$1" in
    finish) echo 'OK|run.md';;
    summary) echo report;;
    archive) printf '%s\n' "$3" >"$FIX/policy";;
    *) return 99;;
  esac
}
telegram(){ return 0; }
kill(){ return 1; }
sleep(){ :; }
'''
        for configured,expected in [(None,'private'),('server-acl','server-acl')]:
            env=dict(os.environ,FIX=str(self.root));env.pop('NAS_PERMISSION_MODE',None)
            if configured:env['NAS_PERMISSION_MODE']=configured
            q=subprocess.run(['bash','-c',harness+'\n'+function+'\nfinish'],env=env,capture_output=True,text=True,timeout=10)
            self.assertEqual(q.returncode,0,q.stderr)
            self.assertEqual((self.root/'policy').read_text().strip(),expected)

if __name__=='__main__':unittest.main()
