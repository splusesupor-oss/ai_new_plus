# -*- coding: utf-8 -*-
"""آزمون تنظیمات و امنیت توکن — بدون توکن واقعی."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import ConfigError, Settings

ROOT = Path(__file__).resolve().parents[1]


class SettingsTest(unittest.TestCase):
    def test_missing_token_is_clear_error(self):
        with self.assertRaises(ConfigError):
            Settings.from_environ({})
        with self.assertRaises(ConfigError):
            Settings.from_environ({"BOT_TOKEN": "   "})

    def test_token_and_options_are_trimmed(self):
        s = Settings.from_environ(
            {
                "BOT_TOKEN": "  dummy  ",
                "SUPPORT_CONTACT": " @support ",
                "FOX_GROUP_URL": "",
                "FOX_CHANNEL_URL": " https://splus.ir/x ",
            }
        )
        self.assertEqual(s.bot_token, "dummy")
        self.assertEqual(s.support_contact, "@support")
        self.assertIsNone(s.group_url)
        self.assertEqual(s.channel_url, "https://splus.ir/x")

    def test_env_example_has_no_real_token(self):
        content = (ROOT / ".env.example").read_text(encoding="utf-8")
        for line in content.splitlines():
            if line.startswith("BOT_TOKEN="):
                self.assertEqual(line, "BOT_TOKEN=")
        # اطلاعات حساس پرداخت و مدیر هم در فایل نمونه باید خالی باشند
        for key in ("ADMIN_CHAT_ID=", "PAYMENT_CARD_NUMBER=", "PAYMENT_CARD_HOLDER="):
            for line in content.splitlines():
                if line.startswith(key):
                    self.assertEqual(line, key)
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".env", gitignore)

    def test_no_secret_hardcoded_in_sources(self):
        # هیچ فایل پایتونی نباید مقدار BOT_TOKEN را به‌صورت ثابت داشته باشد
        for py in ROOT.glob("*.py"):
            self.assertNotRegex(py.read_text(encoding="utf-8"), r"BOT_TOKEN\s*=\s*[\"'][^\"']+[\"']")


if __name__ == "__main__":
    unittest.main()
