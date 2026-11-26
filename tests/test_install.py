import hashlib
import json
import shutil
import subprocess
import textwrap

from test_verify import ROOT, ThemeRepo

SYNC = ROOT / "sync-to-theme.py"
RULES = ".agents/shopify-harness.md"
LOCK = ".agents/shopify-harness.lock.json"
LOCAL_LOCK = ".tmp/shopify-harness-sync.json"
POLICY = ".agents/shopify-harness-policy.json"
EXTRACT = ".agents/skills/section-port/scripts/extract_section.py"
SKILLS = ("section-port", "shopify-commit-message", "shopify-performance")


class InstallTests(ThemeRepo):
    def sync(self, *args, expect=0):
        return self.cli(SYNC, *args, str(self.root), expect=expect)

    def test_team_install_with_existing_tracked_rules_and_fresh_clone(self):
        for f in ("AGENTS.md", "CLAUDE.md"):
            self.write(f, "Team conventions\n")
        self.git("add", ".")
        self.git("commit", "-qm", "team rules")
        self.sync("--profile", "generic", "--dry-run")
        self.assertFalse((self.root / ".agents").exists())
        self.sync("--profile", "generic")
        self.assertFalse((self.root / POLICY).exists())
        self.assertFalse((self.root / LOCAL_LOCK).exists())
        for f in ("AGENTS.md", "CLAUDE.md"):
            self.assertEqual((self.root / f).read_text(), "Team conventions\n")
        self.assertTrue((self.root / RULES).is_file())
        self.assertEqual(set(json.loads((self.root / LOCK).read_text())),
                         set((ROOT / "manifest.txt").read_text().splitlines()))
        self.git("add", ".agents")
        self.git("commit", "-qm", "install fixture")
        clone = self.root / "team-copy"
        self.git("clone", "-q", str(self.root), str(clone))
        self.assertIn("需要复制 0 项", self.cli(SYNC, "--profile", "generic", str(clone)))
        self.assertIn("另一种安装模式", self.sync(expect=1))

    def test_team_upgrade_and_drift_preflight(self):
        self.sync("--profile", "generic")
        # An earlier release has different bytes and a corresponding recorded digest.
        old = self.write(RULES, "Old shared rules\n")
        baseline = json.loads((self.root / LOCK).read_text())
        baseline[RULES] = hashlib.sha256(old.read_bytes()).hexdigest()
        self.write(LOCK, json.dumps(baseline))
        self.git("add", ".agents")
        self.git("commit", "-qm", "old release fixture")
        helper = self.root / EXTRACT
        helper.write_text("local edits")
        self.sync("--profile", "generic", expect=1)
        self.assertEqual(old.read_text(), "Old shared rules\n")
        shutil.copyfile(ROOT / EXTRACT, helper)
        self.sync("--profile", "generic")
        self.assertEqual(old.read_bytes(), (ROOT / RULES).read_bytes())
        self.git("rm", "-q", EXTRACT)
        self.assertIn(EXTRACT, self.sync("--profile", "generic", expect=1))
        self.assertFalse(helper.exists())

    def test_team_clean_install_and_claude_skill_links(self):
        self.sync("--profile", "generic")
        self.write("AGENTS.md", "Read .agents/shopify-harness.md for shared theme rules.\n")
        self.write("CLAUDE.md", "@AGENTS.md\n")
        links = self.root / ".claude/skills"
        # Execute the documented setup twice: ln must not follow an existing skill directory.
        readme = (ROOT / "README.md").read_text()
        start = readme.index("   mkdir -p .claude/skills")
        setup = textwrap.dedent(readme[start:readme.index("   ```", start)])
        for _ in range(2):
            subprocess.run(["sh", "-ec", setup], cwd=self.root, capture_output=True, check=True)
        for name in SKILLS:
            self.assertTrue((links / name / "SKILL.md").is_file())
            self.assertFalse((links / name / name).is_symlink())
        self.write("sections/hero.liquid", '{% schema %}{"name":"Hero"}{% endschema %}')
        extractor = links / "section-port/scripts/extract_section.py"
        self.assertIn("count=1", self.cli(extractor, "templates/index.json", "--editor-name", "Hero"))
        self.cli(self.root / ".agents/scripts/verify-changes.py")

    def test_legacy_ignores_upgrade_and_overrides(self):
        self.sync("--dry-run", expect=1)
        self.assertFalse((self.root / ".agents").exists())
        self.write(".gitignore", "AGENTS.md\nCLAUDE.md\n.agents/\n.tmp/\n")
        old = self.write("AGENTS.md", "old root")
        self.write(LOCAL_LOCK, json.dumps({"AGENTS.md": hashlib.sha256(old.read_bytes()).hexdigest()}))
        self.sync("--dry-run")
        self.assertEqual(old.read_text(), "old root")
        self.sync()
        self.assertEqual(old.read_bytes(), (ROOT / "profiles/ecoflow/AGENTS.md").read_bytes())
        self.assertIn("需要复制 0 项", self.sync())
        self.assertTrue((self.root / ".agents/skills/shopify-performance/references/ecoflow-lessons.md").is_file())
        self.write("snippets/dataLayer.liquid", "{% stylesheet %}{% endstylesheet %}")
        verify = self.root / ".agents/scripts/verify-changes.py"
        output = self.cli(verify, expect=1)
        self.assertIn("Protected path", output)
        self.assertIn("forbids new stylesheet", output)
        self.cli(verify, "--allow-stylesheet", "--allow-protected")
        self.write("templates/product.json", '{"sections":{"hero":{"type":"pdp-slideshow-new"}},"order":["hero"]}')
        self.assertIn("count=1", self.cli(self.root / EXTRACT, "templates/product.json", "--editor-name",
                                         "PDP Slideshow", "--include-variants"))
        self.git("add", "-f", "AGENTS.md")
        self.assertIn("已跟踪", self.sync(expect=1))

    def test_legacy_refuses_unbased_existing_differences_before_copy(self):
        self.write(".gitignore", "AGENTS.md\nCLAUDE.md\n.agents/\n.tmp/\n")
        self.write("AGENTS.md", "local rule\n")
        self.assertIn("profiles/ecoflow/AGENTS.md", self.sync(expect=1))
        self.assertFalse((self.root / LOCK).exists())
        self.assertFalse((self.root / RULES).exists())
        self.assertEqual((self.root / "AGENTS.md").read_text(), "local rule\n")

    def test_profile_alias_preserves_canonical_nth_when_editor_names_collide(self):
        self.write(".gitignore", "AGENTS.md\nCLAUDE.md\n.agents/\n.tmp/\n")
        self.sync()
        for kind in ("pdp-slideshow", "pdp-slideshow-new"):
            self.write("sections/" + kind + ".liquid", '{% schema %}{"name":"PDP Slideshow"}{% endschema %}')
        template = self.write("templates/product.json", json.dumps({
            "sections": {
                "variant": {"type": "pdp-slideshow-new", "disabled": True},
                "renamed": {"type": "hero", "name": "PDP Slideshow"},
                "original": {"type": "pdp-slideshow"},
            },
            "order": ["variant", "renamed", "original"],
        }))
        args = (str(template), "--editor-name", "PDP Slideshow", "--list", "--nth", "1")
        canonical = self.cli(self.root / EXTRACT, *args)
        self.assertIn("count=1", canonical)
        self.assertIn("id=original\n", canonical)
        variants = self.cli(self.root / EXTRACT, *args, "--include-variants")
        self.assertIn("count=2", variants)
        self.assertIn("id=variant\n", variants)
        self.assertIn("disabled=True", variants)

    def test_editor_label_uses_template_order_translations_and_jsonc(self):
        self.sync("--profile", "generic")
        (self.root / "locales/en.default.schema.json").unlink()
        self.write("locales/fr.default.schema.json", '{"sections": {"hero": "Page",},}')
        self.write("sections/short.liquid", '{% schema %}{"name":"Page"}{% endschema %}')
        self.write("sections/long-name.liquid", '{% schema %}{"name":"t:sections.hero", /* label */}{% endschema %}')
        self.write("sections/other.liquid", '{% schema %}{"name":"Other"}{% endschema %}')
        self.write("sections/bad.liquid", '{% schema %}{"name": }{% endschema %}')
        self.write("templates/index.json", '''{/* theme editor */
          "sections": {"a":{"type":"long-name","disabled":true},"b":{"type":"other","name":"Page"},
                       "bad":{"type":"bad"}}, "order": ["b","a","bad",],}''')
        output = self.cli(self.root / EXTRACT, "templates/index.json", "--editor-name", "Page", "--list", "--nth", "2")
        self.assertIn("count=2", output)
        self.assertIn("1. b (other)", output)
        self.assertIn("id=a\n", output)
        self.assertIn("disabled=True", output)
        self.assertIn("bad.liquid", output)
