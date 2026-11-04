import logging

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

class MappingRegistry(models.Model):
    _name = 'mapping.registry'
    _description = 'Mapping Registry'
    _order = 'priority desc, id'

    synonym = fields.Char(string='Synonym', required=True)
    model_id = fields.Many2one('ir.model', string='Model', required=True, ondelete='cascade')
    field_id = fields.Many2one('ir.model.fields', string='Field', required=True, domain="[('model_id', '=', model_id)]", ondelete='cascade')
    language = fields.Selection([
        ('es', 'Spanish'),
        ('en', 'English')
    ], string='Language', default='es', required=True)
    priority = fields.Integer(string='Priority', default=10, help="Higher priority synonyms are matched first.")

    origin = fields.Selection([('seed', 'Seed data'), ('learned', 'Learned')],
                              string='Origin', default='seed', required=True)
    usage_count = fields.Integer(string='Times learned', default=0)
    learned_by = fields.Many2one('res.users', string='Learned by')
    active = fields.Boolean(default=True)

    # Odoo 19 syntax (replaces the old _sql_constraints list)
    _synonym_model_uniq = models.Constraint(
        'unique(synonym, model_id, language)',
        'Synonym must be unique per model and language!',
    )

    @api.model
    def _learn_header(self, model, header, field):
        """Remember that a person mapped ``header`` to ``field`` (called when confirming).

        Seed synonyms are never modified. Runs with sudo: it is the only write
        entry point for regular users.
        """
        from ..services.text_utils import normalize_text

        norm = normalize_text(header)
        if not norm:
            return False
        registry = self.sudo().with_context(active_test=False)
        rows = registry.search([('model_id', '=', model.id)]).filtered(
            lambda r: normalize_text(r.synonym) == norm)
        seeds = rows.filtered(lambda r: r.origin == 'seed')
        if seeds:
            if any(seed.field_id != field for seed in seeds):
                _logger.info("Header '%s' not learned: a seed synonym maps it to another field.", header)
            return False
        learned = rows.filtered(lambda r: r.origin == 'learned')[:1]
        if not learned:
            registry.create({
                'synonym': header.strip(),
                'model_id': model.id,
                'field_id': field.id,
                'language': 'es',
                'origin': 'learned',
                'usage_count': 1,
                'learned_by': self.env.user.id,
            })
        elif learned.field_id == field:
            learned.write({'usage_count': learned.usage_count + 1, 'active': True})
        else:
            learned.write({'field_id': field.id, 'usage_count': 1, 'active': True,
                           'learned_by': self.env.user.id})
        return True
