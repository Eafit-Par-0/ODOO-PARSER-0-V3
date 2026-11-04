from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class ImportValueCorrection(models.Model):
    _name = 'import.value.correction'
    _description = 'Corrección de valor'
    _order = 'column_mapping_id, decision, original_value'

    session_id = fields.Many2one('import.session', string='Sesión', required=True, ondelete='cascade', index=True)
    column_mapping_id = fields.Many2one('import.column.mapping', string='Columna', required=True, ondelete='cascade')
    mapping_signature = fields.Char(string='Firma del mapeo', 
        readonly=True, help='Campo, subcampo y reglas de limpieza de la columna cuando se calculó esta fila. Si la columna cambia, la fila se descarta.')
    field_id = fields.Many2one(string='Campo de Odoo', related='column_mapping_id.target_field_id', store=True)
    comodel_name = fields.Char(string='Modelo relacionado', related='field_id.relation', store=True)

    original_value = fields.Char(string='Valor en el archivo', required=True, help='Valor después de aplicar las reglas de limpieza de la columna.')
    normalized_value = fields.Char(string='Valor normalizado', required=True, index=True)
    occurrence_count = fields.Integer(string='Filas')
    issue_type = fields.Selection([('not_found', 'No encontrado'), ('ambiguous', 'Ambiguo')], string='Problema', required=True)

    suggested_label = fields.Char(string='Sugerencia')
    suggested_key = fields.Char(string='Clave sugerida', help='Clave de la opción.')
    suggested_res_id = fields.Many2oneReference(string='Registro sugerido', model_field='comodel_name')
    confidence = fields.Float(string='Similitud', help='De 0.0 a 1.0, igual que en el mapeo de columnas.')
    is_ambiguous = fields.Boolean(string='Ambiguo')
    source = fields.Selection([('fuzzy', 'Similitud'), ('memory', 'Memoria'), ('none', 'Sin sugerencia')], string='Origen de la sugerencia')

    decision = fields.Selection([
        ('pending', 'Pendiente'),
        ('accept', 'Aceptar sugerencia'),
        ('manual', 'Valor manual'),
        ('empty', 'Dejar vacío'),
    ], string='Decisión', default='pending', required=True)
    manual_value = fields.Char(string='Valor manual', help='Nombre o código exacto. Se busca igual que en la importación.')
    resolved_key = fields.Char(string='Clave elegida')
    resolved_res_id = fields.Many2oneReference(string='Registro elegido', model_field='comodel_name')

    _value_per_column_uniq = models.Constraint(
        'unique(column_mapping_id, normalized_value)',
        'Cada valor aparece una sola vez por columna.',
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
                    raise ValidationError(_("Escribe el valor exacto que se usará para '%s'.", rec.original_value))
        elif vals.get('decision') == 'accept':
            for rec in self:
                if not (rec.suggested_key or rec.suggested_res_id):
                    raise ValidationError(_("No hay ninguna sugerencia para aceptar en '%s'.", rec.original_value))
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
                    _("No se pudo encontrar el valor '%(value)s': %(error)s",
                      value=rec.manual_value, error=str(e)))
            vals = {'decision': 'manual', 'resolved_key': False, 'resolved_res_id': False}
            if field.ttype == 'selection':
                vals['resolved_key'] = resolved
            else:
                vals['resolved_res_id'] = resolved
            super(ImportValueCorrection, rec).write(vals)
