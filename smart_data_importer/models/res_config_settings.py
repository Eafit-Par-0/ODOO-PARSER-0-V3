from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    smart_data_importer_max_file_size_mb = fields.Float(
        string='Tamaño máximo de archivo (MB)',
        config_parameter='smart_data_importer.max_file_size_mb',
        default=50.0
    )
    smart_data_importer_fuzzy_threshold = fields.Integer(
        string='Umbral de similitud',
        config_parameter='smart_data_importer.fuzzy_threshold',
        default=85,
        help='Similitud mínima (0-100) para asignar un encabezado a un campo aunque tenga errores de ortografía.'
    )
    smart_data_importer_chunk_size = fields.Integer(
        string='Tamaño de lote',
        config_parameter='smart_data_importer.chunk_size',
        default=500
    )
    smart_data_importer_value_fuzzy_threshold = fields.Integer(
        string='Umbral para sugerir valores',
        config_parameter='smart_data_importer.value_fuzzy_threshold',
        default=80,
        help='Similitud mínima (0-100) para sugerir una corrección a un valor que no existe en Odoo.'
    )
    smart_data_importer_value_bulk_accept_threshold = fields.Integer(
        string='Umbral de aceptación masiva',
        config_parameter='smart_data_importer.value_bulk_accept_threshold',
        default=90,
        help="Similitud mínima (0-100) para el botón 'Aceptar sugerencias seguras'."
    )
    smart_data_importer_value_fuzzy_max_candidates = fields.Integer(
        string='Máximo de candidatos',
        config_parameter='smart_data_importer.value_fuzzy_max_candidates',
        default=5000,
        help='En modelos relacionados con más registros que este número no se buscan valores parecidos.'
    )

    smart_data_importer_llm_enabled = fields.Boolean(
        string='Activar mapeo y plantillas asistidos por IA',
        config_parameter='smart_data_importer.llm_enabled',
        default=False,
        help='Al activarlo, la IA analiza las hojas, genera plantillas y sugiere mapeos y reglas de limpieza.'
    )
    smart_data_importer_llm_provider = fields.Selection([
        ('deepseek', 'DeepSeek'),
        ('anthropic', 'Anthropic (Claude)'),
        ('gemini', 'Google Gemini'),
        ('openai', 'OpenAI'),
        ('custom', 'Personalizado / Local (Ollama, Groq, OpenRouter)'),
    ], string='Proveedor de IA',
        config_parameter='smart_data_importer.llm_provider',
        default='deepseek'
    )
    smart_data_importer_llm_model = fields.Char(
        string='Nombre del modelo de IA',
        config_parameter='smart_data_importer.llm_model',
        help='Déjalo vacío para usar el modelo por defecto del proveedor: deepseek-chat, claude-haiku-5-5, gemini-3.5-flash-lite, gpt-4o-mini, llama3.'
    )
    smart_data_importer_llm_api_key = fields.Char(
        string='Clave de API',
        config_parameter='smart_data_importer.llm_api_key'
    )
    smart_data_importer_llm_base_url = fields.Char(
        string='URL base personalizada',
        config_parameter='smart_data_importer.llm_base_url',
        help="URL base de un servidor compatible con OpenAI, ej. http://localhost:11434/v1 o https://api.groq.com/openai/v1. '/chat/completions' se agrega automáticamente."
    )
    smart_data_importer_llm_send_samples = fields.Boolean(
        string='Enviar valores de ejemplo a la IA',
        default=True,
        help='Si está desactivado, a la IA solo se envían los encabezados, nunca el contenido de las celdas (útil cuando hay datos personales).'
    )

    @api.model
    def get_values(self):
        res = super().get_values()
        param = self.env['ir.config_parameter'].sudo().get_param('smart_data_importer.llm_send_samples', 'True')
        res['smart_data_importer_llm_send_samples'] = param != 'False'
        return res

    def set_values(self):
        super().set_values()
        self.env['ir.config_parameter'].sudo().set_param(
            'smart_data_importer.llm_send_samples',
            'True' if self.smart_data_importer_llm_send_samples else 'False')

    def action_test_llm_connection(self):
        """Tests the LLM connection and returns a notification to the user."""
        self.ensure_one()
        # Save current settings to ir.config_parameter first so the test runs against them
        config = self.env['ir.config_parameter'].sudo()
        config.set_param('smart_data_importer.llm_enabled', 'True' if self.smart_data_importer_llm_enabled else 'False')
        config.set_param('smart_data_importer.llm_provider', self.smart_data_importer_llm_provider or 'deepseek')
        config.set_param('smart_data_importer.llm_model', self.smart_data_importer_llm_model or '')
        config.set_param('smart_data_importer.llm_api_key', self.smart_data_importer_llm_api_key or '')
        config.set_param('smart_data_importer.llm_base_url', self.smart_data_importer_llm_base_url or '')
        config.set_param('smart_data_importer.llm_send_samples', 'True' if self.smart_data_importer_llm_send_samples else 'False')

        from ..services.mapper_llm import LLMMapper
        success, message = LLMMapper.test_connection(self.env)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Prueba de Conexión IA' if success else 'Fallo de Conexión IA',
                'message': message,
                'type': 'success' if success else 'danger',
                'sticky': not success,
            }
        }
    
    @api.constrains('smart_data_importer_fuzzy_threshold')
    def _check_smart_data_importer_fuzzy_threshold(self):
        for rec in self:
            if not 0 <= rec.smart_data_importer_fuzzy_threshold <= 100:
                raise ValidationError(_('El umbral de similitud debe estar entre 0 y 100.'))