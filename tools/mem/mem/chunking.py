"""Section-aware markdown chunking + line-anchor links (E1, ADR-0011).

ReMe pattern (ACL Findings 2026): split on the heading tree, never
mid-wikilink, and prefix each chunk with its heading skeleton so a
small model sees the chunk's structural position, not an orphaned
fragment. Chunks carry 1-based inclusive line ranges; the anchor form
``[[rel#L9-L12]]`` is the canonical citation link for daily cards,
graph edges, and evidence re-checks.

Chunk text = skeleton headings + body. Ranges refer to the ORIGINAL
body lines (frontmatter already stripped by the caller via
codec.split_frontmatter), so anchors always resolve with read(start_
line=..., end_line=...).
"""

import re

_ANCHOR_LINK_RE = re.compile(r"\[\[([^\]#]+)(?:#L(\d+)(?:-L(\d+))?)?\]\]")
_HEADING_RE = re.compile(r"^(#{1,6}) (.*)$")


def parse_anchor_link(text):
    """First anchor link in text -> (target, start_line, end_line|None)
    or None."""
    m = _ANCHOR_LINK_RE.search(text)
    if not m:
        return None
    start = int(m.group(2)) if m.group(2) else None
    end = int(m.group(3)) if m.group(3) else None
    return m.group(1).strip(), start, end


def anchor(ref, start, end=None):
    end = end if end is not None else start
    return "%s#L%d-L%d" % (ref, start, end)


def chunk_markdown(text, max_lines=48, ref=""):
    """-> [{'ref','start','end','text','heading_path'}].

    Sections per heading boundary; oversized sections split at
    paragraph (blank-line) boundaries, then at line boundaries with a
    [Part x/y] marker. Every chunk text is prefixed by the heading
    skeleton (the stack of headings above it)."""
    lines = text.split("\n")
    n = len(lines)
    sections = []
    stack = []
    start = 0
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if not m:
            continue
        level = len(m.group(1))
        if i > start:
            sections.append((list(stack), start, i))
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, m.group(2)))
        start = i
    if start < n:
        sections.append((list(stack), start, n))

    chunks = []
    for sec_stack, a, b in sections:
        blocks = _split_oversized(lines, a, b, max_lines)
        total = len(blocks)
        for part, (x, y) in enumerate(blocks, 1):
            skeleton = "\n".join("#" * lv + " " + t
                                 for lv, t in sec_stack) + "\n"
            marker = "" if total == 1 else " [Part %d/%d]" % (part, total)
            body = "\n".join(lines[x - 1:y])
            chunks.append({
                "ref": anchor(ref, x, y) if ref else "%d-%d" % (x, y),
                "start": x,
                "end": y,
                "heading_path": [t for _, t in sec_stack],
                "text": (skeleton.rstrip("\n") + marker + "\n" + body
                         if sec_stack else body + marker),
            })
    return chunks


def _split_oversized(lines, a, b, max_lines):
    """Split section [a,b) at blank-line paragraph boundaries (a, b are
    0-based slice bounds) -> list of (start_line_1based, end_line_1based)."""
    if b - a <= max_lines:
        return [(a + 1, b)]
    paras = []
    cur = None
    for i in range(a, b):
        if lines[i].strip() == "":
            if cur:
                paras.append(cur)
            cur = None
        elif cur is None:
            cur = [i, i]
        else:
            cur[1] = i
    if cur:
        paras.append(cur)
    blocks, cur = [], None
    for x, y in paras:
        if y - x + 1 > max_lines:
            if cur:
                blocks.append((cur[0] + 1, cur[1] + 1))
                cur = None
            s = x
            while y - s + 1 > max_lines:
                blocks.append((s + 1, s + max_lines))
                s += max_lines
            if s <= y:
                cur = [s, y]
            continue
        if cur is None:
            cur = [x, y]
        elif cur[1] - cur[0] + 1 + (y - x + 1) <= max_lines:
            cur[1] = y
        else:
            blocks.append((cur[0] + 1, cur[1] + 1))
            cur = [x, y]
    if cur:
        blocks.append((cur[0] + 1, cur[1] + 1))
    return blocks or [(a + 1, b)]


def read_anchored(store, ref):
    """Read a chunk by anchor ref (rel#Lx-Ly) -> text, or None if the
    line range no longer resolves (evidence drift)."""
    parsed = parse_anchor_link("[[" + ref + "]]")
    if not parsed:
        return None
    path, start, end = parsed
    if not store.exists(path):
        return None
    lines = store.read(path).split("\n")
    if start is None:
        return store.read(path)
    if end is None:
        end = start
    if not (1 <= start <= end <= len(lines)):
        return None
    return "\n".join(lines[start - 1:end])
