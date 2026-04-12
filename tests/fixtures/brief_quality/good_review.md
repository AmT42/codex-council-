# Review

## Findings

- Retry handling in the sync path appears to re-insert rows that were already persisted during the partial-success case.
- The current regression coverage does not exercise a retry after partial success.

## Context

- Repro: run the sync job, force a network error after the first persisted row, then retry the same batch.
- Suspect area: the background sync worker and any deduplication or checkpoint logic around batch retries.
