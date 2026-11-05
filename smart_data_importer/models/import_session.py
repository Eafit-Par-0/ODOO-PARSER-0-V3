from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import logging

_logger = logging.getLogger(__name__)


def _default_target_model(self):
    return self.env['ir.model'].search([('model', '=', 'res.partner')], limit=1)


class ImportSession(models.Model):
    _name = 'import.session'
    _inherit = [
        'import.file.mixin',
        'import.deduplication.mixin',
        'import.progress.mixin',
        'import.signature.mixin'
    ]
    _description = 'Sesión de importación'
    _order = 'create_date desc'

    name = fields.Char(string='Nombre', required=True, copy=False, readonly=True, default=lambda self: _('Nuevo'))
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('analyzing', 'Analizando'),
        ('mapped', 'Mapeado'),
        ('queued', 'En cola'),
        ('processing', 'Procesando'),
        ('done', 'Terminado'),
        ('error', 'Error')
    ], string='Estado', default='draft', required=True, copy=False)
    user_id = fields.Many2one('res.users', string='Usuario', default=lambda self: self.env.user, required=True)

    # Workbook / target
    sheet_ids = fields.One2many('import.session.sheet', 'session_id', string='Hojas', readonly=True)
    sheet_id = fields.Many2one(
        'import.session.sheet', string='Hoja a importar',
        domain="[('session_id', '=', id), ('kind', '=', 'data')]",
        help="Un libro de Excel puede tener varias hojas. Las hojas de instrucciones y de 'posibles valores' se omiten.")
    target_model_id = fields.Many2one(
        'ir.model', string='Modelo destino', required=True, ondelete='cascade',
        default=_default_target_model, domain=[('transient', '=', False)],
        help='Modelo de Odoo que recibirá las filas. Se detecta a partir de los encabezados cuando es posible.')
    target_model_name = fields.Char(related='target_model_id.model', string='Nombre técnico del modelo')
    model_detection_score = fields.Float(string='Coincidencia del modelo detectado', readonly=True,
                                         help='Porcentaje de encabezados técnicos que existen en el modelo detectado.')
    model_detection_note = fields.Char(string='Nota de detección del modelo', readonly=True)
    dropped_rows = fields.Integer(string='Filas vacías descartadas', readonly=True)

    column_mapping_ids = fields.One2many('import.column.mapping', 'session_id', string='Mapeo de columnas')
    job_ids = fields.One2many('import.job', 'session_id', string='Lotes')
    row_error_ids = fields.One2many('import.row.error', 'session_id', string='Errores por fila')
    template_id = fields.Many2one('import.template', string='Plantilla aplicada')

    ai_analysis_summary = fields.Text(string='Resumen del análisis de la IA', readonly=True)
    ai_template_name = fields.Char(string='Nombre de plantilla sugerido por la IA', readonly=True)

    required_missing_count = fields.Integer(
        string='Celdas obligatorias vacías', compute='_compute_required_missing',
        help='Celdas vacías en columnas que la plantilla marca como obligatorias.')

    value_correction_ids = fields.One2many('import.value.correction', 'session_id', string='Valores a revisar')
    value_issue_pending_count = fields.Integer(
        string='Valores pendientes', compute='_compute_value_counts',
        help='Valores que no existen en Odoo y aún no tienen decisión.')
    value_memory_applied_count = fields.Integer(
        string='Valores tomados de la memoria', compute='_compute_value_counts')
    value_overflow_count = fields.Integer(
        string='Columnas con demasiados valores desconocidos', compute='_compute_value_counts')

    # Errors grouped by column (PO requirement #1)
    error_summary_ids = fields.One2many('import.error.summary', 'session_id', string='Errores por columna')
    precheck_error_summary_ids = fields.One2many(
        'import.error.summary', 'session_id', string='Problemas detectados antes de importar',
        domain=[('stage', '=', 'precheck')])
    import_error_summary_ids = fields.One2many(
        'import.error.summary', 'session_id', string='Errores de la importación',
        domain=[('stage', '=', 'import')])
    precheck_problem_count = fields.Integer(
        string='Problemas antes de importar', compute='_compute_error_counts',
        help="Filas con datos que Odoo no podrá aceptar, detectadas al analizar el archivo.")
    precheck_column_count = fields.Integer(string='Columnas con problemas', compute='_compute_error_counts')
    import_error_column_count = fields.Integer(string='Columnas con errores', compute='_compute_error_counts')

    # Columns that do not belong to the target model (PO requirement #2)
    foreign_column_count = fields.Integer(
        string='Columnas de otro modelo', compute='_compute_column_fit',
        help="Columnas cuyo nombre técnico es un campo de otro modelo de Odoo, no del modelo destino.")
    unknown_column_count = fields.Integer(
        string='Columnas sin campo', compute='_compute_column_fit',
        help="Columnas para las que no se encontró ningún campo del modelo destino.")
    foreign_columns_text = fields.Char(string='Columnas de otro modelo (lista)', compute='_compute_column_fit')
    unknown_columns_text = fields.Char(string='Columnas sin campo (lista)', compute='_compute_column_fit')
    foreign_model_hint = fields.Char(string='Modelo sugerido por las columnas ajenas', compute='_compute_column_fit')
    is_mixed_models = fields.Boolean(
        string='Archivo con módulos mezclados', compute='_compute_mixed_models',
        help='Verdadero cuando las hojas de datos del libro pertenecen a modelos de Odoo distintos.')
    mixed_models_text = fields.Char(string='Hojas y modelos detectados', compute='_compute_mixed_models')

    @api.depends('error_summary_ids.stage', 'error_summary_ids.row_count')
    def _compute_error_counts(self):
        for rec in self:
            pre = rec.error_summary_ids.filtered(lambda e: e.stage == 'precheck')
            post = rec.error_summary_ids.filtered(lambda e: e.stage == 'import')
            rec.precheck_problem_count = sum(pre.mapped('row_count')) or len(pre)
            rec.precheck_column_count = len(set(pre.mapped('column_header')))
            rec.import_error_column_count = len(set(post.mapped('column_header')))

    @api.depends('column_mapping_ids.model_fit', 'column_mapping_ids.foreign_model_names', 'target_model_id')
    def _compute_column_fit(self):
        for rec in self:
            foreign = rec.column_mapping_ids.filtered(lambda m: m.model_fit == 'foreign')
            unknown = rec.column_mapping_ids.filtered(lambda m: m.model_fit == 'unknown')
            rec.foreign_column_count = len(foreign)
            rec.unknown_column_count = len(unknown)
            rec.foreign_columns_text = self._short_list(foreign.mapped('source_header'))
            rec.unknown_columns_text = self._short_list(unknown.mapped('source_header'))
            rec.foreign_model_hint = rec._guess_foreign_model(foreign)

    @api.depends('sheet_ids.kind', 'sheet_ids.name', 'sheet_ids.detected_model_id')
    def _compute_mixed_models(self):
        for rec in self:
            sheets = rec.sheet_ids.filtered(lambda s: s.kind == 'data' and s.detected_model_id)
            mixed = len(sheets.mapped('detected_model_id')) > 1
            rec.is_mixed_models = mixed
            rec.mixed_models_text = '; '.join(
                '%s → %s' % (sheet.name, sheet.detected_model_id.name) for sheet in sheets
            ) if mixed else False

    @staticmethod
    def _short_list(names, limit=8):
        names = list(names)
        text = ', '.join(names[:limit])
        if len(names) > limit:
            text += _(" y %s más") % (len(names) - limit)
        return text

    def _guess_foreign_model(self, foreign):
        """If most foreign columns belong to the same other model, name it:
        the user probably picked the wrong target model."""
        if len(foreign) < 2:
            return False
        counts = {}
        for mapping in foreign:
            for name in (mapping.foreign_model_names or '').split(', '):
                if name:
                    counts[name] = counts.get(name, 0) + 1
        if not counts:
            return False
        best, hits = max(counts.items(), key=lambda item: item[1])
        return best if hits * 2 >= len(foreign) else False

    @api.depends('value_correction_ids.decision', 'value_correction_ids.source',
                 'column_mapping_ids.value_issue_overflow')
    def _compute_value_counts(self):
        for rec in self:
            corrections = rec.value_correction_ids
            rec.value_issue_pending_count = len(corrections.filtered(lambda c: c.decision == 'pending'))
            rec.value_memory_applied_count = len(corrections.filtered(lambda c: c.source == 'memory'))
            rec.value_overflow_count = len(rec.column_mapping_ids.filtered('value_issue_overflow'))

    @api.depends('column_mapping_ids.empty_count', 'column_mapping_ids.required_level', 'column_mapping_ids.is_ignored')
    def _compute_required_missing(self):
        for rec in self:
            rec.required_missing_count = sum(
                m.empty_count for m in rec.column_mapping_ids
                if m.required_level == 'required' and not m.is_ignored
            )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Nuevo')) == _('Nuevo'):
                vals['name'] = self.env['ir.sequence'].next_by_code('import.session') or _('Nuevo')
        records = super().create(vals_list)
        for rec in records.filtered('file'):
            rec._sync_sheets()
        return records

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get('smart_importer_skip_sync'):
            return res
        if 'column_mapping_ids' in vals:
            # after ALL x2many commands of the save (mapping and correction rows) are applied
            for rec in self.filtered(lambda r: r.state == 'mapped'):
                rec._validate_values()
        if 'file' in vals or 'filename' in vals:
            for rec in self.filtered('file'):
                rec._sync_sheets()
        elif 'sheet_id' in vals and 'target_model_id' not in vals:
            for rec in self:
                rec._detect_target_model()
        return res

    # ------------------------------------------------------------------
    # Workbook helpers
    # ------------------------------------------------------------------

    def _read_file(self):
        """Read the selected sheet of the uploaded file."""
        self.ensure_one()
        from ..services.file_reader import FileReader
        return FileReader.read(self.file, self.filename, sheet_name=self.sheet_id.name or None)

    def _sync_sheets(self):
        """List the sheets of the uploaded workbook and pick a default data sheet."""
        self.ensure_one()
        from ..services.file_reader import FileReader
        summaries = FileReader.list_sheets(self.file, self.filename)

        ctx_self = self.with_context(smart_importer_skip_sync=True)
        ctx_self.sheet_id = False
        self.sheet_ids.unlink()
        sheets = self.env['import.session.sheet'].create([{
            'session_id': self.id,
            'sequence': i,
            'name': s['name'],
            'kind': s['kind'],
            'visible': s['visible'],
            'row_count': s['row_count'],
            'column_count': s['column_count'],
            'dropped_rows': s['dropped_rows'],
            'header_list': ', '.join(s['headers']),
        } for i, s in enumerate(summaries)])

        data_sheets = sheets.filtered(lambda s: s.kind == 'data')
        data_sheets._detect_models()
        default = (data_sheets.filtered('visible') or data_sheets)[:1]
        ctx_self.sheet_id = default.id or False
        self._detect_target_model()

    def _detect_target_model(self):
        """Pick the target model whose fields best match the sheet headers."""
        self.ensure_one()
        if not self.sheet_id or not self.sheet_id.header_list:
            return
        from ..services.field_catalog import FieldCatalog
        headers = [h.strip() for h in self.sheet_id.header_list.split(',')]
        model_name, score = FieldCatalog.detect_model(
            self.env, headers, prefer=self.target_model_id.model or 'res.partner')
        vals = {'model_detection_score': score, 'model_detection_note': False}
        model = model_name and self.env['ir.model'].search([('model', '=', model_name)], limit=1)
        if model:
            vals['target_model_id'] = model.id
            vals['duplicate_criterion'] = 'vat' if model_name == 'res.partner' else 'auto'
        else:
            vals['model_detection_note'] = _(
                "No se pudo detectar el modelo destino a partir de los encabezados de la hoja '%s'. Elígelo manualmente. Si los datos pertenecen a una aplicación que no está instalada (ej. los activos fijos necesitan Contabilidad - Activos), instálala primero."
            ) % self.sheet_id.name
        self.with_context(smart_importer_skip_sync=True).write(vals)

    @api.onchange('file')
    def _onchange_file_reset_sheets(self):
        """A new file invalidates the sheets read from the previous one,
        so the 'Procesar archivo' button shows up again."""
        if self.state == 'draft':
            self.sheet_id = False
            self.sheet_ids = [(5, 0, 0)]

    def action_load_file(self):
        """'Procesar archivo' button: the client saves the record before calling
        this method, so the file is stored and its sheets are read here."""
        self.ensure_one()
        if not self.file:
            raise UserError(_("Selecciona primero un archivo CSV o Excel."))
        if not self.sheet_ids:
            self._sync_sheets()
        if self.sheet_id and self.target_model_id and not self.model_detection_note:
            message = _("Archivo procesado. La hoja '%s' está lista para importar en '%s'. Ahora pulsa 'Analizar (Local / Caché)' o 'Preparar y Subir Plantilla con IA'.") % (
                self.sheet_id.name, self.target_model_id.name)
            ntype = 'success'
        elif self.sheet_id:
            message = _("Archivo procesado, pero no se pudo detectar el modelo destino. Elígelo en el campo 'Modelo destino' antes de analizar.")
            ntype = 'warning'
        else:
            message = _("Archivo procesado, pero no tiene ninguna hoja con datos para importar.")
            ntype = 'warning'
        if self.is_mixed_models:
            message += _(" Atención: el archivo mezcla datos de varios módulos (%s). Solo se importará la hoja seleccionada.") % self.mixed_models_text
            ntype = 'warning'
        return self._notify(_('Archivo procesado'), message, ntype)

    @api.onchange('target_model_id')
    def _onchange_target_model_id(self):
        if self.target_model_id:
            self.duplicate_criterion = 'vat' if self.target_model_id.model == 'res.partner' else 'auto'

    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------

    @api.onchange('template_id')
    def _onchange_template_id(self):
        if self.template_id and self.column_mapping_ids:
            self._apply_template_lines(self.template_id, use_write=False)

    def _apply_template_lines(self, template, use_write=True):
        from ..services.file_reader import FileReader
        lines = {FileReader.normalize_header(l.source_header): l for l in template.line_ids}
        for col in self.column_mapping_ids:
            t_line = lines.get(FileReader.normalize_header(col.source_header))
            if not t_line:
                continue
            vals = {
                'target_field_id': t_line.target_field_id.id or False,
                'target_subfield': t_line.target_subfield or False,
                'cleansing_rule_ids': [(6, 0, t_line.cleansing_rule_ids.ids)],
                'is_ignored': t_line.is_ignored,
                'source': 'template',
                'confidence': 1.0,
                'is_conflict': False,
            }
            if use_write:
                col.write(vals)
            else:
                col.update(vals)
        if template.duplicate_criterion:
            self.duplicate_criterion = template.duplicate_criterion
        if template.duplicate_policy:
            self.duplicate_policy = template.duplicate_policy

    def action_apply_template(self):
        self.ensure_one()
        if not self.template_id:
            raise ValidationError(_('Selecciona una plantilla para aplicar.'))
        self._apply_template_lines(self.template_id)
        self._compute_file_duplicates()
        self._validate_values()
        return True

    def action_save_as_template(self):
        self.ensure_one()
        if not self.column_mapping_ids:
            raise ValidationError(_('No hay mapeo de columnas para guardar como plantilla.'))
        lines_vals = [{
            'source_header': m.source_header,
            'target_field_id': m.target_field_id.id or False,
            'target_subfield': m.target_subfield or False,
            'cleansing_rule_ids': [(6, 0, m.cleansing_rule_ids.ids)],
            'is_ignored': m.is_ignored,
        } for m in self.column_mapping_ids]
        name = _('Plantilla para %s') % (self.sheet_id.name or self.filename or self.name)
        template = self.env['import.template'].upsert_for_headers(
            headers=[m.source_header for m in self.column_mapping_ids],
            model=self.target_model_id,
            name=name,
            lines_vals=lines_vals,
            duplicate_criterion=self.duplicate_criterion,
            duplicate_policy=self.duplicate_policy,
        )
        self.template_id = template.id
        return self._notify(_('Plantilla guardada'), _("El mapeo se guardó como la plantilla '%s'.") % template.name)

    # ------------------------------------------------------------------
    # Pipeline actions
    # ------------------------------------------------------------------

    def _check_ready(self):
        self.ensure_one()
        if not self.file:
            raise UserError(_('Primero sube un archivo (CSV o Excel).'))
        if not self.sheet_id and self.sheet_ids:
            raise UserError(_('Este libro no tiene ninguna hoja de datos para importar. Hojas: %s')
                            % ', '.join(self.sheet_ids.mapped('name')))
        if not self.target_model_id:
            raise UserError(_('Elige el modelo destino antes de analizar.'))

    def action_analyze(self):
        self.ensure_one()
        self._check_ready()
        from ..services.orchestrator import PipelineOrchestrator
        PipelineOrchestrator.run_premapping(self)
        self.dropped_rows = self.sheet_id.dropped_rows
        self._compute_file_duplicates()
        self._validate_values()
        return True

    def action_ai_prepare_and_upload_template(self):
        """
        AI Intelligent Preparation & Upload:
        Reads the selected sheet, asks the configured AI (DeepSeek, Claude, Gemini,
        OpenAI or a custom endpoint) to analyse it, then creates or updates the
        import.template and the session column mappings.
        """
        self.ensure_one()
        self._check_ready()

        config = self.env['ir.config_parameter'].sudo()
        if config.get_param('smart_data_importer.llm_enabled', 'False') != 'True':
            raise UserError(_('El asistente de IA está desactivado. Actívalo en Importador Inteligente > Configuración > Ajustes e ingresa la clave de API.'))

        from ..services.field_catalog import split_header
        from ..services.mapper_hash import HashMapper
        from ..services.mapper_llm import LLMMapper, LLMError
        from ..services.orchestrator import PipelineOrchestrator

        file_info = self._read_file()
        df = file_info['df']
        headers = list(df.columns)
        if not headers:
            raise UserError(_('La hoja seleccionada no tiene columnas reconocibles.'))
        model = self.target_model_id

        self.write({
            'encoding': file_info['encoding'],
            'delimiter': file_info['delimiter'],
            'header_row_index': file_info['header_row_index'],
            'total_rows': file_info['total_rows'],
            'dropped_rows': file_info['dropped_rows'],
        })

        sample_values_map = PipelineOrchestrator.sample_values(df)
        try:
            ai_data = LLMMapper.analyze_and_structure_template(
                env=self.env,
                headers=headers,
                sample_values_map=sample_values_map,
                total_rows=self.total_rows,
                filename="%s / %s" % (self.filename or self.name, self.sheet_id.name or ''),
                model_name=model.model,
            )
        except (LLMError, ValueError) as e:
            raise UserError(_('El análisis de la IA falló: %s') % e)

        # Technical headers are certain: they override whatever the AI said
        exact = HashMapper.map_technical(self.env, headers, model_name=model.model)

        resolved = {}
        for m in ai_data['mappings']:
            header = m['header']
            vals = {
                'target_field_id': m['target_field_id'] or False,
                'target_subfield': False,
                'source': 'llm',
                'confidence': m['confidence'],
                'llm_justification': m['justification'],
                'is_ignored': m['is_ignored'],
                'cleansing_rule_ids': [(6, 0, m['rule_ids'])],
            }
            if header in exact:
                vals.update(exact[header])
                vals['is_ignored'] = False
            base, sub = split_header(header)
            if sub and sub != 'id':
                vals.update({'is_ignored': True, 'target_field_id': False,
                             'llm_justification': _('Subcampo de líneas relacionadas: aún no está soportado.')})
            resolved[header] = vals

        self.column_mapping_ids.unlink()
        mappings = PipelineOrchestrator.create_mappings(
            self, df, file_info['column_meta'], sample_values_map, resolved, auto_rules=False)

        template_name = ai_data.get('template_name') or _('Plantilla IA - %s') % (self.sheet_id.name or self.filename)
        provider_name = (ai_data.get('provider') or 'AI').upper()
        criterion = ai_data.get('duplicate_criterion') if model.model == 'res.partner' else 'auto'
        template = self.env['import.template'].upsert_for_headers(
            headers=headers,
            model=model,
            name=template_name,
            lines_vals=[{
                'source_header': m.source_header,
                'target_field_id': m.target_field_id.id or False,
                'target_subfield': m.target_subfield or False,
                'cleansing_rule_ids': [(6, 0, m.cleansing_rule_ids.ids)],
                'is_ignored': m.is_ignored,
            } for m in mappings],
            duplicate_criterion=criterion,
            duplicate_policy=ai_data.get('duplicate_policy'),
            description=_('Generada por IA (%s - %s):\n\n%s') % (provider_name, ai_data.get('model', ''), ai_data.get('summary', '')),
        )

        self.write({
            'template_id': template.id,
            'duplicate_criterion': template.duplicate_criterion,
            'duplicate_policy': template.duplicate_policy,
            'ai_analysis_summary': ai_data.get('summary', ''),
            'ai_template_name': template.name,
            'state': 'mapped',
        })
        self._compute_file_duplicates()
        self._validate_values()

        mapped_count = len(mappings.filtered(lambda m: m.target_field_id and not m.is_ignored))
        return self._notify(
            _('Plantilla lista'),
            _("La IA (%s) analizó la hoja y guardó la plantilla '%s' con %s de %s columnas mapeadas.")
            % (provider_name, template.name, mapped_count, len(mappings)),
        )

    def action_confirm_mapping(self):
        self.ensure_one()
        if self.state != 'mapped':
            raise ValidationError(_('No se puede confirmar el mapeo en el estado actual.'))
        self._validate_values()
        pending = self.value_issue_pending_count
        if pending:
            raise UserError(_(
                "Hay %s valores que no existen en Odoo y aún no tienen decisión. Revísalos en la pestaña 'Valores a revisar' (acepta la sugerencia, escribe el valor exacto o déjalo vacío)."
            ) % pending)
        self.env['import.value.memory']._learn_from_corrections(self.value_correction_ids)
        self._learn_headers()
        if not self.column_mapping_ids.filtered(lambda m: m.target_field_id and not m.is_ignored):
            raise ValidationError(_('Ninguna columna está asignada a un campo. Asigna al menos una columna antes de importar.'))

        chunk_size = int(self.env['ir.config_parameter'].sudo().get_param('smart_data_importer.chunk_size', default='500')) or 500

        self.write({
            'start_time': fields.Datetime.now(),
            'end_time': False,
            'state': 'queued',
            'processed_rows': 0,
            'created_rows': 0,
            'updated_rows': 0,
            'skipped_rows': 0,
            'failed_rows': 0,
            'duplicate_count_odoo': 0,
        })
        self.job_ids.unlink()
        self._replace_error_summary('import', [])

        job_vals = [{
            'session_id': self.id,
            'chunk_index': i // chunk_size,
            'row_from': i,
            'row_to': min(i + chunk_size, self.total_rows),
            'state': 'pending',
        } for i in range(0, self.total_rows, chunk_size)]

        if not job_vals:
            self.write({'state': 'done', 'end_time': fields.Datetime.now()})
            return True

        self.state = 'processing'
        jobs = self.env['import.job'].create(job_vals)
        for job in jobs:
            if hasattr(job, 'with_delay'):
                job.with_delay(description=f"Import Session {self.name} - Chunk {job.chunk_index}").process_chunk()
            else:
                job.process_chunk()
        return True

    # ------------------------------------------------------------------
    # Value correction (similarity)
    # ------------------------------------------------------------------

    def _validate_values(self):
        """Find the cell values Odoo cannot resolve and sync ``value_correction_ids``.

        Decisions already taken for the same (column, normalized value) are kept.
        """
        self.ensure_one()
        from ..services.value_validator import ValueValidator

        Correction = self.env['import.value.correction']
        mappings = self.column_mapping_ids.filtered(lambda m: not m.is_ignored and m.target_field_id)
        if not mappings or not self.file or not self.target_model_id:
            self.value_correction_ids.unlink()
            self._replace_error_summary('precheck', [])
            return True

        config = self.env['ir.config_parameter'].sudo()
        threshold = float(config.get_param('smart_data_importer.value_fuzzy_threshold', '80') or 80)
        max_candidates = int(config.get_param('smart_data_importer.value_fuzzy_max_candidates', '5000') or 5000)

        plan = [{
            'column_mapping_id': m.id,
            'header': m.source_header,
            'field_name': m.target_field_id.name,
            'subfield': m.target_subfield or None,
            'rules': m.cleansing_rule_ids,
        } for m in mappings]
        df = self._read_file()['df']
        # Same read of the file: also find the cells Odoo will reject (numbers, dates, required...)
        self._precheck_errors(df, mappings)
        validator = ValueValidator(self.env, self.target_model_id.model, threshold=threshold,
                                   max_candidates=max_candidates,
                                   memory=self._load_value_memory(mappings))
        issues, overflow = validator.validate(df, plan)

        signatures = {m.id: self._mapping_signature(m) for m in mappings}
        existing = {(c.column_mapping_id.id, c.normalized_value, c.mapping_signature): c
                    for c in self.value_correction_ids}
        by_mapping = {m.id: m for m in mappings}
        kept, to_create = set(), []
        for issue in issues:
            mapping = by_mapping[issue['column_mapping_id']]
            vals = self._correction_vals(mapping, issue)
            vals['mapping_signature'] = signatures[mapping.id]
            rec = existing.get((mapping.id, issue['normalized_value'], signatures[mapping.id]))
            if rec:
                kept.add(rec.id)
                if rec.decision == 'pending' and issue['decision'] == 'accept':
                    vals['decision'] = 'accept'
                rec.write(vals)
            else:
                vals.update({
                    'session_id': self.id,
                    'column_mapping_id': mapping.id,
                    'normalized_value': issue['normalized_value'],
                    'decision': issue['decision'],
                })
                to_create.append(vals)
        self.value_correction_ids.filtered(lambda c: c.id not in kept).unlink()
        if to_create:
            Correction.create(to_create)
        for m in mappings:
            flag = m.id in overflow
            if m.value_issue_overflow != flag:
                m.write({'value_issue_overflow': flag})
        return True

    # ------------------------------------------------------------------
    # Errors grouped by column (PO requirement #1)
    # ------------------------------------------------------------------

    # Field types whose unknown values are handled in 'Valores a revisar'
    LOOKUP_TYPES = ('selection', 'many2one', 'many2many')
    # Field types whose text is always accepted
    FREE_TEXT_TYPES = ('char', 'text', 'html')

    @api.model
    def _whole_row_label(self):
        from ..services.error_explainer import WHOLE_ROW
        return WHOLE_ROW

    def _precheck_errors(self, df, mappings):
        """Dry run of the conversion, before importing anything.

        Finds, grouped by column: required cells left empty, required Odoo
        fields with no column, and numbers / dates / Sí-No values Odoo cannot
        read. Values of lookup fields are not repeated here: they already have
        the 'Valores a revisar' tab.
        """
        self.ensure_one()
        import pandas as pd
        from ..services.cleansing_engine import CleansingEngine
        from ..services.value_converter import ValueConverter, ConversionError
        from ..services.field_catalog import FieldCatalog

        model_name = self.target_model_id.model
        Model = self.env[model_name]
        converter = ValueConverter(self.env, model_name, overrides=self._value_overrides())
        label = self.env['import.job']._field_label
        errors = []

        for mapping in mappings:
            field = Model._fields.get(mapping.target_field_id.name)
            header = mapping.source_header
            if header not in df.columns:
                continue
            field_label = label(mapping.target_field_id)
            if field is None:
                errors.append({'column': header, 'field_label': field_label, 'category': 'unknown_field'})
                continue
            required = field.required or mapping.required_level == 'required'
            check_values = field.type not in self.LOOKUP_TYPES + self.FREE_TEXT_TYPES
            if not required and not check_values:
                continue
            rules = mapping.cleansing_rule_ids
            for row_number, value in df[header].items():
                empty = value is None or (not isinstance(value, (list, dict)) and pd.isna(value)) or str(value).strip() == ''
                if empty:
                    if required and field.type != 'boolean':
                        errors.append({'column': header, 'field_label': field_label, 'category': 'required',
                                       'row': int(row_number)})
                    continue
                if not check_values:
                    continue
                if rules:
                    value = CleansingEngine.apply_rules(value, rules)
                try:
                    converter.convert(field.name, value, subfield=mapping.target_subfield or None)
                except ConversionError as e:
                    errors.append({
                        'column': header, 'field_label': field_label, 'category': e.code,
                        'row': int(row_number), 'value': e.value if e.value is not None else value,
                        'technical': str(e),
                    })

        # Required Odoo fields that no column fills and that have no default value
        mapped_names = set(mappings.mapped('target_field_id.name'))
        importable = FieldCatalog.importable_fields(self.env, model_name)
        missing = [f for f in importable
                   if f.name not in mapped_names and Model._fields[f.name].required
                   and f.ttype != 'boolean']
        if missing:
            try:
                defaults = Model.default_get([f.name for f in missing])
            except Exception:
                _logger.debug("default_get failed on %s", model_name, exc_info=True)
                defaults = {f.name: True for f in missing}  # do not report what we cannot check
            for f in missing:
                if defaults.get(f.name) in (None, False, ''):
                    errors.append({'column': _("(sin columna) %s") % f.field_description,
                                   'field_label': label(f), 'category': 'missing_column'})

        self._replace_error_summary('precheck', errors)
        return errors

    def _build_error_summary_from_rows(self):
        """After the import: group the row errors by column."""
        self.ensure_one()
        errors = [{
            'column': e.column_header,
            'field_label': e.field_label,
            'category': e.error_category or 'other',
            'row': e.row_number,
            'value': e.cell_value,
            'technical': e.error_message,
        } for e in self.sudo().row_error_ids]
        self._replace_error_summary('import', errors)

    def _replace_error_summary(self, stage, errors):
        from ..services.error_explainer import group_errors
        Summary = self.env['import.error.summary'].sudo()
        Summary.search([('session_id', '=', self.id), ('stage', '=', stage)]).unlink()
        groups = group_errors(errors)
        if groups:
            Summary.create([{
                'session_id': self.id,
                'stage': stage,
                'sequence': i,
                'column_header': g['column'],
                'field_label': g['field_label'] or False,
                'error_category': g['category'],
                'title': g['title'],
                'message': g['message'],
                'hint': g['hint'],
                'error_count': g['error_count'],
                'row_count': g['row_count'],
                'rows_text': g['rows_text'] or False,
                'sample_values': g['sample_values'] or False,
                'technical_detail': g['technical'] or False,
            } for i, g in enumerate(groups)])

    def action_view_all_row_errors(self):
        """All the row errors of the import, grouped by column."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Errores por columna"),
            'res_model': 'import.row.error',
            'view_mode': 'list,form',
            'views': [(self.env.ref('smart_data_importer.view_import_row_error_list').id, 'list'),
                      (False, 'form')],
            'search_view_id': self.env.ref('smart_data_importer.view_import_row_error_search').id,
            'domain': [('session_id', '=', self.id)],
            'context': {'group_by': ['column_header', 'error_category']},
        }

    # ------------------------------------------------------------------
    # Columns that do not belong to the model (PO requirement #2)
    # ------------------------------------------------------------------

    def action_ignore_foreign_columns(self):
        """Mark as ignored the columns that belong to another model or have no field."""
        self.ensure_one()
        columns = self.column_mapping_ids.filtered(lambda m: m.model_fit in ('foreign', 'unknown'))
        columns.write({'is_ignored': True})
        self._validate_values()
        return self._notify(
            _('Columnas ignoradas'),
            _("Se ignoraron %s columnas que no pertenecen a '%s'.") % (len(columns), self.target_model_id.name))

    def _learn_headers(self):
        """Remember the headers a person mapped by hand (not template, not the initial suggestion)."""
        self.ensure_one()
        Registry = self.env['mapping.registry']
        for col in self.column_mapping_ids:
            if (col.is_ignored or not col.target_field_id or col.source == 'template'
                    or col.target_subfield or col.target_field_id == col.suggested_field_id):
                continue
            Registry._learn_header(self.target_model_id, col.source_header, col.target_field_id)

    def _load_value_memory(self, mappings):
        """Active learned corrections for the mapped fields, as the validator expects them.

        Entries pointing to a record that no longer exists are deactivated.
        """
        self.ensure_one()
        entries = self.env['import.value.memory'].sudo().search(
            [('field_id', 'in', mappings.target_field_id.ids)])
        memory = {}
        for entry in entries:
            field = entry.field_id
            if field.ttype == 'selection':
                key, label = entry.selection_key, entry.target_label
            else:
                record = (self.env[field.relation].with_context(active_test=False)
                          .browse(entry.res_id).exists()) if entry.res_id else None
                if not record:
                    entry.active = False
                    continue
                key, label = record.id, record.display_name
            if key:
                memory[(field.name, entry.normalized_value)] = {'key': key, 'label': label}
        return memory

    @staticmethod
    def _mapping_signature(mapping):
        rules = ','.join(map(str, sorted(mapping.cleansing_rule_ids.ids)))
        return "%s|%s|%s" % (mapping.target_field_id.id, mapping.target_subfield or '', rules)

    def _correction_vals(self, mapping, issue):
        """Translate a validator issue into ``import.value.correction`` values."""
        field = mapping.target_field_id
        vals = {
            'original_value': issue['original_value'],
            'occurrence_count': issue['occurrence_count'],
            'issue_type': issue['issue_type'],
            'suggested_label': issue['suggested_label'] or False,
            'suggested_key': False,
            'suggested_res_id': 0,
            'confidence': issue['confidence'],
            'is_ambiguous': issue['is_ambiguous'],
            'source': issue['source'],
        }
        key = issue['suggested_key']
        if key is False or key is None:
            return vals
        if field.ttype == 'selection':
            vals['suggested_key'] = str(key)
            try:
                model = self.env[self.target_model_id.model]
                selection = dict(model._fields[field.name]._description_selection(self.env))
                vals['suggested_label'] = selection.get(key, vals['suggested_label'])
            except Exception:
                _logger.debug("Could not read the label of selection option %s", key, exc_info=True)
        else:
            vals['suggested_res_id'] = int(key)
            record = self.env[field.relation].with_context(active_test=False).browse(int(key)).exists()
            if record:
                vals['suggested_label'] = record.display_name
        return vals

    def action_accept_value_suggestions(self):
        """Accept in bulk the safe suggestions (not ambiguous, high similarity)."""
        self.ensure_one()
        threshold = float(self.env['ir.config_parameter'].sudo().get_param(
            'smart_data_importer.value_bulk_accept_threshold', '90') or 90)
        safe = self.value_correction_ids.filtered(
            lambda c: c.decision == 'pending' and not c.is_ambiguous
            and (c.suggested_key or c.suggested_res_id)
            and c.confidence * 100 >= threshold)
        safe.write({'decision': 'accept'})
        return self._notify(
            _('Sugerencias aceptadas'),
            _('Se aceptaron %s valores. Revisa el resto uno por uno.') % len(safe))

    def _value_overrides(self):
        """``{(field_name, normalized_value): odoo_value}`` from the user decisions."""
        self.ensure_one()
        overrides = {}
        for rec in self.value_correction_ids:
            field = rec.field_id
            key = (field.name, rec.normalized_value)
            is_selection = field.ttype == 'selection'
            if rec.decision == 'accept':
                value = rec.suggested_key if is_selection else rec.suggested_res_id
            elif rec.decision == 'manual':
                value = rec.resolved_key if is_selection else rec.resolved_res_id
            elif rec.decision == 'empty':
                overrides[key] = False
                continue
            else:
                continue
            if value:
                overrides[key] = value
        return overrides

    def _notify(self, title, message, ntype='success'):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': title, 'message': message, 'type': ntype, 'sticky': False,
                       # reload the form so the new mappings are visible
                       'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'}},
        }

    # ------------------------------------------------------------------
    # OWL dashboard
    # ------------------------------------------------------------------

    preview_data = fields.Char(string='Vista previa', compute='_compute_preview_data', store=False)

    def _compute_preview_data(self):
        for rec in self:
            rec.preview_data = 'preview'

    def get_dashboard_summary(self):
        """
        Returns rich data structure for the OWL Human-in-the-Loop Dashboard.
        Includes raw rows, transformed rows (with cleansing rules applied), column metadata, and quality metrics.
        """
        self.ensure_one()
        empty = {'total_rows': 0, 'columns': [], 'raw_rows': [], 'transformed_rows': [], 'metrics': {}}
        if not self.file:
            return empty

        from ..services.cleansing_engine import CleansingEngine

        try:
            file_info = self._read_file()
            df = file_info['df'].astype(object).where(file_info['df'].notna(), '')
            sample_df = df.head(10)

            columns_meta = []
            rules_map = {}
            for col in self.column_mapping_ids:
                rules = col.cleansing_rule_ids
                rules_map[col.source_header] = rules
                target = col.target_field_id
                columns_meta.append({
                    'id': col.id,
                    'header': col.source_header,
                    'target_field': (target.field_description or target.name) if target else False,
                    'target_field_name': target.name if target else False,
                    'target_subfield': col.target_subfield or False,
                    'source': col.source or 'unresolved',
                    'confidence': round((col.confidence or 0.0) * 100, 1),
                    'is_ignored': col.is_ignored,
                    'required_level': col.required_level or False,
                    'empty_count': col.empty_count,
                    'rules_count': len(rules),
                    'rule_names': [r.name for r in rules],
                })

            raw_rows = sample_df.to_dict('records')
            transformed_rows = []
            for _idx, row in sample_df.iterrows():
                trans_row = {}
                for header in sample_df.columns:
                    val = row.get(header, '')
                    rules = rules_map.get(header, [])
                    if rules and val != '':
                        clean_val = CleansingEngine.apply_rules(val, rules)
                        trans_row[header] = {'value': clean_val, 'is_modified': str(clean_val) != str(val)}
                    else:
                        trans_row[header] = {'value': val, 'is_modified': False}
                transformed_rows.append(trans_row)

            mapped_cols = [c for c in columns_meta if c['target_field'] and not c['is_ignored']]
            confidences = [c['confidence'] for c in mapped_cols]
            avg_conf = round(sum(confidences) / len(confidences), 1) if confidences else 0.0

            return {
                'total_rows': self.total_rows or len(df),
                'columns': columns_meta,
                'raw_headers': list(sample_df.columns),
                'raw_rows': raw_rows,
                'transformed_rows': transformed_rows,
                'metrics': {
                    'total_columns': len(columns_meta),
                    'mapped_columns': len(mapped_cols),
                    'unmapped_columns': len(columns_meta) - len(mapped_cols),
                    'duplicate_file': self.duplicate_count_file,
                    'duplicate_odoo': self.duplicate_count_odoo,
                    'avg_confidence': avg_conf,
                    'duplicate_policy': self.duplicate_policy,
                    'duplicate_criterion': self.duplicate_criterion,
                    'required_missing': self.required_missing_count,
                    'dropped_rows': file_info['dropped_rows'],
                    'sheet_name': file_info['sheet_name'],
                    'target_model': self.target_model_id.model,
                }
            }
        except Exception as e:
            _logger.exception("Error building import dashboard")
            return dict(empty, error=str(e))