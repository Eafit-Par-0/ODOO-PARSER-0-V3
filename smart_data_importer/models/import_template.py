from odoo import models, fields, api, _


class ImportTemplate(models.Model):
    _name = 'import.template'
    _inherit = [
        'import.deduplication.mixin',
        'import.signature.mixin'
    ]
    _description = 'Plantilla de importación'
    _order = 'create_date desc'

    name = fields.Char(string='Nombre de la plantilla', required=True)
    active = fields.Boolean(string='Activo', default=True)
    description = fields.Text(string='Descripción / notas de origen')

    model_id = fields.Many2one(
        'ir.model',
        string='Modelo destino',
        required=True,
        ondelete='cascade',
        default=lambda self: self.env['ir.model'].search([('model', '=', 'res.partner')], limit=1)
    )

    line_ids = fields.One2many('import.template.line', 'template_id', string='Columnas de la plantilla', copy=True)
    line_count = fields.Integer(string='Número de columnas', compute='_compute_line_count')

    @api.depends('line_ids')
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    @api.model
    def find_matching_template(self, headers, model_name='res.partner'):
        """Searches for an active template matching the provided column headers."""
        signature = self.compute_header_signature(headers)
        if not signature:
            return self.browse()
        return self.search([
            ('active', '=', True),
            ('model_id.model', '=', model_name),
            ('header_signature', '=', signature)
        ], limit=1)

    @api.model
    def upsert_for_headers(self, headers, model, name, lines_vals, duplicate_criterion=None,
                           duplicate_policy=None, description=None):
        """Create the template for these headers, or update the existing one.

        Re-running the AI or saving the same mapping twice no longer creates
        duplicated templates.
        """
        signature = self.compute_header_signature(headers)
        vals = {
            'header_signature': signature,
            'header_list': self.format_header_list(headers),
            'line_ids': [(5, 0, 0)] + [(0, 0, dict(v, sequence=i)) for i, v in enumerate(lines_vals)],
        }
        if duplicate_criterion:
            vals['duplicate_criterion'] = duplicate_criterion
        if duplicate_policy:
            vals['duplicate_policy'] = duplicate_policy
        if description:
            vals['description'] = description

        template = self.find_matching_template(headers, model_name=model.model)
        if template:
            template.write(vals)
        else:
            vals.update({'name': name, 'model_id': model.id})
            template = self.create(vals)
        return template


class ImportTemplateLine(models.Model):
    _name = 'import.template.line'
    _description = 'Columna de plantilla'
    _order = 'sequence, id'

    template_id = fields.Many2one('import.template', string='Plantilla', required=True, ondelete='cascade')
    sequence = fields.Integer(string='Secuencia', default=10)
    source_header = fields.Char(string='Encabezado del archivo', required=True)
    # The domain is set in the view from the template's model
    target_field_id = fields.Many2one('ir.model.fields', string='Campo destino', ondelete='cascade')
    target_subfield = fields.Char(string='Subcampo')
    cleansing_rule_ids = fields.Many2many('import.cleansing.rule', string='Reglas de limpieza')
    is_ignored = fields.Boolean(string='Ignorar columna', default=False)
