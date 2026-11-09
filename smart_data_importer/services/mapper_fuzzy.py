from rapidfuzz import process, fuzz

from .field_catalog import FieldCatalog, split_header
from .text_utils import normalize_header_loose


class FuzzyMapper:
    """Approximate mapper using Levenshtein-based similarity.

    Headers are compared ignoring case, accents, punctuation and extra spaces,
    against the labels and technical names of the model's fields and against the
    synonyms of the registry (seed and learned).
    """

    @classmethod
    def map(cls, env, headers, model_name='res.partner', threshold=85):
        fields_records = FieldCatalog.importable_fields(env, model_name)

        field_choices = {}
        for f in fields_records:
            for label in (f.field_description, f.name):
                norm = normalize_header_loose(label)
                if norm and norm not in field_choices:
                    field_choices[norm] = f.id

        # Synonyms always use the full-string ratio: a short synonym such as 'nit'
        # must not partially match inside a longer header ('monitor').
        importable_ids = set(fields_records.ids)
        synonym_choices = {}
        registry = env['mapping.registry'].search(
            [('model_id.model', '=', model_name)], order='priority desc, id')
        for reg in registry:
            norm = normalize_header_loose(reg.synonym)
            if (norm and reg.field_id.id in importable_ids
                    and norm not in field_choices and norm not in synonym_choices):
                synonym_choices[norm] = reg.field_id.id

        choices_list = list(field_choices)
        synonyms_list = list(synonym_choices)
        if not choices_list and not synonyms_list:
            return {}

        results = {}
        for header in headers:
            norm_header = normalize_header_loose(header)
            if not norm_header:
                continue
            best_score, best_field = 0.0, None
            # Technical headers (type_regime_id) of fields that don't exist here must not
            # partially match a short field name (type), so they use a full-string ratio.
            base, _sub = split_header(header)
            scorer = fuzz.ratio if base and '_' in base else fuzz.WRatio
            match = choices_list and process.extractOne(norm_header, choices_list, scorer=scorer)
            if match:
                best_score, best_field = match[1], field_choices[match[0]]
            match = synonyms_list and process.extractOne(norm_header, synonyms_list, scorer=fuzz.ratio)
            if match and match[1] > best_score:
                best_score, best_field = match[1], synonym_choices[match[0]]
            if best_field and best_score >= threshold:
                results[header] = {
                    'target_field_id': best_field,
                    'target_subfield': False,
                    'confidence': round(best_score / 100.0, 2),
                    'source': 'fuzzy',
                }
        return results