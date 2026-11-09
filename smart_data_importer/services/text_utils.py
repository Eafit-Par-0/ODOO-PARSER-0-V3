import unicodedata
import re


def normalize_text(value):
    """Shared normalization: trim, lowercase, remove diacritics."""
    if value is None:
        return ''
    value = str(value).strip().lower()
    return ''.join(c for c in unicodedata.normalize('NFD', value)
                if unicodedata.category(c) != 'Mn')

def normalize_header_loose(value):
    """Like normalize_text() and also turns punctuation, underscores, hyphens
    and extra spaces into a single space ('Razón_Social' -> 'razon social')."""
    return ' '.join(re.sub(r'[\W_]+', ' ', normalize_text(value)).split())