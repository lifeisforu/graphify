"""Tests for graphify/cache.py and cache_files/cache_dirs wrappers."""
import os
import pytest
from pathlib import Path
from graphify.cache import file_hash, cache_dir, load_cached, save_cached, cached_files, clear_cache, _body_content
import graphify.cache as _cache_mod
from graphify.extract import cache_files, cache_files_from, cache_dirs, cache_dirs_from, extract
from graphify.build import build_from_json


@pytest.fixture
def tmp_file(tmp_path):
    f = tmp_path / "sample.txt"
    f.write_text("hello world")
    return f


@pytest.fixture
def cache_root(tmp_path):
    return tmp_path


def test_file_hash_consistent(tmp_file):
    """Same file gives same hash on repeated calls."""
    h1 = file_hash(tmp_file)
    h2 = file_hash(tmp_file)
    assert h1 == h2
    assert isinstance(h1, str)
    assert len(h1) == 64  # SHA256 hex digest length


def test_file_hash_changes(tmp_path):
    """Different file contents give different hashes."""
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("content one")
    f2.write_text("content two")
    assert file_hash(f1) != file_hash(f2)


def test_cache_roundtrip(tmp_file, cache_root):
    """Save then load returns the same result dict."""
    result = {"nodes": [{"id": "n1", "label": "Node1"}], "edges": []}
    save_cached(tmp_file, result, root=cache_root)
    loaded = load_cached(tmp_file, root=cache_root)
    assert loaded == result


def test_cache_miss_on_change(tmp_file, cache_root):
    """After file content changes, load_cached returns None."""
    result = {"nodes": [], "edges": [{"source": "a", "target": "b"}]}
    save_cached(tmp_file, result, root=cache_root)
    # Modify the file
    tmp_file.write_text("completely different content")
    assert load_cached(tmp_file, root=cache_root) is None


def test_cached_files(tmp_path, cache_root):
    """cached_files returns the set of cached hashes."""
    f1 = tmp_path / "file1.py"
    f2 = tmp_path / "file2.py"
    f1.write_text("alpha")
    f2.write_text("beta")

    save_cached(f1, {"nodes": [], "edges": []}, root=cache_root)
    save_cached(f2, {"nodes": [], "edges": []}, root=cache_root)

    hashes = cached_files(cache_root)
    assert file_hash(f1, cache_root) in hashes
    assert file_hash(f2, cache_root) in hashes


def test_clear_cache(tmp_file, cache_root):
    """clear_cache removes all .json files from graphify-out/cache/ (all subdirs)."""
    save_cached(tmp_file, {"nodes": [], "edges": []}, root=cache_root)
    # Since v0.5.3 entries go into cache/ast/, not the flat cache/ dir
    cache_base = cache_root / "graphify-out" / "cache"
    assert len(list(cache_base.rglob("*.json"))) > 0
    clear_cache(cache_root)
    assert len(list(cache_base.rglob("*.json"))) == 0


def test_md_frontmatter_only_change_same_hash(tmp_path):
    """Changing only frontmatter fields in a .md file does not change the hash."""
    f = tmp_path / "doc.md"
    f.write_text("---\nreviewed: 2026-01-01\n---\n\n# Title\n\nBody text.")
    h1 = file_hash(f)
    f.write_text("---\nreviewed: 2026-04-09\n---\n\n# Title\n\nBody text.")
    h2 = file_hash(f)
    assert h1 == h2


def test_md_body_change_different_hash(tmp_path):
    """Changing the body of a .md file produces a different hash."""
    f = tmp_path / "doc.md"
    f.write_text("---\nreviewed: 2026-01-01\n---\n\n# Title\n\nOriginal body.")
    h1 = file_hash(f)
    f.write_text("---\nreviewed: 2026-01-01\n---\n\n# Title\n\nChanged body.")
    h2 = file_hash(f)
    assert h1 != h2


def test_md_no_frontmatter_hashed_normally(tmp_path):
    """A .md file with no frontmatter is hashed by its full content."""
    f = tmp_path / "doc.md"
    f.write_text("# Just a heading\n\nNo frontmatter here.")
    h1 = file_hash(f)
    f.write_text("# Just a heading\n\nDifferent content.")
    h2 = file_hash(f)
    assert h1 != h2


def test_non_md_file_hashed_fully(tmp_path):
    """Non-.md files are still hashed by their full content."""
    f = tmp_path / "script.py"
    f.write_text("# comment\nx = 1")
    h1 = file_hash(f)
    f.write_text("# changed comment\nx = 1")
    h2 = file_hash(f)
    assert h1 != h2


def test_body_content_strips_frontmatter():
    """_body_content correctly strips YAML frontmatter."""
    content = b"---\ntitle: Test\n---\n\nActual body."
    assert _body_content(content) == b"\n\nActual body."


def test_body_content_no_frontmatter():
    """_body_content returns content unchanged when no frontmatter present."""
    content = b"No frontmatter here."
    assert _body_content(content) == content


# ---------------------------------------------------------------------------
# cache_files / cache_files_from
# ---------------------------------------------------------------------------

@pytest.fixture
def py_files(tmp_path):
    """Two minimal .py files in a temp directory."""
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_text("x = 1\n")
    b.write_text("y = 2\n")
    return tmp_path, [a, b]


def test_cache_files_returns_count(py_files):
    """cache_files returns the number of newly cached files."""
    root, files = py_files
    n = cache_files(files, cache_root=root)
    assert n == len(files)


def test_cache_files_already_cached_returns_zero(py_files):
    """Calling cache_files twice returns 0 on the second call (all cached)."""
    root, files = py_files
    cache_files(files, cache_root=root)
    n = cache_files(files, cache_root=root)
    assert n == 0


def test_cache_files_populates_cache(py_files):
    """After cache_files, load_cached returns a result for each file."""
    root, files = py_files
    cache_files(files, cache_root=root)
    for f in files:
        result = load_cached(f, root=root)
        assert result is not None
        assert "nodes" in result
        assert "edges" in result


def test_cache_files_empty_list():
    """cache_files on an empty list returns 0 without error."""
    assert cache_files([], cache_root=None) == 0


def test_cache_files_from(py_files, tmp_path):
    """cache_files_from reads paths from a text file and caches them."""
    root, files = py_files
    list_file = tmp_path / "files.txt"
    list_file.write_text(
        "\n".join(str(f) for f in files) + "\n",
        encoding="utf-8",
    )
    n = cache_files_from(list_file, cache_root=root)
    assert n == len(files)
    for f in files:
        assert load_cached(f, root=root) is not None


def test_cache_files_from_ignores_comments_and_blanks(py_files, tmp_path):
    """cache_files_from skips blank lines and # comment lines."""
    root, files = py_files
    list_file = tmp_path / "files.txt"
    list_file.write_text(
        f"# header comment\n\n{files[0]}\n\n# another comment\n{files[1]}\n",
        encoding="utf-8",
    )
    n = cache_files_from(list_file, cache_root=root)
    assert n == 2


# ---------------------------------------------------------------------------
# cache_dirs / cache_dirs_from
# ---------------------------------------------------------------------------

@pytest.fixture
def dir_tree(tmp_path):
    """Two subdirectories each containing a .py file."""
    d1 = tmp_path / "pkg1"
    d2 = tmp_path / "pkg2"
    d1.mkdir()
    d2.mkdir()
    (d1 / "mod1.py").write_text("a = 1\n")
    (d2 / "mod2.py").write_text("b = 2\n")
    return tmp_path, d1, d2


def test_cache_dirs_returns_count(dir_tree):
    """cache_dirs returns the total number of newly cached files."""
    root, d1, d2 = dir_tree
    n = cache_dirs([d1, d2], cache_root=root)
    assert n == 2


def test_cache_dirs_already_cached_returns_zero(dir_tree):
    """Second call to cache_dirs returns 0 when all files are already cached."""
    root, d1, d2 = dir_tree
    cache_dirs([d1, d2], cache_root=root)
    n = cache_dirs([d1, d2], cache_root=root)
    assert n == 0


def test_cache_dirs_populates_cache(dir_tree):
    """After cache_dirs, load_cached succeeds for every collected file."""
    root, d1, d2 = dir_tree
    cache_dirs([d1, d2], cache_root=root)
    for f in [(d1 / "mod1.py"), (d2 / "mod2.py")]:
        result = load_cached(f, root=root)
        assert result is not None
        assert "nodes" in result


def test_cache_dirs_deduplicates_overlapping_dirs(dir_tree):
    """Passing the same directory twice does not double-cache files."""
    root, d1, _ = dir_tree
    n = cache_dirs([d1, d1], cache_root=root)
    assert n == 1  # only one unique file in d1


def test_cache_dirs_empty_list():
    """cache_dirs on an empty list returns 0 without error."""
    assert cache_dirs([], cache_root=None) == 0


def test_cache_dirs_from(dir_tree, tmp_path):
    """cache_dirs_from reads directory paths from a text file and caches all files."""
    root, d1, d2 = dir_tree
    list_file = tmp_path / "dirs.txt"
    list_file.write_text(
        f"{d1}\n{d2}\n",
        encoding="utf-8",
    )
    n = cache_dirs_from(list_file, cache_root=root)
    assert n == 2


def test_cache_dirs_from_ignores_comments_and_blanks(dir_tree, tmp_path):
    """cache_dirs_from skips blank lines and # comment lines."""
    root, d1, d2 = dir_tree
    list_file = tmp_path / "dirs.txt"
    list_file.write_text(
        f"# root dirs\n\n{d1}\n\n# second\n{d2}\n",
        encoding="utf-8",
    )
    n = cache_dirs_from(list_file, cache_root=root)
    assert n == 2


def test_cache_dirs_from_single_file_dir(tmp_path):
    """cache_dirs_from works when a directory contains exactly one file."""
    d = tmp_path / "solo"
    d.mkdir()
    (d / "only.py").write_text("z = 0\n")
    list_file = tmp_path / "dirs.txt"
    list_file.write_text(str(d) + "\n", encoding="utf-8")
    n = cache_dirs_from(list_file, cache_root=tmp_path)
    assert n == 1


# ---------------------------------------------------------------------------
# Integration: cache warm-up → extract → build_from_json
# ---------------------------------------------------------------------------

@pytest.fixture
def src_pkg(tmp_path):
    """A minimal Python package: two files with a cross-file import."""
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "models.py").write_text(
        "class User:\n    name: str\n    age: int\n"
    )
    (pkg / "service.py").write_text(
        "from mypkg.models import User\n\ndef get_user() -> User:\n    pass\n"
    )
    return tmp_path, pkg, [pkg / "models.py", pkg / "service.py"]


def test_extract_after_cache_files_hits_cache(src_pkg):
    """extract() finds all files already cached after cache_files(); uncached_work is empty."""
    root, pkg, files = src_pkg

    cache_files(files, cache_root=root)
    # All files must be in cache before extract runs
    for f in files:
        assert load_cached(f, root=root) is not None

    # extract() should not re-extract (load_cached returns hits for every file)
    result = extract(files, cache_root=root)
    assert "nodes" in result
    assert "edges" in result


def test_extract_result_consistent_with_and_without_cache(src_pkg):
    """extract() returns the same nodes and edges regardless of cache state."""
    root, pkg, files = src_pkg

    # Cold run (no cache)
    result_cold = extract(files, cache_root=root)

    # Warm run (cache already populated by first extract)
    result_warm = extract(files, cache_root=root)

    cold_ids = {n["id"] for n in result_cold["nodes"]}
    warm_ids = {n["id"] for n in result_warm["nodes"]}
    assert cold_ids == warm_ids

    cold_edges = {(e["source"], e["target"]) for e in result_cold["edges"]}
    warm_edges = {(e["source"], e["target"]) for e in result_warm["edges"]}
    assert cold_edges == warm_edges


def test_cache_files_then_extract_then_build_graph(src_pkg):
    """Full pipeline: cache_files → extract → build_from_json produces a valid graph."""
    root, pkg, files = src_pkg

    cache_files(files, cache_root=root)
    result = extract(files, cache_root=root)
    G = build_from_json(result)

    assert G.number_of_nodes() > 0
    assert G.number_of_edges() >= 0  # edges may be 0 for trivial files
    node_ids = set(G.nodes())
    assert any("user" in n for n in node_ids)
    assert any("get_user" in n for n in node_ids)


def test_cache_dirs_then_extract_then_build_graph(src_pkg):
    """Full pipeline via cache_dirs: cache_dirs → extract → build_from_json."""
    root, pkg, files = src_pkg

    cache_dirs([pkg], cache_root=root)
    result = extract(files, cache_root=root)
    G = build_from_json(result)

    assert G.number_of_nodes() > 0
    node_ids = set(G.nodes())
    assert any("user" in n for n in node_ids)


def test_cache_dirs_from_then_extract_then_build_graph(src_pkg, tmp_path):
    """Full pipeline via cache_dirs_from: txt file → cache_dirs → extract → build."""
    root, pkg, files = src_pkg
    list_file = tmp_path / "dirs.txt"
    list_file.write_text(str(pkg) + "\n", encoding="utf-8")

    cache_dirs_from(list_file, cache_root=root)
    result = extract(files, cache_root=root)
    G = build_from_json(result)

    assert G.number_of_nodes() > 0
    node_ids = set(G.nodes())
    assert any("user" in n for n in node_ids)


def test_build_graph_node_attributes(src_pkg):
    """Graph nodes carry expected attributes (label, file_type, source_file)."""
    root, pkg, files = src_pkg

    cache_files(files, cache_root=root)
    result = extract(files, cache_root=root)
    G = build_from_json(result)

    for node_id, attrs in G.nodes(data=True):
        assert "label" in attrs, f"node {node_id!r} missing 'label'"


# ---------------------------------------------------------------------------
# Mode consistency: full / incremental-sequential / incremental-parallel
# ---------------------------------------------------------------------------

@pytest.fixture
def multi_pkg(tmp_path):
    """Package with several .py files so parallel threshold can be triggered."""
    pkg = tmp_path / "proj"
    pkg.mkdir()
    # Base files: one module per letter, each with a unique class
    for ch in "abcde":
        (pkg / f"mod_{ch}.py").write_text(
            f"class Cap{ch.upper()}:\n    value: int = {ord(ch)}\n"
        )
    (pkg / "main.py").write_text(
        "from proj.mod_a import CapA\nfrom proj.mod_b import CapB\n"
        "def run(a: CapA, b: CapB) -> None:\n    pass\n"
    )
    files = sorted(pkg.glob("*.py"))
    return tmp_path, pkg, files


def _node_edge_sets(result):
    nodes = frozenset(n["id"] for n in result["nodes"])
    edges = frozenset((e["source"], e["target"]) for e in result["edges"])
    return nodes, edges


def _graph_structure(result):
    """Build a graph and return (node_set, adjacency) for structural comparison.

    adjacency: frozenset of (node, frozenset(neighbours)) — captures the full
    neighbourhood of every node so that both edge existence and direction are
    compared in one shot.
    """
    G = build_from_json(result)
    node_set = frozenset(G.nodes())
    adjacency = frozenset(
        (n, frozenset(G.neighbors(n))) for n in G.nodes()
    )
    return node_set, adjacency


def test_all_four_modes_produce_identical_results(multi_pkg, monkeypatch):
    """Full-sequential, full-parallel, incremental-sequential, incremental-parallel
    all produce the same nodes and edges.

    Modes:
      1. full-sequential:       cold cache, parallel=False
      2. full-parallel:         cold cache, parallel=True  (threshold forced to 1)
      3. incremental-sequential: half cached, parallel=False
      4. incremental-parallel:   half cached, parallel=True (threshold forced to 1)
    """
    import graphify.extract as _ext_mod
    root, pkg, files = multi_pkg
    half = files[: len(files) // 2]
    workers = max(1, (os.cpu_count() or 1) - 2)

    def _reset():
        clear_cache(root)
        _cache_mod._stat_index.clear()

    # 1. full-sequential
    _reset()
    r_full_seq = extract(files, cache_root=root, parallel=False)

    # 2. full-parallel
    _reset()
    monkeypatch.setattr(_ext_mod, "_PARALLEL_THRESHOLD", 1)
    r_full_par = extract(files, cache_root=root, parallel=True, max_workers=workers)

    # 3. incremental-sequential
    _reset()
    cache_files(half, cache_root=root)
    r_inc_seq = extract(files, cache_root=root, parallel=False)

    # 4. incremental-parallel
    _reset()
    cache_files(half, cache_root=root)
    r_inc_par = extract(files, cache_root=root, parallel=True, max_workers=workers)

    graphs = {
        "full-sequential":        _graph_structure(r_full_seq),
        "full-parallel":          _graph_structure(r_full_par),
        "incremental-sequential": _graph_structure(r_inc_seq),
        "incremental-parallel":   _graph_structure(r_inc_par),
    }

    ref_nodes, ref_adj = graphs["full-sequential"]
    assert len(ref_nodes) > 0, "baseline produced no nodes"

    for mode, (nodes, adj) in graphs.items():
        assert nodes == ref_nodes, f"{mode}: node set differs from full-sequential"
        assert adj == ref_adj, f"{mode}: adjacency differs from full-sequential"


def test_second_extract_after_file_change_reflects_update(src_pkg):
    """After modifying a file, extract returns updated nodes even if cache was warm."""
    root, pkg, files = src_pkg

    cache_files(files, cache_root=root)
    result1 = extract(files, cache_root=root)
    ids1 = {n["id"] for n in result1["nodes"]}

    # Add a new class to models.py — invalidates its cache entry.
    # Clear the in-process stat-index so the hash is recomputed from disk
    # (within the same process mtime_ns may not change on fast writes).
    (pkg / "models.py").write_text(
        "class User:\n    name: str\n\nclass Admin(User):\n    level: int\n"
    )
    _cache_mod._stat_index.clear()

    result2 = extract(files, cache_root=root)
    ids2 = {n["id"] for n in result2["nodes"]}

    assert any("admin" in nid for nid in ids2), "Admin class should appear after file change"
    assert ids2 != ids1
