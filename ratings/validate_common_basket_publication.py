"""Validate the five generated boards before packaging a public release."""
import json
import math
from pathlib import Path
from common_basket import METHOD
from model_dedup import identify
from soft_outcomes import METHOD as OUTCOME_METHOD


def validate(main, categories):
    assert main['snapshot_id'] == categories['snapshot']
    assert main['scoring_revision'] == categories['scoring_revision']
    assert main['score_method'] == categories['score_method'] == METHOD
    assert main['outcome_method'] == categories['outcome_method'] == OUTCOME_METHOD
    assert set(categories['boards']) == {'Science', 'Coding', 'General', 'Agent'}
    reference = main['basket']
    assert reference['status'] == 'READY' and reference['panel_sha256']
    assert reference['minimum_independent_papers_per_board'] >= 12
    report = {}
    boards = [('Main', main['models'], 'elo_scale', reference)] + [
        (name, rows, 'elo', categories['status'][name]['basket'])
        for name, rows in categories['boards'].items()]
    for name, rows, key, basket in boards:
        assert basket['status'] == 'READY'
        for field in ('panel_sha256', 'references', 'baseline', 'minimum_independent_papers_per_board'):
            assert basket[field] == reference[field], (name, field)
        lookup = {identify(r['model'], r.get('setting', ''))['key']: r for r in rows}
        values = []
        for ref in reference['references']:
            row = lookup[identify(ref['model'], ref.get('setting', ''))['key']]
            assert row['papers'] >= reference['minimum_independent_papers_per_board']
            values.append(ref['weight'] * row[key])
        assert math.isclose(math.fsum(values), 1000, abs_tol=1e-8), name
        assert all(math.isfinite(r[key]) and r['score'] == r[key] for r in rows)
        assert all(rows[i][key] >= rows[i+1][key] for i in range(len(rows)-1))
        report[name] = {'fitted_models': len(rows), 'references': len(values)}
    return report


if __name__ == '__main__':
    site = Path(__file__).resolve().parents[1] / 'site'
    text = (site / 'snapshot-elo-data.js').read_text(encoding='utf8')
    main = json.loads(text.removeprefix('window.snapshotElo = ').removesuffix(';'))
    categories = json.loads((site / 'capability-rankings.json').read_text(encoding='utf8'))
    print(json.dumps(validate(main, categories), ensure_ascii=False))
