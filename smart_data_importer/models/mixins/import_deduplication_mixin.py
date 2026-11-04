from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)

class ImportDeduplicationMixin(models.AbstractModel):
    _name = 'import.deduplication.mixin'
    _description = 'Duplicados y política de importación'

    duplicate_criterion = fields.Selection([
        ('vat', 'NIT / documento (vat)'),
        ('email', 'Correo electrónico'),
        ('vat_or_email', 'NIT o correo'),
        ('auto', 'Automático (código, referencia interna o nombre)'),
    ], string='Criterio de duplicados', default='vat', required=True,
        help='Los contactos usan NIT / correo. Los demás modelos (cuentas, impuestos, productos...) usan la primera clave mapeada entre código, referencia interna o nombre.')
    
    duplicate_policy = fields.Selection([
        ('update', 'Actualizar registros existentes'),
        ('skip', 'Omitir duplicados'),
        ('create', 'Crear registros duplicados')
    ], string='Política de duplicados', default='update', required=True)

    duplicate_count_file = fields.Integer(string='Duplicados en el archivo', readonly=True, default=0)
    duplicate_count_odoo = fields.Integer(string='Coincidencias en Odoo', readonly=True, default=0)

    def _compute_file_duplicates(self):
        """Analyzes internal duplicates in file using DeduplicationEngine."""
        for record in self:
            if not getattr(record, 'file', None):
                record.duplicate_count_file = 0
                continue
            from odoo.addons.smart_data_importer.services.deduplication_engine import DeduplicationEngine
            try:
                file_info = record._read_file()
                df = file_info['df']
                dups = DeduplicationEngine.analyze_file_duplicates(df, record)
                record.duplicate_count_file = dups
            except Exception:
                _logger.exception("Could not count duplicates in file")
                record.duplicate_count_file = 0
