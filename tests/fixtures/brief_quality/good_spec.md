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

The dashboard shows invoice summary metrics, recent failed retries, and the current state of key billing flows in a way that lets an operator identify and investigate issues quickly.

## Technical Boundaries

- Reuse the existing billing domain model and repository patterns
- Keep API compatibility for current consumers
- Prefer incremental UI changes over a navigation rewrite

## Validation Expectations

Relevant automated verification must cover the changed behavior, and the final UI should be manually checked for the primary finance workflow.

## Open Questions

- None at the moment
