from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class ImportValueCorrection(models.Model):
    _name = 'import.value.correction'
    _description = 'Import Value Correction'
    _order = 'column_mapping_id, decision, original_value'

    session_id = fields.Many2one('import.session', required=True, ondelete='cascade', index=True)
    column_mapping_id = fields.Many2one('import.column.mapping', required=True, ondelete='cascade')
    mapping_signature = fields.Char(
        readonly=True, help="Field, sub-field and cleansing rules of the column when this row was computed. "
                            "If the column changes, the row is discarded.")
    field_id = fields.Many2one(related='column_mapping_id.target_field_id', store=True)
    comodel_name = fields.Char(related='field_id.relation', store=True)

    original_value = fields.Char(required=True, help="Value after the column cleansing rules.")
    normalized_value = fields.Char(required=True, index=True)
    occurrence_count = fields.Integer(string='Rows')
    issue_type = fields.Selection([('not_found', 'Not found'), ('ambiguous', 'Ambiguous')], required=True)

    suggested_label = fields.Char()
    suggested_key = fields.Char(help="Selection key.")
    suggested_res_id = fields.Many2oneReference(model_field='comodel_name')
    confidence = fields.Float(help="From 0.0 to 1.0, like import.column.mapping.")
    is_ambiguous = fields.Boolean()
    source = fields.Selection([('fuzzy', 'Similarity'), ('memory', 'Memory'), ('none', 'No suggestion')])

    decision = fields.Selection([
        ('pending', 'Pending'),
        ('accept', 'Accept suggestion'),
        ('manual', 'Manual value'),
        ('empty', 'Leave empty'),
    ], default='pending', required=True)
    manual_value = fields.Char(help="Exact name or code. Resolved with the same lookup as the import.")
    resolved_key = fields.Char()
    resolved_res_id = fields.Many2oneReference(model_field='comodel_name')

    _value_per_column_uniq = models.Constraint(
        'unique(column_mapping_id, normalized_value)',
        'Each value appears once per column.',
    )

    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.filtered('manual_value')._resolve_manual()
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'manual_value' in vals:
            self._resolve_manual()
        elif vals.get('decision') == 'manual':
            for rec in self:
                if not rec.manual_value:
                    raise ValidationError(_("Type the exact value to use for '%s'.", rec.original_value))
        elif vals.get('decision') == 'accept':
            for rec in self:
                if not (rec.suggested_key or rec.suggested_res_id):
                    raise ValidationError(_("There is no suggestion to accept for '%s'.", rec.original_value))
        return res

    def _resolve_manual(self):
        """Resolve ``manual_value`` with the same lookup the import uses."""
        from ..services.value_converter import ConversionError, ValueConverter

        for rec in self:
            if not rec.manual_value or not rec.manual_value.strip():
                # cleared: back to pending
                super(ImportValueCorrection, rec).write({
                    'manual_value': False,
                    'resolved_key': False,
                    'resolved_res_id': False,
                    'decision': 'pending' if rec.decision == 'manual' else rec.decision,
                })
                continue
            mapping = rec.column_mapping_id
            field = mapping.target_field_id
            converter = ValueConverter(self.env, rec.session_id.target_model_id.model)
            try:
                resolved = converter.resolve_single(
                    field.name, rec.manual_value, subfield=mapping.target_subfield or None)
            except ConversionError as e:
                raise ValidationError(
                    _("The value '%(value)s' could not be resolved: %(error)s",
                      value=rec.manual_value, error=str(e)))
            vals = {'decision': 'manual', 'resolved_key': False, 'resolved_res_id': False}
            if field.ttype == 'selection':
                vals['resolved_key'] = resolved
            else:
                vals['resolved_res_id'] = resolved
            super(ImportValueCorrection, rec).write(vals)
