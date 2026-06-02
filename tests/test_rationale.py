"""Tests for rationale/docstring extraction in extract.py."""
import textwrap
from pathlib import Path
import pytest
from graphify.extract import extract_python, extract_cpp
from graphify.build import build_from_json


def _write_py(tmp_path: Path, code: str) -> Path:
    p = tmp_path / "sample.py"
    p.write_text(textwrap.dedent(code))
    return p


def test_module_docstring_extracted(tmp_path):
    path = _write_py(tmp_path, '''
        """This module handles authentication because legacy sessions were insecure."""
        def login(): pass
    ''')
    result = extract_python(path)
    rationale = [n for n in result["nodes"] if n.get("file_type") == "rationale"]
    assert len(rationale) >= 1
    assert any("authentication" in n["label"] for n in rationale)


def test_function_docstring_extracted(tmp_path):
    path = _write_py(tmp_path, '''
        def process():
            """We use chunked processing here because the full dataset exceeds RAM."""
            pass
    ''')
    result = extract_python(path)
    rationale = [n for n in result["nodes"] if n.get("file_type") == "rationale"]
    assert any("chunked" in n["label"] for n in rationale)


def test_class_docstring_extracted(tmp_path):
    path = _write_py(tmp_path, '''
        class Cache:
            """Chosen over Redis because we need zero external dependencies in the test env."""
            pass
    ''')
    result = extract_python(path)
    rationale = [n for n in result["nodes"] if n.get("file_type") == "rationale"]
    assert any("Redis" in n["label"] for n in rationale)


def test_rationale_comment_extracted(tmp_path):
    path = _write_py(tmp_path, '''
        def build():
            # NOTE: must run before compile() or linker will fail
            pass
    ''')
    result = extract_python(path)
    rationale = [n for n in result["nodes"] if n.get("file_type") == "rationale"]
    assert any("NOTE" in n["label"] for n in rationale)


def test_rationale_for_edges_present(tmp_path):
    path = _write_py(tmp_path, '''
        """Module docstring explaining the why."""
        def foo():
            """Function docstring with rationale."""
            pass
    ''')
    result = extract_python(path)
    rationale_edges = [e for e in result["edges"] if e.get("relation") == "rationale_for"]
    assert len(rationale_edges) >= 1


def test_short_docstring_ignored(tmp_path):
    """Trivial docstrings under 20 chars should not become rationale nodes."""
    path = _write_py(tmp_path, '''
        def foo():
            """Constructor."""
            pass
    ''')
    result = extract_python(path)
    rationale = [n for n in result["nodes"] if n.get("file_type") == "rationale"]
    assert len(rationale) == 0


def test_rationale_confidence_is_extracted(tmp_path):
    path = _write_py(tmp_path, '''
        """This module exists because we needed a standalone parser."""
        def parse(): pass
    ''')
    result = extract_python(path)
    rationale_edges = [e for e in result["edges"] if e.get("relation") == "rationale_for"]
    assert all(e.get("confidence") == "EXTRACTED" for e in rationale_edges)


def test_alembic_module_docstring_suppressed(tmp_path):
    path = _write_py(tmp_path, '''
        """initial schema

        Revision ID: 0001abcd
        Revises:
        Create Date: 2023-01-01 00:00:00
        """
        revision = "0001abcd"
        down_revision = None
        branch_labels = None

        def upgrade():
            pass

        def downgrade():
            pass
    ''')
    result = extract_python(path)
    rationale = [n for n in result["nodes"] if n.get("file_type") == "rationale"]
    assert not any("Revision ID" in n["label"] for n in rationale)


def test_alembic_function_docstrings_still_extracted(tmp_path):
    """Function docstrings inside upgrade/downgrade should still be captured."""
    path = _write_py(tmp_path, '''
        """Revision ID: 0002 Revises: 0001"""
        revision = "0002"
        down_revision = "0001"

        def upgrade():
            """Add users table because auth was added in this release."""
            pass

        def downgrade():
            pass
    ''')
    result = extract_python(path)
    rationale = [n for n in result["nodes"] if n.get("file_type") == "rationale"]
    # module docstring suppressed
    assert not any("Revision ID" in n["label"] for n in rationale)
    # function docstring still captured
    assert any("auth" in n["label"] for n in rationale)


def test_non_migration_revision_var_not_suppressed(tmp_path):
    """A file with a `revision` variable but no Alembic markers keeps its docstring."""
    path = _write_py(tmp_path, '''
        """This module tracks document revisions because we need audit history."""
        revision = 42

        def get_revision(): pass
    ''')
    result = extract_python(path)
    rationale = [n for n in result["nodes"] if n.get("file_type") == "rationale"]
    assert any("audit history" in n["label"] for n in rationale)


def test_django_migration_module_docstring_suppressed(tmp_path):
    path = _write_py(tmp_path, '''
        """Add post_priority_config table."""
        from django.db import migrations

        class Migration(migrations.Migration):
            dependencies = [("myapp", "0001_initial")]
            operations = []
    ''')
    result = extract_python(path)
    rationale = [n for n in result["nodes"] if n.get("file_type") == "rationale"]
    assert not any("post_priority" in n["label"] for n in rationale)


def test_generated_file_module_docstring_suppressed(tmp_path):
    path = _write_py(tmp_path, '''
        """Generated by the protocol buffer compiler. DO NOT EDIT!"""
        from google.protobuf import descriptor as _descriptor

        class UserMessage:
            pass
    ''')
    result = extract_python(path)
    rationale = [n for n in result["nodes"] if n.get("file_type") == "rationale"]
    assert not any("protocol buffer" in n["label"].lower() for n in rationale)


def test_decorated_method_node_id_is_class_qualified(tmp_path):
    """Regression for #1050: @property / @staticmethod / @classmethod methods
    were emitted with a class-unqualified node id (e.g. ``file_baz``) while the
    rationale walker emitted the class-qualified id (``file_bar_baz``) as the
    docstring's edge target. The mismatch caused ``build_from_json`` to drop
    the rationale_for edge as dangling, orphaning the docstring node.
    """
    path = _write_py(tmp_path, '''
        class Bar:
            @property
            def baz(self) -> int:
                """Return the baz value because callers expect a cached integer."""
                return 1

            @staticmethod
            def helper() -> int:
                """A static helper documented for downstream callers."""
                return 2

            @classmethod
            def factory(cls) -> "Bar":
                """Construct a Bar via the canonical classmethod entry point."""
                return cls()

            def normal(self) -> int:
                """A normal instance method documented for comparison."""
                return 3
    ''')
    result = extract_python(path)
    nodes_by_id = {n["id"]: n for n in result["nodes"]}

    # The plain method's id is the baseline: stem + class + name.
    normal_ids = [nid for nid, n in nodes_by_id.items()
                  if n.get("label") == ".normal()"]
    assert len(normal_ids) == 1, "expected exactly one ``.normal()`` method node"
    normal_id = normal_ids[0]
    assert normal_id.endswith("_bar_normal"), normal_id

    # Each decorated method must share the same class-qualified id shape so the
    # rationale_for edge target matches the method node id.
    for decorated_name in ("baz", "helper", "factory"):
        matches = [nid for nid, n in nodes_by_id.items()
                   if n.get("label") == f".{decorated_name}()"]
        assert len(matches) == 1, (
            f"expected exactly one ``.{decorated_name}()`` method node, got {matches}"
        )
        method_id = matches[0]
        assert method_id.endswith(f"_bar_{decorated_name}"), method_id
        # Unqualified id (the buggy form) must NOT also be present.
        unqualified_buggy_id = method_id.replace(f"_bar_{decorated_name}",
                                                  f"_{decorated_name}")
        assert unqualified_buggy_id not in nodes_by_id, (
            f"buggy unqualified id {unqualified_buggy_id} should not exist alongside "
            f"the class-qualified id"
        )

    # Every rationale_for edge's target must resolve to an actual node in the
    # extraction (no dangling edges into phantom unqualified ids).
    node_ids = set(nodes_by_id.keys())
    rationale_edges = [e for e in result["edges"] if e.get("relation") == "rationale_for"]
    for edge in rationale_edges:
        assert edge["target"] in node_ids, (
            f"rationale_for edge targets missing node id {edge['target']!r}"
        )

    # After build_from_json, each decorated-method docstring node must be
    # connected (degree > 0), not an orphan dropped from the graph.
    g = build_from_json(result)
    for decorated_name in ("baz", "helper", "factory", "normal"):
        method_id = next(
            nid for nid, n in nodes_by_id.items()
            if n.get("label") == f".{decorated_name}()"
        )
        # Find rationale node attached to this method.
        attached_rationale = [
            e["source"] for e in rationale_edges if e["target"] == method_id
        ]
        assert attached_rationale, (
            f"no rationale_for edge found for ``.{decorated_name}()`` method"
        )
        for r_id in attached_rationale:
            assert r_id in g.nodes, f"rationale node {r_id} missing from graph"
            assert g.degree(r_id) > 0, (
                f"rationale node {r_id} for ``.{decorated_name}()`` is orphaned "
                f"(degree 0) after build_from_json"
            )


# ── C/C++ rationale extraction (UE-aware) ─────────────────────────────────────

def _write_cpp(tmp_path: Path, code: str, name: str = "Sample.h") -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(code), encoding="utf-8")
    return p


def _labels_for(result, target_label):
    """Comment texts of rationale nodes attached to the node labelled target_label."""
    by_id = {n["id"]: n for n in result["nodes"]}
    target_ids = {n["id"] for n in result["nodes"] if n.get("label") == target_label}
    out = []
    for e in result["edges"]:
        if e.get("relation") == "rationale_for" and e["target"] in target_ids:
            src = by_id.get(e["source"])
            if src:
                out.append(src["label"])
    return out


def test_cpp_enum_and_enumerator_nodes_created(tmp_path):
    path = _write_cpp(tmp_path, '''
        enum class EState : unsigned char
        {
            Deferred,
            Immediate,
        };
    ''')
    result = extract_cpp(path)
    labels = {n.get("label") for n in result["nodes"]}
    assert "EState" in labels
    assert "EState::Immediate" in labels
    assert "EState::Deferred" in labels


def test_cpp_enumerator_doc_comment_attaches(tmp_path):
    path = _write_cpp(tmp_path, '''
        enum class EState : unsigned char
        {
            Deferred,
            /// inflight even while a request is mid-flight, bypassing the limit.
            Immediate,
        };
    ''')
    result = extract_cpp(path)
    attached = _labels_for(result, "EState::Immediate")
    assert any("inflight" in t for t in attached), attached


def test_cpp_class_doc_block_attaches(tmp_path):
    path = _write_cpp(tmp_path, '''
        /**
         * Owns movement; forces velocity to zero while inflight.
         */
        class UMover
        {
        };
    ''')
    result = extract_cpp(path)
    attached = _labels_for(result, "UMover")
    assert any("velocity to zero" in t for t in attached), attached


def test_cpp_method_prototype_node_and_doc(tmp_path):
    path = _write_cpp(tmp_path, '''
        class UMover
        {
        public:
            /// Returns the world-space velocity; zero while inflight.
            FVector GetVelocity() const;
        };
    ''')
    result = extract_cpp(path)
    labels = {n.get("label") for n in result["nodes"]}
    assert ".GetVelocity()" in labels
    attached = _labels_for(result, ".GetVelocity()")
    assert any("world-space velocity" in t for t in attached), attached


def test_cpp_member_variable_leading_and_trailing_comment(tmp_path):
    path = _write_cpp(tmp_path, '''
        class UMover
        {
            /// The maximum allowed movement speed for this mover.
            float MaxSpeed;
            int Health; // current hit points for the owning actor
        };
    ''')
    result = extract_cpp(path)
    assert any("maximum allowed movement" in t for t in _labels_for(result, "MaxSpeed"))
    assert any("hit points" in t for t in _labels_for(result, "Health"))


def test_cpp_marker_comment_goes_to_file_node(tmp_path):
    path = _write_cpp(tmp_path, '''
        void Build()
        {
            // TODO: must run before linking or the build will fail outright
            return;
        }
    ''')
    result = extract_cpp(path)
    file_nodes = [n for n in result["nodes"]
                  if n.get("label", "").endswith(".h")]
    assert file_nodes
    attached = _labels_for(result, file_nodes[0]["label"])
    assert any("TODO" in t for t in attached), attached


def test_cpp_short_comment_ignored(tmp_path):
    path = _write_cpp(tmp_path, '''
        class UMover
        {
            int X; // ok
        };
    ''')
    result = extract_cpp(path)
    rationale = [n for n in result["nodes"] if n.get("file_type") == "rationale"]
    assert rationale == [], rationale


def test_cpp_license_header_not_attached(tmp_path):
    path = _write_cpp(tmp_path, '''
        // Copyright Foo. All Rights Reserved. This header is license boilerplate.
        #pragma once

        class UMover
        {
        };
    ''')
    result = extract_cpp(path)
    assert not any("Copyright" in n["label"]
                   for n in result["nodes"] if n.get("file_type") == "rationale")


def test_cpp_ue_macros_do_not_create_junk_nodes(tmp_path):
    path = _write_cpp(tmp_path, '''
        UENUM(BlueprintType)
        enum class EState : unsigned char { A, B };

        UCLASS()
        class UMover : public UActorComponent
        {
            GENERATED_BODY()
        public:
            UFUNCTION(BlueprintCallable)
            FVector GetVelocity() const;

            UPROPERTY(EditAnywhere, Category="Movement")
            float MaxSpeed;
        };
    ''')
    result = extract_cpp(path)
    labels = {n.get("label") for n in result["nodes"]}
    # No reflection-macro junk nodes.
    for junk in ("UPROPERTY", "UFUNCTION", "UCLASS", "UENUM", "GENERATED_BODY"):
        assert junk not in labels, f"{junk} leaked as a node"
    # The macros must not break the declarations that follow them.
    assert ".GetVelocity()" in labels, "UFUNCTION broke the method declaration"
    assert "MaxSpeed" in labels, "UPROPERTY broke the field declaration"
    assert "EState" in labels and "UMover" in labels


def test_cpp_rationale_for_edges_resolve_to_nodes(tmp_path):
    path = _write_cpp(tmp_path, '''
        UCLASS()
        class UMover
        {
            GENERATED_BODY()
        public:
            /// Returns the world-space velocity; zero while inflight.
            UFUNCTION()
            FVector GetVelocity() const;
        };
    ''')
    result = extract_cpp(path)
    node_ids = {n["id"] for n in result["nodes"]}
    rationale_edges = [e for e in result["edges"] if e.get("relation") == "rationale_for"]
    assert rationale_edges
    for e in rationale_edges:
        assert e["target"] in node_ids
        assert e.get("confidence") == "EXTRACTED"
    # Survives graph construction without orphaning the rationale node.
    g = build_from_json(result)
    for e in rationale_edges:
        assert e["source"] in g.nodes and g.degree(e["source"]) > 0
