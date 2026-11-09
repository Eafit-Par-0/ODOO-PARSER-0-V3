from odoo import models, fields, api


class ImportSessionSheet(models.Model):
    _name = 'import.session.sheet'
    _description = 'Hoja del archivo cargado'
    _order = 'sequence, id'

    session_id = fields.Many2one('import.session', string='Sesión', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(string='Secuencia', default=10)
    name = fields.Char(string='Hoja', required=True)
    kind = fields.Selection([
        ('data', 'Datos'),
        ('instructions', 'Instrucciones'),
        ('values', 'Posibles valores (listas de consulta)'),
        ('empty', 'Vacía'),
    ], string='Tipo', required=True, default='data')
    visible = fields.Boolean(string='Visible', default=True)
    row_count = fields.Integer(string='Filas')
    column_count = fields.Integer(string='Columnas')
    dropped_rows = fields.Integer(string='Filas vacías descartadas',
                                    help='Filas sin datos reales (vacías, solo con valores por defecto de la plantilla o filas de marcas).')
    header_list = fields.Text(string='Encabezados')
    detected_model_id = fields.Many2one(
        'ir.model', string='Modelo detectado', readonly=True, ondelete='set null',
        help='Modelo de Odoo cuyos campos mejor coinciden con los encabezados de esta hoja.')
    detection_score = fields.Float(
        string='Coincidencia', readonly=True,
        help='Porcentaje de encabezados técnicos de la hoja que existen en el modelo detectado.')

    def _detect_models(self):
        """Detect, for every data sheet, the model its headers belong to."""
        from ..services.field_catalog import FieldCatalog
        for sheet in self.filtered(lambda s: s.kind == 'data' and s.header_list):
            headers = [h.strip() for h in sheet.header_list.split(',')]
            model_name, score = FieldCatalog.detect_model(self.env, headers)
            model = model_name and self.env['ir.model'].search([('model', '=', model_name)], limit=1)
            sheet.write({
                'detected_model_id': model.id if model else False,
                'detection_score': score,
            })

    @api.depends('name', 'kind', 'row_count')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = "%s (%s filas)" % (rec.name, rec.row_count) if rec.kind == 'data' else rec.name
