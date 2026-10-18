"""G-G3: bootstrap CIs on the eval harness + seed rotation.
Sampling noise may not decide architecture: overlapping intervals
yield 'inconclusive', never a winner."""

import json
import shutil
import tempfile
import unittest

from mem import evalkit, graph, hygiene, distill
from mem.store import Store
from tests.test_evalkit import Base, RAW


class TestBootstrapCI(unittest.TestCase):
    def test_deterministic_given_seed(self):
        s = [1.0, 0.0, 0.5, 0.25, 0.0, 1.0, 0.125, 0.0]
        a = evalkit.bootstrap_ci(s, seed=7)
        b = evalkit.bootstrap_ci(s, seed=7)
        self.assertEqual(a, b)

    def test_brackets_mean(self):
        s = [1.0, 0.0, 0.5, 0.25, 0.0, 1.0, 0.125, 0.0]
        lo, hi = evalkit.bootstrap_ci(s)
        mean = sum(s) / len(s)
        self.assertLessEqual(lo, mean + 1e-9)
        self.assertGreaterEqual(hi, mean - 1e-9)

    def test_empty_returns_none(self):
        self.assertIsNone(evalkit.bootstrap_ci([]))

    def test_overlap_rule(self):
        self.assertTrue(evalkit.ci_overlap([0.1, 0.5], [0.4, 0.9]))
        self.assertFalse(evalkit.ci_overlap([0.1, 0.3], [0.4, 0.9]))
        self.assertFalse(evalkit.ci_overlap(None, [0.1, 0.2]))


def _mode(mrr, mh_mrr, mh_ci, exact=1.0, tok=100.0):
    return {"mrr": mrr, "tokens_per_query": tok,
            "per_type": {
                "multihop": {"n": 50, "mrr": mh_mrr, "ci95": mh_ci},
                "conceptual": {"n": 50, "mrr": 0.5, "ci95": [0.4, 0.6]},
                "exact": {"n": 50, "mrr": exact, "ci95": [exact, exact]}}}


class TestScorecardCI(unittest.TestCase):
    def test_overlap_yields_inconclusive(self):
        rep = {"graph": _mode(0.80, 0.30, [0.25, 0.35]),
               "fused": _mode(0.81, 0.28, [0.24, 0.34])}
        self.assertEqual(graph.scorecard(rep), "inconclusive")

    def test_disjoint_gain_yields_keep(self):
        rep = {"graph": _mode(0.80, 0.40, [0.35, 0.45]),
               "fused": _mode(0.81, 0.25, [0.20, 0.30])}
        self.assertEqual(graph.scorecard(rep), "keep-graph")

    def test_legacy_report_without_ci_unchanged(self):
        rep = {"graph": {"mrr": 0.8, "tokens_per_query": 100.0,
                         "per_type": {"multihop": {"n": 50, "mrr": 0.30},
                                      "conceptual": {"n": 50, "mrr": 0.6},
                                      "exact": {"n": 50, "mrr": 1.0}}},
               "fused": {"mrr": 0.81, "tokens_per_query": 100.0,
                         "per_type": {"multihop": {"n": 50, "mrr": 0.2},
                                      "conceptual": {"n": 50, "mrr": 0.5},
                                      "exact": {"n": 50, "mrr": 1.0}}}}
        self.assertEqual(graph.scorecard(rep), "keep-graph")


class TestRunCI(Base):
    def test_run_reports_ci_and_tokens(self):
        qs = evalkit.build_queryset(self.store, n=8, seed=1)
        rep = evalkit.run(self.store, modes=("baseline", "fused"),
                          queryset=qs, keep_samples=True, seed=11)
        self.assertNotIn("error", rep)
        self.assertEqual(rep["ci_seed"], 11)
        for m, mv in rep["modes"].items():
            self.assertIsNotNone(mv["mrr_ci95"])
            self.assertLessEqual(mv["mrr_ci95"][0], mv["mrr"] + 1e-9)
            self.assertGreaterEqual(mv["mrr_ci95"][1], mv["mrr"] - 1e-9)
            self.assertGreater(mv["tokens_per_query"], 0)
            for t, tv in mv["per_type"].items():
                if tv["n"]:
                    self.assertTrue(isinstance(tv["ci95"], list)
                                    or tv["ci95"] is None)
        self.assertIn("rr_samples", rep)

    def test_ci_deterministic_across_runs(self):
        qs = evalkit.build_queryset(self.store, n=8, seed=1)
        r1 = evalkit.run(self.store, modes=("baseline",), queryset=qs,
                         seed=5)
        r2 = evalkit.run(self.store, modes=("baseline",), queryset=qs,
                         seed=5)
        self.assertEqual(r1["modes"]["baseline"]["mrr_ci95"],
                         r2["modes"]["baseline"]["mrr_ci95"])
        self.assertEqual(r1["modes"]["baseline"]["per_type"],
                         r2["modes"]["baseline"]["per_type"])


class TestRotation(Base):
    def test_rotation_pools_and_reports_variance(self):
        out = evalkit.run_rotation(self.store, seeds=[1, 2],
                                   modes=("baseline", "fused"))
        self.assertNotIn("error", out)
        self.assertEqual(len(out["per_seed"]), 2)
        self.assertIn("baseline", out["modes"])
        n_pool = sum(out["modes"][m]["per_type"][t]["n"]
                     for m in out["modes"]
                     for t in out["modes"][m]["per_type"])
        n_seeds = sum(p["n"] for p in out["per_seed"]) * \
            len(out["modes"])
        self.assertEqual(n_pool, n_seeds)
        for m in out["modes"]:
            self.assertIsNotNone(out["modes"][m]["mrr_ci95"])
            self.assertIn(m, out["mrr_variance_across_seeds"])
            self.assertGreater(out["modes"][m]["tokens_per_query"], 0)
        stored = json.loads(self.store.read("metadata/eval_rotation.json"))
        self.assertEqual(stored["seeds"], [1, 2])

    def test_rotation_seed_shas_reported(self):
        out = evalkit.run_rotation(self.store, seeds=[3, 4],
                                   modes=("baseline",))
        shas = {p["queryset_sha"] for p in out["per_seed"]}
        self.assertEqual(len(shas), 2)


class TestCliRotations(Base):
    def _cli(self, argv):
        import contextlib
        import io
        from mem import cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main(["--home", self.store.root] + argv)
        return code, buf.getvalue()

    def test_eval_rotations_exit_zero_with_section(self):
        code, out = self._cli(["eval", "--rotations", "2",
                               "--seed", "1",
                               "--modes", "baseline,fused"])
        self.assertEqual(code, 0, out)
        rot = json.loads(out)["rotation"]
        self.assertEqual(len(rot["per_seed"]), 2)
        self.assertIn("mrr_variance_across_seeds", rot)


if __name__ == "__main__":
    unittest.main()
