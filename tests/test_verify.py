import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agents/scripts"
VERIFY = SCRIPTS / "verify-changes.py"
sys.path.insert(0, str(SCRIPTS))
import theme_json


class ThemeJSONTests(unittest.TestCase):
    def test_strings_comments_trailing_commas_and_line_numbers(self):
        source = r'''{
          // label
          "url": "https://example.com/a/*b*/",
          "text": "escaped \" quote, } //",
          "values": [1, /* line
          break */ ],
        }'''
        self.assertEqual(theme_json.loads(source), {
            "url": "https://example.com/a/*b*/", "text": 'escaped " quote, } //', "values": [1],
        })
        for source in ("{,}", "[,]", "[1,,]", "[1 /* missing ]", '{"a":,}', "[1/**/2]", "[NaN]", "[Infinity,]"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                theme_json.loads(source)
        with self.assertRaises(json.JSONDecodeError) as error:
            theme_json.loads('{/* first\nsecond */\n "a": }')
        self.assertEqual(error.exception.lineno, 3)


class ThemeRepo(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                        GIT_AUTHOR_NAME="Fixture", GIT_COMMITTER_NAME="Fixture",
                        GIT_AUTHOR_EMAIL="test@example.invalid", GIT_COMMITTER_EMAIL="test@example.invalid",
                        SHOPIFY_CLI_NO_ANALYTICS="1", CI="1")
        self.git("init", "-q")
        self.write("layout/theme.liquid", "<html><head>{{ content_for_header }}</head><body>{{ content_for_layout }}</body></html>")
        self.write("locales/en.default.json", "{}")
        self.write("locales/en.default.schema.json", "{}")
        self.write("sections/hero.liquid", "<h1>Hello</h1>")
        self.write("templates/index.json", '{"sections":{"main":{"type":"hero"}},"order":["main"]}')
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.root, env=self.env, capture_output=True, check=True)

    def cli(self, script, *args, expect=0):
        result = subprocess.run([sys.executable, str(script), *args], cwd=self.root,
                                env=self.env, capture_output=True, text=True)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, expect, output)
        return output


class VerifyTests(ThemeRepo):
    def test_base_checks_already_committed_changes_in_clean_checkout(self):
        self.write("templates/index.json", "{broken")
        self.git("add", ".")
        self.git("commit", "-qm", "PR fixture")
        self.assertIn("Checked 0 file(s)", self.cli(VERIFY))
        self.assertIn("templates/index.json", self.cli(VERIFY, "--base", "HEAD~1", expect=1))

    def test_staged_content_with_partially_staged_and_missing_worktree_files(self):
        name = "templates/index.json"
        self.write(name, "{broken")
        self.git("add", name)
        self.write(name, "{}")
        self.assertIn(name, self.cli(VERIFY, "--staged", expect=1))
        (self.root / name).unlink()
        self.assertIn(name, self.cli(VERIFY, "--staged", name, expect=1))
        self.write(name, "{}")
        self.git("add", name)
        self.write(name, "{broken again")
        self.cli(VERIFY, "--staged")
        self.cli(VERIFY, expect=1)

    def test_protect_delete_and_both_ends_of_rename(self):
        policy = {"protected_paths": ["snippets/dataLayer*.liquid"]}
        self.write(".agents/shopify-harness-policy.json", json.dumps(policy))
        self.write("snippets/dataLayer-cart.liquid", "content")
        self.git("add", ".")
        self.git("commit", "-qm", "policy")
        (self.root / "snippets/dataLayer-cart.liquid").unlink()
        self.assertIn("dataLayer-cart", self.cli(VERIFY, expect=1))
        self.write("snippets/new.liquid", "content")
        self.git("add", "-A")
        self.assertIn("dataLayer-cart", self.cli(VERIFY, "--staged", expect=1))
        self.cli(VERIFY, "--staged", "--allow-protected")
        self.git("commit", "-qm", "rename fixture")
        self.git("mv", "snippets/new.liquid", "snippets/DATALAYER-new.liquid")
        self.assertIn("DATALAYER-new", self.cli(VERIFY, "--staged", expect=1))

    def test_jsonc_is_scoped_to_theme_files(self):
        self.write("config/settings_schema.json", '[{"url":"//literal", /* label */},]')
        self.cli(VERIFY)
        self.write("package.json", '{"name":"package",}')
        self.assertIn("package.json", self.cli(VERIFY, expect=1))

    def test_stylesheet_is_opt_in_and_uses_snapshot(self):
        file = "sections/hero.liquid"
        tag = "{%- stylesheet -%}h1{color:red}{%- endstylesheet -%}"
        self.write(file, tag)
        self.cli(VERIFY)
        self.write(".gitignore", ".agents/\n")
        self.write(".agents/shopify-harness-policy.json", '{"forbid_new_stylesheet":true}')
        self.git("add", file)
        self.write(file, "unstaged content")
        self.cli(VERIFY, "--staged", expect=1)
        self.cli(VERIFY, "--staged", "--allow-stylesheet")
        self.cli(VERIFY)
        self.git("commit", "-qm", "existing tag")
        self.write(file, "additional markup\n" + tag)
        self.cli(VERIFY, file)

    @unittest.skipUnless(shutil.which("node"), "Node.js unavailable")
    def test_node_tests_read_index_in_staged_mode(self):
        self.write("tests/hero.test.cjs", "require('node:assert').strictEqual(require('fs').readFileSync('sections/hero.liquid','utf8'), 'staged')")
        self.write("sections/hero.liquid", "staged")
        self.git("add", ".")
        self.write("sections/hero.liquid", "working")
        self.cli(VERIFY, "--staged")
        self.cli(VERIFY, expect=1)

    @unittest.skipUnless(shutil.which("shopify"), "Shopify CLI unavailable")
    def test_theme_check_distinguishes_historical_and_new_errors_on_callers(self):
        self.write("sections/unrelated.liquid", "{% if product %}")
        self.write("sections/caller.liquid", "{% render 'greeting' %}")
        self.write("snippets/greeting.liquid", "Hello")
        self.git("add", ".")
        self.git("commit", "-qm", "baseline with historical error")
        self.write("sections/hero.liquid", "<p>Changed</p>")
        self.assertIn("Pre-existing errors on unchanged files: 1", self.cli(VERIFY, "--theme-check"))
        (self.root / "snippets/greeting.liquid").unlink()
        self.assertIn("[theme] sections/caller.liquid", self.cli(VERIFY, "--theme-check", expect=1))

    @unittest.skipUnless(shutil.which("shopify"), "Shopify CLI unavailable")
    def test_real_theme_check_uses_complete_staged_context(self):
        self.write("sections/hero.liquid", "{% render 'greeting' %}")
        self.write("snippets/greeting.liquid", "Hello")
        self.git("add", ".")
        self.cli(VERIFY, "--theme-check", "--staged")
        self.write("snippets/greeting.liquid", "{% if product %}")
        self.git("add", "snippets/greeting.liquid")
        self.write("snippets/greeting.liquid", "valid in worktree")
        self.assertIn("LiquidHTMLSyntaxError", self.cli(VERIFY, "--theme-check", "--staged", expect=1))
        self.cli(VERIFY, "--theme-check")


if __name__ == "__main__":
    unittest.main()
