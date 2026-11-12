"""Expose the fitted Elo scale without a reference basket or 0–100 mapping."""
from math import isfinite

METHOD = 'raw-batch-elo-v1'

def annotate(rows, elo_key='elo'):
    for row in rows:
        value = row[elo_key]
        if not isfinite(value):
            raise ValueError('Non-finite Elo')
        row['score'] = value
        row['score_unit'] = 'elo'
    return dict(method=METHOD, score_unit='elo')

def validate(rows, elo_key='elo'):
    for row in rows:
        if not isfinite(row[elo_key]) or row.get('score_unit') != 'elo' or row['score'] != row[elo_key]:
            raise ValueError('Display score must equal fitted Elo')
