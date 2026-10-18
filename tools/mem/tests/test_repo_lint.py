import os
import subprocess
import sys
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(
    __file__)), *[".."] * 3))
LINT = os.path.join(REPO, "tests", "repo_lint.py")
sys.path.insert(0, os.path.join(REPO, "tests"))


class TestRepoLint(unittest.TestCase):
    def test_head_commit_discipline(self):
        r = subprocess.run([os.environ.get("PYTHON", "python3"), LINT],
                           cwd=REPO, capture_output=True, text=True)
        if r.returncode == 2:
            self.skipTest("not a git repo")
        self.assertEqual(r.returncode, 0,
                         "repo_lint: %s" % (r.stdout + r.stderr))

    def test_violation_detected_on_synthetic_commit(self):
        import repo_lint
        touched = ["tools/mem/mem/store.py"]
        self.assertTrue(repo_lint.BEHAVIOR_RE.match(touched[0]))
        self.assertFalse(repo_lint.ADR_REF_RE.search("mem: tweak store"))
        self.assertTrue(repo_lint.ADR_REF_RE.search(
            "mem: codec stamp [ADR-0004]"))


if __name__ == "__main__":
    unittest.main()
