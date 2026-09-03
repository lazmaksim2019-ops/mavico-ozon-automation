import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import load_settings

# Фейковые значения: реальные ключи живут ТОЛЬКО в .env и в код не попадают.
FAKE_ENV = {
    "OZON_CLIENT_ID": "12345",
    "OZON_API_KEY": "test-api-key",
    "OZON_BASE_URL": "https://api-seller.ozon.ru",
    "LOW_STOCK_THRESHOLD": "7",
    "TELEGRAM_BOT_TOKEN": "123456:TEST",
    "TELEGRAM_CHAT_ID": "42",
    "SUMMARY_TIME": "08:30",
}


class TestConfig(unittest.TestCase):
    @mock.patch.dict(os.environ, FAKE_ENV)
    def test_load_settings_reads_env(self):
        s = load_settings()
        self.assertEqual(s.ozon_client_id, "12345")
        self.assertEqual(s.ozon_api_key, "test-api-key")
        self.assertEqual(s.ozon_base_url, "https://api-seller.ozon.ru")
        self.assertEqual(s.low_stock_threshold, 7)
        self.assertEqual(s.telegram_bot_token, "123456:TEST")
        self.assertEqual(s.telegram_chat_id, "42")
        self.assertEqual(s.summary_time, "08:30")

    @mock.patch.dict(os.environ, FAKE_ENV)
    def test_default_threshold_is_5(self):
        env = {k: v for k, v in FAKE_ENV.items() if k != "LOW_STOCK_THRESHOLD"}
        with mock.patch.dict(os.environ, env, clear=True):
            s = load_settings()
        self.assertEqual(s.low_stock_threshold, 5)

    @mock.patch.dict(os.environ, {"LOW_STOCK_THRESHOLD": "abc"}, clear=True)
    def test_bad_threshold_raises(self):
        env = dict(os.environ)
        env.update(FAKE_ENV)
        env["LOW_STOCK_THRESHOLD"] = "abc"
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError):
                load_settings()

    @mock.patch.dict(os.environ, {"OZON_CLIENT_ID": "", "OZON_API_KEY": ""}, clear=True)
    def test_missing_ozon_keys_raises(self):
        with self.assertRaises(RuntimeError):
            load_settings()

    @mock.patch.dict(os.environ, FAKE_ENV)
    def test_telegram_required_raises_without_keys(self):
        env = {k: v for k, v in FAKE_ENV.items() if not k.startswith("TELEGRAM_")}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError):
                load_settings(require_telegram=True)
            # без require_telegram — не падает (dry-run режим)
            load_settings()


if __name__ == "__main__":
    unittest.main()
