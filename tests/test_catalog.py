import unittest, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.clean_catalog import clean_price, extract_brand, extract_oem, extract_qty

class TestCatalogCleaning(unittest.TestCase):
    def test_clean_price_normal(self):
        self.assertEqual(clean_price('1 500 руб'), 1500.0)
        self.assertEqual(clean_price('1500.00'), 1500.0)
        self.assertEqual(clean_price('1500р'), 1500.0)
        self.assertEqual(clean_price('8 990,00'), 8990.0)
        self.assertEqual(clean_price('390,5'), 390.5)
    def test_clean_price_from(self):
        self.assertEqual(clean_price('от 450 руб'), 450.0)
    def test_extract_brand(self):
        self.assertEqual(extract_brand('Колодки тормозные Mavico MV1028F'), 'Mavico')
        self.assertEqual(extract_brand('Диск тормозной DBA 42312'), 'DBA')
    def test_extract_oem(self):
        self.assertEqual(extract_oem('BD5510 ... OEM 8200123456'), '8200123456')
    def test_extract_qty_komplekt(self):
        qty, unit = extract_qty('комплект 4 шт')
        self.assertEqual(qty, 4)
        self.assertEqual(unit, 'комплект')

    def test_output_price_two_decimals(self):
        # цена в catalog_clean.csv всегда с двумя знаками после точки
        import tempfile as _t
        tmpdir = _t.mkdtemp()
        src = Path(tmpdir) / 'raw.csv'
        out = Path(tmpdir) / 'clean.csv'
        src.write_text(
            'offer_id,name,price,stock\n'
            'MV1028F,Колодки тормозные Mavico MV1028F,1500 руб,37\n'
            'CF3300,Фильтр салонный Mavico CF-3300,от 450 руб,\n',
            encoding='utf-8-sig',
        )
        from src.clean_catalog import clean_catalog
        clean_catalog(src, out)
        content = out.read_text(encoding='utf-8-sig')
        self.assertIn('1500.00', content)
        self.assertIn('450.00', content)
        self.assertNotIn('1500.0,', content)

if __name__ == '__main__':
    unittest.main()
