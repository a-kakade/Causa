"""
api/ — the FastAPI HTTP layer over the existing Step 1-9 Python engines.

STRUCTURAL RULE: nothing under causa/api/ computes a business number, an
evidence classification, a recommendation, or a narrative claim. Every route
handler calls straight into src/ (kpi.engine.KPIEngine, anomaly.engine.detect,
drivers.engine.decompose, agents.orchestrator.run_investigation,
causal.engine.run_causal_analysis, decision.ranking.run_decision_pipeline,
story.engine.generate_kpi_story, src/feedback/*) and only translates the
result into JSON. No engine file under causa/src/ is modified by this layer.
"""
