import copy
import unittest
from benchmark_entities import build_registry

def row(name, paper='p', **extra):
    return {'benchmark_name': name, 'paper_id': paper, 'benchmark_id': paper+name, **extra}

class IdentityTests(unittest.TestCase):
    def mappings(self, rows):
        return build_registry(rows)['mappings']

    def test_cross_paper_exact_aliases_and_typography(self):
        rows=[row(n,str(i)) for i,n in enumerate(['MMLU','mmlu','Massive Multitask Language Understanding','GSM8K','gsm8k','HumanEval','Human Eval'])]
        m={x['source_name']:x for x in self.mappings(rows)}
        self.assertEqual(m['MMLU']['entity_id'],m['mmlu']['entity_id'])
        self.assertEqual(m['MMLU']['entity_id'],m['Massive Multitask Language Understanding']['entity_id'])
        self.assertEqual(m['GSM8K']['entity_id'],m['gsm8k']['entity_id'])
        self.assertEqual(m['HumanEval']['entity_id'],m['Human Eval']['entity_id'])

    def test_pro_plus_intrinsic_numbers_not_erased(self):
        m={x['source_name']:x for x in self.mappings([row(n) for n in ['MMLU','MMLU-Pro','MMLU Pro','HumanEval','HumanEval+','GSM8K','GSM8K-V','MATH-500','MATH-1000']])}
        self.assertEqual(m['MMLU-Pro']['entity_id'],m['MMLU Pro']['entity_id'])
        for a,b in [('MMLU','MMLU-Pro'),('HumanEval','HumanEval+'),('GSM8K','GSM8K-V'),('MATH-500','MATH-1000')]:
            self.assertNotEqual(m[a]['entity_id'],m[b]['entity_id'])

    def test_versions_languages_and_subsets_keep_distinct_variants(self):
        m=self.mappings([row(n)for n in ['ExampleBench v1','ExampleBench v2','ExampleBench (test)','ExampleBench (train)','ExampleBench (English)','ExampleBench (Chinese)']])
        self.assertEqual(len({x['entity_id']for x in m}),1)
        self.assertEqual(len({x['variant_id']for x in m}),6)

    def test_unresolved_labels_are_not_counted_as_benchmarks(self):
        result=build_registry([row(n)for n in ['名称待核验','Accuracy','Overall','ARC','math','English']])
        self.assertEqual(result['statistics']['resolved_entities'],0)
        self.assertEqual(result['statistics']['unresolved_source_records'],6)

    def test_decimal_versions_and_annual_contests(self):
        mappings=self.mappings([row(n)for n in ['Terminal-Bench 2.0','Terminal-Bench 2.1','AMC23','AMC24']])
        self.assertEqual(len({m['entity_id']for m in mappings}),2)
        self.assertEqual(len({m['variant_id']for m in mappings}),4)

    def test_resource_aliases_require_both_shared_resource_and_alias(self):
        assets={'assets':{'items':[{'kind':'dataset','url':'https://github.com/org/data','evidence_quote':'The dataset is available at this repository.'}]}}
        rows=[row('ExampleBench','p1',enrichment=assets,benchmark_aliases=['Example Benchmark']),
              row('Example Benchmark','p2',enrichment=assets,benchmark_aliases=['ExampleBench']),
              row('UnrelatedBench','p3',enrichment=assets)]
        m=self.mappings(rows);byname={x['source_name']:x for x in m}
        self.assertEqual(byname['ExampleBench']['entity_id'],byname['Example Benchmark']['entity_id'])
        self.assertNotEqual(byname['ExampleBench']['entity_id'],byname['UnrelatedBench']['entity_id'])
        self.assertEqual(build_registry(rows),build_registry(rows[::-1]))

    def test_new_homonyms_and_alias_bridges_do_not_merge(self):
        rows=[row('RealtimeBench','p1',eligibility='ELIGIBLE',date_basis='PAPER_V1_PROXY'),row('RealtimeBench','p2',eligibility='ELIGIBLE',date_basis='PAPER_V1_PROXY'),row('GSM8K','p3',benchmark_aliases=['GSM8K-V']),row('GSM8K-V','p4')]
        m=self.mappings(rows)
        self.assertTrue(all(x['entity_id']is None for x in m if x['source_name']=='RealtimeBench'))
        self.assertEqual(len({x['entity_id']for x in m if x['source_name']!='RealtimeBench'}),2)

    def test_stable_ids_permutation_idempotence_and_no_mutation(self):
        rows=[row('MMLU','p1'),row('MMLU','p2'),row('OtherBench','p3')];original=copy.deepcopy(rows)
        a=build_registry(rows);b=build_registry(rows[::-1]);self.assertEqual(a,b)
        self.assertEqual(rows,original)
        extended=build_registry(rows+[row('MMLU','p9')]);self.assertEqual(a['mappings'][0]['entity_id'],extended['mappings'][0]['entity_id'])

if __name__=='__main__':unittest.main()
