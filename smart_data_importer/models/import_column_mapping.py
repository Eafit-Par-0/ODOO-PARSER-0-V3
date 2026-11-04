from odoo import models, fields, api, _

REQUIRED_LEVELS = [
    ('required', 'Required'),
    ('conditional', 'Conditional'),
    ('optional', 'Optional'),
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
    _description = 'Import Column Mapping'

    session_id = fields.Many2one('import.session', string='Session', required=True, ondelete='cascade')
    source_header = fields.Char(string='Original Header', required=True)
    source_header_normalized = fields.Char(string='Normalized Header', required=True)
    sample_values = fields.Char(string='Sample Values')

    # The domain is set in the view from the session's target model
    target_field_id = fields.Many2one('ir.model.fields', string='Target Field', ondelete='cascade')
    target_field_name = fields.Char(related='target_field_id.name', string='Target Field Name', store=True, readonly=True)
    target_subfield = fields.Char(
        string='Sub-field',
        help="'id' means the cells hold external identifiers (e.g. base.state_co_01) instead of names.")

    confidence = fields.Float(string='Confidence Score', help="From 0.0 to 1.0")
    llm_justification = fields.Text(string='AI Justification', help="Explanation provided by the LLM for this suggested mapping.")
    source = fields.Selection([
        ('template', 'Template'),
        ('hash', 'Hash'),
        ('fuzzy', 'Fuzzy'),
        ('llm', 'LLM'),
        ('memory', 'Memory'),
        ('manual', 'Manual')
    ], string='Source')
    suggested_field_id = fields.Many2one(
        'ir.model.fields', string='Initially suggested field', ondelete='set null', readonly=True,
        help="Field proposed when the mapping was created. If the user changes it, the change is learned.")

    required_level = fields.Selection(REQUIRED_LEVELS, string='Required',
                                      help="Read from the header colour of the base template.")
    empty_count = fields.Integer(string='Empty cells')

    is_ignored = fields.Boolean(string='Ignore', default=False)
    is_conflict = fields.Boolean(string='Conflict', help="Target field is assigned to multiple columns", default=False)
    cleansing_rule_ids = fields.Many2many('import.cleansing.rule', string='Cleansing Rules')
    value_issue_overflow = fields.Boolean(
        string='Too many unknown values', readonly=True,
        help="The column has too many values unknown to Odoo; it is probably mapped to the wrong field.")

    # Does the column belong to the target model? (PO requirement #2)
    foreign_model_names = fields.Char(
        string='Pertenece a', readonly=True,
        help="Other Odoo models that have a field with exactly this technical name, "
             "while the target model does not.")
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