import pandas as pd

from .cleansing_engine import CleansingEngine
from .text_utils import normalize_text
from .value_candidates import CandidateProvider
from .value_converter import (
    AmbiguousValueError, ValueConverter, ValueNotFoundError, split_many2many,
)
from .value_fuzzy_matcher import suggest

RELATIONAL_TYPES = ('selection', 'many2one', 'many2many')
MAX_FAILING_VALUES = 200
PLAN_KEYS = ('column_mapping_id', 'header', 'field_name', 'subfield', 'rules')


class ValueValidator:
    """Finds the cell values that the import would not be able to resolve.

    Uses the same cleansing, splitting and exact lookup as the import job, so
    what is reported here is exactly what would fail there. It only returns
    data; persisting the issues is the caller's job.

    :param memory: optional ``{(field_name, normalized_value): {'key': ..., 'label': ...}}``
        of previously learned corrections.
    """

    def __init__(self, env, model_name, threshold=80.0, max_candidates=5000, memory=None):
        self.env = env
        self.model_name = model_name
        self.threshold = threshold
        self.memory = memory or {}
        self.converter = ValueConverter(env, model_name)
        self.candidates = CandidateProvider(env, max_candidates)

    def validate(self, df, plan):
        """
        :param df: DataFrame of the sheet
        :param plan: list of dicts (or tuples) with column_mapping_id, header,
            field_name, subfield, rules
        :return: (issues, overflow_column_ids)
            issues: list of dicts with column_mapping_id, header, field_name,
            original_value, normalized_value, occurrence_count, issue_type,
            suggested_key, suggested_label, confidence (0-1), is_ambiguous,
            source ('fuzzy'|'memory'|'none'), decision ('pending'|'accept')
        """
        issues, overflow = [], set()
        fields_map = self.converter.model._fields
        for item in plan:
            if not isinstance(item, dict):
                item = dict(zip(PLAN_KEYS, item))
            field = fields_map.get(item['field_name'])
            subfield = item.get('subfield') or None
            if field is None or field.type not in RELATIONAL_TYPES or subfield == 'id':
                continue
            if item['header'] not in df.columns:
                continue
            col_issues = self._validate_column(df, item, field, subfield)
            if col_issues is None:
                overflow.add(item['column_mapping_id'])
                continue
            issues.extend(col_issues)
        return issues, overflow

    # ------------------------------------------------------------------
    def _validate_column(self, df, item, field, subfield):
        rules = item.get('rules')
        counts = {}  # cleaned cell value -> rows
        for raw in df[item['header']]:
            if raw is None or (not isinstance(raw, str) and pd.isna(raw)):
                continue
            val = CleansingEngine.apply_rules(raw, rules) if rules else raw
            text = str(val).strip()
            if text:
                counts[text] = counts.get(text, 0) + 1

        # rows per individual value (a many2many cell counts once per part)
        occurrences = {}
        for text, rows in counts.items():
            parts = split_many2many(text) if field.type == 'many2many' else [text]
            for part in dict.fromkeys(parts):
                occurrences[part] = occurrences.get(part, 0) + rows

        # 1. exact lookup of every value (cheap); 2. only then suggestions
        failures = []
        for value, rows in occurrences.items():
            try:
                self.converter.resolve_single(field.name, value, subfield)
                continue
            except ValueNotFoundError:
                failures.append((value, rows, 'not_found'))
            except AmbiguousValueError:
                failures.append((value, rows, 'ambiguous'))
            if len(failures) > MAX_FAILING_VALUES:
                return None  # probably the wrong field: no suggestions, flag the column

        issues = []
        for value, rows, issue_type in failures:
            norm = normalize_text(value)
            issue = {
                'column_mapping_id': item['column_mapping_id'],
                'header': item['header'],
                'field_name': field.name,
                'original_value': value,
                'normalized_value': norm,
                'occurrence_count': rows,
                'issue_type': issue_type,
                'suggested_key': False,
                'suggested_label': False,
                'confidence': 0.0,
                'is_ambiguous': False,
                'source': 'none',
                'decision': 'pending',
            }
            if issue_type == 'not_found':
                self._fill_suggestion(issue, field, subfield, norm)
            issues.append(issue)
        return issues

    def _fill_suggestion(self, issue, field, subfield, norm):
        remembered = self.memory.get((field.name, norm))
        if remembered:
            issue.update({
                'suggested_key': remembered.get('key'),
                'suggested_label': remembered.get('label'),
                'confidence': 1.0,
                'source': 'memory',
                'decision': 'accept',
            })
            return
        candidates = self.candidates.get(self.converter, field.name, subfield)
        suggestion = suggest(norm, candidates, threshold=self.threshold)
        if suggestion:
            issue.update({
                'suggested_key': suggestion.key,
                'suggested_label': suggestion.label,
                'confidence': suggestion.score / 100.0,
                'is_ambiguous': suggestion.ambiguous,
                'source': 'fuzzy',
            })
