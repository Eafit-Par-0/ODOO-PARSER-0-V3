from odoo import models, fields, api, _

class ImportProgressMixin(models.AbstractModel):
    _name = 'import.progress.mixin'
    _description = 'Seguimiento de ejecución y progreso de importación'

    start_time = fields.Datetime(string='Inicio', readonly=True)
    end_time = fields.Datetime(string='Fin', readonly=True)
    
    processed_rows = fields.Integer(string='Filas procesadas', readonly=True, default=0,
                                    help='Filas procesadas hasta ahora: creadas + actualizadas + omitidas + fallidas.')
    created_rows = fields.Integer(string='Filas creadas', readonly=True, default=0)
    updated_rows = fields.Integer(string='Filas actualizadas', readonly=True, default=0)
    skipped_rows = fields.Integer(string='Filas omitidas', readonly=True, default=0)
    failed_rows = fields.Integer(string='Filas fallidas', readonly=True, default=0)

    progress_percent = fields.Float(string='Progreso (%)', compute='_compute_progress_metrics')
    duration_seconds = fields.Float(string='Duración (s)', compute='_compute_progress_metrics')
    speed_rows_per_sec = fields.Float(string='Velocidad (filas/s)', compute='_compute_progress_metrics')

    @api.depends('processed_rows', 'total_rows', 'start_time', 'end_time')
    def _compute_progress_metrics(self):
        for record in self:
            total = getattr(record, 'total_rows', 0) or 0
            processed = record.processed_rows or 0
            
            # Progress %
            record.progress_percent = round((processed / total * 100), 1) if total > 0 else 0.0
            
            # Duration & Speed
            if record.start_time:
                end = record.end_time or fields.Datetime.now()
                duration = (end - record.start_time).total_seconds()
                record.duration_seconds = round(duration, 2)
                record.speed_rows_per_sec = round(processed / duration, 1) if duration > 0 else 0.0
            else:
                record.duration_seconds = 0.0
                record.speed_rows_per_sec = 0.0
