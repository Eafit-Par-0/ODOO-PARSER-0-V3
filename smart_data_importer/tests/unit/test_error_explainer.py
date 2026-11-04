from error_explainer import WHOLE_ROW, classify_exception, describe, group_errors


def test_groups_by_column_and_category():
    errors = [
        {'column': 'fecha', 'field_label': 'Fecha (date)', 'category': 'invalid_date', 'row': 3, 'value': '31/02/2024'},
        {'column': 'fecha', 'field_label': 'Fecha (date)', 'category': 'invalid_date', 'row': 9, 'value': 'ayer'},
        {'column': 'fecha', 'field_label': 'Fecha (date)', 'category': 'required', 'row': 4},
        {'column': 'valor', 'field_label': 'Valor (amount)', 'category': 'invalid_number', 'row': 3, 'value': '12 USD'},
    ]
    groups = group_errors(errors)
    assert len(groups) == 3
    # required errors go first: they block the most
    assert groups[0]['category'] == 'required'
    dates = next(g for g in groups if g['category'] == 'invalid_date')
    assert dates['column'] == 'fecha'
    assert dates['row_count'] == 2
    assert dates['rows_text'] == '3, 9'
    assert dates['sample_values'] == '31/02/2024, ayer'
    assert "'Fecha (date)'" in dates['message']
    assert dates['hint']


def test_rows_text_is_truncated_and_samples_unique():
    errors = [{'column': 'n', 'category': 'invalid_number', 'row': r, 'value': 'x'} for r in range(1, 26)]
    group = group_errors(errors)[0]
    assert group['row_count'] == 25
    assert group['rows_text'].endswith('(+15)')
    assert group['sample_values'] == 'x'


def test_error_without_column_goes_to_whole_row():
    group = group_errors([{'category': 'validation', 'row': 2, 'technical': 'boom'}])[0]
    assert group['column'] == WHOLE_ROW
    assert group['technical'] == 'boom'


def test_unknown_category_falls_back_to_other():
    info = describe('does_not_exist', 'Nombre (name)')
    assert info['title'] == describe('other')['title']
    assert "'Nombre (name)'" in info['message']


def test_classify_not_null_points_to_column():
    msg = 'null value in column "name" of relation "res_partner" violates not-null constraint'
    assert classify_exception('NotNullViolation', msg, {'name': 'Razón social'}) == ('required', 'Razón social')


def test_classify_unique_constraint():
    msg = ('duplicate key value violates unique constraint "account_account_code_company_uniq"\n'
           'DETAIL:  Key (code, company_id)=(110505, 1) already exists.')
    assert classify_exception('UniqueViolation', msg, {'code': 'Código'}) == ('duplicate', 'Código')


def test_classify_validation_guesses_single_column():
    msg = "The VAT number [vat] is not valid for Colombia"
    assert classify_exception('ValidationError', msg, {'vat': 'NIT', 'name': 'Nombre'}) == ('validation', 'NIT')
    assert classify_exception('ValidationError', 'Something failed', {'vat': 'NIT'}) == ('validation', None)


def test_classify_access_and_other():
    assert classify_exception('AccessError', 'no', {}) == ('access', None)
    assert classify_exception('KeyError', 'x', {}) == ('other', None)