"""Minimal Streamlit frontend for the policy knowledge graph."""

import os
import sys
import tempfile
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx
import streamlit as st

# Make the repo root importable regardless of the working directory Streamlit
# was launched from (fixes "ModuleNotFoundError: No module named 'src'" when
# running from inside frontend/ instead of the repo root).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ponytail: import backend modules directly instead of wiring an MCP client
from src.extraction import SemanticContext, extract_semantic_context
from src.graph_store import KnowledgeGraph
from src.ingestion import to_markdown

st.set_page_config(page_title="Policy Knowledge Graph", layout="wide")
st.title("Policy Knowledge Graph")

# Shared state
if "kg" not in st.session_state:
    st.session_state.kg = KnowledgeGraph()
if "markdown" not in st.session_state:
    st.session_state.markdown = ""
if "context" not in st.session_state:
    st.session_state.context = None


tab_ingest, tab_build, tab_explore = st.tabs(["1. Ingest", "2. Build Graph", "3. Explore Graph"])


with tab_ingest:
    st.header("Convert document to Markdown")
    source_input = st.text_area("Or paste raw text / markdown here", height=200, key="raw_input")
    uploaded = st.file_uploader("Or upload a file", type=["txt", "md", "pdf", "docx"])

    if st.button("Convert"):
        if uploaded:
            suffix = Path(uploaded.name).suffix
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(uploaded.getvalue())
                tmp_path = tmp.name
            st.session_state.markdown = to_markdown(tmp_path)
            os.unlink(tmp_path)
        elif source_input:
            st.session_state.markdown = to_markdown(source_input)
        else:
            st.warning("Provide text or a file.")

    if st.session_state.markdown:
        st.subheader("Markdown Output")
        st.markdown(st.session_state.markdown)
        st.download_button("Download markdown", st.session_state.markdown, "policy.md")


with tab_build:
    st.header("Extract semantic context and upsert to graph")
    md_input = st.text_area(
        "Markdown policy",
        value=st.session_state.markdown,
        height=250,
        key="build_md",
    )
    col1, col2 = st.columns(2)
    with col1:
        policy_id = st.text_input("Policy ID", "POL-001")
    with col2:
        version = st.text_input("Version", "v1")

    if st.button("Extract Context"):
        if not md_input.strip():
            st.warning("Paste markdown first.")
        else:
            with st.spinner("Calling Claude..."):
                try:
                    st.session_state.context = extract_semantic_context(md_input)
                    st.success("Extraction complete")
                except Exception as e:
                    st.error(f"Extraction failed: {e}")

    if st.session_state.context:
        st.subheader("Extracted Context")
        st.json(st.session_state.context.model_dump(mode="json"))

        if st.button("Upsert to Graph"):
            uri = st.session_state.kg.upsert_policy(st.session_state.context, policy_id, version)
            st.success(f"Upserted {policy_id}@{version}")
            st.write(f"Graph now has {len(st.session_state.kg.g.nodes)} nodes and {len(st.session_state.kg.g.edges)} edges")
            st.json({"policy_uri": uri})


with tab_explore:
    st.header("Explore the knowledge graph")
    st.write(f"Current graph: {len(st.session_state.kg.g.nodes)} nodes, {len(st.session_state.kg.g.edges)} edges")

    seeds = st.text_input("Seed entities (comma separated)", "Acme, customerPII")
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
        sub = st.session_state.kg.read_graph(seed_list, depth)
        st.session_state.subgraph = sub

    sub = st.session_state.get("subgraph")
    if sub is None and len(st.session_state.kg.g.nodes) > 0:
        # ponytail: default to full graph if no subgraph yet
        sub = st.session_state.kg.g.copy()
        st.session_state.subgraph = sub

    if sub is not None:
        if run_f2:
            sub = st.session_state.kg.reduce_edges(sub, [e.strip() for e in keep_edges.split(",") if e.strip()])
        if run_f3:
            sub = st.session_state.kg.eliminate_nodes(sub, min_degree)
        if run_f4:
            seed_list = [s.strip() for s in seeds.split(",") if s.strip()]
            sub = st.session_state.kg.augment_graph(sub, seed_list, scoring)

        st.session_state.subgraph = sub

        st.subheader("Graph Data")
        st.write(f"Nodes: {len(sub.nodes)}, Edges: {len(sub.edges)}")
        st.json({
            "nodes": [{"uri": n, **d} for n, d in sub.nodes(data=True)],
            "edges": [{"source": u, "target": v, **d} for u, v, d in sub.edges(data=True)],
        })

        st.subheader("Visualization")
        fig, ax = plt.subplots(figsize=(10, 8))
        pos = nx.spring_layout(sub.to_undirected(), seed=42)
        labels = {n: sub.nodes[n].get("label", n.split("/")[-1]) for n in sub.nodes}
        node_colors = []
        type_color = {
            "Policy": "tab:blue",
            "PolicyRule": "tab:green",
            "DataCategory": "tab:orange",
            "Partner": "tab:purple",
            "NDAContract": "tab:red",
            "ClassificationLabel": "tab:pink",
        }
        for n in sub.nodes:
            node_colors.append(type_color.get(sub.nodes[n].get("type"), "tab:gray"))
        nx.draw_networkx_nodes(sub, pos, node_color=node_colors, ax=ax, node_size=700)
        nx.draw_networkx_labels(sub, pos, labels, ax=ax, font_size=8)
        nx.draw_networkx_edges(sub, pos, ax=ax, arrows=True, edge_color="gray")
        ax.set_title("Knowledge Graph Subgraph")
        ax.axis("off")
        st.pyplot(fig)