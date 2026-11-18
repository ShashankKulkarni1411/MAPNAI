"""
MAPNAI — tests/agent5_fakes.py
Agent 5 fakes (chat model, single-pass LLM, retriever) and the `make` builder, shared by
test_query_graph.py and test_query_retrieval.py.
"""

from types import SimpleNamespace

from agents.agent5_query import QueryAgent
from agents.query_graph import (
    AnswerCheck, ClaimCheck, DocGrade, GeneratedAnswer, GradeResult, QueryGraph, RewriteResult,
)
from agents.query_llm import QueryLLM
from agents.query_retriever import QueryRetriever
from config.settings import settings

CRED = SimpleNamespace(source_cred={"Reuters": 0.8, "Wire": 0.6, "RumorMill": 0.1},
                       source_cred_default=0.5, source_field="source_name")

def art(i, relevance=0.8, source="Reuters", title=None):
    return {"article_id": f"a{i}", "title": title or f"Story {i}", "domain": "finance", "category": "",
            "summary_short": f"Summary {i}.", "summary_long": f"Details {i}.", "entities": [],
            "relevance_score": relevance, "risk_score": None, "source_name": source}

def cfg(**over):
    base = {"query_graph_max_rewrites": 2, "query_graph_max_regenerations": 1, "query_graph_max_llm_calls": 10,
            "query_graph_min_relevant_docs": 2, "query_graph_deadline_seconds": 60.0,
            "query_graph_credibility_weight": 0.3, "query_graph_min_credibility": 0.2}
    base.update(over)
    return settings.model_copy(update=base)

# ── Fakes ───────────────────────────────────────────────

class FakeChat:
    """
    A chat model whose structured outputs are scripted per schema. Each script entry is a value, an exception
    (raised), or a callable(messages) → value. When a script runs out, its last entry repeats.
    """

    def __init__(self, **scripts):
        self.scripts = {k: list(v) if isinstance(v, list) else [v] for k, v in scripts.items()}
        self.calls = []     # (schema name, messages)

    def with_structured_output(self, schema, method=None):
        chat = self

        class Runnable:
            def invoke(self, messages):
                chat.calls.append((schema.__name__, messages))
                script = chat.scripts[schema.__name__]
                step = script.pop(0) if len(script) > 1 else script[0]
                if isinstance(step, BaseException):
                    raise step
                return step(messages) if callable(step) else step

        return Runnable()

    def count(self, schema_name=None):
        return len([c for c in self.calls if schema_name is None or c[0] == schema_name])

class FakeLLM(QueryLLM):
    model_name = "fake-llm"

    def __init__(self):
        self.calls = 0

    def generate_answer(self, question, context):
        self.calls += 1
        return "Single-pass answer [1]."

class FakeRetriever(QueryRetriever):
    """Real route()/fallback logic over scripted keyword / semantic / graph results."""

    def __init__(self, keyword=None, semantic=None, graph=None, graph_error=None):
        self._keyword, self._semantic, self._graph = keyword or [], semantic or [], graph or []
        self.graph_error = graph_error
        self.searches = []

    def _pick(self, results, query):
        return [dict(a) for a in (results(query) if callable(results) else results)]

    def keyword_search(self, query, domain_filter=None, top_k=10):
        self.searches.append(("keyword", query))
        return self._pick(self._keyword, query)

    def semantic_search(self, query, domain_filter=None, top_k=10, min_similarity_threshold=0.22):
        self.searches.append(("semantic", query))
        return self._pick(self._semantic, query)

    def graph_search(self, entities, domain_filter=None, top_k=10):
        self.searches.append(("graph", tuple(entities)))
        if self.graph_error:
            raise self.graph_error
        return self._pick(self._graph, entities)

def grades(*flags):
    return GradeResult(grades=[DocGrade(index=i, relevant=f) for i, f in enumerate(flags, start=1)])

def all_relevant(messages):
    n = messages[1]["content"].count('<article index="')
    return grades(*[True] * n)

def none_relevant(messages):
    n = messages[1]["content"].count('<article index="')
    return grades(*[False] * n)

GOOD_ANSWER = GeneratedAnswer(answerable=True, answer="The Fed raised rates [1]. Stocks fell [2].", cited=[1, 2])
GROUNDED = AnswerCheck(claims=[ClaimCheck(claim="The Fed raised rates", supported=True, article_indices=[1]),
                               ClaimCheck(claim="Stocks fell", supported=True, article_indices=[2])])

def make(retriever=None, chat=None, llm=None, cred=CRED, **cfg_over):
    retriever = retriever or FakeRetriever(keyword=[art(1, 0.9), art(2, 0.8)], semantic=[art(3, 0.7)])
    chat = chat or FakeChat(GradeResult=all_relevant, RewriteResult=RewriteResult(query="better query"),
                            GeneratedAnswer=GOOD_ANSWER, AnswerCheck=GROUNDED)
    llm = llm or FakeLLM()
    graph = QueryGraph(retriever, chat, cfg=cfg(**cfg_over), cred_cfg=cred, model_name="fake-groq")
    return QueryAgent(llm=llm, retriever=retriever, graph=graph), chat, llm, retriever
