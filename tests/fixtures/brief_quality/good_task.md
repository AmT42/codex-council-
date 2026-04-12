# Task

## Request

Debug why the sync job duplicates rows when a retry happens after partial success.

## Context

- The issue appears in the background sync worker, not the manual import flow.
- Preserve the current public API unless the fix requires a clearly justified schema or state change.

## Success Signal

The retry path no longer creates duplicate rows, the intended rows still sync successfully, and the relevant verification passes.
