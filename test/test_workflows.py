"""The GitHub workflows and the repository layout."""
import os
import re

import support
from support import TestCase

import yaml

WF = support.REPO / ".github" / "workflows"


def load(name):
    doc = yaml.safe_load((WF / name).read_text())
    doc["on"] = doc.pop(True, doc.get("on"))                    # YAML reads the key `on` as True
    return doc


class UpdateWorkflowTest(TestCase):
    def setUp(self):
        super().setUp()
        self.wf = load("update.yml")
        self.steps = self.wf["jobs"]["build-and-deploy"]["steps"]
        self.text = (WF / "update.yml").read_text()

    def test_triggers(self):
        on = self.wf["on"]
        self.assertNotIn("schedule", on)                          # no periodic refresh
        self.assertNotIn("cron", self.text)
        self.assertEqual(set(on["workflow_dispatch"]["inputs"]), {"kind", "hours", "count"})
        self.assertEqual(on["workflow_dispatch"]["inputs"]["kind"]["options"], ["adhoc", "scheduled"])
        self.assertIn("inputs.kind", self.wf["run-name"])                          # the jobs tell scheduled and adhoc runs apart by name
        self.assertEqual(on["push"]["branches"], ["main"])

    def test_inputs_have_no_hard_coded_defaults(self):
        for name in ("hours", "count"):
            self.assertEqual(self.wf["on"]["workflow_dispatch"]["inputs"][name]["default"], "")
        self.assertNotIn("|| '24'", self.text)
        self.assertNotIn("|| '300'", self.text)

    def test_fetch_step_receives_the_chosen_values(self):
        fetch = next(s for s in self.steps if s.get("name", "").startswith("Fetch latest headlines"))
        self.assertEqual(fetch["env"], {"WINDOW_HOURS": "${{ github.event.inputs.hours }}", "ARTICLE_COUNT": "${{ github.event.inputs.count }}",
                                        "REFRESH_KIND": "${{ github.event.inputs.kind }}", "PREVIOUS_REFRESH_FILE": "${{ runner.temp }}/previous_refresh.json"})
        self.assertEqual(fetch["run"], "python3 src/fetch_news.py")

    def test_build_step_runs_before_fetch(self):
        runs = [s.get("run") for s in self.steps]
        self.assertLess(runs.index("python3 src/build_site.py"), runs.index("python3 src/fetch_news.py"))

    def test_gate_reads_the_cooldown_from_settings_and_cancels_early_runs(self):
        gate = next(s for s in self.steps if s.get("id") == "gate")
        self.assertIn("python3 src/settings.py cooldown_minutes", gate["run"])
        self.assertIn("event=workflow_dispatch&status=success", gate["run"])      # only real refreshes count, not pushes
        self.assertIn("gh run cancel", gate["run"])
        self.assertEqual(self.wf["permissions"]["actions"], "write")

    def test_a_code_push_keeps_the_current_headlines(self):
        keep = next(s for s in self.steps if s.get("id") == "keep")
        self.assertIn("github.event_name == 'push'", keep["if"])
        self.assertIn("news.json", keep["run"]); self.assertIn("refresh.json", keep["run"])
        fetch = next(s for s in self.steps if s.get("name", "").startswith("Fetch latest headlines"))
        self.assertIn("steps.keep.outputs.kept != 'true'", fetch["if"])            # fetch only when nothing could be kept
        names = [s.get("id") or s.get("run") for s in self.steps]
        self.assertLess(names.index("pages"), names.index("keep"))

    def test_checkout_comes_before_anything_that_needs_the_code(self):
        names = [s.get("uses", s.get("name")) for s in self.steps]
        self.assertTrue(names[0].startswith("actions/checkout"))

    def test_deploys_the_generated_site_folder(self):
        upload = next(s for s in self.steps if str(s.get("uses", "")).startswith("actions/upload-pages-artifact"))
        self.assertEqual(upload["with"]["path"], "site")

    def test_every_script_it_runs_exists(self):
        for script in re.findall(r"python3 (src/\S+\.py)", self.text):
            self.assertTrue((support.REPO / script).is_file(), script)

    def test_one_deployment_at_a_time_and_a_running_refresh_is_never_cancelled(self):
        self.assertEqual(self.wf["concurrency"], {"group": "pages", "cancel-in-progress": False})

    def test_a_scheduled_refresh_skips_the_cooldown_gate(self):
        gate = next(s for s in self.steps if s.get("id") == "gate")
        self.assertIn('"${{ inputs.kind }}" = "scheduled"', gate["run"])

    def test_the_previous_refresh_record_is_read_before_fetching(self):
        names = [s.get("name", "") for s in self.steps]
        i = next(n for n, x in enumerate(names) if x.startswith("Read the previous refresh record"))
        self.assertLess(i, next(n for n, x in enumerate(names) if x.startswith("Fetch latest headlines")))


class ChainWorkflowTest(TestCase):
    """The two independent chains: adhoc_refresh.yml (Refresh button) and scheduled_refresh.yml (the 4-hourly schedule)."""
    CHAINS = {"adhoc_refresh.yml": ("adhoc_refresh", [{"cron": "47 */3 * * *"}]),
              "scheduled_refresh.yml": ("scheduled_refresh", [{"cron": "7,37 * * * *"}])}

    def each(self):
        for name, (module, cron) in self.CHAINS.items():
            wf = load(name)
            yield name, module, cron, wf, wf["jobs"]["loop"]["steps"], (WF / name).read_text()

    def test_triggers_and_permissions(self):
        for name, module, cron, wf, steps, text in self.each():
            self.assertIn("chain", wf["on"]["workflow_dispatch"]["inputs"], name)
            self.assertEqual(wf["on"]["schedule"], cron, name)
            self.assertEqual(wf["permissions"]["actions"], "write", name)

    def test_runs_its_own_loop_from_src_and_chains_itself(self):
        for name, module, cron, wf, steps, text in self.each():
            runs = " ".join(str(s.get("run", "")) for s in steps)
            self.assertIn(f"python3 src/{module}.py", runs, name)
            self.assertIn(f"gh workflow run {name}", runs, name)
            self.assertIn(f"--workflow {name}", runs, name)          # the one-chain guard only counts its own runs
            self.assertIn("chain=true", runs, name)
            self.assertTrue((support.REPO / "src" / f"{module}.py").is_file(), module)

    def test_loop_is_shorter_than_the_job_timeout(self):
        import adhoc_refresh, scheduled_refresh
        for name, module, cron, wf, steps, text in self.each():
            loop = {"adhoc_refresh": adhoc_refresh, "scheduled_refresh": scheduled_refresh}[module].LOOP_MINUTES
            self.assertLess(loop, wf["jobs"]["loop"]["timeout-minutes"], name)

    def test_the_two_modules_do_not_depend_on_each_other(self):
        sched = (support.SRC / "scheduled_refresh.py").read_text()
        adhoc = (support.SRC / "adhoc_refresh.py").read_text()
        self.assertNotIn("adhoc_refresh", sched)
        self.assertNotIn("scheduled_refresh", adhoc)
        self.assertNotIn("refresh_schedule", adhoc)               # the slot maths belongs to the schedule only


class LayoutTest(TestCase):
    """Code in src/, tests in test/, configuration in external_config/ (only listed, never read here)."""
    ROOT_ALLOWED_PY = set()

    def test_all_python_code_is_under_src_or_test(self):
        stray = []
        for dirpath, dirs, files in os.walk(support.REPO):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "site", "node_modules", ".pytest_cache")]
            rel = os.path.relpath(dirpath, support.REPO)
            for f in files:
                if f.endswith(".py") and rel.split(os.sep)[0] not in ("src", "test"):
                    stray.append(os.path.join(rel, f))
        self.assertEqual(stray, [])

    def test_expected_folders_and_config_files_exist(self):
        for d in ("src", "test", "external_config", ".github/workflows"):
            self.assertTrue((support.REPO / d).is_dir(), d)
        self.assertEqual(sorted(os.listdir(support.REPO / "external_config")), ["backgrounds", "legacy_newspapers.json", "newspaper_sections", "sections.json", "settings.json", "topics"])
        for f in ("fetch_news.py", "config.py", "settings.py", "build_site.py", "adhoc_refresh.py", "scheduled_refresh.py", "refresh_runs.py", "refresh_schedule.py", "check_images.py"):
            self.assertTrue((support.SRC / f).is_file(), f)
        self.assertTrue((support.SRC / "web" / "index.html").is_file())

    def test_old_layout_is_gone(self):
        for old in ("feeds.json", "homepages.py", "fetch_news.py", "scheduler_loop.py", "scheduler.yml", "refresh_topic.txt", "refresh_minutes.txt", "config", "tests", "web"):
            self.assertFalse((support.REPO / old).exists(), old)

    def test_generated_site_folder_is_not_committed(self):
        self.assertIn("site/", (support.REPO / ".gitignore").read_text().splitlines())

    def test_code_does_not_refer_to_the_old_files(self):
        for f in support.SRC.glob("*.py"):
            text = f.read_text()
            for old in ("feeds.json", "refresh_topic.txt", "refresh_minutes.txt", "homepages"):
                self.assertNotIn(old, text, f"{f.name} still mentions {old}")
