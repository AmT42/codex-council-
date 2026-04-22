# Definition of Done

- [ ] M1. Dashboard Summary Surface
  - [ ] M1.A1 Finance operators can see invoice health, totals, and retry-state summary from one dashboard view.
  - [ ] M1.A2 The page uses the intended billing read path instead of introducing an ad hoc state source.
  - [ ] M1.A3 The dashboard keeps the existing route names and auth boundaries intact.
- [ ] M2. Retry-State Visibility And Degraded Behavior
  - [ ] M2.A1 Recent failed retries are visible on the main dashboard path.
  - [ ] M2.A2 If retry-state details are unavailable, the main billing summary still renders and the retry panel shows an explicit degraded-state notice.
  - [ ] M2.A3 The dashboard does not surface stale retry counts that drift from the billing source of truth.
- [ ] M3. Validation And Approval Guardrails
  - [ ] M3.A1 Automated verification covers the changed summary and retry-state rendering.
  - [ ] M3.A2 Manual validation is defined for the primary finance-operator workflow.
  - [ ] M3.A3 No known adjacent regression remains in the touched billing read path or degraded retry-state path.
