import unittest, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.ozon_client import chunked

class TestOzonClient(unittest.TestCase):
    def test_chunked(self):
        items = [1, 2, 3, 4, 5]
        chunks = list(chunked(items, 2))
        self.assertEqual(chunks, [[1, 2], [3, 4], [5]])

if __name__ == '__main__':
    unittest.main()
