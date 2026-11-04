import base64

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestColumnErrors(TransactionCase):
    """PO requirements #1 (errors grouped by column, plain language) and
    #2 (columns that do not belong to the target model)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Session = cls.env['import.session']
        cls.env['ir.config_parameter'].sudo().set_param('smart_data_importer.llm_enabled', 'False')
        cls.partner_model = cls.env['ir.model']._get('res.partner')

    def _session(self, csv_text, filename='contactos.csv'):
        session = self.Session.create({
            'filename': filename,
            'file': base64.b64encode(csv_text.encode('utf-8')),
            'target_model_id': self.partner_model.id,
        })
        session.target_model_id = self.partner_model
        session.action_analyze()
        return session

    def _mapping(self, session, header):
        return session.column_mapping_ids.filtered(lambda m: m.source_header == header)

    # ------------------------------------------------------------------
    # Requirement #1
    # ------------------------------------------------------------------
    def test_01_precheck_groups_bad_numbers_by_column(self):
        session = self._session(
            "name,color\nAna EC,3\nBeto EC,rojo\nCarla EC,azul\nDani EC,rojo\n")
        self.assertEqual(session.state, 'mapped')
        summary = session.precheck_error_summary_ids
        self.assertEqual(len(summary), 1, "One line for the column, not one per row")
        self.assertEqual(summary.column_header, 'color')
        self.assertEqual(summary.error_category, 'invalid_number')
        self.assertEqual(summary.row_count, 3)
        self.assertIn('rojo', summary.sample_values)
        self.assertIn('azul', summary.sample_values)
        self.assertTrue(summary.hint)
        self.assertEqual(session.precheck_problem_count, 3)
        self.assertEqual(session.precheck_column_count, 1)

    def test_02_precheck_refreshes_when_column_is_ignored(self):
        session = self._session("name,color\nAna EC2,rojo\n")
        self.assertTrue(session.precheck_error_summary_ids)
        session.write({'column_mapping_ids': [(1, self._mapping(session, 'color').id, {'is_ignored': True})]})
        self.assertFalse(session.precheck_error_summary_ids)

    def test_03_import_errors_grouped_with_plain_message(self):
        session = self._session("name,color\nAna EC3,3\nBeto EC3,rojo\nCarla EC3,verde\n")
        session.action_confirm_mapping()
        self.assertEqual(session.state, 'done')
        self.assertEqual(session.created_rows, 1)
        self.assertEqual(session.failed_rows, 2)

        errors = session.row_error_ids
        self.assertEqual(len(errors), 2)
        self.assertEqual(set(errors.mapped('column_header')), {'color'})
        self.assertEqual(set(errors.mapped('error_category')), {'invalid_number'})
        self.assertTrue(all(errors.mapped('friendly_message')))
        self.assertEqual(set(errors.mapped('cell_value')), {'rojo', 'verde'})

        summary = session.import_error_summary_ids
        self.assertEqual(len(summary), 1)
        self.assertEqual(summary.row_count, 2)
        self.assertEqual(session.import_error_column_count, 1)
        action = summary.action_view_rows()
        self.assertEqual(self.env['import.row.error'].search(action['domain']), errors)

    def test_04_confirm_again_resets_import_summary(self):
        session = self._session("name,color\nAna EC4,rojo\n")
        session.action_confirm_mapping()
        self.assertTrue(session.import_error_summary_ids)
        session.write({'state': 'mapped'})
        session.write({'column_mapping_ids': [(1, self._mapping(session, 'color').id, {'is_ignored': True})]})
        session.action_confirm_mapping()
        self.assertFalse(session.import_error_summary_ids)

    # ------------------------------------------------------------------
    # Requirement #2
    # ------------------------------------------------------------------
    def test_10_column_of_another_model_is_flagged(self):
        session = self._session("name,login,symbol\nAna EC10,ana,$\n")
        login = self._mapping(session, 'login')
        self.assertEqual(login.model_fit, 'foreign')
        self.assertTrue(login.foreign_model_names)
        self.assertIn('login', login.model_fit_note)
        self.assertEqual(self._mapping(session, 'name').model_fit, 'ok')
        self.assertEqual(session.foreign_column_count, 2)
        self.assertIn('login', session.foreign_columns_text)

    def test_11_unknown_column_is_flagged_and_can_be_ignored(self):
        session = self._session("name,Columna Rara XYZ\nAna EC11,algo\n")
        odd = self._mapping(session, 'Columna Rara XYZ')
        self.assertEqual(odd.model_fit, 'unknown')
        self.assertEqual(session.unknown_column_count, 1)

        session.action_ignore_foreign_columns()
        self.assertTrue(odd.is_ignored)
        self.assertEqual(odd.model_fit, 'ignored')
        self.assertEqual(session.unknown_column_count, 0)

    def test_12_manual_mapping_clears_the_warning(self):
        session = self._session("name,Columna Rara XYZ\nAna EC12,algo\n")
        odd = self._mapping(session, 'Columna Rara XYZ')
        comment = self.env['ir.model.fields']._get('res.partner', 'comment')
        session.write({'column_mapping_ids': [(1, odd.id, {'target_field_id': comment.id, 'source': 'manual'})]})
        self.assertEqual(odd.model_fit, 'ok')
        self.assertFalse(odd.model_fit_note)