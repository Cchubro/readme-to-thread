#!/usr/bin/env python3
"""Tests for readme_to_thread.py.

The sample README is the real reply-scorer README (see the goal daily
log): the generated thread must read well, fit the limit, and only say
things that README actually says.
Run: python -m unittest test_readme_to_thread.py -v
"""

import os
import subprocess
import sys
import tempfile
import unittest

from readme_to_thread import (
    build_thread,
    check_thread,
    clean_inline,
    fit,
    number_posts,
    parse_readme,
    x_len,
)

HERE = os.path.dirname(os.path.abspath(__file__))
REPLY_SCORER_README = os.path.join(
    HERE, "..", "reply-scorer", "README.md")

with open(REPLY_SCORER_README, encoding="utf-8") as f:
    REPLY_SCORER_TEXT = f.read()


class TestXLen(unittest.TestCase):
    def test_link_counts_23(self):
        self.assertEqual(
            x_len("see https://example.com/a/very/long/path here"), 4 + 23 + 5)

    def test_plain_text_unchanged(self):
        self.assertEqual(x_len("hello world"), 11)


class TestParseReadme(unittest.TestCase):
    def test_name_from_title(self):
        info = parse_readme(REPLY_SCORER_TEXT)
        self.assertEqual(info["name"], "reply-scorer")

    def test_tagline_is_first_paragraph(self):
        info = parse_readme(REPLY_SCORER_TEXT)
        self.assertTrue(info["tagline"].startswith("Score a reply draft 0"))
        self.assertIn("starts a conversation", info["tagline"])

    def test_features_from_checks_table(self):
        info = parse_readme(REPLY_SCORER_TEXT)
        self.assertEqual(
            info["features"],
            ["Specificity", "Stance", "Value", "Clean", "Length"])
        self.assertNotIn("Check", info["features"])  # header is not a feature

    def test_lesson_from_why_section(self):
        info = parse_readme(REPLY_SCORER_TEXT)
        self.assertIn("24 peer replies, 0 followers", info["lesson"])

    def test_usage_command_found(self):
        info = parse_readme(REPLY_SCORER_TEXT)
        self.assertTrue(info["usage"].startswith("python reply_scorer.py"))

    def test_single_file_detected(self):
        info = parse_readme(REPLY_SCORER_TEXT)
        self.assertTrue(info["single_file"])

    def test_empty_readme_raises(self):
        with self.assertRaises(ValueError):
            parse_readme("   \n")

    def test_no_heading_raises(self):
        with self.assertRaises(ValueError):
            parse_readme("Just a paragraph, no heading at all.\n")

    def test_bullet_features(self):
        info = parse_readme(
            "# my-tool\n\nDoes a thing well.\n\n## Features\n\n"
            "- Packs whole sentences\n- Counts URLs as 23 chars\n")
        self.assertEqual(
            info["features"],
            ["Packs whole sentences", "Counts URLs as 23 chars"])

    def test_long_bullet_shortens_to_first_clause(self):
        info = parse_readme(
            "# my-tool\n\nDoes a thing well.\n\n## How it works\n\n"
            "- Parse the README; the title becomes the name; the rest "
            "becomes the thread. Second sentence nobody needs.\n")
        self.assertEqual(info["features"], ["Parse the README"])

    def test_wrapped_bullet_joins_continuation_lines(self):
        info = parse_readme(
            "# my-tool\n\nDoes a thing well.\n\n## How it works\n\n"
            "1. Draft the thread: what it is, how it works,\n"
            "   the repo link, and what it taught you.\n"
            "2. Fit each post to the limit.\n")
        self.assertEqual(info["features"], [
            "Draft the thread: what it is, how it works, the repo link, "
            "and what it taught you",
            "Fit each post to the limit",
        ])

    def test_clean_inline_strips_links(self):
        self.assertEqual(
            clean_inline("See [the docs](https://example.com/x) for more."),
            "See the docs for more.")


class TestBuildThread(unittest.TestCase):
    def _thread(self, text=REPLY_SCORER_TEXT, **kwargs):
        info = parse_readme(text)
        info["license_hint"] = "MIT" if "MIT" in text else ""
        repo = kwargs.pop("repo", "https://github.com/Cchubro/reply-scorer")
        posts, _ = build_thread(info, repo, **kwargs)
        return number_posts(posts, 280)

    def test_reply_scorer_thread_is_four_posts(self):
        self.assertEqual(len(self._thread()), 4)

    def test_all_posts_fit_280(self):
        for post in self._thread():
            with self.subTest(post=post):
                self.assertLessEqual(x_len(post), 280)

    def test_posts_are_numbered(self):
        posts = self._thread()
        self.assertTrue(posts[0].startswith("1/4 "))
        self.assertTrue(posts[3].startswith("4/4 "))

    def test_second_post_explains_each_check(self):
        posts = self._thread()
        self.assertIn("specificity (numbers / stats / code tokens)", posts[1])
        self.assertIn("stance (contrast or a claim about what matters)", posts[1])
        self.assertIn("clean (empty praise and AI-flavoured filler)", posts[1])

    def test_first_post_names_tool_and_what_it_does(self):
        posts = self._thread()
        self.assertIn("reply-scorer", posts[0])
        self.assertIn("Score a reply draft", posts[0])

    def test_number_option_labels_launch(self):
        posts = self._thread(number=2)
        self.assertTrue(posts[0].startswith("1/4 Tool #2 is live: reply-scorer."))

    def test_last_post_has_repo_link(self):
        posts = self._thread()
        self.assertIn("https://github.com/Cchubro/reply-scorer", posts[-1])

    def test_lesson_post_carries_measured_number(self):
        posts = self._thread()
        self.assertTrue(any("24 peer replies, 0 followers" in p for p in posts))

    def test_no_lesson_no_lesson_post(self):
        posts = self._thread("# tiny-tool\n\nDoes one small thing.\n")
        self.assertEqual(len(posts), 3)
        self.assertNotIn("learned", " ".join(posts).lower())

    def test_default_repo_derived_from_name(self):
        info = parse_readme("# my-tool\n\nDoes a thing.\n")
        posts, _ = build_thread(info, "https://github.com/Cchubro/my-tool")
        self.assertIn("https://github.com/Cchubro/my-tool", posts[-1])

    def test_long_tagline_still_fits(self):
        long_text = "# big-tool\n\n" + " ".join(
            ["This tool does something genuinely useful and specific."] * 12)
        posts = self._thread(long_text)
        for post in posts:
            self.assertLessEqual(x_len(post), 280)


class TestFit(unittest.TestCase):
    def test_short_text_unchanged(self):
        text, cut = fit("short and sweet", 280)
        self.assertEqual((text, cut), ("short and sweet", False))

    def test_drops_trailing_sentences(self):
        text, cut = fit(
            "First sentence fits. Second sentence is extra. Third too.", 30)
        self.assertEqual(text, "First sentence fits.")
        self.assertTrue(cut)

    def test_hard_cut_adds_ellipsis(self):
        text, cut = fit("oneverylongwordwithoutanyspacesinit", 10)
        self.assertTrue(cut)
        self.assertLessEqual(x_len(text), 10)
        self.assertTrue(text.endswith("…"))


class TestCheckMode(unittest.TestCase):
    def test_check_passes_generated_thread(self):
        info = parse_readme(REPLY_SCORER_TEXT)
        info["license_hint"] = "MIT"
        posts, _ = build_thread(info, "https://github.com/Cchubro/reply-scorer")
        posts = number_posts(posts, 280)
        with tempfile.NamedTemporaryFile("w", suffix=".txt",
                                         delete=False) as f:
            f.write("\n\n".join(posts))
            path = f.name
        try:
            self.assertEqual(check_thread(path, 280), 0)
        finally:
            os.unlink(path)

    def test_check_fails_over_limit(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt",
                                         delete=False) as f:
            f.write("x" * 300)
            path = f.name
        try:
            self.assertEqual(check_thread(path, 280), 1)
        finally:
            os.unlink(path)


class TestCLI(unittest.TestCase):
    def test_cli_plain_on_reply_scorer(self):
        result = subprocess.run(
            [sys.executable, os.path.join(HERE, "readme_to_thread.py"),
             REPLY_SCORER_README, "--number", "2", "--plain"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        posts = [p for p in result.stdout.strip().split("\n\n") if p.strip()]
        self.assertEqual(len(posts), 4)
        for post in posts:
            self.assertLessEqual(x_len(post), 280)

    def test_cli_missing_file_exits_2(self):
        result = subprocess.run(
            [sys.executable, os.path.join(HERE, "readme_to_thread.py"),
             "no-such-readme.md"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
