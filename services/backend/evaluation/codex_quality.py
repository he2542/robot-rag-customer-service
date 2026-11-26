"""Independent Qwen scoring of frozen Codex answers; no generation or retrieval."""
import argparse
import hashlib
import json
from pathlib import Path

from evaluation.codex_client import fingerprint, read, save
from evaluation.codex_validation import summarize as check_codex, verify_source
from evaluation.paired_statistics import paired_binary
from evaluation.postprocess_validation import JUDGE, call, make_body, parse_verdict, passed, size
from evaluation.budget import add_budget_arguments, budget_from_args, require_budget


def same_policy_baseline(source, frozen, question):
    if hashlib.sha256((source / 'candidate_policy.py').read_bytes()).hexdigest() != frozen['policy_sha256']:
        raise ValueError('Baseline and Codex must use the same output policy')
    answer = read(source / 'answers' / (question['id'] + '.json'))
    if answer['sources'] != question['sources']:
        raise ValueError('Baseline references differ')
    binding = read(source / 'judgments' / (question['id'] + '-post.json'))
    if Path(binding['score_file']).name != binding['score_file']:
        raise ValueError('Unsafe baseline score path')
    score = read(source / 'scores' / binding['score_file'])
    payload = {'question': question['query'], 'required_points': question['required_points'],
               'references': question['sources'], 'answer': answer['answers']['post']}
    messages = [{'role': 'system', 'content': JUDGE},
                {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]
    expected = fingerprint(make_body('qwen-max', messages, 512, 20261124))
    if (binding['answer_sha256'] != fingerprint(payload['answer'])
            or score['input_sha256'] != expected or score['response']['input_sha256'] != expected
            or binding['score_file'] != expected + '.json'):
        raise ValueError('Baseline judge input changed')
    verdict = parse_verdict(score['response']['text'], len(question['required_points']))
    if score['verdict'] != verdict or score['response']['finish_reason'] != 'stop':
        raise ValueError('Baseline judgment changed or truncated')
    return payload['answer'], verdict, answer['generation']['finish_reason']


def prepare(source, output, baseline_source):
    checked = check_codex(source)
    frozen = read(source / 'frozen-inputs.json')
    verify_source(baseline_source)
    if hashlib.sha256((baseline_source / 'inputs-manifest.json').read_bytes()).hexdigest() != frozen['source_manifest_sha256']:
        raise ValueError('Baseline source changed')
    if checked['generated'] != 20:
        raise ValueError('Twenty verified generations required before quality scoring')
    questions = []
    for q in frozen['questions']:
        baseline_answer, baseline_verdict, baseline_finish = same_policy_baseline(baseline_source, frozen, q)
        answer = read(source / 'generate' / (q['id'] + '.json'))['answer']
        payload = {'question': q['query'], 'required_points': q['required_points'],
                   'references': q['sources'], 'answer': answer}
        messages = [{'role': 'system', 'content': JUDGE},
                    {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]
        body = make_body('qwen-max', messages, 512, 20261124)
        if size(body) > 16384:
            raise ValueError('Independent scoring input exceeds approved limit')
        questions.append({'id': q['id'], 'category': q['category'], 'body': body,
            'body_sha256': fingerprint(body), 'baseline_answer': baseline_answer,
            'baseline_verdict': baseline_verdict, 'baseline_finish': baseline_finish})
    value = {'version': 'codex-quality-20-v1', 'frozen_sha256': fingerprint(frozen),
             'codex_summary': checked, 'questions': questions}
    save(output / 'inputs.json', value)
    save(output / 'manifest.json', {'inputs_sha256': fingerprint(value)})
    return value


def checked_inputs(root):
    data = read(root / 'inputs.json')
    if fingerprint(data) != read(root / 'manifest.json')['inputs_sha256']:
        raise ValueError('Frozen scoring inputs changed')
    questions = data['questions']
    if len(questions) != 20 or len({q['id'] for q in questions}) != 20:
        raise ValueError('Expected twenty unique questions')
    if len({q['category'] for q in questions}) != 5:
        raise ValueError('Expected five categories')
    for q in questions:
        if fingerprint(q['body']) != q['body_sha256']:
            raise ValueError('Scoring body changed')
        body = q['body']
        if (body['model'] != 'qwen-max' or body['parameters']['max_tokens'] != 512
                or body['input']['messages'][0] != {'role': 'system', 'content': JUDGE}
                or size(body) > 16384):
            raise ValueError('Independent scoring protocol changed')
        payload = json.loads(body['input']['messages'][1]['content'])
        parse_verdict(json.dumps(q['baseline_verdict']), len(payload['required_points']))
    return data


def run(root):
    require_budget()
    data = checked_inputs(root)
    if (root / 'failure.json').exists():
        raise ValueError('Prior scoring failure requires inspection; automatic retry disabled')
    import httpx
    with httpx.Client(timeout=90, trust_env=False) as client:
        for q in data['questions']:
            target = root / 'scores' / (q['id'] + '.json')
            if target.exists():
                check_score(q, read(target))
                continue
            try:
                body = q['body']
                response = call(client, 'qwen-max', body['input']['messages'], 512, 20261124, 16384)
                score = {'input_sha256': q['body_sha256'], 'response': response}
                check_score(q, score)
                save(target, score)
                print(json.dumps({'judged': q['id']}), flush=True)
            except Exception as error:
                save(root / 'failure.json', {'id': q['id'], 'error_type': type(error).__name__})
                raise


def check_score(q, score):
    response = score['response']
    if (score['input_sha256'] != q['body_sha256']
            or response['input_sha256'] != q['body_sha256']
            or response['finish_reason'] != 'stop'):
        raise ValueError('Score input changed or output truncated')
    count = len(json.loads(q['body']['input']['messages'][1]['content'])['required_points'])
    return parse_verdict(response['text'], count)


def summarize(root):
    data = checked_inputs(root)
    if {p.stem for p in (root / 'scores').glob('*.json')} != {q['id'] for q in data['questions']}:
        raise ValueError('Complete twenty-question scoring required')
    rows = []
    for q in data['questions']:
        score = read(root / 'scores' / (q['id'] + '.json'))
        verdict = check_score(q, score)
        rows.append({'id': q['id'], 'category': q['category'],
            'before': passed(q['baseline_verdict'], q['baseline_finish']),
            'after': passed(verdict, 'stop'), 'baseline_verdict': q['baseline_verdict'],
            'candidate_verdict': verdict, 'usage': score['response']['usage']})
    pairs = [dict(r, source=r['category'], cluster=r['id']) for r in rows]
    return {'version': data['version'], 'inputs_sha256': fingerprint(data),
        'scope': 'Frozen evidence; Qwen-Max judges both models; baseline scores reused from earlier run',
        'statistics': paired_binary(pairs), 'per_question': rows,
        'by_category': {c: {'n': sum(r['category'] == c for r in rows),
            'baseline_pass': sum(r['before'] for r in rows if r['category'] == c),
            'codex_pass': sum(r['after'] for r in rows if r['category'] == c)}
            for c in sorted({r['category'] for r in rows})},
        'codex_judge_agreement': data['codex_summary']['baseline_judge_agreement']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['prepare', 'judge', 'summarize'])
    parser.add_argument('--source', type=Path)
    parser.add_argument('--baseline-source', type=Path)
    parser.add_argument('--root', type=Path, required=True)
    add_budget_arguments(parser)
    args = parser.parse_args()
    if args.stage == 'prepare':
        prepare(args.source, args.root, args.baseline_source)
    elif args.stage == 'judge':
        with budget_from_args(args):
            run(args.root)
    else:
        print(json.dumps(summarize(args.root), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
