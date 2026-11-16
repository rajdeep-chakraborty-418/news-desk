"""settings.py: the refresh cooldown, relay topic, allowed time ranges and story counts."""
import copy
import json
import os
import sys

import support
from support import SAMPLE_SETTINGS, TestCase, write_config

import config
import settings


class SettingsTest(TestCase):
    def _bad(self, mutate, message):
        data = copy.deepcopy(SAMPLE_SETTINGS)
        mutate(data)
        d = write_config(self.tmp / "c", settings=data)
        with self.assertRaises(config.ConfigError) as cm:
            settings.load_settings(d)
        self.assertIn(message, str(cm.exception))

    def test_loads_the_sample(self):
        st = settings.load_settings(support.SAMPLE_CONFIG)
        self.assertEqual((st["cooldown_minutes"], st["min_gap_seconds"], st["request_topic"]), (60, 120, "test-topic-abc"))
        self.assertEqual(st["hours"], (6, 24, 72, 168))
        self.assertEqual(st["default_hours"], 24)
        self.assertEqual(st["counts"], (50, 150, 250))
        self.assertEqual(st["default_count"], 150)
        self.assertEqual(st["time_ranges"][1], {"hours": 24, "label": "One day"})

    def test_the_schedule(self):
        sch = settings.load_settings(support.SAMPLE_CONFIG)["schedule"]
        self.assertEqual(sch, {"every_hours": 6, "first_slot": (1, 30), "timezone": "Asia/Kolkata", "range_hours": 72, "count": 250,
                               "retries": 2, "retry_gap_minutes": 7, "catchup_grace_minutes": 20})

    def test_schedule_validation(self):
        self._bad(lambda d: d.pop("schedule"), "'schedule' is missing")
        self._bad(lambda d: d["schedule"].update(every_hours=5), "must divide 24")
        self._bad(lambda d: d["schedule"].update(every_hours=0), "every_hours")
        self._bad(lambda d: d["schedule"].update(first_slot="25:00"), "first_slot")
        self._bad(lambda d: d["schedule"].update(first_slot="9:00"), "first_slot")
        self._bad(lambda d: d["schedule"].update(timezone="Mars/Base"), "not a known time zone")
        self._bad(lambda d: d["schedule"].update(count=0), "schedule.count")
        self._bad(lambda d: d["schedule"].update(retries=-1), "schedule.retries")
        self._bad(lambda d: d["schedule"].update(retry_gap_minutes=0), "schedule.retry_gap_minutes")

    def test_the_page_gets_the_schedule(self):
        from datetime import datetime, timezone
        pub = settings.public_settings(settings.load_settings(support.SAMPLE_CONFIG), datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(pub["schedule"], {"every_minutes": 360, "anchor": "2026-11-16T08:00:00Z", "range_hours": 72, "count": 250, "grace_minutes": 20})

    def test_validation(self):
        self._bad(lambda d: d["refresh"].update(manual_cooldown_minutes=-1), "manual_cooldown_minutes must be a whole number")
        self._bad(lambda d: d["refresh"].update(manual_cooldown_minutes="60"), "manual_cooldown_minutes")
        self._bad(lambda d: d["refresh"].update(request_topic="a b"), "request_topic")
        self._bad(lambda d: d["refresh"].update(request_topic="ab"), "request_topic")
        self._bad(lambda d: d["time_ranges"].update(options=[]), "at least one")
        self._bad(lambda d: d["time_ranges"]["options"][0].pop("label"), "needs a 'label'")
        self._bad(lambda d: d["time_ranges"]["options"][1].update(hours=6), "repeats an hours value")
        self._bad(lambda d: d["time_ranges"].update(default_hours=5), "default_hours (5) must be one of")
        self._bad(lambda d: d["article_counts"].update(default=99), "default (99) must be one of")
        self._bad(lambda d: d["article_counts"].update(options=[50, 50]), "repeats a number")
        self._bad(lambda d: d["article_counts"].update(options=["50"]), "article_counts.options entries")

    def test_zero_gap_is_allowed(self):
        data = copy.deepcopy(SAMPLE_SETTINGS); data["refresh"]["min_gap_seconds"] = 0
        self.assertEqual(settings.load_settings(write_config(self.tmp / "c", settings=data))["min_gap_seconds"], 0)

    def test_missing_and_malformed(self):
        with self.assertRaises(config.ConfigError):
            settings.load_settings(self.tmp / "nope")
        d = write_config(self.tmp / "c"); (d / "settings.json").write_text("[1]")
        with self.assertRaises(config.ConfigError):
            settings.load_settings(d)
        (d / "settings.json").write_text("{oops")
        with self.assertRaises(config.ConfigError):
            settings.load_settings(d)

    def test_cooldown_cli_value(self):
        import subprocess
        out = subprocess.run([sys.executable, str(support.REPO / "src" / "settings.py"), "cooldown_minutes"], capture_output=True, text=True,
                             env={**os.environ, "NEWSDESK_CONFIG_DIR": str(support.SAMPLE_CONFIG)})
        self.assertEqual(out.stdout.strip(), "60")

    def test_public_settings_for_the_page(self):
        pub = settings.public_settings(settings.load_settings(support.SAMPLE_CONFIG))
        self.assertEqual(pub["article_counts"], [50, 150, 250])
        self.assertEqual(pub["default_count"], 150)
        self.assertEqual(pub["request_topic"], "test-topic-abc")
        self.assertEqual(pub["time_ranges"][0], {"hours": 6, "label": "Six hours"})
        self.assertEqual(pub["cooldown_minutes"], 60)       # the page works out when the next manual refresh is allowed
        self.assertNotIn("min_gap_seconds", pub)            # server-side detail, not for the page
        json.dumps(pub)
