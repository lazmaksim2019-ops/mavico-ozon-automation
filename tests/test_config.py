import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import load_settings

class TestConfig(unittest.TestCase):
    def test_load_settings_with_env(self):
        settings = load_settings()
        self.assertEqual(settings.ozon_client_id, '5304144')
        self.assertTrue(settings.ozon_api_key.startswith('71be708c'))
        self.assertEqual(settings.low_stock_threshold, 5)
        self.assertEqual(settings.telegram_bot_token, '8987021692:AAEVnZo7sw4EMWdKyVfB9GbKIOFIPmA-Ngk')
        self.assertEqual(settings.telegram_chat_id, '7830322013')

if __name__ == '__main__':
    unittest.main()
