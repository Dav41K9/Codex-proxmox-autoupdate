"""Exercise the one-file hotfix in a disposable filesystem, never the Proxmox host."""
import fcntl, hashlib, json, os, pathlib, subprocess, sys, tempfile, unittest

REPO=pathlib.Path(__file__).resolve().parents[1]
BASE='ebc9f6249c4c23e51479cf9043a419860e36e6fc'
FILES=('coordinator.sh','docker-maint.py','pve-guest-worker.sh','state.py')

@unittest.skipUnless(os.geteuid()==0,'root ownership checks require an isolated root test runner')
class Hotfix(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=pathlib.Path(self.tmp.name)
        self.releases=self.root/'releases';self.old=self.releases/'old';self.old.mkdir(parents=True)
        self.current=self.root/'current';self.current.symlink_to(self.old)
        self.backups=self.root/'backups';self.backups.mkdir()
        self.lock=self.root/'worker.lock'
        self.before={}
        for name in FILES:
            data=subprocess.check_output(['git','show',BASE+':proxmox-maintenance/'+name],cwd=REPO)
            (self.old/name).write_bytes(data);self.before[name]=data
        code=(REPO/'fixes/apply-alerts-4.1.1.py').read_text()
        for old,new in [
            ("current=pathlib.Path('/usr/local/libexec/pve-maintenance-current')","current=pathlib.Path("+repr(str(self.current))+")"),
            ("releases=pathlib.Path('/usr/local/libexec/pve-maintenance-releases')","releases=pathlib.Path("+repr(str(self.releases))+")"),
            ("lock=os.open('/var/lock/update-guests.lock',","lock=os.open("+repr(str(self.lock))+","),
            ("backup=pathlib.Path('/var/backups')","backup=pathlib.Path("+repr(str(self.backups))+")"),
        ]:
            self.assertEqual(code.count(old),1);code=code.replace(old,new)
        self.script=self.root/'apply.py';self.script.write_text(code)

    def run_patch(self,mode):
        return subprocess.run([sys.executable,str(self.script),mode],capture_output=True,text=True,timeout=30)

    def test_check_does_not_switch_release(self):
        q=self.run_patch('--check')
        self.assertEqual(q.returncode,0,q.stderr);self.assertIn('CHECK OK',q.stdout)
        self.assertEqual(self.current.resolve(),self.old);self.assertEqual(list(self.backups.iterdir()),[])
        for name,data in self.before.items():self.assertEqual((self.old/name).read_bytes(),data)

    def test_apply_preserves_old_release_and_repeat_is_idempotent(self):
        q=self.run_patch('--apply')
        self.assertEqual(q.returncode,0,q.stderr);self.assertIn('APPLICATO:',q.stdout)
        new=self.current.resolve();self.assertNotEqual(new,self.old)
        for name,data in self.before.items():
            self.assertEqual((self.old/name).read_bytes(),data)
            self.assertEqual((new/name).read_bytes(),(REPO/'proxmox-maintenance'/name).read_bytes())
        backup=list(self.backups.iterdir());self.assertEqual(len(backup),1)
        self.assertEqual((backup[0]/'previous-release').read_text().strip(),str(self.old))
        q=self.run_patch('--apply');self.assertEqual(q.returncode,0,q.stderr)
        self.assertIn('gia applicato',q.stdout);self.assertEqual(self.current.resolve(),new)
        self.assertEqual(len(list(self.backups.iterdir())),1)

    def test_local_edits_are_not_overwritten(self):
        (self.old/'state.py').write_text('# local change\n')
        q=self.run_patch('--apply')
        self.assertNotEqual(q.returncode,0);self.assertIn('Versione locale diversa',q.stderr)
        self.assertEqual(self.current.resolve(),self.old);self.assertEqual(list(self.backups.iterdir()),[])

    def test_busy_job_lock_blocks_patch(self):
        with open(self.lock,'w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            q=self.run_patch('--apply')
        self.assertNotEqual(q.returncode,0);self.assertIn('Job manutenzione attivo',q.stderr)
        self.assertEqual(self.current.resolve(),self.old)

    def test_failed_regression_test_prevents_switch(self):
        code=self.script.read_text()
        code=code.replace('\ndef main():\n','\nPAYLOAD["tests"]="raise RuntimeError(\'injected test failure\')"\n\ndef main():\n',1)
        self.script.write_text(code)
        q=self.run_patch('--apply')
        self.assertNotEqual(q.returncode,0);self.assertEqual(self.current.resolve(),self.old)
        self.assertEqual(list(self.backups.iterdir()),[])

if __name__=='__main__':unittest.main()
