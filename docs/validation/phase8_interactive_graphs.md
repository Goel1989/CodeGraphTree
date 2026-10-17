# Phase 8: interactive 3D visualization

Scope: Phase 8 of `codegraphtree_requirements_assessment_and_implementation_plan_EN.md` (§6, "Implement genuine
interactive 3D visualization"; requirements 1, 7–8, 21, 24). Base: Phase 7 working tree on
`phase1/engine-reliability`. Decision: D34 in `docs/architecture.md` (D21 chose the renderer, D23 the overview).

## Findings on the base

The plan's assessment ("existing graph rendering is 2D") predates decision D21: the entity and file graphs were
already drawn in 3D (3d-force-graph 1.80.1 with three.js, vendored, in a `QWebEngineView`). D21 recorded the
prototype criteria the plan asks for: offline packaging (inline vendored script, CSP without network source,
request interceptor), node picking (click, right-click, link click), readable text (labels on hover, details panel,
search), performance on modest CPUs (cooldown, node limits, overview spheres). Phase 8 completes the contract and
the interactions.

## Renderer-neutral contract (`query.types.Graph3D`)

| Element | Fields |
| --- | --- |
| Nodes | `id`, `label`, `kind`, `lang`, `file`, `line`, `fan_in`, `fan_out`, `group` (folder), `in_scope`, `size`, `note` |
| Links | `source`, `target`, `kind` (type), `count`, `confidence`, `status` (resolved, ambiguous, external, out_of_scope), `cross_dir` |
| References | `GraphQuery.link_evidence(source, target)` → the dependency-table filter of the rows behind a link |
| Layout | `layout = {"version": 1, "algorithm": "force-directed", "dimensions": 3}`; positions are computed by the renderer |
| Level | `entity`, `file` or `directory` (`GraphQuery.graph3d_directories`) |

## Interactions

| Required | Where |
| --- | --- |
| Rotate, pan, zoom, reset, focus selection | Orbit controls; **Fit**; **Reset** (filters, grouping, selection, fit); click focuses the camera on a node |
| Select nodes and edges | Click a node (inspector, hero card), click a link (evidence) |
| Expand callers and callees | Right-click; depth and node limit controls |
| Filter types, languages, paths, statuses | Filter panel: link types, languages, link statuses, "path starts with" |
| Group by directory, file, module or class | **Group by** folder, language, module / class: colour plus a clustering force; spheres of the overview group connected components |
| Direction and relation type | Arrows, colour per type and per status |
| Open edge evidence | A link click lists its occurrences in Explore › Dependencies (the same rows and evidence as the table) and, for routines, in the inspector |
| Entity, file and directory levels | Functions 3D, Files 3D, **Folders 3D** |
| Cycles, disconnected components, multiple entry points | **cycles** (strongly connected components), overview spheres per component and isolated nodes, **entry points** (nodes with outgoing but no incoming link) |
| 2D alternative | **2D / 3D** switch (same renderer, two dimensions) |
| No `main` required, progressive loading, explicit limits | Overview of the whole project (D23); "From main" is optional; right-click expands; "Max nodes" control and a visible "limit reached" note |

## Plan requirements → tests

| Requirement | Test |
| --- | --- |
| Contract: nodes, links with status, groups, layout, level | `test_nodes_and_links_carry_the_contract`, `test_link_statuses` |
| Table and graph selections open the same evidence | `test_nodes_and_links_carry_the_contract` (every link → rows), `test_link_click_opens_the_same_evidence_as_the_table` (UI) |
| Directory level | `test_directory_level`, `test_directory_level_view` (UI) |
| No `main` needed | `test_library_without_main_is_navigable`, `test_cycles_and_entry_points_without_main` (UI) |
| 2D/3D, filters, grouping | `test_dimensions_filters_and_grouping` (UI) |
| Cycles and multiple entry points | `test_cycles_and_entry_points_without_main` (UI) |

## Not covered by Phase 8

- The tests check the state of the page (what is shown, filtered, grouped, detected), not pixels: the CI machine
  renders offscreen and may have no WebGL. A visual check on a desktop remains a manual step.
- Positions are not stored: two openings of the same graph give a similar but not identical layout.
- Text labels are shown on hover and in the details panel, not permanently on every node (readability on dense
  graphs).
