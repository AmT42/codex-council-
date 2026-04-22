# Spec

## Goal

Implement a reliable billing dashboard that summarizes invoice status without changing the existing public API surface.

## User Outcome

Finance operators can review invoice health, totals, and retry state from one dashboard without needing to inspect raw logs.

## In Scope

- Add a billing dashboard page
- Reuse existing billing data sources where possible
- Surface retry and failure state clearly

## Out of Scope

- No changes to invoice generation rules
- No redesign of unrelated admin navigation

## Constraints

- Preserve existing route names and auth boundaries
- Avoid introducing background jobs unless the current data path is insufficient

## Existing Context

There is already a billing area and invoice data model, but visibility into retry state is fragmented across logs and separate admin surfaces.

## Desired Behavior

## M1. Dashboard Summary Surface

The dashboard shows invoice summary metrics and the current state of key billing flows in a way that lets an operator identify issues quickly.

### Acceptance Criteria
- A1. Finance operators can see invoice health, totals, and retry-state summary from one dashboard view.
- A2. The page uses the intended billing read path instead of introducing an ad hoc state source.
- A3. The dashboard keeps the existing route names and auth boundaries intact.

## M2. Retry-State Visibility And Degraded Behavior

The dashboard exposes recent failed retries clearly without making the whole page fail when retry-state data is missing temporarily.

### Acceptance Criteria
- A1. Recent failed retries are visible on the main dashboard path.
- A2. If retry-state details are unavailable, the main billing summary still renders and the retry panel shows an explicit degraded-state notice.
- A3. The dashboard does not surface stale retry counts that drift from the billing source of truth.

## M3. Validation And Approval Guardrails

This work is only approvable if the changed user-visible path is validated and the touched subsystem remains clean.

### Acceptance Criteria
- A1. Automated verification covers the changed summary and retry-state rendering.
- A2. Manual validation is defined for the primary finance-operator workflow.
- A3. No known adjacent regression remains in the touched billing read path or degraded retry-state path.

### Source of Truth / Ownership

The existing billing tables and retry-state records remain the source of truth. The dashboard only reads derived aggregates and must not introduce a parallel billing state store.

### Read Path

The page should load through the existing billing service and repository layer, using the current retry-state queries instead of scraping logs or adding ad hoc data fetches.

### Write Path / Mutation Flow

Not applicable because this dashboard is read-only and should not create or mutate billing state.

### Runtime / Performance Expectations

The page should reuse existing query paths and avoid per-row N+1 fetches. It should not require a new background materialization step for the first implementation.

### Failure / Fallback / Degraded Behavior

If retry-state details are temporarily unavailable, the dashboard should still render the main billing summary and show an explicit degraded-state notice for the missing retry panel instead of failing the whole page.

### State / Integrity / Concurrency Invariants

The dashboard must not change invoice generation semantics, route compatibility, or auth boundaries, and it must not surface stale retry counts that can drift from the billing source of truth.

### Observability / Validation Hooks

Automated verification should cover the changed summary and retry-state rendering, and the final implementation should keep enough explicit UI state or response structure that a reviewer can falsify degraded-path behavior.

## Technical Boundaries

- Reuse the existing billing domain model and repository patterns
- Keep API compatibility for current consumers
- Prefer incremental UI changes over a navigation rewrite

## Validation Expectations

Relevant automated verification must cover the changed behavior, and the final UI should be manually checked for the primary finance workflow.

## Open Questions

- None at the moment
