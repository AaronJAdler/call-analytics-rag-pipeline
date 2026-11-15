# 6. Tenant isolation by construction

- Status: Accepted
- Date: 2026-11-14

## Context

Three businesses share one index. One business seeing another's customer calls is the worst
failure this system has. Calls at different companies sound alike ("And the best number to
reach you?"), so an unfiltered similarity search crosses tenants readily.

## Decision

- `search(tenant_id, query, k)` requires the tenant. No pipeline or command-line method
  searches across tenants.
- The tenant id is validated against `^[A-Za-z0-9_-]{1,64}$` before it is placed in the filter
  expression. Anything else raises.
- The filter is a pre-filter: rows are restricted to the tenant, then the nearest k are taken.
- Results are checked again on the way out. A row from another tenant raises instead of being
  returned.
- Ties in distance are broken by chunk id, so results are the same on every run.

## Consequences

- In the evaluation, 600 searches return 0 chunks from another tenant.
- Without the filter, 125 of those 600 searches (21%) would have had another tenant's chunk in
  the top 5. The filter is doing real work, not guarding against something that never happens.
- A tenant with one call still gets results from its own call (tested). A post-filter would
  take the top k overall and return nothing for a small tenant.
- Five malformed tenant ids, including `x' OR '1'='1`, are rejected (tested).
- `search_unfiltered` exists for the evaluation's "what if" number only, and is named so that
  a reviewer would notice it being called.
- Isolation depends on every caller going through `Index`. Someone opening the LanceDB
  directory directly can read everything.

## Alternatives considered

- **A table per tenant**: stronger separation and simple deletion of a whole tenant, with more
  tables to manage and no cross-tenant maintenance in one pass. The better choice with few,
  large tenants or contractual separation.
- **Post-filtering**: simpler with approximate indexes, and it starves small tenants.
