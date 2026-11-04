from odoo import models, fields, api, _

REQUIRED_LEVELS = [
    ('required', 'Obligatorio'),
    ('conditional', 'Condicional'),
    ('optional', 'Opcional'),
]

# Field name -> cleansing rule suggested when the user picks it manually
DEFAULT_RULES_BY_FIELD = {
    'email': 'email',
    'email_edi': 'email',
    'phone': 'phone',
    'mobile': 'phone',
    'vat': 'vat_document',
}


class ImportColumnMapping(models.Model):
    _name = 'import.column.mapping'
    _description = 'Mapeo de columna'

    session_id = fields.Many2one('import.session', string='Sesión', required=True, ondelete='cascade')
    source_header = fields.Char(string='Encabezado original', required=True)
    source_header_normalized = fields.Char(string='Encabezado normalizado', required=True)
    sample_values = fields.Char(string='Valores de ejemplo')

    # The domain is set in the view from the session's target model
    target_field_id = fields.Many2one('ir.model.fields', string='Campo destino', ondelete='cascade')
    target_field_name = fields.Char(related='target_field_id.name', string='Nombre técnico del campo', store=True, readonly=True)
    target_subfield = fields.Char(
        string='Subcampo',
        help="'id' indica que las celdas traen identificadores externos (ej. base.state_co_01) en lugar de nombres.")

    confidence = fields.Float(string='Confianza', help='De 0.0 a 1.0')
    llm_justification = fields.Text(string='Justificación de la IA', help='Explicación de la IA para este mapeo sugerido.')
    source = fields.Selection([
        ('template', 'Plantilla'),
        ('hash', 'Nombre exacto'),
        ('fuzzy', 'Similitud'),
        ('llm', 'IA'),
        ('memory', 'Memoria'),
        ('manual', 'Manual')
    ], string='Origen')
    suggested_field_id = fields.Many2one(
        'ir.model.fields', string='Campo sugerido inicialmente', ondelete='set null', readonly=True,
        help='Campo propuesto al crear el mapeo. Si el usuario lo cambia, el cambio se aprende.')

    required_level = fields.Selection(REQUIRED_LEVELS, string='Obligatorio',
                                      help='Se lee del color del encabezado en la plantilla base.')
    empty_count = fields.Integer(string='Celdas vacías')

    is_ignored = fields.Boolean(string='Ignorar', default=False)
    is_conflict = fields.Boolean(string='Conflicto', help='El campo destino está asignado a varias columnas', default=False)
    cleansing_rule_ids = fields.Many2many('import.cleansing.rule', string='Reglas de limpieza')
    value_issue_overflow = fields.Boolean(
        string='Demasiados valores desconocidos', readonly=True,
        help='La columna tiene demasiados valores que Odoo no conoce; probablemente está asignada al campo equivocado.')

    # Does the column belong to the target model? (PO requirement #2)
    foreign_model_names = fields.Char(
        string='Pertenece a', readonly=True,
        help='Otros modelos de Odoo que tienen un campo con este mismo nombre técnico, que el modelo destino no tiene.')
    model_fit = fields.Selection([
        ('ok', 'Del modelo'),
        ('foreign', 'De otro modelo'),
        ('unknown', 'Sin campo'),
        ('ignored', 'Ignorada'),
    ], string='¿Pertenece?', compute='_compute_model_fit', store=True)
    model_fit_note = fields.Char(string='Aviso de columna', compute='_compute_model_fit', store=True)

    @api.depends('target_field_id', 'is_ignored', 'foreign_model_names', 'source',
                 'session_id.target_model_id')
    def _compute_model_fit(self):
        for rec in self:
            model = rec.session_id.target_model_id.name or rec.session_id.target_model_id.model or ''
            header = rec.source_header
            guessed = rec.source in ('fuzzy', 'llm')
            if rec.is_ignored:
                rec.model_fit = 'ignored'
                rec.model_fit_note = False
            elif rec.foreign_model_names and (not rec.target_field_id or guessed):
                rec.model_fit = 'foreign'
                if rec.target_field_id:
                    rec.model_fit_note = _(
                        "'%(header)s' es un campo de %(others)s, no de %(model)s. Se asignó por parecido a "
                        "'%(field)s': confirma que es correcto o ignora la columna."
                    ) % {'header': header, 'others': rec.foreign_model_names, 'model': model,
                         'field': rec.target_field_id.field_description}
                else:
                    rec.model_fit_note = _(
                        "'%(header)s' no existe en %(model)s: es un campo de %(others)s. "
                        "Esta columna no se importará."
                    ) % {'header': header, 'model': model, 'others': rec.foreign_model_names}
            elif not rec.target_field_id:
                rec.model_fit = 'unknown'
                rec.model_fit_note = _(
                    "No se encontró un campo de %(model)s para '%(header)s'. "
                    "Asígnalo a mano o ignóralo; si no, esta columna no se importará."
                ) % {'model': model, 'header': header}
            else:
                rec.model_fit = 'ok'
                rec.model_fit_note = False

    @api.onchange('target_field_id')
    def _onchange_target_field_id(self):
        if not self.target_field_id:
            return
        self.source = 'manual'
        Rule = self.env['import.cleansing.rule']
        rules = Rule
        if self.target_field_id.ttype in ('char', 'text', 'many2one', 'many2many', 'selection'):
            rules |= Rule.search([('action_type', '=', 'strip')], limit=1)
        special = DEFAULT_RULES_BY_FIELD.get(self.target_field_id.name)
        if special:
            rules |= Rule.search([('action_type', '=', special)], limit=1)
        self.cleansing_rule_ids = [(6, 0, rules.ids)]