-- CodeGraph-Sci project database (schema version in PRAGMA user_version, §3.6).
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);

-- Analysed content
CREATE TABLE files(id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, lang TEXT, variant TEXT,
                   sha256 TEXT, size INTEGER, mtime_ns INTEGER, encoding TEXT, parse_status TEXT,
                   adapter TEXT, adapter_version TEXT, error TEXT, cache_key TEXT);
CREATE TABLE inventory(file_id INTEGER NOT NULL, lang TEXT, variant TEXT, confidence REAL, decided_by TEXT);
-- Every discovered entry and what became of it; discovery problems (schema 2).
CREATE TABLE inventory_entries(path TEXT PRIMARY KEY, parent TEXT, kind TEXT NOT NULL, extension TEXT,
                               size INTEGER, files INTEGER, lang TEXT, variant TEXT, confidence REAL,
                               evidence TEXT, eligibility TEXT NOT NULL, status TEXT NOT NULL, reason TEXT,
                               link_target TEXT);
CREATE TABLE inventory_issues(path TEXT NOT NULL, kind TEXT NOT NULL, message TEXT);
CREATE TABLE nodes(id INTEGER PRIMARY KEY, uid TEXT UNIQUE NOT NULL, display_name TEXT, kind TEXT,
                   subtype TEXT, lang TEXT, file_id INTEGER, line_start INTEGER, line_end INTEGER,
                   in_scope INTEGER, attrs TEXT);
CREATE TABLE conditions(id INTEGER PRIMARY KEY, expr TEXT UNIQUE NOT NULL);
CREATE TABLE call_sites(id INTEGER PRIMARY KEY, src_node INTEGER, file_id INTEGER, line INTEGER,
                        col INTEGER, ref_kind TEXT, target_text TEXT, dst_node INTEGER,
                        resolution TEXT, confidence TEXT, origin TEXT, condition_id INTEGER,
                        evidence TEXT);  -- JSON, bridge resolutions only (schema 3)
CREATE TABLE call_site_candidates(site_id INTEGER NOT NULL, dst_node INTEGER NOT NULL);
CREATE TABLE data_accesses(id INTEGER PRIMARY KEY, src_node INTEGER, data_node INTEGER,
                           family_node INTEGER, mode TEXT, key_kind TEXT, file_id INTEGER,
                           line INTEGER, origin TEXT);
CREATE TABLE facts_cache(cache_key TEXT PRIMARY KEY, facts BLOB);

-- Precomputed for the interface (Index step)
CREATE TABLE edges(src INTEGER, dst INTEGER, kind TEXT, site_count INTEGER, min_confidence TEXT,
                   origins TEXT, conditions TEXT);
CREATE TABLE node_stats(node_id INTEGER PRIMARY KEY, fan_in INTEGER, fan_out INTEGER,
                        fan_in_filtered INTEGER, fan_out_filtered INTEGER, impact_size INTEGER,
                        impact_size_filtered INTEGER, is_noise INTEGER, noise_reason TEXT);
CREATE TABLE file_edges(src_file INTEGER, dst_file INTEGER, kind TEXT, count INTEGER);
CREATE TABLE dir_edges(src_dir TEXT, dst_dir TEXT, kind TEXT, count INTEGER);
CREATE VIRTUAL TABLE search_fts USING fts5(name, display, path, doc, node_id UNINDEXED,
                                           tokenize = "unicode61 tokenchars '_'");

-- Traceability
CREATE TABLE plugins(name TEXT, type TEXT, version TEXT);
CREATE TABLE scan_runs(id INTEGER PRIMARY KEY, started_at TEXT, finished_at TEXT, root TEXT,
                       git_rev TEXT, profile_version INTEGER, profile_sha256 TEXT, plugins TEXT,
                       stats TEXT);

-- Later lots
CREATE TABLE summaries(node_id INTEGER, content_hash TEXT, model_id TEXT, prompt_version TEXT, text TEXT);
CREATE TABLE layout_cache(key TEXT PRIMARY KEY, layout_version INTEGER, data TEXT);
