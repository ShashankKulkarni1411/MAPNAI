"""
Agent 5 retrieval and the no-LLM answer: keyword ranking (rarity-weighted, anchored on names), domain scope
from MongoDB, the story a question is asked from, and the extractive fallback. mongomock + a fake FAISS store.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import mongomock
import pytest

from agents import query_llm
from agents.agent5_query import QueryAgent
from agents.query_llm import FALLBACK_NOTHING, FALLBACK_PREFIX, extractive_answer
from agents.query_retriever import QueryRetriever
from agents.query_graph import AnswerCheck, ClaimCheck, GeneratedAnswer, RewriteResult
from tests.test_query_graph import FakeChat, FakeRetriever, art, make, none_relevant

T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)


def doc(aid, title, body="", domain="entertainment_movies", entities=(), days=0, summary=""):
    return {"article_id": aid, "title": title, "body": body or title, "domain": domain,
            "summary_short": summary, "summary_long": summary,
            "entities": [{"name": e, "type": "Person"} for e in entities],
            "published_ts": T0 + timedelta(days=days), "source_name": "Variety"}


class FakeFaiss:
    def __init__(self, results=()):
        self.results, self.queries = list(results), []

    def search(self, query, top_k=10, domain_filter=None):
        self.queries.append(query)
        return [dict(r) for r in self.results][:top_k]


def retriever(docs, faiss=None):
    db = mongomock.MongoClient().db
    if docs:
        db["processed_articles"].insert_many([dict(d) for d in docs])
    store = SimpleNamespace(db=db, get_article_by_id=lambda i: db["processed_articles"].find_one(
        {"article_id": i}, {"_id": 0}))
    return QueryRetriever(mongo_store=store, faiss_store=faiss or FakeFaiss())


BOND = doc("bond", "New James Bond announced: Robert Pattinson", entities=["Robert Pattinson", "James Bond"],
           body="Robert Pattinson has been cast as the next James Bond. Celebrities reacted online.")
FD = doc("fd", "Highest senior citizen FD interest rates after RBI repo rate hike", domain="other",
         body="What happens next for savers: new bond yields and FD rates rise as the RBI hikes.")
FILLER = [doc(f"f{i}", f"New season preview {i}", body="What happens next is a new start.", domain="sports",
              days=i + 1) for i in range(40)]


class TestKeywordSearch:
    def test_names_anchor_the_search_and_common_words_do_not_match(self):
        r = retriever([BOND, FD] + FILLER)
        out = r.keyword_search("Has any celebrity reacted to Robert Pattinson being cast as the new bond")
        assert [a["article_id"] for a in out] == ["bond"]
        out = r.keyword_search("What happens next with Pattinson?")
        assert [a["article_id"] for a in out] == ["bond"] and out[0]["relevance_score"] > 0.5

    def test_a_rare_term_is_not_crowded_out_by_common_ones(self):
        dhoni = doc("dhoni", "Dhoni retires from playing role with Chennai Super Kings", domain="sports",
                    entities=["MS Dhoni"])
        cups = [doc(f"c{i}", f"World Cup qualifier {i}", domain="sports", days=i + 1) for i in range(150)]
        out = retriever([dhoni] + cups).keyword_search("has ms dhoni retired from the world cup?")
        assert out[0]["article_id"] == "dhoni"

    def test_domain_list_uses_agent2_domain(self):
        other_bond = {**BOND, "article_id": "bond-other", "domain": "other"}
        r = retriever([BOND, other_bond])
        assert {a["article_id"] for a in r.keyword_search("Pattinson")} == {"bond", "bond-other"}
        scoped = r.keyword_search("Pattinson", domain_filter=["sports", "entertainment_movies"])
        assert [a["article_id"] for a in scoped] == ["bond"]

    def test_nothing_matches(self):
        assert retriever([BOND]).keyword_search("Who is Zyxwv?") == []


class TestSemanticScope:
    def test_domain_comes_from_mongo_and_unknown_articles_are_dropped(self):
        faiss = FakeFaiss([
            {"article_id": "fd", "domain": "finance", "similarity_score": 0.9},     # Mongo: other
            {"article_id": "ghost", "domain": "sports", "similarity_score": 0.8},   # not in Mongo
            {"article_id": "bond", "domain": "finance", "similarity_score": 0.7},   # Mongo: entertainment_movies
        ])
        r = retriever([BOND, FD], faiss)
        scoped = r.semantic_search("bond", domain_filter=["sports", "entertainment_movies"])
        assert [a["article_id"] for a in scoped] == ["bond"]
        assert [a["article_id"] for a in r.semantic_search("bond")] == ["fd", "ghost", "bond"]


class TestContextArticle:
    def test_retrieve_pins_the_story_and_steers_semantic_search(self):
        faiss = FakeFaiss([{"article_id": "fd", "similarity_score": 0.9}])
        r = retriever([BOND, FD], faiss)
        out, route = r.retrieve("what happens next?", top_k=2, context_article_id="bond")
        assert route == "semantic" and [a["article_id"] for a in out] == ["bond", "fd"]
        assert faiss.queries == ["what happens next? " + BOND["title"]]

    def test_pinned_story_is_not_repeated(self):
        faiss = FakeFaiss([{"article_id": "bond", "similarity_score": 0.6}])
        out, _ = retriever([BOND], faiss).retrieve("what now", context_article_id="bond")
        assert [a["article_id"] for a in out] == ["bond"]

    def test_unknown_story_is_ignored(self):
        out, _ = retriever([BOND]).retrieve("Pattinson", context_article_id="missing")
        assert [a["article_id"] for a in out] == ["bond"]

    def test_graph_path_pins_the_story_and_searches_the_readers_words(self):
        fake = FakeRetriever(keyword=[art(1, 0.9), art(2, 0.8)])
        fake.mongo_store = SimpleNamespace(get_article_by_id=lambda i: {**art(9), "article_id": i})
        agent, _, _, _ = make(retriever=fake)
        res = agent.process("What did the Fed do? (about: Story 9)", search_query="What did the Fed do?",
                            context_article_id="ctx")
        assert res["sources"][0]["article_id"] == "ctx"
        assert fake.searches[0] == ("keyword", "What did the Fed do?")

    def test_grader_cannot_drop_the_pinned_story(self):
        fake = FakeRetriever(keyword=[art(1, 0.9)])
        fake.mongo_store = SimpleNamespace(get_article_by_id=lambda i: {**art(9), "article_id": i})
        chat = FakeChat(GradeResult=none_relevant, RewriteResult=RewriteResult(query="better query"),
                        GeneratedAnswer=GeneratedAnswer(answerable=True, answer="Filming starts soon [1].", cited=[1]),
                        AnswerCheck=AnswerCheck(claims=[ClaimCheck(claim="Filming starts soon", supported=True,
                                                                   article_indices=[1])]))
        agent, _, _, _ = make(retriever=fake, chat=chat, query_graph_min_relevant_docs=1)
        res = agent.process("What now? (about: Story 9)", search_query="What now?", context_article_id="ctx")
        assert [s["article_id"] for s in res["sources"]] == ["ctx"]
        assert res["_metadata"]["graph"]["outcome"] == "answered"

    def test_single_pass_pins_the_story(self):
        fake = FakeRetriever(semantic=[art(1, 0.9)])
        fake.mongo_store = SimpleNamespace(get_article_by_id=lambda i: {**art(9), "article_id": i})
        _, _, llm, _ = make()
        agent = QueryAgent(llm=llm, retriever=fake, graph=None)     # FakeLLM → no graph
        res = agent.process("what now (about: Story 9)", search_query="what now", context_article_id="ctx")
        assert [s["article_id"] for s in res["sources"]] == ["ctx", "a1"]
        assert fake.searches == [("semantic", "what now Story 9")]


def context(*summaries):
    blocks = [f"[Source Article {i} - ID: a{i}]\nTitle: Story {i}\nDomain: sports\nShort Summary: x\n"
              f"Detailed Summary: {s}\nKey Entities: None listed\n" for i, s in enumerate(summaries, start=1)]
    return "\n".join(blocks)


@pytest.fixture
def no_embeddings(monkeypatch):
    import storage.faiss_store as fs
    monkeypatch.setattr(fs, "_get_model", lambda: None)


class TestExtractiveFallback:
    def test_quotes_the_closest_sentences_with_citations(self, no_embeddings):
        ctx = context(
            "The Reserve Bank of India raised the repo rate to 5.5%. Banks will adjust deposit rates.",
            "Former India captain MS Dhoni has retired from playing with Chennai Super Kings. "
            "He will take up a new role as team mentor from the 2027 season.",
        )
        out = extractive_answer("Has MS Dhoni retired from playing?", ctx)
        assert out.startswith(FALLBACK_PREFIX)
        assert "Dhoni has retired from playing with Chennai Super Kings. [2]" in out
        assert "Reserve Bank" not in out

    def test_says_so_when_nothing_answers(self, no_embeddings):
        ctx = context("The Reserve Bank of India raised the repo rate to 5.5% in its meeting today.")
        assert extractive_answer("Has any celebrity reacted to Robert Pattinson?", ctx) == FALLBACK_NOTHING

    def test_story_title_suffix_is_not_matched(self, no_embeddings):
        ctx = context("The studio confirmed the release date for next summer at a press event.")
        assert extractive_answer("Who directs it? (about: Studio confirms release date)", ctx) == FALLBACK_NOTHING

    def test_ask_uses_its_own_model_when_set(self, monkeypatch):
        monkeypatch.setattr(query_llm.settings, "groq_model", "shared-model")
        monkeypatch.setattr(query_llm.settings, "query_graph_model", "")
        assert query_llm.GroqQueryLLM(api_key="x").model_name == "shared-model"
        monkeypatch.setattr(query_llm.settings, "query_graph_model", "ask-model")
        assert query_llm.GroqQueryLLM(api_key="x").model_name == "ask-model"

    def test_groq_failure_uses_it(self, no_embeddings, monkeypatch):
        monkeypatch.setattr(query_llm, "chat_completion", lambda **kw: None)
        llm = query_llm.GroqQueryLLM(api_key="x")
        ctx = context("Former India captain MS Dhoni has retired from playing with Chennai Super Kings.")
        assert llm.generate_answer("Has Dhoni retired?", ctx).endswith("[1]")
