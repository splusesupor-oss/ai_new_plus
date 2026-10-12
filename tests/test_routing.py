# -*- coding: utf-8 -*-
"""آزمون رفتار دستورها و تک‌تک دکمه‌ها — بدون شبکه و بدون توکن واقعی."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import texts
from bot_logic import route_message
from config import Settings

EMPTY = Settings(bot_token="test-token-not-real")
FILLED = Settings(
    bot_token="test-token-not-real",
    support_contact="@fox_support_test",
    group_url="https://splus.ir/test_group",
    channel_url="https://splus.ir/test_channel",
)


class MenuCommandsTest(unittest.TestCase):
    def test_start_menu_and_menu_fa_show_welcome(self):
        for text in ("/start", "/menu", "منو"):
            with self.subTest(text=text):
                reply = route_message(text, EMPTY)
                self.assertEqual(reply.text, texts.WELCOME_TEXT)
                self.assertTrue(reply.show_main_keyboard)

    def test_start_again_reshows_menu(self):
        self.assertEqual(route_message("/start", EMPTY), route_message("/start", EMPTY))

    def test_start_with_args_and_mention(self):
        self.assertEqual(route_message("/start hello", EMPTY).text, texts.WELCOME_TEXT)
        self.assertEqual(route_message("/start@SomeBot", EMPTY).text, texts.WELCOME_TEXT)


class ButtonsTest(unittest.TestCase):
    def test_coming_soon_buttons_exact(self):
        self.assertEqual(
            route_message(texts.BTN_CREATE_IMAGE, EMPTY).text,
            "بخش ساخت تصویر به‌زودی فعال می‌شود.",
        )
        self.assertEqual(
            route_message(texts.BTN_CREATE_VIDEO, EMPTY).text,
            "بخش ساخت ویدیو به‌زودی فعال می‌شود.",
        )

    def test_not_launched_buttons(self):
        self.assertIn("هنوز راه‌اندازی نشده است", route_message(texts.BTN_MY_ORDERS, EMPTY).text)
        self.assertIn("هنوز راه‌اندازی نشده است", route_message(texts.BTN_FREE_CREDIT, EMPTY).text)
        self.assertIn("به‌زودی اضافه می‌شوند", route_message(texts.BTN_SAMPLES, EMPTY).text)

    def test_each_button_has_its_own_reply(self):
        buttons = [b for row in texts.MENU_ROWS for b in row]
        replies = {route_message(b, FILLED).text for b in buttons}
        self.assertEqual(len(replies), len(buttons))

    def test_support_not_set_makes_no_fake_link(self):
        reply = route_message(texts.BTN_SUPPORT, EMPTY).text
        self.assertIn("تنظیم نشده است", reply)
        self.assertNotIn("http", reply)
        self.assertNotIn("@", reply)

    def test_support_set_shows_configured_contact(self):
        reply = route_message(texts.BTN_SUPPORT, FILLED).text
        self.assertIn("@fox_support_test", reply)

    def test_group_channel_not_set_no_fake_link(self):
        for btn in (texts.BTN_GROUP, texts.BTN_CHANNEL):
            with self.subTest(btn=btn):
                reply = route_message(btn, EMPTY).text
                self.assertIn("تنظیم نشده است", reply)
                self.assertNotIn("http", reply)

    def test_group_channel_set_shows_configured_link(self):
        self.assertIn("https://splus.ir/test_group", route_message(texts.BTN_GROUP, FILLED).text)
        self.assertIn("https://splus.ir/test_channel", route_message(texts.BTN_CHANNEL, FILLED).text)

    def test_unknown_and_empty_messages(self):
        for text in ("سلام", "یک متن تصادفی", "", None):
            with self.subTest(text=text):
                reply = route_message(text, EMPTY)  # type: ignore[arg-type]
                self.assertEqual(reply.text, texts.UNKNOWN_TEXT)
                self.assertTrue(reply.show_main_keyboard)


if __name__ == "__main__":
    unittest.main()
