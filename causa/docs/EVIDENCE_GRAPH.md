# Evidence Graph (Step 4)

`src/evidence/graph.py` builds a NetworkX evidence graph over structured and
review evidence. It is a representation and traceability layer only — it
never decides which node is "correct" and never resolves a contradiction.

## 1. Node and edge reference

**Node types** (`evidence.models.GRAPH_NODE_TYPES`): `INVESTIGATION`, `KPI`,
`MOVEMENT`, `DRIVER`, `SEGMENT`, `EVIDENCE`, `BUSINESS_CONTEXT`, `CONFIDENCE`,
`ACTION`. (`BUSINESS_CONTEXT` and `ACTION` are declared for future steps and
not populated by any Step 4 code path.)

**Edge types** (`evidence.models.RelationshipType`): `HAS_MOVEMENT`,
`EXPLAINED_BY`, `SUPPORTED_BY`, `CONTRADICTS`, `CONTEXTUALIZED_BY`,
`DERIVED_FROM`, `HAS_CONFIDENCE`, `RECOMMENDS`.

`evidence_type → node_type` mapping (`graph._NODE_TYPE_FOR_EVIDENCE_TYPE`):
`KPI_MOVEMENT → MOVEMENT`, `DRIVER_CONTRIBUTION → DRIVER`,
`SEGMENT_CONTRIBUTION → SEGMENT`, everything else (`KPI_OBSERVATION`,
`ANOMALY_SIGNAL`, `STATISTICAL_RESULT`, `CONCURRENT_KPI`, `CUSTOMER_REVIEW`) `→ EVIDENCE`.

The graph is a `networkx.MultiDiGraph`, deliberately — a plain `DiGraph`
would let a later `CONTRADICTS` edge silently overwrite an existing
`SUPPORTED_BY` edge between the same two nodes. `MultiDiGraph` lets both
coexist (verified by
`test_graph.py::test_contradicts_and_supported_by_can_coexist_between_same_nodes`).

## 2. Worked November 2017 example

```
kpi_revenue --HAS_MOVEMENT--> [Revenue Nov 2017 movement, +52.1%]
                                       |
                                 EXPLAINED_BY
                          /            |            \
                     volume         price          mix
                   (+417,227.65) (+4,674.63)   (-75,850.34)

kpi_avg_delivery_days --HAS_MOVEMENT--> [Delivery Nov 2017 movement, +27.87%]
                                                |
                                          SUPPORTED_BY
                                    /      |      |      \
                              review   review  review   review   (Nov 2017
                                                                   delivery-
                                                                   related
                                                                   reviews)
```

Built by `graph.build_november_2017_graph(kpi_movement_evidence, driver_evidence,
delivery_review_evidence)`. Every `MOVEMENT`/`DRIVER` node additionally gets a
`HAS_CONFIDENCE` edge to its own `CONFIDENCE` node (`add_confidence_node`),
making confidence independently queryable rather than buried in node
attributes.

In the real built graph (`reports/step4_validation.json::graph_summary`):
**39 nodes, 29 edges**, node types
`{CONFIDENCE, DRIVER, EVIDENCE, INVESTIGATION, KPI, MOVEMENT}`, relationship
types `{EXPLAINED_BY, HAS_CONFIDENCE, HAS_MOVEMENT, SUPPORTED_BY}` (no
`CONTRADICTS` edge was added in that particular run — see §3).

## 3. Contradiction model — real statistics, never fabricated

`graph.check_low_score_rate_contradiction(previous_scores, current_scores)`
runs a standard two-proportion z-test (pooled variance) comparing the share
of `review_score <= 2` between two periods for one category. It returns
`contradicts=True` only when that rate did **not** increase (flat or
decreased) — i.e. genuinely inconsistent with a "things got worse" story —
never a made-up signal.

`graph.add_contradiction_check(g, movement_node_id, check, stat_node_id)`
adds a `CONTRADICTS` edge only if `check.contradicts` is `True`. It never
deletes, downgrades, or otherwise touches the movement node
(`test_graph.py::test_contradiction_is_never_auto_resolved` asserts the
movement node's attributes are byte-identical before and after).

**In the real November 2017 package**: every one of the 9 top revenue-mover
product categories with sufficient sample (n≥15 both periods) — bed_bath_table,
health_beauty, furniture_decor, watches_gifts, toys, computers_accessories,
garden_tools, housewares, sports_leisure — showed the low-score rate
**increasing** alongside the delivery slowdown (z-scores from 0.62 to 4.46).
None triggered a contradiction, so no `CONTRADICTS` edge appears in
`reports/step4_validation.json`'s graph. That is the honest, real result —
this build does not search past the principled "top revenue movers" set
looking for a category that would produce a contradiction.

The mechanism itself is demonstrated working on real data in
`tests/test_graph.py` using the `electronics` category (not a top-10 revenue
mover, but present in the same corpus), whose low-score rate genuinely
*decreased* from October to November (18.2% → 15.3%, z=-0.50) despite the
overall delivery slowdown — a real, verifiable contradiction case.

## 4. Access control at query time

`graph.query_graph(g, requester_clearance)` is the only sanctioned read path
into a built graph from outside `graph.py` — it always routes through
`access_control.filter_graph()`. See `docs/RAG_GOVERNANCE.md` §3 and
`src/evidence/access_control.py` for how node/edge/count/error-message
leakage is prevented.

## 5. Rebuild and determinism guarantee

Building the graph involves no randomness: node IDs are the evidence
objects' own deterministic `evidence_id`s (or fixed prefixes like
`kpi_{kpi_id}`/`investigation_{id}`/`confidence_of_{evidence_id}`), and edges
are added in a fixed order from already-computed evidence lists.
`tests/test_traceability.py::test_november_revenue_movement_evidence_id_reproducible_across_runs`
and the review-evidence equivalent confirm two independent builds produce
identical evidence IDs; by extension, the graph built from them has the same
node set and edge relationships each time.
