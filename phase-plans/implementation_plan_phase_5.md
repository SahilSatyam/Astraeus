# Phase 5 — Sentiment & Alternative Data

**Timeline:** Weeks 14–20 (parallel with Phase 4) · **Depends on:** Phases 1, 2 · **Blocks:** Phases 6, 7

---

## 1. Phase Goals & Refined Exit Criteria

Build an **institutional-grade alt-data pipeline** that produces PIT-correct sentiment, topic, and embedding features for every name in the universe — the kind of pipeline Two Sigma's "Halite" or AQR's text-research stack would recognize. The phase is *not* about clever sentiment scores winning trades. Naive sentiment trading lost most of its alpha by 2018; the alt-data game now is **non-obvious aggregation, careful timestamping, and feature interactions** with quant signals from Phase 3.

Refined exit criteria:

- **Per-ticker daily sentiment + topic vectors** materialised as features in the feature store, PIT-correct on three timestamps (event, publish, ingest).
- **Entity linking accuracy ≥ 92%** on a 500-mention labelled fixture covering ambiguous tickers (Apple Inc., Berkshire B/A, T vs the letter T).
- **Demo: sentiment-divergence detector on AAPL** showing where social sentiment diverges from price for ≥ 30 days, with backtest contextualizing whether that divergence has predictive content (we expect "weak; not stand-alone alpha").
- **Source coverage:** Reddit (top 20 finance subs), X (curated allowlist via partner API), RSS news (Reuters, Bloomberg-eligible feeds, FT, WSJ where licensed), SEC EDGAR (8-K, 10-Q, 10-K), earnings transcripts (Seeking Alpha or vendor).
- **PIT discipline proven:** a feature query at `as_of_ts = T` cannot return any row whose `available_at_ts > T`. Tested by red-team property tests.
- **RAG corpus ready** for Phase 6 — every document has a chunk-level embedding and a hybrid (BM25 + vector) index.

---

## 2. Scope Boundaries

| In | Out |
|---|---|
| Reddit, X (partner API), RSS news, SEC EDGAR, earnings transcripts | YouTube transcripts (deferred — ROI low for the effort) |
| English-language only | Multi-lingual (deferred to international expansion) |
| FinBERT + sentence-transformers + spaCy NER + BERTopic | Fine-tuned LLM-as-judge sentiment (deferred; expensive and unclear lift) |
| Sector & event sentiment aggregates | Per-analyst-style "consensus" extraction |
| pgvector for embeddings | Dedicated vector DB (Qdrant/Weaviate) — pgvector is enough at this scale |
| Hybrid retrieval (BM25 + vector) | Dense-only or LLM-rerank (revisit with measured recall) |
| News-impact event study | Causal inference / DiD modeling (research follow-on) |

YouTube transcripts are a trap: high engineering effort (audio → ASR → diarization → linking), legal grey area on transcripts, and the alpha is dominated by the same news that's already in our text feeds. Defer.

---

## 3. Week-by-Week Breakdown

### Week 14 — Ingestion Foundations
- Document model & schema (raw_document, document_chunk).
- Reddit (PRAW) adapter; rate-limit aware; subreddit allowlist.
- RSS news adapter (with licensed sources only).
- Outbox + DLQ pattern (mirror Phase 1).

### Week 15 — SEC EDGAR + Transcripts
- EDGAR daily index ingest; 8-K immediate, 10-Q/K T+1.
- Earnings transcripts adapter (vendor or scrape with caution).
- HTML/XBRL → clean text pipeline.
- Three timestamps captured per doc: `event_ts`, `publish_ts`, `ingest_ts`.

### Week 16 — NLP Pipeline
- spaCy NER with finance-tuned model; ticker dictionary; entity linker.
- FinBERT sentiment (HuggingFace) wrapped behind a service.
- Sentence-transformers embeddings (`bge-small-en` or `e5-base-v2`).
- Batch worker; GPU optional, CPU fallback.

### Week 17 — Topic Modeling + X
- BERTopic on rolling windows (30/90 day).
- X (Twitter) adapter via partner API; curated handle list, finance-only.
- Topic assignment table; topic drift monitoring.

### Week 18 — Feature Materialisation
- Sentiment time-series feature views in Phase 2 feature store.
- Topic exposure features per ticker.
- Embedding features (mean-pooled per ticker per day).
- News-impact event-study scoring.

### Week 19 — RAG Corpus + Hybrid Retrieval
- pgvector index on document chunks.
- BM25 index (Tantivy or Postgres ts_vector) on the same chunks.
- Reciprocal-rank-fusion combiner.
- Phase 6 retrieval API (read-only; agents are next phase).

### Week 20 — Demo + Hardening
- Sentiment-divergence detector dashboard (AAPL).
- PIT red-team tests.
- Entity linking accuracy benchmark.
- Drift monitoring dashboards live.

---

## 4. Component & Service Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Source Adapters                         │
│ Reddit (PRAW)  X (partner API)  RSS  EDGAR  Transcripts         │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │   Raw Document Store │   ← MinIO (full text + html)
                    │   + Outbox           │   ← Postgres
                    └──────────┬───────────┘
                               │ events
                               ▼
                ┌──────────────────────────────┐
                │          NLP Pipeline        │
                │  ┌────────────────────────┐  │
                │  │  Cleaner + Chunker     │  │
                │  └────────────────────────┘  │
                │  ┌────────────────────────┐  │
                │  │  NER + Entity Linker   │──┼── Ticker Dictionary
                │  └────────────────────────┘  │
                │  ┌────────────────────────┐  │
                │  │  FinBERT Sentiment     │  │
                │  └────────────────────────┘  │
                │  ┌────────────────────────┐  │
                │  │  Embeddings (S-BERT)   │  │
                │  └────────────────────────┘  │
                │  ┌────────────────────────┐  │
                │  │  BERTopic (batch)      │  │
                │  └────────────────────────┘  │
                └──────────────┬───────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                      ▼
┌──────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ Feature Store│    │ pgvector + BM25  │    │ Topic Store      │
│ (Phase 2)    │    │ (RAG corpus)     │    │ (assignments)    │
└──────────────┘    └────────┬─────────┘    └──────────────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │  RAG Retrieval   │  → Phase 6 agents
                    │  Service         │
                    └──────────────────┘
```

---

## 5. Folder & File Structure

```
apps/
├─ altdata-ingest-reddit/
├─ altdata-ingest-x/
├─ altdata-ingest-rss/
├─ altdata-ingest-edgar/
├─ altdata-ingest-transcripts/
├─ nlp-pipeline-worker/
├─ topic-batch-worker/
└─ rag-retrieval-service/
libs/
├─ altdata/
│  ├─ documents.py
│  ├─ adapters/             # one per source
│  └─ outbox.py
├─ nlp/
│  ├─ cleaner.py
│  ├─ chunker.py            # recursive, w/ token-aware splitting
│  ├─ ner.py
│  ├─ entity_linker.py      # ticker disambiguation
│  ├─ sentiment.py          # FinBERT wrapper
│  ├─ embeddings.py
│  └─ topic.py              # BERTopic wrapper
├─ entities/
│  ├─ ticker_dict.py        # company name ↔ ticker
│  └─ aliases.py
└─ rag/
   ├─ retriever.py          # hybrid (BM25 + vector + RRF)
   └─ chunk_store.py
```

---

## 6. Data Model / Schema Changes

```sql
CREATE TABLE raw_document (
    doc_id          UUID PRIMARY KEY,
    source          TEXT NOT NULL,                   -- reddit, x, rss, edgar, transcript
    source_doc_id   TEXT NOT NULL,                   -- vendor-side id
    url             TEXT,
    title           TEXT,
    body_uri        TEXT NOT NULL,                   -- minio://...
    body_hash       BYTEA NOT NULL,
    language        TEXT,
    event_ts        TIMESTAMPTZ,                     -- when did the thing happen
    publish_ts      TIMESTAMPTZ NOT NULL,            -- when published
    ingest_ts       TIMESTAMPTZ NOT NULL DEFAULT now(),
    schema_version  SMALLINT NOT NULL,
    UNIQUE (source, source_doc_id)
);

CREATE TABLE document_chunk (
    chunk_id        UUID PRIMARY KEY,
    doc_id          UUID NOT NULL REFERENCES raw_document,
    chunk_idx       INT NOT NULL,
    text            TEXT NOT NULL,
    token_count     INT NOT NULL,
    embedding       VECTOR(384),                     -- bge-small-en
    UNIQUE (doc_id, chunk_idx)
);
CREATE INDEX ON document_chunk USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON document_chunk USING gin (to_tsvector('english', text));

CREATE TABLE entity_mention (
    mention_id    UUID PRIMARY KEY,
    chunk_id      UUID NOT NULL REFERENCES document_chunk,
    surface_form  TEXT NOT NULL,
    entity_kind   TEXT NOT NULL,                     -- ticker, person, org, ...
    canonical_id  TEXT,                              -- e.g., AAPL
    confidence    REAL NOT NULL,
    char_start    INT, char_end INT
);
CREATE INDEX ON entity_mention (canonical_id);

CREATE TABLE sentiment_score (
    doc_id        UUID NOT NULL,
    ticker        TEXT NOT NULL,
    model         TEXT NOT NULL,                     -- finbert v1.0
    label         TEXT NOT NULL,                     -- pos/neg/neu
    score         REAL NOT NULL,                     -- -1..1
    available_at  TIMESTAMPTZ NOT NULL,              -- max(publish_ts, ingest_ts)
    PRIMARY KEY (doc_id, ticker, model)
);
CREATE INDEX ON sentiment_score (ticker, available_at);

CREATE TABLE topic_assignment (
    chunk_id      UUID NOT NULL REFERENCES document_chunk,
    topic_id      INT NOT NULL,
    model_run_id  UUID NOT NULL,                     -- BERTopic snapshot
    probability   REAL NOT NULL,
    PRIMARY KEY (chunk_id, topic_id, model_run_id)
);

CREATE TABLE topic_model_run (
    model_run_id  UUID PRIMARY KEY,
    fit_window_from DATE NOT NULL,
    fit_window_to   DATE NOT NULL,
    n_topics      INT,
    topic_summary JSONB,
    fit_at        TIMESTAMPTZ DEFAULT now()
);
```

`available_at = max(publish_ts, ingest_ts)` is the **single most important column in this phase**. PIT joins from the feature store join on `available_at`, never on `publish_ts` alone (because backtests would otherwise pretend we ingested the news instantaneously, which we didn't).

---

## 7. API Surface

```
GET  /altdata/documents?ticker=AAPL&from=...&to=...
GET  /altdata/sentiment?ticker=AAPL&model=finbert&from=...
POST /altdata/ingest/manual                # operator backfill trigger
GET  /altdata/topics?model_run=<id>
POST /rag/retrieve                         # hybrid search
GET  /rag/chunks/{chunk_id}
```

`POST /rag/retrieve` request:
```json
{
  "query": "AAPL guidance commentary on services growth Q4 2024",
  "k": 12,
  "filters": {"ticker": "AAPL", "source": ["edgar","transcripts","rss"], "as_of": "2024-12-15T00:00:00Z"},
  "rerank": "rrf"
}
```

The `as_of` filter is non-negotiable — every retrieval is implicitly PIT.

---

## 8. External Dependencies

| Source | Mechanism | Cost & Risk |
|---|---|---|
| Reddit | PRAW (free OAuth) | API tier changes since 2023; allowlist subreddits |
| X | Partner API (paid) | Pricing volatile; capped budget |
| RSS news | Direct fetch | Licensing varies — only ingest sources we can prove rights to |
| SEC EDGAR | Free index API | Stable; rate limits documented |
| Transcripts | Vendor (e.g., Refinitiv) or licensed scrape | Cost is the gating factor |
| HuggingFace | model weights | Cache locally; pin versions; mirror to internal registry |
| spaCy | model weights | Same |

PII redaction at ingest: usernames hashed unless we have a legal reason to retain. Reddit author names are stored as `sha256(salt || username)` for de-duplication only.

---

## 9. Key Technical Decisions & Tradeoffs

**FinBERT vs LLM-as-judge sentiment.** FinBERT for default. It's deterministic, fast on CPU, and battle-tested in literature. LLM-as-judge sentiment is more nuanced but introduces non-determinism, cost, and a moving target — the score under model X today is different under model Y next quarter. Use LLM only for *narrative summary*, not scalar sentiment.

**Sentence-transformers model.** `bge-small-en-v1.5` (384-dim, fast on CPU) for default; `e5-base-v2` for an A/B comparison. Don't go to 1024-dim until we have measured recall lift.

**pgvector vs Qdrant/Weaviate.** pgvector. We're at most 100M chunks/year; pgvector with HNSW handles that. Operational simplicity (one DB to back up, one to monitor) beats the marginal recall gain of a dedicated store at this scale.

**Hybrid retrieval (BM25 + vector + RRF).** BM25-only loses on paraphrase; vector-only loses on exact-token queries (CIK numbers, ticker symbols). RRF (reciprocal rank fusion) is the literature consensus combiner. We do not LLM-rerank yet — measure recall first.

**GPU vs CPU inference.** CPU for ingest, GPU optional. Throughput at our document volume (~10K docs/day) is fine on a single 16-core box. The GPU question opens up only if we backfill 5+ years of transcripts in a hurry.

**Three timestamps, never two.** `event_ts`, `publish_ts`, `ingest_ts`. Joining on the wrong one is the most common PIT error. The default join column for sentiment features is `available_at = max(publish_ts, ingest_ts)`. The `event_ts` is reserved for event-study analysis.

**Entity linking via dictionary + NER + reranker.** Pure NER is too noisy ("Apple" — fruit or company?). Dictionary alone misses paraphrases ("the iPhone-maker"). The pattern: NER proposes, dictionary confirms, a small reranker (gradient-boosted on context features) handles ambiguous cases. Confidence threshold tunable; <0.7 mentions are dropped.

**Topic model cadence.** Re-fit BERTopic every 30 days on a 90-day window. New `model_run_id` on every refit; never overwrite. Topic drift is then a first-class observable, not a silent change.

---

## 10. Risks, Failure Modes & Mitigations

| Risk | Mitigation |
|---|---|
| Naive sentiment trading hits crowded trades | Treat sentiment as a *feature*, not a signal; combined with quant signals in Phase 7 ensemble |
| Entity ambiguity (Apple Inc / fruit) | Dictionary + NER + context reranker; confidence threshold |
| Reddit/X ToS changes | Subreddit/handle allowlist; backup on RSS+EDGAR; legal review before adding sources |
| Late-arriving documents pollute backtests | `available_at = max(publish_ts, ingest_ts)`; backtest joins on this column only |
| News story leak (article timestamped before write) | Captured by `event_ts` separation; flagged as anomaly if `event_ts > publish_ts` |
| Model drift (FinBERT trained 2019) | Track inter-model agreement on a held-out current sample; alert if drift > threshold |
| PII in user-generated content | Hash usernames; redaction pass before storage; never store DMs even if accessible |
| Hallucinated entities from NER | Confidence threshold + dictionary cross-check |
| Rate-limit lockout | Exponential backoff; per-source circuit breaker; vendor-aware quota tracking |
| Topic instability across refits | Topic alignment via embedding centroid matching; expose `model_run_id` to consumers |
| Earnings transcript license breach | Vendor-only ingest; no scraping of paywalled sources |

---

## 11. Testing Strategy

**PIT property tests.** Generate documents with arbitrary `(event_ts, publish_ts, ingest_ts)`; assert no feature value at `as_of_ts = T` ever uses a doc with `available_at > T`.

**Entity linking benchmark.** 500-mention labelled set covering ambiguous cases. Accuracy ≥ 92%, F1 ≥ 0.90.

**Sentiment fixture.** 200 hand-labelled finance sentences; FinBERT accuracy must be within 3% of the original paper's published number.

**Embedding consistency.** Hash-pin embeddings; same text + same model version = same vector across runs (deterministic seeds).

**Topic stability.** Re-fit on slightly perturbed window; ≥ 70% topic-vocabulary overlap with previous run (else drift alert).

**RAG retrieval recall.** Curated query set (50 questions, gold passages); BM25 alone, vector alone, RRF combined; assert RRF ≥ best of either by ≥ 5%.

**Time-zone discipline.** All timestamps stored UTC; convert at edges only; explicit test for SEC filings published in EST.

---

## 12. Observability Hooks

- `altdata_docs_ingested_total{source}` counter.
- `altdata_pipeline_lag_seconds{stage}` histogram (cleaner, ner, sentiment, embed, topic).
- `nlp_inference_latency_ms{model}` histogram.
- `entity_link_confidence` distribution; alert on shift.
- `sentiment_score_distribution` per ticker bucket.
- `rag_query_latency_ms`, `rag_recall_at_k` (sampled offline).
- `topic_model_drift_score` per re-fit.
- `pit_violation_alerts_total` (must stay 0).

---

## 13. Definition of Done

- [ ] All five sources ingesting in dev compose; outbox + DLQ wired.
- [ ] NLP pipeline batch + streaming modes both green.
- [ ] Entity linking benchmark passes 92% accuracy.
- [ ] FinBERT sentiment within 3% of paper benchmarks.
- [ ] Topic model re-fit cadence automated; drift dashboard live.
- [ ] pgvector + BM25 hybrid retrieval API live; recall@10 > BM25-alone by ≥ 5%.
- [ ] PIT red-team suite green.
- [ ] AAPL sentiment-divergence dashboard demo working with last 12 months of data.
- [ ] Per-ticker daily sentiment, topic, embedding features available in feature store.
- [ ] PII redaction verified on Reddit + X samples.

---

## 14. Interview Talking Points

- **Why naive sentiment lost its alpha.** Most retail-accessible sentiment is priced in by the time you read it. The work now is in *combinations* (sentiment × earnings surprise × short interest) and *narrative shifts*, not absolute polarity.
- **The three-timestamp discipline.** Most amateur sentiment systems backtest with `publish_ts`, leaking ingestion latency. We separate `event_ts` (when it happened), `publish_ts` (when it was published), and `available_at` (when *we* could have seen it). Backtests use `available_at`.
- **Entity linking is the unsexy 80%.** "Apple" vs the fruit, "T" vs the letter — most teams gloss this and get garbage.
- **Hybrid retrieval (BM25 + vector + RRF).** Reciprocal-rank fusion is robust across query types. Pure-dense retrieval loses on exact tokens (CIKs).
- **Topic models as drift monitors.** BERTopic refits expose narrative drift — when the topic vocabulary moves, the regime is moving with it.
- **PII discipline at ingest.** Hashed usernames, no DMs, license-aware ingestion. The legal failure mode kills startups, not the technical one.

---

## 15. Open Questions

1. X partner-API budget — confirm with user.
2. Earnings-transcript vendor — Refinitiv vs S&P CapIQ; pricing-driven decision.
3. Should we add Stocktwits in week 17? Lean no; Reddit + X covers the same space with better signal/noise.
4. LLM rerank on top of RRF — measure recall lift before adding cost.
5. Topic alignment across refits — embedding-centroid match works in practice but breaks under regime change. Open question: fall back to manual labels?

---

## Scope Mode: 2-Year Resume + Self-Sustaining Trading

Phase 5 is where the original plan's costs balloon (X partner API at $100+/mo, NewsAPI commercial at $449/mo, paid transcript vendors). Scope mode rebuilds the alt-data tier on free sources only.

**Source priority (revised)**

| Source | Status | Notes |
|---|---|---|
| Reddit (PRAW) | Keep | Free, register an app, rate-limited but workable |
| SEC EDGAR | Keep | Free, full-text filings + 8-K stream |
| RSS news feeds | Keep | Bloomberg, Reuters, WSJ headlines, FT — free; HTML scraping for body where allowed |
| GDELT | Keep | Free firehose of news events; coarse but global |
| X / Twitter | **Drop** | Basic tier $100/mo is real money; signal/cost ratio doesn't justify in scope mode |
| NewsAPI commercial | **Drop** | RSS + GDELT cover it |
| Earnings transcripts (paid) | **Drop** | Use Seeking Alpha public transcripts (legal grey, scrape with care) or skip; document the gap |
| Stocktwits | **Drop** | Reddit covers the same niche |

**Models**

- **FinBERT** — runs on CPU, slow but free; cache aggressively. GPU optional.
- **Sentence-transformers (BGE-large or E5)** — local, free, no API. Replaces Voyage / Cohere embeddings. Quality is 90%+ of paid embeddings on the financial corpus that matters here.
- **NER (spaCy + custom ticker dictionary)** — local, free.
- **BERTopic** — local, free.

**What stays (resume-load-bearing)**

- Three-timestamp PIT discipline, entity-linking accuracy bar, sentiment time-series as features, news-impact event study, divergence-detector demo. These are the talking points; keep them.

**Budget impact:** $0/mo for data + models. The full plan's $500–800/mo of paid alt-data spend is descoped.
