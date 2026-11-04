from odoo import models, fields

from ..services.error_explainer import CATEGORIES

ERROR_CATEGORIES = [(code, title) for code, (title, _msg, _hint) in CATEGORIES.items()]


class ImportRowError(models.Model):
    _name = 'import.row.error'
    _description = 'Error de fila'
    _order = 'column_header, row_number, id'

    job_id = fields.Many2one('import.job', string='Lote', required=True, ondelete='cascade')
    session_id = fields.Many2one('import.session', related='job_id.session_id', store=True, string='Sesión')
    row_number = fields.Integer(string='Fila')
    raw_data = fields.Text(string='Datos de la fila')
    error_type = fields.Char(string='Tipo técnico')
    error_message = fields.Text(string='Detalle técnico')

    # Plain-language description, one record per cell (or per row when the
    # error is not tied to a single column)
    column_header = fields.Char(string='Columna', index=True)
    field_label = fields.Char(string='Campo de Odoo')
    cell_value = fields.Char(string='Valor')
    error_category = fields.Selection(ERROR_CATEGORIES, string='Problema', index=True)
    friendly_message = fields.Char(string='Qué pasó')
    hint = fields.Char(string='Cómo corregirlo')