# Phase 7: dependency tables

Scope: Phase 7 of `codegraphtree_requirements_assessment_and_implementation_plan_EN.md` (§6, "Build dependency
tables"; requirements 6, 21, 24, 29). Base: Phase 6 working tree on `phase1/engine-reliability`. Decision: D33 in
`docs/architecture.md`.

## What exists now

| Need | Implementation |
| --- | --- |
| Paginated dependency query | `GraphQuery.dependencies(filters, sort, descending, limit, offset)`: one row per occurrence (call sites, and binding declarations that have no call site) |
| Row content | caller identifier, name, file and language; target text; resolved target, name, file and language; candidates; relationship; line and column; resolution; confidence; rule (origin); condition |
| Relationship types kept | `call`, `dynamic_call`, `import`, `include`, `inherit`, `bridge`, `binding`, `binding_declaration` (the graph tables keep their `calls`/`uses` aggregation; the table never collapses them) |
| SQLite filtering and sorting | text (caller, target, file), relationships, statuses, caller language, path prefix, caller, target, rule prefix; sort by path, line, caller, target, relationship, status, language, rule (ascending or descending); unknown keys are refused |
| Entity, file and directory views | `GraphQuery.dependency_groups(level, …)`: count and statuses per (source, target, relationship); each group carries the filter that lists its occurrences |
| Navigation to source evidence | `GraphQuery.dependency_evidence(row)`: source lines around the row and its evidence (extraction rule, resolution rule, mechanism, binding, candidate selection, reason) |
| Export | `cgs deps … --format csv|json [-o file]` (all pages of a filter, or aggregated levels); `Export CSV…` in the window |
| Desktop view | Explore › Dependencies: filters, level, sortable columns, pages of 200, double click: source in the inspector and evidence under the table, or the occurrences of an aggregated row; queries run in the background runner |

## Measurement

Synthetic code base (15,000 routines, 3,000 files, 121,387 rows), same machine:

| Query | Time |
| --- | --- |
| First page, path order | 0.34 s |
| Page at offset 20,000 | 0.31 s |
| Sorted by target, descending | 0.32 s |
| Text filter | 0.32 s |
| Relationship and status filter | 0.06 s |
| File groups | 0.89 s |
| Directory groups | 1.30 s |

Each page scans the whole table once (the rows are a union of call sites and binding declarations), so time grows
linearly with the number of sites; on a code base of a million sites, a page takes a few seconds, always off the
main thread.

## Plan requirements → tests

| Requirement | Test |
| --- | --- |
| Every relationship with its meaning (calls, imports, includes, bridges, bindings, binding declarations) | `test_every_relationship_is_a_row_with_its_meaning`, `test_binding_declarations_are_rows` |
| Filtering, sorting, paging in SQLite | `test_filters_sorting_and_paging_are_consistent` |
| Candidates of ambiguous rows | `test_ambiguous_rows_list_their_candidates` |
| Entity, file, directory views with occurrences reachable | `test_aggregated_views_keep_their_occurrences` |
| Navigate each row to source evidence | `test_rows_lead_to_their_source_evidence`, `test_row_opens_source_and_evidence_then_export` (UI) |
| Export a filtered table | `test_cli_exports_a_filtered_table`, `test_row_opens_source_and_evidence_then_export` (UI) |
| Table view | `test_table_filters_sorts_pages_and_drills_down` (UI) |

## Not covered by Phase 7

- Structural relationships that are not call sites or binding declarations (`dispatches` and `implements` from
  packs and generic interfaces, data accesses) are not rows of this table yet.
- The graph-level aggregates (`file_edges`, `dir_edges`) still use `calls`/`uses`; the 3D views (Phase 8) read the
  relationship types from the table queries.
