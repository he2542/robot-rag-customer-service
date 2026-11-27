"""Pointers into complete evidence; never remove or rewrite source passages."""
from collections import Counter
import math
import re

from .keyword import tokenize

def navigation(question, sources, limit=8):
    entries=[]
    for source in sources:
        for number,line in enumerate(source['excerpt'].splitlines(),1):
            if re.match(r'^\d+[.、]\s*\S',line):
                entries.append({'source_id':source['id'],'excerpt_line':number,
                                'label':line[:100]})
    terms=set(tokenize(question))
    words=[set(tokenize(e['label'])) for e in entries]
    frequency=Counter(w for row in words for w in row)
    def score(index):
        return sum(1+math.log((len(entries)+1)/(frequency[t]+1)) for t in terms & words[index])
    ordered=sorted(range(len(entries)),key=lambda i:(-score(i),i))
    return [entries[i] for i in ordered[:limit] if score(i)>0]

