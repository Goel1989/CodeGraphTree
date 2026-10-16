"""3D view of the connections between functions and files (3d-force-graph in a PyWebView window).

Runs in its own process (``cgs view3d``): PyWebView has its own GUI loop. No HTTP server, no port:
the page and its JavaScript are local files, data is embedded, the Python <-> JS bridge is ``js_api``.
"""
