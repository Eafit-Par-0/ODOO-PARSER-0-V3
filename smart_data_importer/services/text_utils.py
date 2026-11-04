import unicodedata


def normalize_text(value):
    """Shared normalization: trim, lowercase, remove diacritics."""
    if value is None:
        return ''
    value = str(value).strip().lower()
    return ''.join(c for c in unicodedata.normalize('NFD', value)
                   if unicodedata.category(c) != 'Mn')
