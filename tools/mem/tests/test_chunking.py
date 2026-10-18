import unittest

from mem import chunking
from mem.store import Store

PAGE = """# Title

Intro paragraph line one.
line two of intro.

## Section A

A first line.
A second line.

## Section B

B body line.
"""


class TestChunking(unittest.TestCase):
    def test_sections_per_heading_and_skeleton(self):
        chunks = chunking.chunk_markdown(PAGE, max_lines=40, ref="p.md")
        self.assertEqual(len(chunks), 3)  # title, A, B
        for ch in chunks:
            self.assertTrue(ch["text"].startswith("# Title"))
        a = chunks[1]
        self.assertIn("## Section A", a["text"])
        self.assertNotIn("## Section B", a["text"])
        self.assertEqual(a["heading_path"], ["Title", "Section A"])

    def test_line_ranges_resolve(self):
        chunks = chunking.chunk_markdown(PAGE, max_lines=40, ref="p.md")
        a = chunks[1]
        self.assertLessEqual(a["start"], a["end"])
        lines = PAGE.split("\n")
        excerpt = "\n".join(lines[a["start"] - 1:a["end"]])
        self.assertIn("## Section A", excerpt)
        self.assertIn("A first line", excerpt)
        self.assertNotIn("## Section B", excerpt)

    def test_oversized_splits_with_parts(self):
        body = "# Big\n\n" + "\n\n".join(
            "para %d line1\npara %d line2" % (i, i) for i in range(20))
        chunks = chunking.chunk_markdown(body, max_lines=6, ref="b.md")
        self.assertGreater(len(chunks), 1)
        self.assertIn("[Part", chunks[0]["text"])
        covered = set()
        for ch in chunks:
            covered.update(range(ch["start"], ch["end"] + 1))
        self.assertEqual(min(covered), 1)
        self.assertEqual(max(covered), len(body.split("\n")))

    def test_anchor_roundtrip_and_read(self):
        import tempfile, shutil
        root = tempfile.mkdtemp()
        try:
            store = Store(root)
            store.write("raw/x.md", PAGE)
            got = chunking.read_anchored(store, "raw/x.md#L6-L8")
            self.assertIn("Section A", got)
            self.assertIn("A first line", got)
            self.assertIsNone(chunking.read_anchored(store, "raw/x.md#L99-L100"))
            self.assertIsNone(chunking.read_anchored(store, "raw/none.md#L1"))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_parse_anchor(self):
        self.assertEqual(
            chunking.parse_anchor_link("see [[a/b.md#L3-L9]]"),
            ("a/b.md", 3, 9))
        self.assertEqual(chunking.parse_anchor_link("[[c.md]]"),
                         ("c.md", None, None))


if __name__ == "__main__":
    unittest.main()
