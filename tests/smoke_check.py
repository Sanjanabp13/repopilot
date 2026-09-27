import sys
import re
sys.path.insert(0, '.')

from src.ingestion.walker import walk_repository
from src.ingestion.parsers.python_parser import PythonParser
from src.analysis.symbol_index import build_index
from src.analysis.call_graph import build_call_graph
from src.analysis.dep_graph import build_dep_graph
from src.diagrams.mermaid_renderer import MermaidRenderer
from src.knowledge.embedder import Embedder
from src.knowledge.vector_store import VectorStore
from src.knowledge.rag_chain import RAGChain

files   = walk_repository('tests/fixtures/sample_project', languages={'python'})
parser  = PythonParser()
results = [parser.parse(f.absolute_path) for f in files]
index   = build_index(files, parser)
cg      = build_call_graph(index, results)
dg      = build_dep_graph(index, results)

r = MermaidRenderer()
call_md = r.render_call_graph(cg)
dep_md  = r.render_dep_graph(dg)

def strip(raw):
    s = raw.strip()
    s = re.sub(r'^```mermaid\s*', '', s, flags=re.I)
    s = re.sub(r'^```\s*', '', s, flags=re.I)
    s = re.sub(r'\s*```$', '', s)
    return s.strip()

call_clean = strip(call_md)
dep_clean  = strip(dep_md)
assert call_clean.startswith('flowchart LR'), f'Bad call graph header: {call_clean[:40]}'
assert dep_clean.startswith('flowchart TD'),  f'Bad dep graph header: {dep_clean[:40]}'
print('Mermaid syntax OK')
print('call_graph first 120:', call_clean[:120])

vs = VectorStore()
e  = Embedder()
chain = RAGChain(vector_store=vs, embedder=e)
n = chain.index_repository(index, results)
print(f'Indexed {n} chunks')
ans = chain.answer('What does get_user do?')
print('confidence:', ans['confidence'])
print('citations:', [(c['fqn'], c['line']) for c in ans['citations']])
assert ans['answer'] != 'No confident answer found for this question.', 'still returning no-answer'
print('RAG answer first 120:', ans['answer'][:120])
print('ALL OK')
