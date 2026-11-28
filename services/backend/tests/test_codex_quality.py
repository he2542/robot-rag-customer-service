import json
import hashlib

import pytest

from evaluation import codex_quality as quality
from evaluation.codex_client import fingerprint, save
from evaluation.budget import BudgetError


@pytest.fixture
def evidence(tmp_path):
    questions = []
    for index in range(20):
        payload = {'question': '问题', 'required_points': ['要点'], 'references': [], 'answer': '回答'}
        body = quality.make_body('qwen-max', [
            {'role': 'system', 'content': quality.JUDGE},
            {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}], 512, 20261124)
        verdict = {'points': [True], 'correct': True, 'supported': True, 'safe': True, 'reason': '完整'}
        q = {'id': str(index), 'category': str(index // 4), 'body': body,
             'body_sha256': fingerprint(body), 'baseline_verdict': verdict, 'baseline_finish': 'stop'}
        questions.append(q)
        save(tmp_path / 'scores' / (q['id'] + '.json'), {'input_sha256': fingerprint(body),
            'response': {'input_sha256': fingerprint(body), 'finish_reason': 'stop',
                         'text': json.dumps(verdict), 'usage': {'input_tokens': 10, 'output_tokens': 5}}})
    data = {'version': 'test', 'questions': questions,
            'codex_summary': {'baseline_judge_agreement': {'n': 20, 'same': 19}}}
    save(tmp_path / 'inputs.json', data)
    save(tmp_path / 'manifest.json', {'inputs_sha256': fingerprint(data)})
    return tmp_path


def test_paired_quality_and_judge_agreement_are_separate(evidence):
    score_path = evidence / 'scores/0.json'
    score = quality.read(score_path)
    verdict = json.loads(score['response']['text'])
    verdict['points'] = [False]
    score['response']['text'] = json.dumps(verdict)
    score_path.write_text(json.dumps(score))
    report = quality.summarize(evidence)
    assert sum(r['before'] for r in report['per_question']) == 20
    assert sum(r['after'] for r in report['per_question']) == 19
    assert report['codex_judge_agreement'] == {'n': 20, 'same': 19}


def test_missing_score_cannot_be_reported_as_twenty(evidence):
    (evidence / 'scores/0.json').unlink()
    with pytest.raises(ValueError, match='Complete twenty'):
        quality.summarize(evidence)


@pytest.mark.parametrize('change', ['input', 'truncated', 'integer_boolean'])
def test_mismatched_or_invalid_judgment_rejected(evidence, change):
    q = quality.checked_inputs(evidence)['questions'][0]
    score = quality.read(evidence / 'scores/0.json')
    if change == 'input':
        score['response']['input_sha256'] = 'other'
    elif change == 'truncated':
        score['response']['finish_reason'] = 'length'
    else:
        verdict = json.loads(score['response']['text'])
        verdict['points'] = [1]
        score['response']['text'] = json.dumps(verdict)
    with pytest.raises((ValueError, AssertionError)):
        quality.check_score(q, score)


def test_frozen_input_tampering_stops_before_paid_work(evidence):
    path = evidence / 'inputs.json'
    data = quality.read(path)
    data['questions'][0]['body']['model'] = 'other'
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='inputs changed'):
        quality.checked_inputs(evidence)


def test_paid_scoring_requires_budget(evidence):
    with pytest.raises(BudgetError):
        quality.run(evidence)


def test_scoring_failure_is_persisted_and_not_automatically_retried(evidence, monkeypatch):
    for path in (evidence / 'scores').glob('*.json'):
        path.unlink()
    calls = []
    def fail(*args, **kwargs):
        calls.append(1)
        raise TimeoutError('fixture')
    monkeypatch.setattr(quality, 'require_budget', lambda: None)
    monkeypatch.setattr(quality, 'call', fail)
    with pytest.raises(TimeoutError):
        quality.run(evidence)
    with pytest.raises(ValueError, match='automatic retry disabled'):
        quality.run(evidence)
    assert len(calls) == 1


def test_old_output_policy_cannot_confound_model_comparison(tmp_path):
    (tmp_path / 'candidate_policy.py').write_text('old policy')
    with pytest.raises(ValueError, match='same output policy'):
        quality.same_policy_baseline(tmp_path, {'policy_sha256': 'different'}, {'id': 'test'})


def test_reuses_matching_policy_baseline_and_exact_judge_input(evidence, tmp_path):
    policy = evidence / 'candidate_policy.py'
    policy.write_text('frozen output policy')
    q = quality.checked_inputs(evidence)['questions'][0]
    score = quality.read(evidence / 'scores/0.json')
    name = q['body_sha256'] + '.json'
    save(evidence / 'scores' / name, {'input_sha256': q['body_sha256'],
         'verdict': q['baseline_verdict'], 'response': score['response']})
    save(evidence / 'answers/0.json', {'sources': [], 'answers': {'post': '回答'},
                                     'generation': {'finish_reason': 'stop'}})
    save(evidence / 'judgments/0-post.json', {'score_file': name, 'answer_sha256': fingerprint('回答')})
    result = quality.same_policy_baseline(evidence,
        {'policy_sha256': hashlib.sha256(policy.read_bytes()).hexdigest()},
        {'id': '0', 'query': '问题', 'required_points': ['要点'], 'sources': []})
    assert result == ('回答', q['baseline_verdict'], 'stop')
