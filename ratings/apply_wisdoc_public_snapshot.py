"""Publish the approved Wisdoc ratings against the site's live browsing catalog."""
import hashlib
import json
import math
from pathlib import Path

from common_basket import METHOD
from model_dedup import identify


SITE = Path(__file__).resolve().parents[1] / 'site'
BOARDS = ('Main', 'Science', 'Coding', 'General', 'Agent')
PREFIX = 'window.snapshotElo = '


def identity(row):
    return identify(row['model'], row['setting'])['key']


def publish(site=SITE):
    source_path = 'wisdoc-rankings/rankings.json'
    raw = (site / source_path).read_bytes()
    source = json.loads(raw)
    panels = source['boards']
    assert set(panels) == set(BOARDS)
    panel = source['common_basket']
    refs = [{k: row[k] for k in ('model', 'setting', 'weight')} for row in panel['references']]
    assert len(refs) == panel['count'] and panel['minimum_papers_per_board'] >= 12
    assert all(math.isfinite(row['weight']) and row['weight'] > 0 for row in refs)
    assert math.isclose(math.fsum(row['weight'] for row in refs), 1)
    for name, board in panels.items():
        rows = board['models']
        assert board['display_threshold'] == (7 if name == 'Main' else 5)
        assert board['narrow_display_paper_credit'] == .5
        assert all(row['rank'] == i and math.isfinite(row['elo'])
                   and board['display_threshold'] <= row['display_papers'] <= row['papers']
                   for i, row in enumerate(rows, 1)), name
        assert all(a['elo'] >= b['elo'] for a, b in zip(rows, rows[1:])), name
        lookup = {identity(row): row for row in rows}
        assert len(lookup) == len(rows), name
        assert all(lookup[identity(ref)]['papers'] >= panel['minimum_papers_per_board'] for ref in refs), name
        assert math.isclose(math.fsum(ref['weight'] * lookup[identity(ref)]['elo'] for ref in refs),
                            1000, abs_tol=1e-8), name

    main_path = site / 'snapshot-elo-data.js'
    catalog = json.loads((site / 'snapshot/current.json').read_bytes())
    existing = json.loads(main_path.read_text(encoding='utf-8').removeprefix(PREFIX).removesuffix(';'))
    assert existing['snapshot_id'] == catalog['snapshot_id']
    assert existing['task_inputs_sha256'] == catalog['task_inputs']['sha256']
    aliases = {identity(row): row.get('source_names', []) for row in existing['models']}
    sha = hashlib.sha256(raw).hexdigest()
    basket = dict(status='READY', references=refs, reference_count=len(refs), baseline=1000,
                  panel_sha256=hashlib.sha256(json.dumps(refs, sort_keys=True).encode()).hexdigest(),
                  minimum_independent_papers_per_board=panel['minimum_papers_per_board'])
    common = dict(scoring_revision='wisdoc-' + sha[:12], score_method=METHOD, score_unit='elo',
                  outcome_method='wisdoc-source-gap-soft-outcomes', references=refs,
                  ranking_snapshot=dict(generated_at=source['generated_at'], as_of=source['as_of'],
                                        sha256=sha, path=source_path), narrow_display_paper_credit=.5)

    def row_with_score(row):
        return dict(row, score=row['elo'], score_unit='elo')

    main = dict(common, snapshot_id=catalog['snapshot_id'], task_inputs_sha256=catalog['task_inputs']['sha256'],
                basket=basket, display_min_papers=panels['Main']['display_threshold'],
                papers=panels['Main']['fitted_papers'], reviews=[],
                models=[dict(row_with_score(row), elo_scale=row['elo'], source_names=aliases.get(identity(row), []))
                        for row in panels['Main']['models']])
    categories = dict(common, snapshot=catalog['snapshot_id'], method='main-batch-elo',
                      boards={name: [row_with_score(row) for row in panels[name]['models']] for name in BOARDS[1:]},
                      status={name: dict(basket=basket, min_papers=panels[name]['display_threshold'],
                                         fitted_papers=panels[name]['fitted_papers'], narrow_display_paper_credit=.5)
                              for name in BOARDS[1:]})
    for path, prefix, suffix, data in [(main_path, PREFIX, ';', main),
                                       (site / 'capability-rankings.json', '', '', categories)]:
        output = path.with_suffix('.tmp')
        output.write_text(prefix + json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + suffix,
                          encoding='utf-8')
        output.replace(path)


if __name__ == '__main__':
    publish()
