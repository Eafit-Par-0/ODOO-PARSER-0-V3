import base64
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestHeaderMemory(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Session = cls.env['import.session']
        cls.Registry = cls.env['mapping.registry'].with_context(active_test=False)
        cls.env['ir.config_parameter'].sudo().set_param('smart_data_importer.llm_enabled', 'False')

    def _field(self, name):
        return self.env['ir.model.fields'].search([('model', '=', 'res.partner'), ('name', '=', name)])

    def _session(self, csv_text):
        session = self.Session.create({
            'filename': 'cabeceras.csv',
            'file': base64.b64encode(csv_text.encode('utf-8')),
        })
        session.action_analyze()
        return session

    def _map(self, session, header, **vals):
        col = session.column_mapping_ids.filtered(lambda m: m.source_header == header)
        session.write({'column_mapping_ids': [(1, col.id, vals)]})
        return col

    def _learned(self, synonym):
        return self.Registry.search([('synonym', '=ilike', synonym), ('origin', '=', 'learned')])

    def test_01_manual_header_is_learned_and_reused(self):
        """CA-11: a header mapped by hand is mapped automatically, from memory, next time."""
        from odoo.addons.smart_data_importer.services.mapper_llm import LLMMapper

        header = 'Zzq Cliente Interno'
        first = self._session("name,%s\nAna HM,901\n" % header)
        col = first.column_mapping_ids.filtered(lambda m: m.source_header == header)
        self.assertFalse(col.target_field_id)
        self._map(first, header, target_field_id=self._field('vat').id)
        first.action_confirm_mapping()

        learned = self._learned(header)
        self.assertEqual(len(learned), 1)
        self.assertEqual(learned.field_id.name, 'vat')
        self.assertEqual(learned.language, 'es')
        self.assertEqual(learned.usage_count, 1)

        config = self.env['ir.config_parameter'].sudo()
        config.set_param('smart_data_importer.llm_enabled', 'True')
        config.set_param('smart_data_importer.llm_provider', 'deepseek')
        config.set_param('smart_data_importer.llm_api_key', 'dummy-key')
        with patch.object(LLMMapper, '_call_llm', return_value='[]') as mocked:
            second = self._session("name,%s\nBeto HM,902\n" % header)
        mocked.assert_not_called()
        col = second.column_mapping_ids.filtered(lambda m: m.source_header == header)
        self.assertEqual(col.target_field_name, 'vat')
        self.assertEqual(col.source, 'memory')

    def test_02_seed_synonym_is_not_modified(self):
        """CA-12: remapping a factory synonym does not change it nor create a learned row."""
        seed = self.env.ref('smart_data_importer.mapping_es_nit')
        self.assertEqual(seed.field_id.name, 'vat')
        session = self._session("NIT,name\n123,Ana HM\n")
        self._map(session, 'NIT', target_field_id=self._field('ref').id)
        session.action_confirm_mapping()
        self.assertEqual(seed.field_id.name, 'vat')
        self.assertEqual(seed.origin, 'seed')
        self.assertFalse(self._learned('NIT'))

    def test_03_template_mappings_are_not_learned(self):
        header = 'Zzq Plantilla Interna'
        session = self._session("name,%s\nAna HM,903\n" % header)
        self._map(session, header, target_field_id=self._field('vat').id, source='template')
        session.action_confirm_mapping()
        self.assertFalse(self._learned(header))

    def test_04_last_decision_wins_and_unchanged_is_not_learned(self):
        header = 'Zzq Otro Encabezado'
        first = self._session("name,%s\nAna HM,904\n" % header)
        self._map(first, header, target_field_id=self._field('vat').id)
        first.action_confirm_mapping()
        # a later person maps the same header to another field
        second = self._session("name,%s\nBeto HM,905\n" % header)
        self._map(second, header, target_field_id=self._field('ref').id)
        second.action_confirm_mapping()
        learned = self._learned(header)
        self.assertEqual(len(learned), 1)
        self.assertEqual(learned.field_id.name, 'ref')
        self.assertEqual(learned.usage_count, 1)
        # a column left as suggested (name -> name) is never learned
        self.assertFalse(self._learned('name'))
