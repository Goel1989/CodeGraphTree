# UI audit: corrections

Scope: the nine findings of the user-interface audit of October 18, 2026 (`ui_audit_2026-10-18.md`, UI-01 to
UI-09), on branch `ui/audit-fixes`. Each finding has a non-regression test in `tests/ui/test_ui_audit_fixes.py`;
every test failed before the correction.

| Priority | Finding | Cause | Correction | Test |
| --- | --- | --- | --- | --- |
| P1 | Window too wide (minimum measured at 2,370 px), graph controls overlapping | One-row toolbars (graph, dependency table), labels that never shrink (title bar, header, status, hero card, inventory), a long checkbox text; fixed positions of the panels inside the 3D page | Toolbars on several rows, compact combo boxes, shrinkable labels (`shell.elastic`), short checkbox text with a tooltip; the 3D page uses four bounded zones (left column, legend, details, status line) | `test_window_fits_a_small_screen_with_a_project_loaded` (minimum ≤ 1,100 px with long texts; 974 px measured without project, 1,704 before), `test_graph_page_controls_never_overlap` (1,400, 900 and 600 px) |
| P1 | Previous selection and source still shown after a project change | Nothing was reset; late answers of the previous project's queries were still applied | `_clear_project_state`: queries of the previous project dropped, inspector, callers/callees, hero card, results, files, call tree, graphs, dependency table, inventory and health cleared | `test_project_change_clears_the_previous_selection` |
| P1 | Cancel kills the main process but not its descendants | Extraction workers never watched their parent; Cancel killed one process | Workers exit as soon as their parent disappears (`extract_pool`, watchdog thread); Cancel kills the process tree (`taskkill /T` on Windows, process group on POSIX) | `test_cancel_stops_the_whole_process_tree`, `test_cancel_kills_the_command_and_its_children` |
| P2 | Call tree queries on the GUI thread | `CallTreeModel` held a database connection and queried in `fetchMore` | Pages loaded by the query runner and inserted when they arrive ("loading…" meanwhile); the model holds no connection | `test_call_tree_never_queries_on_the_gui_thread`, `test_lazy_tree_and_navigation` |
| P2 | Link evidence loaded in a hidden view, inconsistent filters | The Dependencies view was filled without being shown; its widgets kept older values and replaced the link filter on the next change | A link click shows the Dependencies view; the link is a scope ("Link: A -> B", **Clear**, **Back to the graph**) refined, never replaced, by the widgets, which start from "All" | `test_link_evidence_is_shown_with_consistent_filters` |
| P2 | Overestimated confidence | The routine row of the callers/callees lists took the strongest confidence of its sites | The weakest confidence of the sites is shown (`weakest_confidence`) | `test_the_weakest_confidence_of_a_routine_is_shown` |
| P2 | Failures leaving the UI blocked or "Analysis in progress" | A failed command showed nothing in some cases; a command that could not start never sent `finished`; some queries had no error handler | Every failure ends with "… failed: reason" and a message, buttons re-enabled; a command that cannot start is reported as a failure; a cancellation (including by a project change) is reported as such, without an error dialog | `test_failed_command_unblocks_the_interface`, `test_command_that_cannot_start_unblocks_the_interface` |
| P2 | Counters and badges with different filters | Badges and summary counted before the panel filters, tabs after | Badges, tabs and summary count the routines the lists show; the summary adds "of N before the filters" | `test_badges_and_summary_count_what_the_lists_show` |
| P2 | Main actions not reachable by keyboard, without accessible names | Rail, hero and title-bar buttons had no focus and no name | Focusable with Tab, accessible names on every icon button and on the table controls; shortcuts Ctrl+F (search), F5 (analyze), Shift+F5 (cancel), Alt+1 / Alt+2 (Explore / Project), Ctrl+O | `test_main_actions_are_reachable_by_keyboard_and_named` |

Details of the report also corrected:

| Report item | Correction | Test |
| --- | --- | --- |
| UI-02: `QueryRunner.cancel_all()` reset the generations, so an answer of a request made before a cancellation could be accepted by a new request with the same key | Generations only grow | `test_cancelled_queries_never_come_back` |
| UI-03: the window-close path left the analysis running | Closing the window stops the command and its process tree | `test_closing_the_window_stops_the_analysis` |
| UI-05: the relationship type of a clicked link was ignored | The link type selects its relationship types (per level: entity links keep each type, file and folder links aggregate them) | `test_link_evidence_respects_the_relationship_type` |
| UI-08, UI-09: filters that look global; no shortcut | The popover and its button say "Filters of the Callers / Callees panel"; Ctrl+Shift+F opens it | `test_panel_filters_say_what_they_apply_to` |
| Additional: the graph-local search did not notify the selection | A node found by the graph search becomes the selection (inspector, hero card) | covered by the page script |

Test infrastructure: modal message boxes are recorded instead of shown in every test (`tests/conftest.py`), so a
dialog can never block an offscreen run.

## Not covered

- Cancellation kills the process tree and the workers exit with their parent; a cooperative cancellation channel
  between the window and `cgs scan` (UI-03, "request cooperative cancellation") is not implemented. The previous
  database stays valid because writes are atomic (temporary file and replace, or one transaction).
- UI-08: the graph and the call tree are not filtered by the confidence, AI and ambiguity filters; the filters are
  labelled as belonging to the Callers / Callees panel instead.
- UI-01 acceptance at 125 % and 150 % scaling, and the additional UX recommendations (line numbers, empty/loading
  states, layout persistence, health summary) were not done.

- The tests check sizes, state and page layout offscreen; a visual check on a real screen (including high-DPI
  scaling) remains a manual step.
- Accessibility was checked through names and focus, not with a screen reader.
