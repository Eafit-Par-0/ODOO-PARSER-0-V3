import logging

import psycopg2

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class ImportValueMemory(models.Model):
    _name = 'import.value.memory'
    _description = 'Learned Value Correction'
    _order = 'usage_count desc, id desc'

    field_id = fields.Many2one('ir.model.fields', required=True, ondelete='cascade', index=True)
    model_id = fields.Many2one(related='field_id.model_id', store=True)
    comodel_name = fields.Char(related='field_id.relation', store=True)

    original_value = fields.Char(required=True)
    normalized_value = fields.Char(required=True, index=True)
    res_id = fields.Many2oneReference(model_field='comodel_name')   # many2one / many2many
    selection_key = fields.Char()                                   # selection
    target_label = fields.Char(compute='_compute_target_label')

    usage_count = fields.Integer(default=1)
    last_used = fields.Datetime(default=fields.Datetime.now)
    learned_by = fields.Many2one('res.users', default=lambda self: self.env.user)
    active = fields.Boolean(default=True)

    _field_value_uniq = models.Constraint(
        'unique(field_id, normalized_value)',
        'This value already has a learned correction for this field.',
    )

    @api.depends('field_id', 'res_id', 'selection_key')
    def _compute_target_label(self):
        for rec in self:
            label = rec.selection_key or False
            if rec.field_id.ttype != 'selection' and rec.res_id and rec.comodel_name in self.env:
                record = self.env[rec.comodel_name].sudo().with_context(active_test=False).browse(rec.res_id).exists()
                label = record.display_name if record else "%s,%s (deleted)" % (rec.comodel_name, rec.res_id)
            rec.target_label = label

    # ------------------------------------------------------------------
    # Learning (the only write entry point for regular users)
    # ------------------------------------------------------------------

    @api.model
    def _learn_from_corrections(self, corrections):
        """Remember the decisions a person took (accept / manual, never 'empty')."""
        for corr in corrections:
            if corr.decision not in ('accept', 'manual'):
                continue
            selection = corr.field_id.ttype == 'selection'
            if corr.decision == 'accept':
                target = corr.suggested_key if selection else corr.suggested_res_id
            else:
                target = corr.resolved_key if selection else corr.resolved_res_id
            if not target:
                continue
            self._upsert(corr.field_id, corr.original_value, corr.normalized_value, target, selection)
        return True

    @api.model
    def _upsert(self, field, original_value, normalized_value, target, selection):
        memory = self.sudo().with_context(active_test=False)
        domain = [('field_id', '=', field.id), ('normalized_value', '=', normalized_value)]
        entry = memory.search(domain, limit=1)
        if not entry:
            vals = {
                'field_id': field.id,
                'original_value': original_value,
                'normalized_value': normalized_value,
                'selection_key': target if selection else False,
                'res_id': 0 if selection else target,
            }
            try:
                with self.env.cr.savepoint():
                    memory.create(vals)
                return
            except psycopg2.IntegrityError:
                # created at the same time by another session: update it instead
                entry = memory.search(domain, limit=1)
                if not entry:
                    raise
        same = (entry.selection_key == target) if selection else (entry.res_id == target)
        if same:
            entry.write({'usage_count': entry.usage_count + 1, 'last_used': fields.Datetime.now(),
                         'active': True})
        else:
            entry.write({
                'selection_key': target if selection else False,
                'res_id': 0 if selection else target,
                'original_value': original_value,
                'usage_count': 1,
                'last_used': fields.Datetime.now(),
                'learned_by': self.env.user.id,
                'active': True,
            })
