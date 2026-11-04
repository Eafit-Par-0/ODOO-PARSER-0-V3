import base64

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestValueCorrection(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Session = cls.env['import.session']
        cls.Config = cls.env['ir.config_parameter']
        cls.Config.sudo().set_param('smart_data_importer.llm_enabled', 'False')
        cls.Config.sudo().set_param('smart_data_importer.value_fuzzy_threshold', '80')
        cls.Config.sudo().set_param('smart_data_importer.value_bulk_accept_threshold', '90')
        cls.Config.sudo().set_param('smart_data_importer.value_fuzzy_max_candidates', '5000')
        cls.colombia = cls.env.ref('base.co')

    def _session(self, csv_text, filename='contactos.csv'):
        session = self.Session.create({
            'filename': filename,
            'file': base64.b64encode(csv_text.encode('utf-8')),
        })
        session.action_analyze()
        return session

    def _country_session(self):
        return self._session("name,country_id\nAna VC,Colmbia\nBeto VC,Colmbia\nCarla VC,Colmbia\n")

    # ------------------------------------------------------------------
    def test_01_typo_creates_one_correction(self):
        """CA-01: one row per distinct value, with the rows affected and a suggestion."""
        session = self._country_session()
        self.assertEqual(session.state, 'mapped')
        self.assertEqual(len(session.value_correction_ids), 1)
        corr = session.value_correction_ids
        self.assertEqual(corr.occurrence_count, 3)
        self.assertEqual(corr.issue_type, 'not_found')
        self.assertEqual(corr.source, 'fuzzy')
        self.assertEqual(corr.suggested_res_id, self.colombia.id)
        self.assertEqual(corr.suggested_label, self.colombia.display_name)
        self.assertGreaterEqual(corr.confidence, 0.9)
        self.assertFalse(corr.is_ambiguous)
        self.assertEqual(corr.decision, 'pending')
        self.assertEqual(session.value_issue_pending_count, 1)

    def test_02_confirm_blocked_while_pending(self):
        """CA-02: pending values block the import."""
        session = self._country_session()
        with self.assertRaises(UserError):
            session.action_confirm_mapping()
        self.assertEqual(session.state, 'mapped')
        self.assertFalse(session.job_ids)

    def test_03_accept_then_import(self):
        """CA-03: an accepted suggestion is applied by the import job."""
        session = self._country_session()
        session.action_accept_value_suggestions()
        self.assertEqual(session.value_correction_ids.decision, 'accept')
        self.assertEqual(session.value_issue_pending_count, 0)
        session.action_confirm_mapping()

        self.assertEqual(session.state, 'done')
        self.assertEqual(session.failed_rows, 0)
        partners = self.env['res.partner'].search([('name', 'in', ['Ana VC', 'Beto VC', 'Carla VC'])])
        self.assertEqual(len(partners), 3)
        self.assertEqual(partners.country_id, self.colombia)
        self.assertFalse(session.row_error_ids)

    def test_04_selection_typo(self):
        """CA-06: a typo on a selection field suggests the option key."""
        session = self._session("name,company_type\nPersona VC,persna\n")
        corr = session.value_correction_ids
        self.assertEqual(len(corr), 1)
        self.assertEqual(corr.suggested_key, 'person')
        self.assertGreaterEqual(corr.confidence, 0.8)
        self.assertLess(corr.confidence, 0.9)
        # below the bulk threshold: needs an individual decision
        session.action_accept_value_suggestions()
        self.assertEqual(corr.decision, 'pending')
        corr.decision = 'accept'
        self.assertEqual(session._value_overrides(), {('company_type', 'persna'): 'person'})

    def test_05_changing_the_column_target_clears_corrections(self):
        """CA-07: editing the mapping of a column discards its corrections."""
        session = self._country_session()
        self.assertTrue(session.value_correction_ids)
        col = session.column_mapping_ids.filtered(lambda m: m.source_header == 'country_id')
        city = self.env['ir.model.fields'].search([('model', '=', 'res.partner'), ('name', '=', 'city')])
        session.write({'column_mapping_ids': [(1, col.id, {'target_field_id': city.id})]})
        self.assertFalse(session.value_correction_ids)
        self.assertFalse(col.value_issue_overflow)

    def test_05b_one_save_changes_mapping_and_decision(self):
        """A single save that edits another mapping and a correction row keeps the decision."""
        session = self._country_session()
        corr = session.value_correction_ids
        name_col = session.column_mapping_ids.filtered(lambda m: m.source_header == 'name')
        session.write({
            'column_mapping_ids': [(1, name_col.id, {'confidence': 0.5})],
            'value_correction_ids': [(1, corr.id, {'decision': 'accept'})],
        })
        self.assertEqual(len(session.value_correction_ids), 1)
        self.assertEqual(session.value_correction_ids.decision, 'accept')

    def test_05c_apply_same_values_keeps_decisions(self):
        """Re-writing a mapping with the same values does not discard decisions."""
        session = self._country_session()
        session.value_correction_ids.decision = 'accept'
        col = session.column_mapping_ids.filtered(lambda m: m.source_header == 'country_id')
        session.write({'column_mapping_ids': [(1, col.id, {'target_field_id': col.target_field_id.id})]})
        self.assertEqual(session.value_correction_ids.decision, 'accept')

    def test_06_too_many_candidates_means_no_suggestion(self):
        """CA-08: relational models above the cap are not searched."""
        self.Config.sudo().set_param('smart_data_importer.value_fuzzy_max_candidates', '1')
        session = self._country_session()
        corr = session.value_correction_ids
        self.assertEqual(len(corr), 1)
        self.assertEqual(corr.issue_type, 'not_found')
        self.assertEqual(corr.source, 'none')
        self.assertFalse(corr.suggested_res_id)

    def test_07_manual_value(self):
        """A manual value is resolved with the import lookup."""
        session = self._country_session()
        corr = session.value_correction_ids
        peru = self.env.ref('base.pe')
        corr.write({'manual_value': peru.name})
        self.assertEqual(corr.decision, 'manual')
        self.assertEqual(corr.resolved_res_id, peru.id)
        self.assertEqual(session._value_overrides(), {('country_id', 'colmbia'): peru.id})

        with self.assertRaises(ValidationError):
            corr.write({'manual_value': 'Pais que no existe'})

        corr.write({'manual_value': False})
        self.assertEqual(corr.decision, 'pending')
        self.assertFalse(corr.resolved_res_id)

    def test_08_leave_empty(self):
        """Decision 'empty' imports the rows without the country."""
        session = self._country_session()
        session.value_correction_ids.decision = 'empty'
        session.action_confirm_mapping()
        self.assertEqual(session.state, 'done')
        self.assertEqual(session.failed_rows, 0)
        partners = self.env['res.partner'].search([('name', 'in', ['Ana VC', 'Beto VC', 'Carla VC'])])
        self.assertEqual(len(partners), 3)
        self.assertFalse(partners.country_id)

    def test_09_decisions_survive_revalidation(self):
        """Validating again keeps what the user already decided."""
        session = self._country_session()
        session.value_correction_ids.decision = 'accept'
        session._validate_values()
        self.assertEqual(len(session.value_correction_ids), 1)
        self.assertEqual(session.value_correction_ids.decision, 'accept')

    # ------------------------------------------------------------------
    # Value memory
    # ------------------------------------------------------------------

    def _memory(self, field_name, normalized_value):
        return self.env['import.value.memory'].with_context(active_test=False).search([
            ('field_id.name', '=', field_name), ('normalized_value', '=', normalized_value)])

    def test_10_memory_is_learned_and_applied(self):
        """CA-09: an accepted correction is remembered and applied, visibly, in the next load."""
        first = self._country_session()
        first.action_accept_value_suggestions()
        first.action_confirm_mapping()
        memory = self._memory('country_id', 'colmbia')
        self.assertEqual(len(memory), 1)
        self.assertEqual(memory.res_id, self.colombia.id)
        self.assertEqual(memory.usage_count, 1)

        second = self._session("name,country_id\nDiana VC,Colmbia\n")
        corr = second.value_correction_ids
        self.assertEqual(len(corr), 1)
        self.assertEqual(corr.source, 'memory')
        self.assertEqual(corr.decision, 'accept')
        self.assertEqual(corr.suggested_res_id, self.colombia.id)
        self.assertEqual(second.value_issue_pending_count, 0)
        self.assertEqual(second.value_memory_applied_count, 1)

        second.action_confirm_mapping()
        self.assertEqual(second.state, 'done')
        partner = self.env['res.partner'].search([('name', '=', 'Diana VC')])
        self.assertEqual(partner.country_id, self.colombia)
        self.assertEqual(memory.usage_count, 2)

    def test_11_memory_of_deleted_record_is_deactivated(self):
        """CA-10: a memory pointing to a deleted record is not applied and gets deactivated."""
        state = self.env['res.country.state'].create({
            'name': 'Estadoprueba VC', 'code': 'ZZV', 'country_id': self.colombia.id})
        csv_text = "name,state_id\nPepe VC,Estadoprueba VQ\n"
        session = self._session(csv_text)
        corr = session.value_correction_ids
        self.assertEqual(len(corr), 1)
        corr.write({'manual_value': 'Estadoprueba VC'})
        session.action_confirm_mapping()
        memory = self._memory('state_id', 'estadoprueba vq')
        self.assertEqual(memory.res_id, state.id)
        self.assertTrue(memory.active)

        self.env['res.partner'].search([('name', '=', 'Pepe VC')]).unlink()
        state.unlink()

        again = self._session(csv_text)
        self.assertEqual(len(again.value_correction_ids), 1)
        self.assertNotEqual(again.value_correction_ids.source, 'memory')
        self.assertEqual(again.value_correction_ids.decision, 'pending')
        self.assertFalse(memory.active)

    def test_12_empty_decision_is_not_learned(self):
        session = self._country_session()
        session.value_correction_ids.decision = 'empty'
        session.action_confirm_mapping()
        self.assertFalse(self._memory('country_id', 'colmbia'))
