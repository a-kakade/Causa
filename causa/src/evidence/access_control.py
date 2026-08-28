"""
access_control.py — Step 4: the Evidence Fabric's policy filter (task
§21/§22).

Reuses the exact PUBLIC_ANALYTICAL/INTERNAL/RESTRICTED scale and
CLEARANCE_RANK ordering already established in config/kpis.yaml and
enforced in src/kpi/query_planner.py / src/drivers/engine.py -- not
redefined here.

Hiding a restricted node's LABEL is not enough (task §22): this module
filters graphs by actually removing unauthorized nodes/edges (never just
masking a display field), computes counts AFTER filtering (never on the
unfiltered graph with labels hidden), and scrubs identifier-shaped tokens out
of exception messages before they propagate.
"""

from __future__ import annotations

import re
from typing import Any

import networkx as nx

from evidence.models import CLEARANCE_RANK
from evidence.schema import EvidenceObject

# customer_id / customer_unique_id are RESTRICTED by documented rule in
# config/kpis.yaml's prose (not as an actual queryable dimension entry --
# they are never exposed as a KPI dimension at all), so there is no
# SemanticRegistry lookup to defer to here. This module hardcodes the rule
# itself: these keys never appear in any node/edge attribute this fabric
# returns, at ANY clearance level.
NEVER_SURFACE_NODE_ATTRS = {"customer_id", "customer_unique_id"}
INTERNAL_ONLY_NODE_ATTRS = {"seller", "seller_id"}

_ID_LOOKING_TOKEN = re.compile(r"\b[0-9a-f]{16,64}\b", re.IGNORECASE)


def clearance_sufficient(classification: str, requester_clearance: str) -> bool:
    return CLEARANCE_RANK.get(requester_clearance, 0) >= CLEARANCE_RANK.get(classification, 0)


def filter_evidence_objects(evidence: list[EvidenceObject], requester_clearance: str) -> list[EvidenceObject]:
    return [e for e in evidence if clearance_sufficient(e.security.classification.value, requester_clearance)]


def _strip_disallowed_attrs(attrs: dict[str, Any], requester_clearance: str) -> dict[str, Any]:
    cleaned = {k: v for k, v in attrs.items() if k not in NEVER_SURFACE_NODE_ATTRS}
    if CLEARANCE_RANK.get(requester_clearance, 0) < CLEARANCE_RANK["INTERNAL"]:
        cleaned = {k: v for k, v in cleaned.items() if k not in INTERNAL_ONLY_NODE_ATTRS}
        dims = cleaned.get("dimensions")
        if isinstance(dims, dict):
            cleaned["dimensions"] = {k: v for k, v in dims.items() if k not in INTERNAL_ONLY_NODE_ATTRS}
    return cleaned


def filter_graph(g: nx.MultiDiGraph, requester_clearance: str) -> nx.MultiDiGraph:
    """Returns a NEW graph containing only nodes whose
    `security_classification` attribute (when present -- KPI/INVESTIGATION/
    CONFIDENCE nodes carry no classification of their own and are always
    kept) clears `requester_clearance`, with disallowed attribute keys
    stripped from every surviving node. `g.subgraph(...)` would keep the
    original attribute dicts by reference and would not strip
    seller/customer_id keys, so this builds a fresh graph explicitly instead
    of relying on subgraph()."""
    allowed_nodes = [
        n for n, attrs in g.nodes(data=True)
        if clearance_sufficient(attrs.get("security_classification", "PUBLIC_ANALYTICAL"), requester_clearance)
    ]
    allowed_set = set(allowed_nodes)

    result = nx.MultiDiGraph()
    for n in allowed_nodes:
        result.add_node(n, **_strip_disallowed_attrs(dict(g.nodes[n]), requester_clearance))
    for u, v, key, attrs in g.edges(keys=True, data=True):
        if u in allowed_set and v in allowed_set:
            result.add_edge(u, v, key=key, **attrs)
    return result


def safe_node_count(g: nx.MultiDiGraph, requester_clearance: str) -> int:
    """Counts computed AFTER filtering -- never on the unfiltered graph with
    only labels hidden (task §22: "no leakage via ... counts, aggregates")."""
    return filter_graph(g, requester_clearance).number_of_nodes()


def safe_edge_count(g: nx.MultiDiGraph, requester_clearance: str) -> int:
    return filter_graph(g, requester_clearance).number_of_edges()


def redact_error_message(message: str, requester_clearance: str) -> str:
    """Scrubs long hex-looking tokens (the shape of every seller_id/
    customer_id/customer_unique_id/order_id in this dataset) out of an
    exception message before it is allowed to propagate to a caller below
    INTERNAL clearance (task §22: "no leakage via ... error messages")."""
    if CLEARANCE_RANK.get(requester_clearance, 0) >= CLEARANCE_RANK["INTERNAL"]:
        return message
    return _ID_LOOKING_TOKEN.sub("[REDACTED_ID]", message)
