import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.morning_summary import build_message, fmt_money

ROW_OK = {"offer_id": "MV1028F", "name": "Колодки тормозные Mavico", "price": "1500.0", "stock": "37"}
ROW_LOW = {"offer_id": "AF2205", "name": "Фильтр воздушный Mavico", "price": "390.5", "stock": "2"}
ROW_OUT = {"offer_id": "WB01", "name": "Щетки стеклоочистителя", "price": "990", "stock": "0"}


class TestBuildMessage(unittest.TestCase):
    def test_ok_product_no_alert(self):
        msg = build_message([ROW_OK], threshold=5)
        self.assertIn("✅ в наличии", msg)
        self.assertNotIn("заканчивается", msg)
        self.assertNotIn("Требуют внимания", msg)

    def test_low_stock_marked_as_ending(self):
        msg = build_message([ROW_LOW], threshold=5)
        self.assertIn("⚠️ <b>заканчивается</b>", msg)
        self.assertIn("Требуют внимания (1)", msg)
        self.assertIn("осталось 2 при пороге 5", msg)

    def test_zero_stock_marked_out_of_stock(self):
        msg = build_message([ROW_OUT], threshold=5)
        self.assertIn("⛔ <b>нет в наличии</b>", msg)
        self.assertIn("Требуют внимания (1)", msg)
        self.assertIn("закончился", msg)

    def test_custom_threshold(self):
        # stock=4 при пороге 5 — «заканчивается», при пороге 3 — «в наличии»
        row = dict(ROW_OK, stock="4")
        self.assertIn("заканчивается", build_message([row], threshold=5))
        self.assertIn("✅ в наличии", build_message([row], threshold=3))

    def test_message_contains_header_and_stats(self):
        msg = build_message([ROW_OK, ROW_LOW, ROW_OUT], threshold=5)
        self.assertIn("Утренняя сводка Ozon", msg)
        self.assertIn("Порог остатка: 5", msg)
        self.assertIn("Всего: 3", msg)
        self.assertIn("Заканчиваются: 1", msg)
        self.assertIn("Нет в наличии: 1", msg)

    def test_empty_cabinet(self):
        msg = build_message([], threshold=5)
        self.assertIn("Товаров в кабинете пока нет", msg)

    def test_html_escaped(self):
        row = dict(ROW_OK, name="Товар <b>&special")
        msg = build_message([row], threshold=5)
        self.assertNotIn("<b>&special", msg)
        self.assertIn("&amp;special", msg)


class TestFmtMoney(unittest.TestCase):
    def test_int(self):
        self.assertEqual(fmt_money("1000"), "1 000")

    def test_float_dot(self):
        self.assertEqual(fmt_money("1500.00"), "1 500")

    def test_float_comma(self):
        self.assertEqual(fmt_money("390,5"), "390,5")

    def test_empty(self):
        self.assertEqual(fmt_money(""), "—")
        self.assertEqual(fmt_money(None), "—")


if __name__ == "__main__":
    unittest.main()