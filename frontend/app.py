"""Streamlit frontend — multi-policy automated pipeline.

This app provides a web UI for the policy knowledge graph. Users can paste or
upload policy documents, extract semantic context with Claude, upsert policies
into a combined knowledge graph, and visualize the graph with interactive
Graph RAG controls (read, reduce, eliminate, augment).

It also provides a document classification section: upload a target document,
retrieve the relevant subgraph via Graph RAG, and get a structured sensitivity
classification (Restricted / Confidential / Internal / Public) from Claude.
"""

import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import networkx as nx
import streamlit as st
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.extraction import SemanticContext, extract_semantic_context
from src.graph_store import KnowledgeGraph
from src.ingestion import to_markdown
from src.context_assembler import assemble_prompt
from src.classifier import classify

st.set_page_config(page_title="Policy Knowledge Graph", layout="wide")
st.title("Policy Knowledge Graph")

# Shared state
if "kg" not in st.session_state:
    logger.info("Initializing session_state.kg")
    st.session_state.kg = KnowledgeGraph()
if "policies" not in st.session_state:
    logger.info("Initializing session_state.policies")
    # list of dicts: {policy_id, version, title, markdown, context, added_at}
    st.session_state.policies = []
if "subgraph" not in st.session_state:
    logger.info("Initializing session_state.subgraph")
    st.session_state.subgraph = None
if "classifications" not in st.session_state:
    logger.info("Initializing session_state.classifications")
    # list of dicts: {doc_name, doc_text, seed_entities, result, classified_at}
    st.session_state.classifications = []


def run_visualization(sub):
    """Render the given subgraph as an interactive matplotlib network diagram.

    Nodes are colored by type and labeled with shortened text. Edge predicates
    are drawn as curved arrows with small white bounding boxes.

    Args:
        sub: A ``networkx.DiGraph`` (or compatible subgraph) to visualize.

    Returns:
        None
    """
    logger.info("run_visualization called with {} node(s) and {} edge(s)", len(sub.nodes), len(sub.edges))
    type_color = {
        "Policy": "#4C72B0",
        "PolicyRule": "#55A868",
        "DataCategory": "#DD8452",
        "Partner": "#8172B2",
        "NDAContract": "#C44E52",
        "ClassificationLabel": "#CCB974",
    }
    n_nodes = len(sub.nodes)
    if n_nodes == 0:
        logger.warning("run_visualization: no nodes to display")
        st.info("No nodes to display.")
        return

    fig_size = max(14, min(n_nodes * 1.2, 30))
    fig, ax = plt.subplots(figsize=(fig_size, fig_size * 0.7))

    try:
        logger.debug("Attempting Kamada-Kawai layout")
        pos = nx.kamada_kawai_layout(sub.to_undirected())
    except Exception:
        logger.warning("Kamada-Kawai layout failed; falling back to spring layout")
        pos = nx.spring_layout(sub.to_undirected(), seed=42, k=3.0 / max(n_nodes ** 0.5, 1))

    labels = {n: sub.nodes[n].get("label", n.split("/")[-1].replace("_", " ")) for n in sub.nodes}
    labels = {n: (v[:20] + "…") if len(v) > 20 else v for n, v in labels.items()}
    node_colors = [type_color.get(sub.nodes[n].get("type", "Node"), "#999999") for n in sub.nodes]

    nx.draw_networkx_nodes(sub, pos, node_color=node_colors, ax=ax, node_size=1800, alpha=0.92)
    nx.draw_networkx_labels(sub, pos, labels, ax=ax, font_size=7, font_color="white", font_weight="bold")
    nx.draw_networkx_edges(
        sub, pos, ax=ax, arrows=True, arrowstyle="->", arrowsize=18,
        edge_color="#888888", width=1.2, connectionstyle="arc3,rad=0.1",
        min_source_margin=25, min_target_margin=25,
    )
    edge_labels = {(u, v): d.get("predicate", "") for u, v, d in sub.edges(data=True)}
    nx.draw_networkx_edge_labels(
        sub, pos, edge_labels=edge_labels, ax=ax, font_size=6, font_color="#444444",
        bbox=dict(boxstyle="round,pad=0.2", fc="white", alpha=0.6, ec="none"),
    )
    legend_handles = [mpatches.Patch(color=c, label=t) for t, c in type_color.items()]
    ax.legend(handles=legend_handles, loc="upper left", fontsize=8, framealpha=0.8)
    ax.set_title("Knowledge Graph", fontsize=14, pad=20)
    ax.axis("off")
    plt.tight_layout()
    logger.info("Rendering matplotlib figure in Streamlit")
    st.pyplot(fig)


LABEL_COLOR = {
    "Restricted": "🔴",
    "Confidential": "🟠",
    "Internal": "🟡",
    "Public": "🟢",
}


def render_classification_result(result: dict):
    """Render a classification result dict returned by src.classifier.classify().

    Args:
        result: Dict matching the submit_classification tool schema.

    Returns:
        None
    """
    label = result.get("classification", "Unknown")
    confidence = result.get("confidence", 0.0)
    icon = LABEL_COLOR.get(label, "⚪")

    col_a, col_b = st.columns([2, 1])
    with col_a:
        st.markdown(f"### {icon} {label}")
    with col_b:
        st.metric("Confidence", f"{confidence:.0%}")

    if result.get("needsHumanReview"):
        st.warning("⚠️ Flagged for human review")

    st.markdown("**Rationale**")
    st.write(result.get("rationale", "—"))

    col_c, col_d = st.columns(2)
    with col_c:
        st.markdown("**Cited Policy Refs**")
        refs = result.get("citedPolicyRefs", [])
        if refs:
            for ref in refs:
                st.markdown(f"- `{ref.get('id')}`" + (f" ({ref.get('version')})" if ref.get("version") else ""))
        else:
            st.markdown("_None_")
    with col_d:
        st.markdown("**Cited NDA Refs**")
        ndas = result.get("citedNDARefs", [])
        if ndas:
            for nda in ndas:
                st.markdown(f"- `{nda}`")
        else:
            st.markdown("_None_")

    assumptions = result.get("assumptions", [])
    if assumptions:
        st.markdown("**Assumptions**")
        for a in assumptions:
            st.markdown(f"- {a}")


# ─────────────────────────────────────────────
# SECTION 1: Upload & Process New Policy
# ─────────────────────────────────────────────
st.header("1. Add Policy")

source_input = st.text_area("Paste raw text / markdown here", height=150, key="raw_input")
uploaded = st.file_uploader("Or upload a file", type=["txt", "md", "pdf", "docx"])

col1, col2 = st.columns(2)
with col1:
    policy_id = st.text_input("Policy ID", f"POL-{len(st.session_state.policies) + 1:03d}")
with col2:
    version = st.text_input("Version", "v1")

if st.button("➕ Convert & Extract & Add to Graph", type="primary"):
    logger.info("Add Policy button clicked for {}@{}", policy_id, version)

    # Check duplicate policy ID
    existing_ids = [p["policy_id"] for p in st.session_state.policies]
    if policy_id in existing_ids:
        logger.warning("Duplicate policy ID submitted: {}", policy_id)
        st.error(f"Policy ID '{policy_id}' already exists. Use a different ID.")
        st.stop()

    # Step 1: Convert
    raw_md = ""
    if uploaded:
        suffix = Path(uploaded.name).suffix
        logger.info("Uploaded file received: {} (suffix: {})", uploaded.name, suffix)
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uploaded.getvalue())
            tmp_path = tmp.name
        raw_md = to_markdown(tmp_path)
        os.unlink(tmp_path)
        logger.info("Converted uploaded file to markdown ({} characters)", len(raw_md))
    elif source_input.strip():
        logger.info("Using raw text input ({} characters)", len(source_input))
        raw_md = to_markdown(source_input)
    else:
        logger.warning("No input provided")
        st.warning("Provide text or upload a file first.")
        st.stop()

    st.success("✅ Step 1: Converted to Markdown")

    # Step 2: Extract
    with st.spinner("⏳ Step 2: Extracting semantic context with Claude..."):
        logger.info("Starting semantic extraction")
        try:
            ctx = extract_semantic_context(raw_md)
            logger.info(
                "Semantic extraction succeeded: {} rules, {} categories, {} partners, {} NDAs",
                len(ctx.rules),
                len(ctx.data_categories),
                len(ctx.partners),
                len(ctx.nda_contracts),
            )
            st.success("✅ Step 2: Semantic context extracted")
        except Exception as e:
            logger.exception("Semantic extraction failed")
            st.error(f"Extraction failed: {e}")
            st.stop()

    # Step 3: Upsert to graph
    with st.spinner("⏳ Step 3: Adding to knowledge graph..."):
        logger.info("Upserting policy {}@{} into graph", policy_id, version)
        try:
            uri = st.session_state.kg.upsert_policy(ctx, policy_id, version)
            st.session_state.subgraph = st.session_state.kg.g.copy()

            # Save to policy list
            st.session_state.policies.append({
                "policy_id": policy_id,
                "version": version,
                "title": ctx.title or policy_id,
                "markdown": raw_md,
                "context": ctx,
                "added_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            })
            logger.info(
                "Policy added: '{}' -> {}. Graph now has {} nodes, {} edges",
                ctx.title or policy_id,
                uri,
                len(st.session_state.kg.g.nodes),
                len(st.session_state.kg.g.edges),
            )
            st.success(
                f"✅ Step 3: '{ctx.title or policy_id}' added! "
                f"Graph now has {len(st.session_state.kg.g.nodes)} nodes, "
                f"{len(st.session_state.kg.g.edges)} edges"
            )
        except Exception as e:
            logger.exception("Graph upsert failed")
            st.error(f"Graph build failed: {e}")
            st.stop()

st.divider()

# ─────────────────────────────────────────────
# SECTION 2: Policy List
# ─────────────────────────────────────────────
if st.session_state.policies:
    logger.debug("Rendering policy list ({} policies)", len(st.session_state.policies))
    st.header(f"2. Policies ({len(st.session_state.policies)})")

    for i, policy in enumerate(st.session_state.policies):
        with st.expander(
            f"📋 [{policy['policy_id']}] {policy['title']}  —  {policy['version']}  ·  {policy['added_at']}",
            expanded=False
        ):
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown(f"**Policy ID:** `{policy['policy_id']}`")
                st.markdown(f"**Version:** `{policy['version']}`")
                st.markdown(f"**Added:** {policy['added_at']}")
            with col_b:
                st.markdown(f"**Type:** {policy['context'].policy_type}")
                st.markdown(f"**Effective Date:** {policy['context'].effective_date or 'N/A'}")
                st.markdown(f"**Rules:** {len(policy['context'].rules)}  |  **Partners:** {len(policy['context'].partners)}")

            inner_tab1, inner_tab2 = st.tabs(["📄 Markdown", "🧠 Extracted Context"])
            with inner_tab1:
                st.markdown(policy["markdown"])
                st.download_button(
                    "Download markdown",
                    policy["markdown"],
                    f"{policy['policy_id']}.md",
                    key=f"dl_{i}"
                )
            with inner_tab2:
                st.json(policy["context"].model_dump(mode="json"))

    st.divider()

# ─────────────────────────────────────────────
# SECTION 3: Combined Knowledge Graph
# ─────────────────────────────────────────────
if st.session_state.subgraph is not None:
    sub = st.session_state.subgraph
    logger.debug("Rendering combined knowledge graph ({} nodes)", len(sub.nodes))
    st.header("3. Combined Knowledge Graph")
    st.write(f"**{len(sub.nodes)} nodes** across **{len(st.session_state.policies)} policies**")

    with st.expander("⚙️ Graph Controls", expanded=False):
        seeds = st.text_input("Seed entities (comma separated)", "")
        depth = st.slider("Depth", 1, 5, 2)
        col_f1, col_f2, col_f3, col_f4 = st.columns(4)
        with col_f1:
            run_f1 = st.button("F1 Read Graph")
        with col_f2:
            keep_edges = st.text_input("Keep edges", "governs, covers, mapsTo")
            run_f2 = st.button("F2 Reduce Edges")
        with col_f3:
            min_degree = st.number_input("Min degree", min_value=0, value=1)
            run_f3 = st.button("F3 Eliminate Nodes")
        with col_f4:
            scoring = st.selectbox("Scoring", ["hop_distance"])
            run_f4 = st.button("F4 Augment")

        if run_f1:
            seed_list = [s.strip() for s in seeds.split(",") if s.strip()]
            logger.info("F1 Read Graph triggered with seeds: {}", seed_list)
            sub = st.session_state.kg.read_graph(seed_list, depth)
            st.session_state.subgraph = sub
            logger.info("F1 complete: {} nodes, {} edges", len(sub.nodes), len(sub.edges))
        if run_f2:
            keep_list = [e.strip() for e in keep_edges.split(",") if e.strip()]
            logger.info("F2 Reduce Edges triggered; keeping: {}", keep_list)
            sub = st.session_state.kg.reduce_edges(sub, keep_list)
            st.session_state.subgraph = sub
            logger.info("F2 complete: {} nodes, {} edges", len(sub.nodes), len(sub.edges))
        if run_f3:
            logger.info("F3 Eliminate Nodes triggered with min_degree {}", min_degree)
            sub = st.session_state.kg.eliminate_nodes(sub, min_degree)
            st.session_state.subgraph = sub
            logger.info("F3 complete: {} nodes, {} edges", len(sub.nodes), len(sub.edges))
        if run_f4:
            seed_list = [s.strip() for s in seeds.split(",") if s.strip()]
            logger.info("F4 Augment triggered with seeds: {}, scoring: {}", seed_list, scoring)
            sub = st.session_state.kg.augment_graph(sub, seed_list, scoring)
            st.session_state.subgraph = sub
            logger.info("F4 complete: {} nodes, {} edges", len(sub.nodes), len(sub.edges))

    with st.expander("📊 Graph Data", expanded=False):
        st.json({
            "nodes": [{"uri": n, **d} for n, d in sub.nodes(data=True)],
            "edges": [{"source": u, "target": v, **d} for u, v, d in sub.edges(data=True)],
        })

    run_visualization(sub)

    st.divider()

# ─────────────────────────────────────────────
# SECTION 4: Classify a Document
# ─────────────────────────────────────────────
st.header("4. Classify a Document")

if not st.session_state.policies:
    st.info("Add at least one policy above before classifying a document — "
             "the classifier needs graph context (partners, data categories, rules) to work against.")
else:
    doc_input = st.text_area("Paste the document text to classify", height=150, key="classify_raw_input")
    doc_uploaded = st.file_uploader(
        "Or upload a document file", type=["txt", "md", "pdf", "docx"], key="classify_file_uploader"
    )

    if st.button("🔍 Classify Document", type="primary"):
        logger.info("Classify Document button clicked")

        # Step 1: Convert to markdown (reuse the same ingestion path as policies)
        doc_text = ""
        doc_name = "pasted text"
        if doc_uploaded:
            suffix = Path(doc_uploaded.name).suffix
            doc_name = doc_uploaded.name
            logger.info("Document uploaded for classification: {} (suffix: {})", doc_name, suffix)
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(doc_uploaded.getvalue())
                tmp_path = tmp.name
            doc_text = to_markdown(tmp_path)
            os.unlink(tmp_path)
            logger.info("Converted document to markdown ({} characters)", len(doc_text))
        elif doc_input.strip():
            logger.info("Using pasted document text ({} characters)", len(doc_input))
            doc_text = to_markdown(doc_input)
        else:
            logger.warning("No document provided for classification")
            st.warning("Provide text or upload a file first.")
            st.stop()

        st.success("✅ Step 1: Document converted to Markdown")

        # Step 2: Assemble the Graph RAG prompt (find seeds -> traverse -> build context block)
        with st.spinner("⏳ Step 2: Retrieving relevant policy context from the graph..."):
            logger.info("Assembling classification prompt via context_assembler")
            try:
                prompt = assemble_prompt(st.session_state.kg, doc_text)
                logger.info(
                    "Prompt assembled: {} seed entities found: {}",
                    len(prompt["seed_entities"]),
                    prompt["seed_entities"],
                )
                if prompt["seed_entities"]:
                    st.success(f"✅ Step 2: Found {len(prompt['seed_entities'])} relevant entities: "
                               f"{', '.join(prompt['seed_entities'])}")
                else:
                    st.warning("⚠️ Step 2: No known partners or data categories were mentioned in this "
                               "document — classification will be flagged for human review.")
            except Exception as e:
                logger.exception("Context assembly failed")
                st.error(f"Context assembly failed: {e}")
                st.stop()

        # Step 3: Call the classifier
        with st.spinner("⏳ Step 3: Classifying with Claude..."):
            logger.info("Calling classifier.classify()")
            try:
                result = classify(prompt)
                logger.info(
                    "Classification complete: {} (confidence={}, needsHumanReview={})",
                    result.get("classification"),
                    result.get("confidence"),
                    result.get("needsHumanReview"),
                )
                st.success("✅ Step 3: Classification complete")
            except Exception as e:
                logger.exception("Classification failed")
                st.error(f"Classification failed: {e}")
                st.stop()

        # Save to history
        st.session_state.classifications.append({
            "doc_name": doc_name,
            "doc_text": doc_text,
            "seed_entities": prompt["seed_entities"],
            "result": result,
            "classified_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })

        st.divider()
        st.subheader("Result")
        render_classification_result(result)

    # History of past classifications this session
    if st.session_state.classifications:
        st.divider()
        with st.expander(f"🕓 Classification history ({len(st.session_state.classifications)})", expanded=False):
            for i, entry in enumerate(reversed(st.session_state.classifications)):
                label = entry["result"].get("classification", "Unknown")
                icon = LABEL_COLOR.get(label, "⚪")
                with st.expander(f"{icon} {entry['doc_name']} — {label} · {entry['classified_at']}", expanded=False):
                    render_classification_result(entry["result"])
                    st.markdown("**Seed entities detected**")
                    st.write(", ".join(entry["seed_entities"]) or "_None_")