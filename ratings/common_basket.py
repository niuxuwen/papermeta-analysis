"""One frozen reference panel for every board, keeping the 400-point Elo scale."""
import math
from collections import defaultdict
from model_dedup import identify
from normalization import reference_panel
from raw_elo import annotate as raw_annotate

METHOD = 'common-basket-centered-elo-v1'
BASELINE = 1000.


def calibrate(rows, *, elo_key='elo', panel=None):
    panel = panel or reference_panel()
    refs = panel['references']
    keys = [identify(r['model'], r.get('setting', ''))['key'] for r in refs]
    weights = [r['weight'] for r in refs]
    if not keys or len(set(keys)) != len(keys):
        raise ValueError('Empty or duplicate reference identities')
    if any(not math.isfinite(w) or w <= 0 for w in weights) or not math.isclose(math.fsum(weights), 1., abs_tol=1e-12):
        raise ValueError('Basket weights must be positive and sum to one')
    by_key = defaultdict(list)
    for row in rows:
        if not math.isfinite(row[elo_key]):
            raise ValueError('Non-finite Elo')
        by_key[identify(row['model'], row.get('setting', ''))['key']].append(row)
    invalid = [r['model'] for r, key in zip(refs, keys) if len(by_key[key]) != 1]
    if invalid:
        # Never quietly use a different panel or synthesize missing strengths.
        raise ValueError('Common basket missing or ambiguous references: ' + ', '.join(invalid))
    minimum = panel.get('selection', {}).get('minimum_independent_papers_per_board', 0)
    insufficient = [r['model'] for r, key in zip(refs, keys)
                    if by_key[key][0].get('papers', 0) < minimum]
    if insufficient:
        raise ValueError('Common basket references below paper minimum: ' + ', '.join(insufficient))
    original = elo_key + '_uncentered'
    anchor_values = [by_key[key][0].get(original, by_key[key][0][elo_key]) for key in keys]
    center = math.fsum(w * v for w, v in zip(weights, anchor_values))
    shift = BASELINE - center
    for row in rows:
        row.setdefault(original, row[elo_key])
        row[elo_key] = row[original] + shift
    raw_annotate(rows, elo_key=elo_key)
    return dict(method=METHOD, status='READY', version=panel['version'],
                panel_sha256=panel.get('sha256'), references=refs, reference_count=len(refs),
                minimum_independent_papers_per_board=minimum,
                baseline=BASELINE, offset=shift, score_unit='elo',
                formula='R_board = R_raw - sum_k(weight_k * R_raw_k) + 1000',
                interpretation='Same reference identities and weights in every board; domain-relative Elo, not absolute cross-domain ability.')
