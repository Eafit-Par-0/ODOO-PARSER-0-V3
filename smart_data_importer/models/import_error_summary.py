from odoo import models, fields, _

from .import_row_error import ERROR_CATEGORIES


class ImportErrorSummary(models.Model):
    """One line per (column, kind of problem) so the user sees *what* to fix
    in *which* column instead of a long list of row errors."""
    _name = 'import.error.summary'
    _description = 'Import Errors Grouped by Column'
    _order = 'stage, sequence, id'

    session_id = fields.Many2one('import.session', required=True, ondelete='cascade', index=True)
    stage = fields.Selection([
        ('precheck', 'Antes de importar'),
        ('import', 'Durante la importación'),
    ], string='Etapa', required=True, default='precheck')
    sequence = fields.Integer(default=10)

    column_header = fields.Char(string='Columna', required=True)
    field_label = fields.Char(string='Campo de Odoo')
    error_category = fields.Selection(ERROR_CATEGORIES, string='Problema', required=True)
    title = fields.Char(string='Problema (resumen)')
    message = fields.Char(string='Qué pasó')
    hint = fields.Char(string='Cómo corregirlo')
    error_count = fields.Integer(string='Errores')
    row_count = fields.Integer(string='Filas afectadas')
    rows_text = fields.Char(string='Filas')
    sample_values = fields.Char(string='Valores de ejemplo')
    technical_detail = fields.Text(string='Detalle técnico (ejemplo)')

    def action_view_rows(self):
        """Open the row errors behind this line (only after an import)."""
        self.ensure_one()
        domain = [('session_id', '=', self.session_id.id), ('error_category', '=', self.error_category)]
        if self.column_header == self.env['import.session']._whole_row_label():
            domain.append(('column_header', 'in', [False, self.column_header]))
        else:
            domain.append(('column_header', '=', self.column_header))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Filas con error en '%s'") % self.column_header,
            'res_model': 'import.row.error',
            'view_mode': 'list,form',
            'views': [(self.env.ref('smart_data_importer.view_import_row_error_list').id, 'list'),
                      (False, 'form')],
            'domain': domain,
            'target': 'new',
        }