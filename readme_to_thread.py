#!/usr/bin/env python3
"""readme-to-thread — turn a repo README into a launch-thread draft.

Reads a GitHub repo README and drafts the 2-4 post thread you would
write to launch it: what the tool does, how it works, the repo link,
and what building it taught you. Every post fits X's 280-character
limit, counted the way X counts it (every URL weighs 23 characters).

Nothing here is invented. The thread is built only from what the
README actually says: the title, the first paragraph, the feature
list, the "why" section, and the requirements. If the README has no
"why" section, the thread has no lesson post — it ships with three
posts instead of four, rather than making one up.

Usage:
    python readme_to_thread.py README.md
    python readme_to_thread.py README.md --repo https://github.com/Cchubro/reply-scorer
    python readme_to_thread.py README.md --number 2 --plain
    python readme_to_thread.py README.md --json
    python readme_to_thread.py --check thread.txt   # validate a thread file

Options:
    --repo URL     repo link for the final post (default: derived from
                   the README title as https://github.com/Cchubro/<name>)
    --number N     label the launch "Tool #N is live" in the first post
    --limit N      max characters per post (default 280)
    --plain        print posts separated by a blank line, no headers
    --json         print a JSON list of posts with their character counts
    --check FILE   validate a thread file (posts separated by blank lines)
                   and report any post over the limit; exit code 1 if any

Exit codes: 0 ok, 1 --check found an over-limit post, 2 usage/input error.

Built in public by @Cchubro — an AI agent building AI agents in public.
"""

import argparse
import json
import re
import sys

DEFAULT_LIMIT = 280
URL_WEIGHT = 23  # X counts every link as 23 characters (t.co)

URL_RE = re.compile(r"https?://\S+")

# A sentence ends on . ! ? … (Latin or CJK) followed by whitespace or the
# end of the text. The punctuation stays with the sentence it ends.
SENTENCE_END_RE = re.compile(r"(?<=[.!?…。！？])\s+")

# A bullet line in a README: "- item", "* item", or "1. item".
BULLET_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(.*)$")

# A Markdown table row: "| col | col |". The header separator row is
# "|---|---|" and is skipped.
TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
TABLE_SEP_RE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def x_len(text):
    """Length of text the way X counts it: URLs weigh 23, the rest weigh 1."""
    total = 0
    pos = 0
    for m in URL_RE.finditer(text):
        total += len(text[pos:m.start()])
        total += URL_WEIGHT
        pos = m.end()
    total += len(text[pos:])
    return total


def clean_inline(text):
    """Strip Markdown inline formatting, keeping the readable words."""
    # [text](url) -> text (the URL is dropped; the repo link is added
    # separately in the final post, never smuggled in from the README).
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("`", "")
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)  # HTML tags, e.g. <br>
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def split_sentences(text):
    """Split text into sentences, keeping the punctuation."""
    parts = SENTENCE_END_RE.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


def split_sections(text):
    """Split a README into (heading, body) sections.

    Text before the first heading is the preamble, returned with
    heading None. Headings are compared case-insensitively.
    """
    sections = []
    heading = None
    body = []
    for line in text.splitlines():
        m = HEADING_RE.match(line)
        if m:
            sections.append((heading, "\n".join(body)))
            heading = clean_inline(m.group(2)).strip()
            body = []
        else:
            body.append(line)
    sections.append((heading, "\n".join(body)))
    return sections


def first_paragraph(body):
    """First non-empty paragraph of a section body, as plain text."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    for para in paragraphs:
        # Skip code fences and tables — they are not prose.
        if para.startswith("```") or para.startswith("|"):
            continue
        return clean_inline(para)
    return ""


def extract_bullets(body):
    """Bullet / numbered-list items from a section body, as plain text.

    Items may wrap across lines: continuation lines (indented text
    under the bullet, up to the next blank line or bullet) are joined
    in. Each item is shortened to its first sentence, then its first
    clause (before ";"), so a multi-sentence "How it works" item
    becomes one phrase instead of a paragraph smuggled into the thread.
    The first-sentence split uses only "." / "。" — an ellipsis "…"
    mid-sentence (as in "gets a … and a warning") is not a sentence end.
    """
    items = []
    current = None
    for line in body.splitlines():
        m = BULLET_RE.match(line)
        if m:
            if current is not None:
                items.append(current)
            current = clean_inline(m.group(1))
        elif current is not None:
            if not line.strip():
                items.append(current)
                current = None
            elif line.startswith((" ", "\t")):
                current += " " + clean_inline(line)
            else:
                items.append(current)
                current = None
    if current is not None:
        items.append(current)
    shortened = []
    for item in items:
        first = re.split(r"(?<=[.。])\s+", item.strip())
        item = first[0] if first else item
        item = item.split(";")[0].strip().rstrip(".")
        if item:
            shortened.append(item)
    return shortened


def extract_table_first_column(body):
    """First-column cells of a Markdown table, as plain text.

    Feature tables (like reply-scorer's "What it checks") list one
    feature per row; the first column is the feature name. The header
    row (the row before the |---|---| separator) is not a feature.
    Returns a list of (name, detail) pairs; detail is the last column
    (the description), or "" when the table has only one column.
    """
    rows = []
    has_separator = False
    for line in body.splitlines():
        if TABLE_SEP_RE.match(line):
            has_separator = True
            continue
        m = TABLE_ROW_RE.match(line)
        if not m:
            continue
        parts = [c.strip() for c in m.group(1).split("|")]
        if parts and parts[0]:
            detail = clean_inline(parts[-1]) if len(parts) > 1 else ""
            rows.append((clean_inline(parts[0]), detail))
    if has_separator and rows:
        rows = rows[1:]
    return rows


def clean_detail(detail):
    """Shorten a table description to one plain phrase.

    Keeps the first clause (before ";"), drops parenthetical examples,
    lowercases the first letter, strips a trailing period.
    """
    detail = re.sub(r"\([^)]*\)", "", detail)  # parenthetical examples
    detail = detail.split(";")[0].strip()
    detail = re.sub(r"\s+", " ", detail).rstrip(".").strip()
    if detail:
        detail = detail[:1].lower() + detail[1:]
    return detail


def extract_usage(body):
    """First command line of the first fenced code block, if any."""
    m = re.search(r"```(?:\w*)\n(.*?)```", body, re.DOTALL)
    if not m:
        return ""
    for line in m.group(1).splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return ""


def parse_readme(text):
    """Pull the thread material out of a README.

    Returns a dict: name, tagline, features (list), lesson, usage,
    single_file (bool). Raises ValueError on a README with nothing
    usable in it.
    """
    if not text.strip():
        raise ValueError("README is empty")

    sections = split_sections(text)
    preamble = sections[0][1]

    # Name: the first level-1 heading; fall back to the first heading.
    name = ""
    for heading, _body in sections:
        if heading:
            name = heading
            break
    if not name:
        raise ValueError("README has no heading to use as the tool name")
    name = re.sub(r"\s+", "-", name.strip().lower())
    name = re.sub(r"[^a-z0-9_-]", "", name)
    if not name:
        raise ValueError("README heading has no usable tool name in it")

    # Tagline: the first paragraph after the title heading. If the
    # preamble is empty (title and tagline in the same block), use the
    # first paragraph of the first section.
    tagline = first_paragraph(preamble)
    if not tagline:
        for _heading, body in sections[1:]:
            tagline = first_paragraph(body)
            if tagline:
                break
    if not tagline:
        raise ValueError("README has no description paragraph to use")

    features = []
    feature_details = {}
    lesson = ""
    usage = ""
    single_file = False
    for heading, body in sections:
        low = (heading or "").lower()
        if "why" in low or "lesson" in low or "learn" in low:
            if not lesson:
                lesson = first_paragraph(body)
        if not features:
            bullets = extract_bullets(body)
            if bullets:
                features = bullets
            else:
                table_rows = extract_table_first_column(body)
                if table_rows:
                    features = [name for name, _ in table_rows]
                    feature_details = {
                        name: clean_detail(detail)
                        for name, detail in table_rows if detail
                    }
        if not usage:
            usage = extract_usage(body)
        if "no dependencies" in body.lower():
            single_file = True

    # The tagline is sometimes the "why" paragraph itself (a one-section
    # README). Don't repeat it as the lesson.
    if lesson == tagline:
        lesson = ""

    return {
        "name": name,
        "tagline": tagline,
        "features": features,
        "feature_details": feature_details,
        "lesson": lesson,
        "usage": usage,
        "single_file": single_file,
    }


def slugify(name):
    return re.sub(r"[^a-z0-9-]", "", name.lower().replace(" ", "-"))


def fit(text, limit):
    """Shorten `text` to fit `limit` X-chars, if it doesn't already.

    Drops trailing sentences first, then trailing words; a single
    over-long sentence is cut mid-sentence and marked. Returns
    (text, was_cut).
    """
    if x_len(text) <= limit:
        return text, False
    sentences = split_sentences(text)
    while len(sentences) > 1:
        candidate = " ".join(sentences[:-1])
        if x_len(candidate) <= limit:
            return candidate, True
        sentences = sentences[:-1]
    # One sentence left and still too long: cut words from the end.
    words = sentences[0].split()
    while words and x_len(" ".join(words) + "…") > limit:
        words.pop()
    if not words:
        return "…", True
    # A cut that lands right after a comma or colon leaves dangling
    # punctuation ("..., and fit…") — strip it before the ellipsis.
    return " ".join(words).rstrip(",;:") + "…", True


def build_thread(info, repo_url, number=None, limit=DEFAULT_LIMIT):
    """Draft the launch thread from parsed README info.

    Returns (posts, had_hard_cut). Posts are unnumbered bodies here;
    numbering is applied by the caller.
    """
    name = info["name"]
    posts = []

    # Post 1 — what it is. Keep the tagline's first sentence if the
    # whole tagline won't fit; the tagline is the tool's own words.
    opener = f"Tool #{number} is live: {name}." if number else f"{name} is live:"
    tagline_sentences = split_sentences(info["tagline"])
    first_sentence = tagline_sentences[0] if tagline_sentences else info["tagline"]
    post1 = f"{opener} {first_sentence}"
    post1, cut1 = fit(post1, limit)
    posts.append(post1)

    # Post 2 — how it works, from the feature list. A bare list of
    # names reads like a menu, so each feature carries its one-phrase
    # description from the README table when one exists ("specificity
    # (numbers, named terms)"). If that runs long, fall back to bare
    # names, then to fewer features — never to invented filler.
    if info["features"]:
        feats = info["features"][:4]
        details = info.get("feature_details", {})

        def join_features(with_detail):
            parts = []
            for f in feats:
                low = f[:1].lower() + f[1:]
                d = details.get(f, "") if with_detail else ""
                parts.append(f"{low} ({d})" if d else low)
            if len(parts) > 1:
                return ", ".join(parts[:-1]) + ", and " + parts[-1]
            return parts[0]

        post2 = f"It covers: {join_features(True)}."
        if x_len(post2) > limit:
            post2 = f"It covers: {join_features(False)}."
        if x_len(post2) > limit:
            post2 = f"It covers: {join_features(False).rsplit(', and ', 1)[0]}."
        cut2 = False
        post2, cut2 = fit(post2, limit)
    else:
        rest = " ".join(tagline_sentences[1:]) or info["tagline"]
        post2, cut2 = fit(rest, limit)
    posts.append(post2)

    # Post 3 — what building it taught you, from the "why" section.
    # No lesson in the README means no lesson post — never invented.
    cut3 = False
    if info["lesson"]:
        lesson_sentences = split_sentences(info["lesson"])
        post3 = " ".join(lesson_sentences[:2])
        post3, cut3 = fit(post3, limit)
        if post3.strip():
            posts.append(post3)

    # Post 4 — the link. Single-file note only when the README says
    # "no dependencies"; the license line only when the README says MIT.
    bits = []
    if info["single_file"]:
        bits.append("Single-file Python, zero dependencies.")
    bits.append(f"Code: {repo_url}")
    if "mit" in info.get("license_hint", "").lower():
        bits[-1] += " — MIT licensed."
    post4 = " ".join(bits)
    if info["usage"]:
        candidate = f"{post4} Try it: {info['usage']}"
        if x_len(candidate) <= limit:
            post4 = candidate
    post4, cut4 = fit(post4, limit)
    posts.append(post4)

    had_hard_cut = any([cut1, cut2, cut3, cut4])
    return posts, had_hard_cut


def number_posts(posts, limit):
    """Add the "i/N " prefix, resolving the width by fixed-point
    iteration (the prefix eats characters, and N depends on the count).
    """
    prefix_width = 0
    numbered = posts
    for _ in range(5):
        body_limit = limit - prefix_width
        if body_limit < 1:
            raise ValueError("limit too small for the numbering prefix")
        refit = []
        for post in posts:
            fitted, _ = fit(post, body_limit)
            refit.append(fitted)
        n = len(refit)
        new_width = len(f"{n}/{n} ")
        if new_width == prefix_width:
            numbered = refit
            break
        prefix_width = new_width
        numbered = refit
    else:
        numbered = refit
    n = len(numbered)
    return [f"{i + 1}/{n} {p}" for i, p in enumerate(numbered)]


def read_readme(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError as e:
        print(f"readme-to-thread: cannot read {path}: {e}", file=sys.stderr)
        sys.exit(2)


def check_thread(path, limit):
    """Validate a thread file: posts separated by blank lines."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        print(f"readme-to-thread: cannot read {path}: {e}", file=sys.stderr)
        return 2
    posts = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    bad = 0
    for i, post in enumerate(posts, 1):
        n = x_len(post)
        status = "OK " if n <= limit else "OVER"
        if n > limit:
            bad += 1
        print(f"{status} {i}/{len(posts)}: {n}/{limit} chars")
    if bad:
        print(f"{bad} post(s) over the {limit}-char limit.", file=sys.stderr)
        return 1
    if not posts:
        print("readme-to-thread: thread file is empty.", file=sys.stderr)
        return 2
    print(f"All {len(posts)} post(s) fit within {limit} chars.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Turn a repo README into a launch-thread draft.")
    parser.add_argument("file", nargs="?",
                        help="README file to turn into a thread")
    parser.add_argument("--repo",
                        help="repo link for the final post "
                             "(default: https://github.com/Cchubro/<name>)")
    parser.add_argument("--number", type=int, default=None,
                        help='label the launch "Tool #N is live"')
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"max characters per post (default {DEFAULT_LIMIT})")
    parser.add_argument("--plain", action="store_true",
                        help="print posts separated by a blank line, no headers")
    parser.add_argument("--json", action="store_true",
                        help="print a JSON list of posts with character counts")
    parser.add_argument("--check", metavar="FILE",
                        help="validate a thread file instead of generating")
    args = parser.parse_args(argv)

    if args.limit < 10:
        print("readme-to-thread: --limit must be at least 10.", file=sys.stderr)
        return 2

    if args.check:
        return check_thread(args.check, args.limit)

    if not args.file:
        if sys.stdin.isatty():
            print("readme-to-thread: no input — pass a README file.",
                  file=sys.stderr)
            return 2
        text = sys.stdin.read()
    else:
        text = read_readme(args.file)

    try:
        info = parse_readme(text)
    except ValueError as e:
        print(f"readme-to-thread: {e}", file=sys.stderr)
        return 2

    # License hint: only claim MIT when the README itself says so.
    info["license_hint"] = "MIT" if re.search(r"\bMIT\b", text) else ""
    repo_url = args.repo or f"https://github.com/Cchubro/{slugify(info['name'])}"

    try:
        posts, had_hard_cut = build_thread(info, repo_url, args.number, args.limit)
        posts = number_posts(posts, args.limit)
    except ValueError as e:
        print(f"readme-to-thread: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(
            [{"n": i + 1, "total": len(posts), "chars": x_len(p), "text": p}
             for i, p in enumerate(posts)],
            ensure_ascii=False, indent=2))
    elif args.plain:
        print("\n\n".join(posts))
    else:
        for i, post in enumerate(posts, 1):
            print(f"--- {i}/{len(posts)} ({x_len(post)} chars) ---")
            print(post)
            print()

    if had_hard_cut:
        print(
            "warning: a post had to be shortened to fit the limit — "
            "check it still reads well before posting.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
