# -*- coding: utf-8 -*-
"""آزمون ساختار و متن دقیق کیبورد اصلی — بدون شبکه و بدون توکن."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import texts
from keyboards import build_main_keyboard, keyboard_to_dict

EXPECTED_ROWS = [
    ["ساخت تصویر", "ساخت ویدیو"],
    ["سفارش‌های من", "دریافت اعتبار رایگان"],
    ["نمونه‌ها", "ارتباط با پشتیبانی"],
    ["گروه روباه", "کانال روباه"],
]


class MainKeyboardTest(unittest.TestCase):
    def test_rows_exact_texts_and_order(self):
        data = keyboard_to_dict(build_main_keyboard())
        rows = [[btn["text"] for btn in row] for row in data["keyboard"]]
        self.assertEqual(rows, EXPECTED_ROWS)

    def test_is_reply_keyboard_shape(self):
        data = keyboard_to_dict(build_main_keyboard())
        self.assertIn("keyboard", data)  # ReplyKeyboardMarkup
        self.assertNotIn("inline_keyboard", data)
        self.assertTrue(data["resize_keyboard"])
        self.assertFalse(data["one_time_keyboard"])  # منو باید باقی بماند

    def test_zwnj_in_persian_titles(self):
        # «سفارش‌های» و «نمونه‌ها» باید نیم‌فاصله (U+200C) داشته باشند
        self.assertIn("\u200c", texts.BTN_MY_ORDERS)
        self.assertIn("\u200c", texts.BTN_SAMPLES)

    def test_menu_rows_constant_matches(self):
        self.assertEqual([list(r) for r in texts.MENU_ROWS], EXPECTED_ROWS)


if __name__ == "__main__":
    unittest.main()
