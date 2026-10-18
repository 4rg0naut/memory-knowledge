"""Unit tests for ocl (run: .venv/bin/python -m unittest discover -s tests)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from jcs import canonicalize, event_digest, verify_event_digest  # noqa: E402

OCL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ocl")


class TestCanonicalize(unittest.TestCase):
    def test_key_sorting_ascii(self):
        self.assertEqual(canonicalize({"b": 1, "a": 2}), '{"a":2,"b":1}')

    def test_key_sorting_nested(self):
        doc = {"z": {"y": 1, "x": 2}, "a": [3, {"n": None, "m": 1}]}
        self.assertEqual(canonicalize(doc), '{"a":[3,{"m":1}],"z":{"x":2,"y":1}}')

    def test_key_sorting_uses_utf16_order(self):
        # U+1F600 (astral, encodes to surrogates D83D DE00) sorts BEFORE U+E000
        # under UTF-16 code-unit ordering, after under code-point ordering.
        astral = "\U0001F600"
        self.assertLess(_u16(astral), _u16("\uE000"))
        out = canonicalize({"\uE000": 1, astral: 2})
        self.assertTrue(out.startswith('{"' + astral + '":2'), out)
        self.assertLess(out.index('"' + astral + '"'), out.index('"\\uE000"'.encode().decode("unicode_escape")), out)

    def test_number_format_js(self):
        cases = {
            5: "5",
            5.0: "5",
            -0.0: "0",
            0.1: "0.1",
            1e21: "1e+21",
            1.5e-7: "1.5e-7",
            1e-5: "0.00001",
            1000000.5: "1000000.5",
        }
        for value, expected in cases.items():
            self.assertEqual(canonicalize(value), expected, repr(value))

    def test_string_escapes_match_json_stringify(self):
        self.assertEqual(canonicalize('a"b\\c\nd\te\x00f\x7fg'), '"a\\"b\\\\c\\nd\\te\\u0000f\x7fg"')
        self.assertEqual(canonicalize("héllo"), '"héllo"')

    def test_undefined_keys_dropped(self):
        self.assertEqual(canonicalize({"a": 1, "b": None}), '{"a":1}')


def _u16(s):
    units = []
    for ch in s:
        cp = ord(ch)
        if cp < 0x10000:
            units.append(cp)
        else:
            v = cp - 0x10000
            units.extend((0xD800 + (v >> 10), 0xDC00 + (v & 0x3FF)))
    return units


class TestDigest(unittest.TestCase):
    def test_fixture_digest_reproduces(self):
        fixture = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "..",
            "..",
            "vendor",
            "openclaims",
            "fixtures",
            "valid",
            "claim-emitted.json",
        )
        with open(fixture, encoding="utf-8") as handle:
            event = json.load(handle)
        self.assertEqual(event_digest(event)["value"], event["digest"]["value"])

    def test_verify_roundtrip(self):
        event = {"event_id": "evt_1", "x": 1}
        event["digest"] = event_digest(event)
        self.assertTrue(verify_event_digest(event))
        event["x"] = 2
        self.assertFalse(verify_event_digest(event))


class TestCli(unittest.TestCase):
    def run_ocl(self, *args, store=None):
        cmd = [OCL]
        if store:
            cmd += ["--store", store]
        cmd += list(args)
        proc = subprocess.run(cmd, capture_output=True, text=True)
        return proc

    def test_emit_check_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = os.path.join(tmp, "claims.jsonl")
            proc = self.run_ocl(
                "emit",
                "--text",
                "The test suite passes 42/42.",
                "--type",
                "factual",
                "--source-uri",
                "https://example.org/ci",
                "--selector",
                "text_span:10:80",
                "--support-type",
                "supports_directly",
                store=store,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            emitted = json.loads(proc.stdout)
            proc = self.run_ocl(
                "verify",
                emitted["claim_id"],
                "--result",
                "supported",
                "--method",
                "formal_proof",
                "--evidence-uri",
                "https://example.org/ci",
                store=store,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            proc = self.run_ocl("check", emitted["claim_id"], store=store)
            state = json.loads(proc.stdout)
            self.assertEqual(state["status"], "active")
            self.assertEqual(state["last_result"], "supported")
            proc = self.run_ocl("chain", "--verify", store=store)
            self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_tampered_chain_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = os.path.join(tmp, "claims.jsonl")
            for i in range(3):
                self.run_ocl("emit", "--text", "fact %d" % i, "--type", "factual", store=store)
            lines = open(store, encoding="utf-8").read().splitlines()
            event = json.loads(lines[1])
            event["claim"]["text"] = "tampered"
            lines[1] = json.dumps(event)
            open(store, "w", encoding="utf-8").write("\n".join(lines) + "\n")
            proc = self.run_ocl("chain", "--verify", store=store)
            self.assertEqual(proc.returncode, 1)
            report = json.loads(proc.stdout)
            self.assertFalse(report["digest_ok"])


if __name__ == "__main__":
    unittest.main()
