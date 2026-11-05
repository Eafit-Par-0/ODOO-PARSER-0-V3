import base64
import io

from odoo.tests.common import TransactionCase, tagged


def _make_workbook(sheets):
    """Workbook with one data sheet per ``{name: (headers, rows)}`` entry."""
    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, (headers, rows) in sheets.items():
        ws = wb.create_sheet(name)
        ws.append(headers)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return base64.b64encode(buf.getvalue())


CONTACTOS = (['name', 'vat', 'email', 'phone'],
             [['Empresa Uno', '901705206-5', 'uno@prueba.co', '3001234567']])
MONEDAS = (['name', 'symbol', 'rounding', 'decimal_places'],
           [['XYZ', 'X', 0.01, 2]])
CONTACTOS_2 = (['name', 'vat', 'email', 'phone'],
               [['Empresa Dos', '901705207-5', 'dos@prueba.co', '3007654321']])


@tagged('post_install', '-at_install')
class TestMixedModels(TransactionCase):

    def _session(self, sheets):
        return self.env['import.session'].create({
            'filename': 'libro.xlsx',
            'file': _make_workbook(sheets),
        })

    def test_01_detects_model_per_sheet(self):
        session = self._session({'Contactos': CONTACTOS, 'Monedas': MONEDAS})
        by_name = {s.name: s.detected_model_id.model for s in session.sheet_ids}
        self.assertEqual(by_name['Contactos'], 'res.partner')
        self.assertEqual(by_name['Monedas'], 'res.currency')

    def test_02_warns_when_models_are_mixed(self):
        session = self._session({'Contactos': CONTACTOS, 'Monedas': MONEDAS})
        self.assertTrue(session.is_mixed_models)
        self.assertIn('Contactos', session.mixed_models_text)
        self.assertIn('Monedas', session.mixed_models_text)

    def test_03_no_warning_when_same_model(self):
        session = self._session({'Contactos': CONTACTOS, 'Más contactos': CONTACTOS_2})
        self.assertFalse(session.is_mixed_models)
        self.assertFalse(session.mixed_models_text)

    def test_04_no_warning_with_single_sheet(self):
        session = self._session({'Contactos': CONTACTOS})
        self.assertFalse(session.is_mixed_models)

    def test_05_load_file_notification_mentions_mixed(self):
        session = self._session({'Contactos': CONTACTOS, 'Monedas': MONEDAS})
        action = session.action_load_file()
        params = action['params']
        self.assertEqual(params['type'], 'warning')
        self.assertIn('mezcla datos de varios módulos', params['message'])