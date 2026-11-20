"""Recompute paired results from frozen answers and explicit point-level review."""
import argparse
import json
from pathlib import Path
import re
import statistics

from evaluation.intent_workflow import checked, digest, read, write


def decision(value, count):
    points=value['points']
    if (len(points)!=count or any(type(p) is not bool for p in points)
            or type(value['supported']) is not bool or type(value['boundary']) is not bool):
        raise ValueError('Review requires one boolean per frozen point and explicit support/boundary decisions')
    if not all(points) or not value['supported'] or not value['boundary']:
        if not value.get('note','').strip():
            raise ValueError('Failed review requires a reason')
    return all(points) and value['supported'] and value['boundary']


def aggregate(rows):
    result={}
    for arm in ['baseline','optimized']:
        values=[r[arm] for r in rows]
        usage=[r['usage'] for r in values]
        result[arm]={
            'questions':len(rows),
            'raw_pass':sum(v['raw_pass'] for v in values),
            'visible_pass':sum(v['visible_pass'] for v in values),
            'raw_points':sum(v['raw_points'] for v in values),
            'visible_points':sum(v['visible_points'] for v in values),
            'total_points':sum(r['point_count'] for r in rows),
            'risk_pass':sum(r[arm]['visible_pass'] for r in rows if r['risk']),
            'risk_questions':sum(r['risk'] for r in rows),
            'truncated':sum(v['finish_reason']!='stop' for v in values),
            'input_tokens':sum(u['input_tokens'] for u in usage),
            'output_tokens':sum(u['output_tokens'] for u in usage),
            'cached_tokens':sum(u.get('cached_tokens',0) for u in usage),
            'raw_claims':sum(v.get('raw_claims',0) for v in values),
            'matched_quotes':sum(v.get('matched_quotes',0) for v in values),
            'invalid_visible_citations':sum(v.get('invalid_visible_citations',0) for v in values),
            'median_ms':statistics.median(v['elapsed_ms'] for v in values),
        }
        result[arm]['list_cost_cny']=(result[arm]['input_tokens']*0.8+result[arm]['output_tokens']*2)/1_000_000
    for kind in ['raw','visible']:
        gains=[r['id'] for r in rows if not r['baseline'][kind+'_pass'] and r['optimized'][kind+'_pass']]
        losses=[r['id'] for r in rows if r['baseline'][kind+'_pass'] and not r['optimized'][kind+'_pass']]
        result[kind+'_paired']={'gains':gains,'losses':losses,'delta_percentage_points':100*(len(gains)-len(losses))/len(rows)}
    return result


def summarize(root, review_path):
    from src.services.answer_policy import quote_in_source
    dataset,protocol,_=checked(root)
    review=read(review_path)
    reviewed={r['id']:r for r in review['per_question']}
    if set(reviewed)!={q['id'] for q in dataset['questions']}:
        raise ValueError('Review must cover the exact frozen questions')
    if len(reviewed)!=len(review['per_question']):
        raise ValueError('Duplicate reviewed question')
    rows=[]
    for q in dataset['questions']:
        row={'id':q['id'],'risk':q['review_risk'],'point_count':len(q['review_points'])}
        for arm in ['baseline','optimized']:
            path=root/'answers'/f"{q['id']}-{arm}.json"
            answer=read(path);rated=reviewed[q['id']][arm]
            if rated['answer_sha256']!=digest(path):
                raise ValueError('Review is not bound to this answer')
            for key,file in [('message_sha256',root/'messages'/path.name),('dataset_sha256',root/'dataset.json'),('protocol_sha256',root/'protocol.json')]:
                if answer[key]!=digest(file):raise ValueError('Answer inputs changed')
            info=answer['generation_info'];tokens=info['token_usage']
            finish=info['finish_reason']
            usage={'input_tokens':tokens['input_tokens'],'output_tokens':tokens['output_tokens']}
            usage['cached_tokens']=tokens.get('prompt_tokens_details',{}).get('cached_tokens',0)
            if any(type(v) is not int or v<0 for v in usage.values()):raise ValueError('Invalid usage')
            raw={}
            try:
                raw=json.loads(answer['raw_generation'])
                valid_json=isinstance(raw,dict) and raw.get('decision') in {'answer','conflict','insufficient','clarify','refer'}
            except json.JSONDecodeError:valid_json=False
            claims=raw.get('claims',[]) if isinstance(raw,dict) else []
            matches=sum(isinstance(c,dict) and isinstance(c.get('quote'),str)
                        and 6<=len(c['quote'].strip())<=400
                        and any(quote_in_source(c['quote'].strip(),s['excerpt']) for s in answer['sources']) for c in claims)
            allowed={s['id'] for s in answer['sources']}
            row[arm]={
                'raw_pass':decision(rated['raw'],len(q['review_points'])) and finish=='stop' and valid_json,
                'visible_pass':decision(rated['visible'],len(q['review_points'])) and finish=='stop' and valid_json,
                'raw_points':sum(rated['raw']['points']),
                'visible_points':sum(rated['visible']['points']),
                'finish_reason':finish,'usage':usage,'elapsed_ms':answer['elapsed_ms'],
                'raw_claims':len(claims),'matched_quotes':matches,
                'invalid_visible_citations':sum(c not in allowed for c in re.findall(r'\[(S\d+)\]',answer['answer'])),
            }
        rows.append(row)
    return {'version':'intent-workflow-paired-results-v1',
            'protocol_sha256':digest(root/'protocol.json'),'dataset_sha256':digest(root/'dataset.json'),
            'review_sha256':digest(review_path),'method':review['method'],
            'summary':aggregate(rows),'per_question':rows}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--review',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=summarize(args.root,args.review)
    write(args.output,result)
    print(json.dumps(result['summary'],ensure_ascii=False))
