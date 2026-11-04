from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class ImportFileMixin(models.AbstractModel):
    _name = 'import.file.mixin'
    _description = 'Manejo de archivos de importación'

    file = fields.Binary(string='Archivo', required=True, attachment=True)
    filename = fields.Char(string='Nombre del archivo', required=True)
    
    encoding = fields.Char(string='Codificación', readonly=True)
    delimiter = fields.Char(string='Separador', readonly=True)
    header_row_index = fields.Integer(string='Fila de encabezados', readonly=True)
    total_rows = fields.Integer(string='Total de filas', readonly=True)

    @api.constrains('filename', 'file')
    def _check_file_validity(self):
        max_size_mb = float(self.env['ir.config_parameter'].sudo().get_param('smart_data_importer.max_file_size_mb', default='50'))
        max_size_bytes = max_size_mb * 1024 * 1024
        
        for record in self:
            if not record.filename:
                continue
            
            # Check extension
            valid_extensions = ['.csv', '.xls', '.xlsx']
            if not any(record.filename.lower().endswith(ext) for ext in valid_extensions):
                raise ValidationError(_('Solo se admiten archivos CSV y Excel (.csv, .xls, .xlsx).'))
            
            # Check size
            if record.file:
                # Odoo stores binaries in base64. Length of base64 string * 3/4 is roughly size in bytes.
                file_size = len(record.file) * 3 / 4
                if file_size > max_size_bytes:
                    raise ValidationError(_('El archivo supera el tamaño máximo de %s MB.') % max_size_mb)
