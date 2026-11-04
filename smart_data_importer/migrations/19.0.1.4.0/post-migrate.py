"""19.0.1.4.0: the module is now fully in Spanish.

The default cleansing rules are loaded with noupdate="1", so an upgrade does
not rename them by itself. Rename only the ones nobody has edited (their name
is still the original English one).
"""
import logging

_logger = logging.getLogger(__name__)

OLD_NAMES = {
    'rule_strip_whitespace': 'Trim Whitespace',
    'rule_titlecase': 'Capitalize Words (Title Case)',
    'rule_uppercase': 'Convert to Uppercase',
    'rule_lowercase': 'Convert to Lowercase',
    'rule_remove_accents': 'Remove Accents / Diacritics',
    'rule_digits_only': 'Keep Digits Only',
    'rule_normalize_email': 'Normalize Email',
    'rule_normalize_phone': 'Normalize Phone / Mobile',
    'rule_normalize_vat': 'Normalize Tax ID / Document',
    'rule_clean_currency_cop': 'Clean Currency ($ COP / USD)',
    'rule_normalize_date_iso': 'Normalize Date to ISO (YYYY-MM-DD)',
}

NEW_VALUES = {
    'rule_strip_whitespace': ('Quitar espacios sobrantes', 'Quita los espacios al inicio y al final del texto.'),
    'rule_titlecase': ('Primera letra en mayúscula', 'Pone en mayúscula la primera letra de cada palabra (ej. Juan Perez Rodriguez).'),
    'rule_uppercase': ('Convertir a mayúsculas', 'Convierte todas las letras a MAYÚSCULAS.'),
    'rule_lowercase': ('Convertir a minúsculas', 'Convierte todas las letras a minúsculas.'),
    'rule_remove_accents': ('Quitar tildes', 'Reemplaza las letras con tilde por su equivalente sin tilde (ej. á -> a, ñ -> n).'),
    'rule_digits_only': ('Dejar solo dígitos', 'Quita todo lo que no sea un número.'),
    'rule_normalize_email': ('Normalizar correo', 'Limpia los correos: quita espacios, pasa a minúsculas y extrae la dirección.'),
    'rule_normalize_phone': ('Normalizar teléfono / celular', 'Limpia los teléfonos: quita espacios, guiones y paréntesis, y conserva el indicativo del país.'),
    'rule_normalize_vat': ('Normalizar NIT / documento', 'Limpia NIT/RUT/documentos: quita puntos y espacios internos y pasa a mayúsculas.'),
    'rule_clean_currency_cop': ('Limpiar moneda ($ COP / USD)', 'Quita símbolos de moneda ($, COP, USD) y convierte la coma decimal al formato estándar.'),
    'rule_normalize_date_iso': ('Normalizar fecha a ISO (AAAA-MM-DD)', 'Convierte fechas (DD/MM/AAAA, MM/DD/AAAA) al formato ISO estándar (AAAA-MM-DD).'),
}


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})
    for xmlid, (name, description) in NEW_VALUES.items():
        rule = env.ref('smart_data_importer.%s' % xmlid, raise_if_not_found=False)
        if not rule or rule.name != OLD_NAMES.get(xmlid):
            continue
        vals = {'name': name}
        if description:
            vals['description'] = description
        rule.write(vals)
        _logger.info("Cleansing rule %s renamed to '%s'", xmlid, name)
