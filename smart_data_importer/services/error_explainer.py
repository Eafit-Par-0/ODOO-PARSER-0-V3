"""Plain-language explanation and per-column grouping of import errors.

Pure Python on purpose (no Odoo imports) so it can be unit tested with pytest.

Every error found while validating or importing is described as a dict::

    {'column': 'Fecha de alta', 'field_label': 'Fecha (date)', 'category': 'invalid_date',
     'row': 7, 'value': '31/02/2024', 'technical': '...original message...'}

``group_errors`` turns that list into one entry per (column, category) with the
number of rows, the affected rows, sample values and a message a non technical
user can act on.
"""
import re

WHOLE_ROW = '(toda la fila)'

# category -> (short title, sentence explaining the problem, how to fix it)
# ``{field}`` is replaced by the target field label.
CATEGORIES = {
    'required': (
        "Dato obligatorio vacío",
        "Odoo exige un valor en {field} y estas filas lo tienen vacío.",
        "Llena la celda en el archivo o ignora las filas que no tengan ese dato.",
    ),
    'missing_column': (
        "Falta una columna obligatoria",
        "Odoo exige {field}, pero ninguna columna del archivo está asignada a ese campo.",
        "Asigna una columna a ese campo en el mapeo o agrega la columna al archivo.",
    ),
    'invalid_number': (
        "No es un número",
        "{field} solo acepta números y estas celdas traen texto u otros símbolos.",
        "Deja solo dígitos, con punto o coma decimal (ej. 1250.50). Quita letras y unidades.",
    ),
    'invalid_date': (
        "Fecha no reconocida",
        "{field} espera una fecha y estas celdas no tienen un formato de fecha válido.",
        "Usa el formato AAAA-MM-DD (ej. 2026-11-04) o DD/MM/AAAA y revisa que la fecha exista.",
    ),
    'invalid_boolean': (
        "Valor Sí/No no válido",
        "{field} es una casilla Sí/No y estas celdas traen otro valor.",
        "Usa 1/0, Sí/No o Verdadero/Falso.",
    ),
    'not_found': (
        "El valor no existe en Odoo",
        "Los valores de {field} deben existir antes en Odoo y estos no se encontraron.",
        "Corrígelos en la pestaña 'Valores a revisar' o crea primero esos registros en Odoo.",
    ),
    'xmlid_not_found': (
        "Identificador externo inexistente",
        "La columna trae identificadores externos para {field} que no existen en Odoo.",
        "Revisa la escritura (ej. base.co) o importa primero los registros a los que apuntan.",
    ),
    'ambiguous': (
        "Valor ambiguo",
        "En {field} hay varios registros de Odoo con el mismo nombre que estos valores.",
        "Usa un dato único (código, NIT o identificador externo) en lugar del nombre.",
    ),
    'duplicate': (
        "Registro repetido",
        "Ya existe un registro con el mismo valor único ({field}).",
        "Cambia la política de duplicados a 'Actualizar' u 'Omitir', o corrige el valor repetido.",
    ),
    'too_long': (
        "Texto demasiado largo",
        "El texto de {field} supera el largo máximo que permite Odoo.",
        "Acorta el texto de esas celdas.",
    ),
    'unsupported_type': (
        "Tipo de campo no soportado",
        "El campo {field} no se puede llenar desde un archivo con este importador.",
        "Ignora la columna o asígnala a otro campo.",
    ),
    'unknown_field': (
        "Campo inexistente",
        "La columna está asignada a {field}, que no existe en el modelo destino.",
        "Asigna la columna a un campo válido o ignórala.",
    ),
    'validation': (
        "Regla de Odoo no cumplida",
        "Odoo rechazó estas filas por una regla de negocio de {field}.",
        "Lee el detalle del error de una fila de ejemplo y corrige el dato en el archivo.",
    ),
    'access': (
        "Sin permisos",
        "Tu usuario no tiene permiso para crear o modificar estos registros.",
        "Pide a un administrador los permisos del módulo correspondiente.",
    ),
    'other': (
        "Error no clasificado",
        "Odoo no pudo guardar estas filas por un error en {field}.",
        "Revisa el detalle técnico de una fila de ejemplo.",
    ),
}

# Order in which groups are shown: what blocks the most first.
SEVERITY = [
    'missing_column', 'required', 'unknown_field', 'unsupported_type', 'access',
    'not_found', 'xmlid_not_found', 'ambiguous', 'invalid_number', 'invalid_date',
    'invalid_boolean', 'too_long', 'duplicate', 'validation', 'other',
]

_NOT_NULL = re.compile(r'null value in column "(?P<col>[^"]+)"', re.I)
_UNIQUE = re.compile(r'duplicate key value violates unique constraint', re.I)
_UNIQUE_KEY = re.compile(r'Key \((?P<cols>[^)]+)\)=', re.I)
_TOO_LONG = re.compile(r'value too long for type', re.I)


def describe(category, field_label=None):
    """``{'title', 'message', 'hint'}`` for a category, in plain Spanish."""
    title, message, hint = CATEGORIES.get(category) or CATEGORIES['other']
    field = "'%s'" % field_label if field_label else "esta columna"
    return {'title': title, 'message': message.format(field=field), 'hint': hint}


def classify_exception(exc_name, message, fields_by_name=None):
    """Classify an exception raised by Odoo while saving a row.

    :param exc_name: class name of the exception (``ValidationError``, ``IntegrityError``...)
    :param message: ``str(exc)``
    :param fields_by_name: ``{technical field name: column header}`` of the mapped
        columns, used to point the error at the column that caused it.
    :return: ``(category, column or None)``
    """
    message = message or ''
    fields_by_name = fields_by_name or {}

    match = _NOT_NULL.search(message)
    if match:
        return 'required', fields_by_name.get(match.group('col'))
    if _UNIQUE.search(message):
        key = _UNIQUE_KEY.search(message)
        column = None
        if key:
            for name in (c.strip() for c in key.group('cols').split(',')):
                if name in fields_by_name:
                    column = fields_by_name[name]
                    break
        return 'duplicate', column
    if _TOO_LONG.search(message):
        return 'too_long', None
    if exc_name == 'AccessError':
        return 'access', None
    if exc_name in ('ValidationError', 'UserError'):
        return 'validation', _guess_column(message, fields_by_name)
    return 'other', _guess_column(message, fields_by_name)


def _guess_column(message, fields_by_name):
    """Column whose technical field name appears in an Odoo message, if exactly one does."""
    hits = [header for name, header in fields_by_name.items()
            if re.search(r'\b%s\b' % re.escape(name), message)]
    return hits[0] if len(set(hits)) == 1 else None


def _format_rows(rows, limit=10):
    rows = sorted(set(r for r in rows if r is not None))
    text = ', '.join(str(r) for r in rows[:limit])
    if len(rows) > limit:
        text += " … (+%s)" % (len(rows) - limit)
    return text


def group_errors(errors, sample_limit=3, row_limit=10):
    """Group error dicts by (column, category).

    :return: list of dicts with ``column``, ``field_label``, ``category``, ``title``,
        ``message``, ``hint``, ``error_count``, ``row_count``, ``rows_text``,
        ``sample_values`` and ``technical`` (first technical message), sorted by
        severity and then by the number of rows affected.
    """
    groups = {}
    for err in errors:
        column = err.get('column') or WHOLE_ROW
        category = err.get('category') or 'other'
        key = (column, category)
        group = groups.get(key)
        if group is None:
            group = groups[key] = {
                'column': column,
                'field_label': err.get('field_label') or '',
                'category': category,
                'error_count': 0,
                'rows': [],
                'samples': [],
                'technical': err.get('technical') or '',
            }
        group['error_count'] += 1
        if err.get('row') is not None:
            group['rows'].append(err['row'])
        value = err.get('value')
        if value not in (None, '') and str(value) not in group['samples'] and len(group['samples']) < sample_limit:
            group['samples'].append(str(value))

    result = []
    for group in groups.values():
        info = describe(group['category'], group['field_label'] or None)
        result.append({
            'column': group['column'],
            'field_label': group['field_label'],
            'category': group['category'],
            'title': info['title'],
            'message': info['message'],
            'hint': info['hint'],
            'error_count': group['error_count'],
            'row_count': len(set(group['rows'])),
            'rows_text': _format_rows(group['rows'], row_limit),
            'sample_values': ', '.join(group['samples']),
            'technical': group['technical'],
        })
    rank = {c: i for i, c in enumerate(SEVERITY)}
    result.sort(key=lambda g: (rank.get(g['category'], len(rank)), -g['row_count'], g['column']))
    return result