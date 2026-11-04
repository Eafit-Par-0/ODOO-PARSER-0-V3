import logging

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

class MappingRegistry(models.Model):
    _name = 'mapping.registry'
    _description = 'Sinónimos de encabezados'
    _order = 'priority desc, id'

    synonym = fields.Char(string='Sinónimo', required=True)
    model_id = fields.Many2one('ir.model', string='Modelo', required=True, ondelete='cascade')
    field_id = fields.Many2one('ir.model.fields', string='Campo', required=True, domain="[('model_id', '=', model_id)]", ondelete='cascade')
    language = fields.Selection([
        ('es', 'Español'),
        ('en', 'Inglés')
    ], string='Idioma', default='es', required=True)
    priority = fields.Integer(string='Prioridad', default=10, help='Los sinónimos con mayor prioridad se comparan primero.')

    origin = fields.Selection([('seed', 'Datos de fábrica'), ('learned', 'Aprendido')],
                              string='Origen', default='seed', required=True)
    usage_count = fields.Integer(string='Veces aprendido', default=0)
    learned_by = fields.Many2one('res.users', string='Aprendido por')
    active = fields.Boolean(string='Activo', default=True)

    # Odoo 19 syntax (replaces the old _sql_constraints list)
    _synonym_model_uniq = models.Constraint(
        'unique(synonym, model_id, language)',
        '¡El sinónimo debe ser único por modelo e idioma!',
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
