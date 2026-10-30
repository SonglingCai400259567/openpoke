"""Data integrity tests, independent of torch/OpenRouter and OpenPoke internals."""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent / 'datasets'
FULL = ROOT / 'workflow_routing_v2_200.json'


def test_v2_dataset_structure_and_label_scope():
    data = json.loads(FULL.read_text(encoding='utf-8'))
    workflows = data['workflows']
    cases = data['cases']
    assert data['dataset_version'] == 'v2.0'
    assert len(workflows) == 200
    assert len(cases) == 200
    assert len({w['key'] for w in workflows}) == 200
    assert len({c['case_id'] for c in cases}) == 200
    assert len({c['query'].casefold().strip() for c in cases}) == 200
    assert all(c['case_id'] == f'V2-{i:03}' for i, c in enumerate(cases, 1))
    assert Counter(c['expected_action'] for c in cases) == {
        'RESUME': 84, 'CREATE': 71, 'CLARIFY': 45
    }
    assert Counter(c['split'] for c in cases) == {'dev': 40, 'holdout': 160}
    allowed_types = {'RESUME', 'CREATE', 'CLARIFY'}
    keys = {w['key'] for w in workflows}
    by_key = {w['key']: w for w in workflows}
    valid_intents = {'new', 'continue', 'unspecified'}
    for c in cases:
        assert c['expected_action'] in allowed_types
        assert c['intent'] in valid_intents
        assert isinstance(c['group'], str) and c['group']
        assert isinstance(c['rationale'], str) and c['rationale']
        assert isinstance(c['query'], str) and c['query'].strip()
        assert isinstance(c['entity_hints'], dict)
        assert all(isinstance(k,str) and isinstance(v,str)
                   for k,v in c['entity_hints'].items())
        # No hidden reference in oracle hint which the user never uttered.
        assert all(v.casefold() in c['query'].casefold()
                   for v in c['entity_hints'].values()), c['case_id']
        if c['expected_action'] == 'RESUME':
            assert c['target_key'] in keys
            assert c['task_type_hint'] == by_key[c['target_key']]['task_type']
            stored = by_key[c['target_key']]['entities']
            assert all(stored.get(k) == v for k,v in c['entity_hints'].items()), c['case_id']
        else:
            assert c['target_key'] is None
    assert 'external' in data['label_policy']['scope'].lower()


def test_missing_external_refs_are_missing_from_internal_workflows():
    data=json.loads(FULL.read_text(encoding='utf-8'))
    known_refs = {
        (k,v) for w in data['workflows']
        for k,v in w['entities'].items()
        if k!='contact'
    }
    missing=[c for c in data['cases'] if c['group']=='missing_internal_external_reference']
    assert len(missing)==30
    assert all(c['expected_action']=='CREATE' and c['intent']=='continue' for c in missing)
    for c in missing:
        refs={(k,v) for k,v in c['entity_hints'].items() if k!='contact'}
        assert refs, c['case_id']
        assert refs.isdisjoint(known_refs), c['case_id']


def test_splits_share_exact_same_corpus_and_partition_cases():
    full = json.loads(FULL.read_text(encoding='utf-8'))
    dev = json.loads((ROOT / 'workflow_routing_v2_dev.json').read_text(encoding='utf-8'))
    holdout = json.loads((ROOT / 'workflow_routing_v2_holdout.json').read_text(encoding='utf-8'))
    assert full['workflows'] == dev['workflows'] == holdout['workflows']
    assert len(dev['cases']) == 40
    assert len(holdout['cases']) == 160
    assert {c['case_id'] for c in dev['cases']}.isdisjoint(
        {c['case_id'] for c in holdout['cases']}
    )
    # No RESUME workflow target should appear in both dev and holdout.
    dev_targets = {c['target_key'] for c in dev['cases'] if c['expected_action']=='RESUME'}
    holdout_targets = {c['target_key'] for c in holdout['cases'] if c['expected_action']=='RESUME'}
    assert dev_targets.isdisjoint(holdout_targets)
    assert {c['case_id'] for c in full['cases']} == (
        {c['case_id'] for c in dev['cases']} |
        {c['case_id'] for c in holdout['cases']}
    )


def test_no_duplicate_fixture_ids_or_external_ids():
    data=json.loads(FULL.read_text(encoding='utf-8'))
    # Non-contact reference IDs can repeat across workflows in reality; here
    # the *generated distractor* references are intentionally unique.
    decoys=[w for w in data['workflows'] if w['key'].startswith('distractor_')]
    assert len(decoys)==158
    references=[]
    for w in decoys:
        refs=[v for k,v in w['entities'].items() if k!='contact']
        assert len(refs)==1
        references.extend(refs)
    assert len(references)==len(set(references))
