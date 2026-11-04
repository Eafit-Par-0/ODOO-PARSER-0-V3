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
    _description = 'Import Session'
    _order = 'create_date desc'

    name = fields.Char(string='Name', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    state = fields.Selection([
        ('draft', 'Draft'),
        ('analyzing', 'Analyzing'),
        ('mapped', 'Mapped'),
        ('queued', 'Queued'),
        ('processing', 'Processing'),
        ('done', 'Done'),
        ('error', 'Error')
    ], string='Status', default='draft', required=True, copy=False)
    user_id = fields.Many2one('res.users', string='User', default=lambda self: self.env.user, required=True)

    # Workbook / target
    sheet_ids = fields.One2many('import.session.sheet', 'session_id', string='Sheets', readonly=True)
    sheet_id = fields.Many2one(
        'import.session.sheet', string='Sheet to import',
        domain="[('session_id', '=', id), ('kind', '=', 'data')]",
        help="Excel workbooks can contain several sheets. Instructions and 'possible values' sheets are skipped.")
    target_model_id = fields.Many2one(
        'ir.model', string='Target Model', required=True, ondelete='cascade',
        default=_default_target_model, domain=[('transient', '=', False)],
        help="Odoo model that will receive the rows. Detected from the column headers when possible.")
    target_model_name = fields.Char(related='target_model_id.model', string='Target Model Name')
    model_detection_score = fields.Float(string='Model detection match', readonly=True,
                                         help="Share of technical column headers that exist on the detected model.")
    model_detection_note = fields.Char(string='Model detection note', readonly=True)
    dropped_rows = fields.Integer(string='Discarded empty rows', readonly=True)

    column_mapping_ids = fields.One2many('import.column.mapping', 'session_id', string='Column Mappings')
    job_ids = fields.One2many('import.job', 'session_id', string='Jobs')
    row_error_ids = fields.One2many('import.row.error', 'session_id', string='Row Errors')
    template_id = fields.Many2one('import.template', string='Applied Template')

    ai_analysis_summary = fields.Text(string='AI Analysis Summary', readonly=True)
    ai_template_name = fields.Char(string='AI Suggested Template Name', readonly=True)

    required_missing_count = fields.Integer(
        string='Empty required cells', compute='_compute_required_missing',
        help="Cells left empty in columns that the template marks as required.")

    value_correction_ids = fields.One2many('import.value.correction', 'session_id', string='Values to review')
    value_issue_pending_count = fields.Integer(
        string='Pending values', compute='_compute_value_counts',
        help="Values that do not exist in Odoo and still have no decision.")
    value_memory_applied_count = fields.Integer(
        string='Values from memory', compute='_compute_value_counts')
    value_overflow_count = fields.Integer(
        string='Columns with too many unknown values', compute='_compute_value_counts')

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
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('import.session') or _('New')
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
        model_name, score = FieldCatalog.detect_model(self.env, headers)
        vals = {'model_detection_score': score, 'model_detection_note': False}
        model = model_name and self.env['ir.model'].search([('model', '=', model_name)], limit=1)
        if model:
            vals['target_model_id'] = model.id
            vals['duplicate_criterion'] = 'vat' if model_name == 'res.partner' else 'auto'
        else:
            vals['model_detection_note'] = _(
                "The target model could not be detected from the headers of sheet '%s'. "
                "Choose it manually. If the data belongs to an app that is not installed "
                "(e.g. fixed assets need Accounting Assets), install it first."
            ) % self.sheet_id.name
        self.with_context(smart_importer_skip_sync=True).write(vals)

    @api.onchange('file')
    def _onchange_file_reset_sheets(self):
        """A new file invalidates the sheets read from the previous one,
        so the 'Cargar archivo' button shows up again."""
        if self.state == 'draft':
            self.sheet_id = False
            self.sheet_ids = [(5, 0, 0)]

    def action_load_file(self):
        """'Cargar archivo' button: the client saves the record before calling
        this method, so the file is stored and its sheets are read here."""
        self.ensure_one()
        if not self.file:
            raise UserError(_("Selecciona primero un archivo CSV o Excel."))
        if not self.sheet_ids:
            self._sync_sheets()
        if self.sheet_id and self.target_model_id and not self.model_detection_note:
            message = _("Archivo cargado. Hoja '%s' lista para importar en '%s'. Ahora pulsa 'Analizar' o 'Preparar con IA'.") % (
                self.sheet_id.name, self.target_model_id.name)
            ntype = 'success'
        elif self.sheet_id:
            message = _("Archivo cargado, pero no se pudo detectar el modelo destino. Elígelo en el campo 'Target Model' antes de analizar.")
            ntype = 'warning'
        else:
            message = _("Archivo cargado, pero no tiene ninguna hoja con datos para importar.")
            ntype = 'warning'
        return self._notify(_('Archivo cargado'), message, ntype)

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
            raise ValidationError(_("Please select a template to apply."))
        self._apply_template_lines(self.template_id)
        self._compute_file_duplicates()
        self._validate_values()
        return True

    def action_save_as_template(self):
        self.ensure_one()
        if not self.column_mapping_ids:
            raise ValidationError(_("No column mappings available to save as template."))
        lines_vals = [{
            'source_header': m.source_header,
            'target_field_id': m.target_field_id.id or False,
            'target_subfield': m.target_subfield or False,
            'cleansing_rule_ids': [(6, 0, m.cleansing_rule_ids.ids)],
            'is_ignored': m.is_ignored,
        } for m in self.column_mapping_ids]
        name = _("Template for %s") % (self.sheet_id.name or self.filename or self.name)
        template = self.env['import.template'].upsert_for_headers(
            headers=[m.source_header for m in self.column_mapping_ids],
            model=self.target_model_id,
            name=name,
            lines_vals=lines_vals,
            duplicate_criterion=self.duplicate_criterion,
            duplicate_policy=self.duplicate_policy,
        )
        self.template_id = template.id
        return self._notify(_('Template Saved'), _("Mapping saved as template '%s'.") % template.name)

    # ------------------------------------------------------------------
    # Pipeline actions
    # ------------------------------------------------------------------

    def _check_ready(self):
        self.ensure_one()
        if not self.file:
            raise UserError(_("Please upload a file (CSV or Excel) first."))
        if not self.sheet_id and self.sheet_ids:
            raise UserError(_("This workbook has no data sheet to import. Sheets: %s")
                            % ', '.join(self.sheet_ids.mapped('name')))
        if not self.target_model_id:
            raise UserError(_("Choose the target model before analysing."))

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
            raise UserError(_("The AI assistant is disabled. Enable it in Smart Importer > Configuration > Settings and enter the API key."))

        from ..services.field_catalog import split_header
        from ..services.mapper_hash import HashMapper
        from ..services.mapper_llm import LLMMapper, LLMError
        from ..services.orchestrator import PipelineOrchestrator

        file_info = self._read_file()
        df = file_info['df']
        headers = list(df.columns)
        if not headers:
            raise UserError(_("The selected sheet has no recognisable columns."))
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
            raise UserError(_("The AI analysis failed: %s") % e)

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
                             'llm_justification': _("Sub-field of related lines: not supported yet.")})
            resolved[header] = vals

        self.column_mapping_ids.unlink()
        mappings = PipelineOrchestrator.create_mappings(
            self, df, file_info['column_meta'], sample_values_map, resolved, auto_rules=False)

        template_name = ai_data.get('template_name') or _("AI Template - %s") % (self.sheet_id.name or self.filename)
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
            description=_("Generated by AI (%s - %s):\n\n%s") % (provider_name, ai_data.get('model', ''), ai_data.get('summary', '')),
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
            _('Template ready'),
            _("The AI (%s) analysed the sheet and saved template '%s' with %s mapped columns out of %s.")
            % (provider_name, template.name, mapped_count, len(mappings)),
        )

    def action_confirm_mapping(self):
        self.ensure_one()
        if self.state != 'mapped':
            raise ValidationError(_("Cannot confirm mapping in current state."))
        self._validate_values()
        pending = self.value_issue_pending_count
        if pending:
            raise UserError(_(
                "There are %s values that do not exist in Odoo and have no decision yet. "
                "Review them in the 'Valores a revisar' tab (accept a suggestion, type the exact value, or leave empty)."
            ) % pending)
        self.env['import.value.memory']._learn_from_corrections(self.value_correction_ids)
        self._learn_headers()
        if not self.column_mapping_ids.filtered(lambda m: m.target_field_id and not m.is_ignored):
            raise ValidationError(_("No column is mapped to a field. Map at least one column before importing."))

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
            _('Suggestions accepted'),
            _("%s values were accepted. Review the rest one by one.") % len(safe))

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

    preview_data = fields.Char(string='Preview', compute='_compute_preview_data', store=False)

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