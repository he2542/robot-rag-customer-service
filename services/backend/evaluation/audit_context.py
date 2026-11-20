"""Offline source fidelity and frozen-evidence audit; no model/database calls."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import tarfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.repo.resolve()
    sys.path.insert(0, str(root / 'services/backend'))
    from langchain_core.documents import Document
    from src.services.context import EvidenceContextBuilder, source_entries
    from src.services.corpus import load_internal_files
    from src.services.evidence_review import REVIEW_DECISIONS
    from src.services.rag import source_items
    files = {file.filename: file for file in load_internal_files()}
    reviewed = []
    for decision in REVIEW_DECISIONS:
        file = files[decision.filename]
        assert file.document_hash == decision.document_hash
        entry = next(e for e in source_entries(file) if e.start_line == decision.start_line
                     and e.entry_hash == decision.entry_hash)
        reviewed.append((decision, file.text[entry.start:entry.end]))
    archive = root / 'docs/validation/paired-300-20261111-v1.tar.gz'
    with tarfile.open(archive) as source:
        corpus = json.load(source.extractfile('corpus.json'))
        dataset_bytes = source.extractfile('dataset.json').read()
        dataset = json.loads(dataset_bytes)
        rankings = {q['id']: json.load(source.extractfile('retrieval/' + q['id'] + '.json'))
                    ['rankings']['hybrid_rerank'][:4] for q in dataset['questions']}
    docs = {row['id']: Document(id=row['id'], page_content=row['content'], metadata=row['metadata']) for row in corpus}
    builder = EvidenceContextBuilder()
    whole = builder.build(list(docs.values()))
    assert not whole.fallback_reasons
    assert set(whole.excluded_reviews) == {d.id for d in REVIEW_DECISIONS}
    for doc in whole.documents:
        file = files[doc.metadata['source']]
        assert doc.metadata['document_hash'] == file.document_hash
        lines = file.text.splitlines()
        restored = '\n\n'.join('\n'.join(lines[s['start_line'] - 1:s['end_line']]).strip()
                                for s in doc.metadata['source_spans'])
        assert doc.page_content == restored, (doc.metadata['source'], doc.metadata['chunk_index'])
        for decision, blocked in reviewed:
            assert blocked not in doc.page_content
    rows = []
    for q in dataset['questions']:
        original = [docs[key] for key in rankings[q['id']]]
        prepared = builder.build(original)
        assert not prepared.fallback_reasons
        original_hit = any(q['evidence'] in d.page_content and d.metadata['source'] == q['source'] for d in original)
        prepared_hit = any(q['evidence'] in d.page_content and d.metadata['source'] == q['source'] for d in prepared.documents)
        target_excluded = any(decision.filename == q['source'] and q['evidence'] in blocked
                              for decision, blocked in reviewed)
        if original_hit and not target_excluded:
            assert prepared_hit, q['id']
        public = source_items(prepared.documents)
        assert [s['id'] for s in public] == [f'S{i}' for i in range(1, len(public) + 1)]
        rows.append({'id': q['id'], 'source': q['source'], 'original_anchor_present': original_hit,
                     'prepared_anchor_present': prepared_hit, 'target_review_excluded': target_excluded,
                     'excluded_reviews': prepared.excluded_reviews,
                     'original_bytes': sum(len(d.page_content.encode()) for d in original),
                     'prepared_bytes': sum(len(d.page_content.encode()) for d in prepared.documents),
                     'source_count': len(public)})
    protected = [r for r in rows if r['original_anchor_present'] and not r['target_review_excluded']]
    result = {'kind': 'offline evidence-fidelity audit; not answer-quality scoring',
              'frozen_dataset_sha256': hashlib.sha256(dataset_bytes).hexdigest(),
              'corpus_chunks': len(docs), 'prepared_sources': len(whole.documents),
              'fallbacks': len(whole.fallback_reasons), 'blocked_review_ids': list(whole.excluded_reviews),
              'reviewed_entry_leaks': 0, 'source_text_and_line_ranges_verified': True,
              'questions': len(rows), 'protected_original_anchors': len(protected),
              'protected_anchors_retained': sum(r['prepared_anchor_present'] for r in protected),
              'intentionally_excluded_question_ids': [r['id'] for r in rows if r['target_review_excluded']],
              'original_anchor_present': sum(r['original_anchor_present'] for r in rows),
              'prepared_anchor_present': sum(r['prepared_anchor_present'] for r in rows),
              'total_original_excerpt_bytes': sum(r['original_bytes'] for r in rows),
              'total_prepared_excerpt_bytes': sum(r['prepared_bytes'] for r in rows), 'per_question': rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in result.items() if k != 'per_question'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
