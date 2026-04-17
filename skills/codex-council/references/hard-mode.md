# Hard Mode

## Purpose

`hard` mode is the strict planning posture for work that needs unusually rigorous specs.

It belongs to the planning stage, not the execution loop.

## What it means

`hard` mode means:

- decision-complete specs
- explicit treatment of relevant product interfaces
- no hidden assumptions
- no vague contract language
- no important omitted dimensions

It does **not** mean:

- maximize length for its own sake
- include irrelevant sections without reason
- turn every small task into a giant architecture document

## When to use it

Prefer `hard` mode when the task is:

- agentic or prompt-driven
- tool/schema-heavy
- workflow-heavy
- operationally risky
- unusually broad
- sensitive to approvals, sandboxing, evaluator behavior, or state integrity

## Approval bar

In `hard` mode:

- every relevant review dimension must pass
- `uncertain` blocks approval
- omitted relevant sections are failures
- specs that leave policy to the execution council are not approvable
