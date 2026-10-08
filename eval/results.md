Corpus: 42 pages, 112 passages. Embedder: BAAI/bge-small-en-v1.5.
Queries: 59 labelled (24 keyword, 35 natural-language).

| Queries | Method | nDCG@10 | MRR@10 | Recall@5 |
|---|---|---|---|---|
| all (59) | Hybrid (RRF) | 0.848 | 0.830 | 0.941 |
| all (59) | BM25 | 0.819 | 0.808 | 0.881 |
| all (59) | Semantic (embeddings) | 0.840 | 0.832 | 0.873 |
| keyword (24) | Hybrid (RRF) | 0.982 | 1.000 | 1.000 |
| keyword (24) | BM25 | 0.979 | 0.979 | 1.000 |
| keyword (24) | Semantic (embeddings) | 0.956 | 1.000 | 1.000 |
| natural (35) | Hybrid (RRF) | 0.755 | 0.713 | 0.900 |
| natural (35) | BM25 | 0.709 | 0.691 | 0.800 |
| natural (35) | Semantic (embeddings) | 0.761 | 0.716 | 0.786 |
