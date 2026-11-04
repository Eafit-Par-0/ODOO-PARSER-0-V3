import logging

from .text_utils import normalize_text

_logger = logging.getLogger(__name__)


class CandidateProvider:
    """Lists the values a cell could have meant, as ``[(key, normalized_label)]``.

    Selection fields use their options (keys and labels in every installed
    language). Relational fields use the record names, only when the comodel
    is small enough (``max_candidates``). Cached per instance.
    """

    def __init__(self, env, max_candidates):
        self.env = env
        self.max_candidates = max_candidates
        self._cache = {}

    def get(self, converter, field_name, subfield=None):
        """Return the candidates of ``field_name`` of the converter's model."""
        field = converter.model._fields.get(field_name)
        if field is None or subfield == 'id':
            return []
        cache_key = (converter.model_name, field_name)
        if cache_key not in self._cache:
            if field.type == 'selection':
                self._cache[cache_key] = self._selection_candidates(converter, field_name)
            elif field.type in ('many2one', 'many2many'):
                self._cache[cache_key] = self._relational_candidates(field.comodel_name)
            else:
                self._cache[cache_key] = []
        return self._cache[cache_key]

    @staticmethod
    def _selection_candidates(converter, field_name):
        seen, result = set(), []
        for norm_label, key in converter.selection_options(field_name).items():
            if (key, norm_label) in seen:
                continue
            seen.add((key, norm_label))
            result.append((key, norm_label))
        return result

    def _relational_candidates(self, comodel_name):
        if comodel_name not in self.env:
            return []
        comodel = self.env[comodel_name].with_context(active_test=False)
        rec_name = comodel._rec_name
        field = comodel._fields.get(rec_name) if rec_name else None
        if field is None or not field.store:
            return []
        try:
            if comodel.search_count([]) > self.max_candidates:
                return []
        except Exception:
            _logger.warning("Could not count %s for value suggestions", comodel_name, exc_info=True)
            return []
        langs = [code for code, _name in self.env['res.lang'].get_installed()] or ['en_US']
        result, seen = [], set()
        for lang in set(langs + ['en_US']):
            for rec in comodel.with_context(lang=lang).search([]):
                name = normalize_text(rec[rec_name])
                if not name or (rec.id, name) in seen:
                    continue
                seen.add((rec.id, name))
                result.append((rec.id, name))
        return result
