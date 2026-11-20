"""Audit complete-entry selection against frozen candidates without API calls."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import tarfile

from langchain_core.documents import Document
from src.services.context import EvidenceContextBuilder, source_entries
from src.services.corpus import load_internal_files
from src.services.evidence_review import REVIEW_DECISIONS
from src.services.prompt_context import PromptContextBuilder, source_items
from src.services.prompts import CONTEXT_SYSTEM_PROMPT


def audit(repo):
    with tarfile.open(repo / 'docs/validation/paired-300-20261111-v1.tar.gz') as archive:
        dataset_bytes = archive.extractfile('dataset.json').read()
        questions = json.loads(dataset_bytes)['questions']
        corpus = json.load(archive.extractfile('corpus.json'))
        rankings = {q['id']: json.load(archive.extractfile('retrieval/' + q['id'] + '.json'))
                    ['rankings']['hybrid_rerank'][:4] for q in questions}
    files = {f.filename: f for f in load_internal_files(repo / 'knowledge/robot')}
    blocked = [(r, next(files[r.filename].text[e.start:e.end] for e in source_entries(files[r.filename])
                       if e.start_line == r.start_line and e.entry_hash == r.entry_hash)) for r in REVIEW_DECISIONS]
    docs = {row['id']: Document(id=row['id'], page_content=row['content'], metadata=row['metadata']) for row in corpus}
    recovery = EvidenceContextBuilder(lambda: list(files.values()))
    builder = PromptContextBuilder(CONTEXT_SYSTEM_PROMPT)
    rows = []
    for q in questions:
        original = [docs[key] for key in rankings[q['id']]]
        recovered = recovery.build(original)
        selected = builder.evidence(q['query'], recovered.documents)
        value, diagnostic = builder.messages(q['query'], selected.documents, [])
        assert json.loads(value['request_payload'])['references'] == source_items(selected.documents)
        assert diagnostic['input_bytes'] <= builder.limits.total
        assert selected.evidence_bytes <= builder.limits.evidence
        for doc in selected.documents:
            source = files[doc.metadata['source']]
            text = '\n\n'.join('\n'.join(source.text.splitlines()[s['start_line'] - 1:s['end_line']]).strip()
                               for s in doc.metadata['source_spans'])
            assert text == doc.page_content
            assert not any(raw in text for _, raw in blocked)
        hit = lambda documents: any(q['evidence'] in d.page_content and d.metadata['source'] == q['source'] for d in documents)
        reviewed = any(r.filename == q['source'] and q['evidence'] in raw for r, raw in blocked)
        rows.append({'id': q['id'], 'source': q['source'], 'original_hit': hit(original),
                     'selected_hit': hit(selected.documents), 'review_excluded': reviewed,
                     'duplicates': selected.duplicates, 'omitted_units': selected.dropped_units,
                     'input_bytes': diagnostic['input_bytes'], 'evidence_bytes': selected.evidence_bytes,
                     'source_count': len(selected.documents), 'fallbacks': recovered.fallback_reasons})
    eligible = [r for r in rows if r['original_hit'] and not r['review_excluded']]
    return {'dataset_sha256': hashlib.sha256(dataset_bytes).hexdigest(), 'questions': len(rows),
            'source_counts': dict(Counter(q['source'] for q in questions)),
            'eligible_anchors': len(eligible), 'retained_anchors': sum(r['selected_hit'] for r in eligible),
            'lost_eligible_ids': [r['id'] for r in eligible if not r['selected_hit']],
            'review_excluded_ids': [r['id'] for r in rows if r['review_excluded']],
            'removed_duplicate_units': sum(r['duplicates'] for r in rows),
            'budget_omitted_units': sum(r['omitted_units'] for r in rows),
            'max_input_bytes': max(r['input_bytes'] for r in rows),
            'total_input_bytes': sum(r['input_bytes'] for r in rows),
            'max_evidence_bytes': max(r['evidence_bytes'] for r in rows),
            'total_evidence_bytes': sum(r['evidence_bytes'] for r in rows),
            'per_question': rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.repo.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in result.items() if k != 'per_question'}, ensure_ascii=False))
