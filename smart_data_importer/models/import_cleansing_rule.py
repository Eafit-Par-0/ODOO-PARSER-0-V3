from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)

class ImportCleansingRule(models.Model):
    _name = 'import.cleansing.rule'
    _description = 'Regla de limpieza y normalización'
    _order = 'sequence, id'

    name = fields.Char(string='Nombre de la regla', required=True, translate=True)
    sequence = fields.Integer(string='Secuencia', default=10)
    active = fields.Boolean(string='Activo', default=True)
    description = fields.Text(string='Descripción')

    category = fields.Selection([
        ('text', 'Texto y formato'),
        ('contact', 'Contactos y documentos'),
        ('number', 'Números y moneda'),
        ('date', 'Fechas y horas'),
        ('custom', 'Personalizada / Avanzada')
    ], string='Categoría', default='text', required=True)

    action_type = fields.Selection([
        # Text & Formatting
        ('strip', 'Quitar espacios sobrantes'),
        ('lowercase', 'Minúsculas'),
        ('uppercase', 'Mayúsculas'),
        ('titlecase', 'Primera letra en mayúscula'),
        ('remove_accents', 'Quitar tildes'),
        ('digits_only', 'Dejar solo dígitos'),
        ('find_replace', 'Buscar y reemplazar texto'),
        ('prefix_suffix', 'Agregar/quitar prefijo y sufijo'),
        ('value_mapping', 'Equivalencia de valores (diccionario)'),
        ('default_value', 'Valor por defecto si está vacío'),
        
        # Contacts & Tax IDs
        ('email', 'Normalizar correo'),
        ('phone', 'Normalizar teléfono'),
        ('vat_document', 'Normalizar NIT / documento'),
        
        # Numbers & Dates
        ('number_clean', 'Limpiar moneda / número'),
        ('date_format', 'Normalizar formato de fecha'),
        
        # Custom / Advanced
        ('regex', 'Reemplazo con expresión regular'),
        ('python_code', 'Código Python (evaluación segura)')
    ], string='Tipo de acción', required=True, default='strip')

    # Specific Configuration Fields
    # Find & Replace
    find_text = fields.Char(string='Texto a buscar')
    replace_text = fields.Char(string='Reemplazar por', default='')
    case_sensitive = fields.Boolean(string='Distinguir mayúsculas', default=False)

    # Prefix & Suffix
    prefix_text = fields.Char(string='Prefijo')
    suffix_text = fields.Char(string='Sufijo')
    remove_prefix = fields.Boolean(string='Quitar prefijo si existe', default=False)
    remove_suffix = fields.Boolean(string='Quitar sufijo si existe', default=False)

    # Value Mapping
    line_ids = fields.One2many('import.cleansing.rule.line', 'rule_id', string='Tabla de equivalencias')

    # Default Value
    default_value = fields.Char(string='Valor por defecto si está vacío')

    # Number / Currency Clean
    decimal_separator = fields.Selection([
        ('dot', 'Punto decimal (ej. 1,250.50 -> 1250.50)'),
        ('comma', 'Coma decimal (ej. 1.250,50 -> 1250.50)')
    ], string='Notación decimal', default='comma')

    # Date Format
    date_input_format = fields.Selection([
        ('auto', 'Detectar automáticamente'),
        ('%d/%m/%Y', 'DD/MM/AAAA (ej. 31/12/2025)'),
        ('%m/%d/%Y', 'MM/DD/AAAA (ej. 12/31/2025)'),
        ('%Y-%m-%d', 'AAAA-MM-DD (ej. 2025-12-31)'),
        ('%Y/%m/%d', 'AAAA/MM/DD (ej. 2025/12/31)'),
        ('%d-%m-%Y', 'DD-MM-AAAA (ej. 31-12-2025)'),
        ('%Y%m%d', 'AAAAMMDD (ej. 20251231)')
    ], string='Formato de fecha de entrada', default='auto')

    # Regex
    regex_pattern = fields.Char(string='Patrón (regex)', help='Expresión regular que se busca.')
    regex_replacement = fields.Char(string='Reemplazo (regex)', default='', help='Texto con el que se reemplazan las coincidencias.')

    # Python Code
    python_code = fields.Text(
        string='Código Python',
        default="# Available variables: 'value' (input string), 'rule' (rule record)\n# Store output in 'result'\nresult = value.strip()"
    )

    # Live Sandbox / Interactive Tester
    test_input = fields.Char(string='Entrada de prueba', default='  Example Text 123  ')
    test_output = fields.Char(string='Resultado transformado', compute='_compute_test_output', readonly=True)

    @api.depends('test_input', 'action_type', 'find_text', 'replace_text', 'case_sensitive',
                 'prefix_text', 'suffix_text', 'remove_prefix', 'remove_suffix',
                 'default_value', 'decimal_separator', 'date_input_format',
                 'regex_pattern', 'regex_replacement', 'python_code', 'line_ids.source_value', 'line_ids.target_value')
    def _compute_test_output(self):
        for rec in self:
            if rec.test_input is not False and rec.test_input is not None:
                from ..services.cleansing_engine import CleansingEngine
                rec.test_output = CleansingEngine.apply_rules(rec.test_input, [rec])
            else:
                rec.test_output = ''

    @api.onchange('test_input', 'action_type', 'find_text', 'replace_text', 'case_sensitive',
                  'prefix_text', 'suffix_text', 'remove_prefix', 'remove_suffix',
                  'default_value', 'decimal_separator', 'date_input_format',
                  'regex_pattern', 'regex_replacement', 'python_code', 'line_ids')
    def _onchange_sandbox_preview(self):
        if self.test_input is not False and self.test_input is not None:
            from ..services.cleansing_engine import CleansingEngine
            self.test_output = CleansingEngine.apply_rules(self.test_input, [self])
        else:
            self.test_output = ''

    def action_test_rule(self):
        """Manual test trigger for UI feedback"""
        self.ensure_one()
        self._compute_test_output()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Regla probada correctamente'),
                'message': _("Entrada: '%s' -> Resultado: '%s'") % (self.test_input or '', self.test_output or ''),
                'type': 'success',
                'sticky': False,
            }
        }


class ImportCleansingRuleLine(models.Model):
    _name = 'import.cleansing.rule.line'
    _description = 'Línea de equivalencia'
    _order = 'sequence, id'

    rule_id = fields.Many2one('import.cleansing.rule', string='Regla', required=True, ondelete='cascade')
    sequence = fields.Integer(string='Secuencia', default=10)
    source_value = fields.Char(string='Valor original (de)', required=True)
    target_value = fields.Char(string='Valor equivalente (a)', required=True)
