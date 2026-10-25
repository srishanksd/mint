from flask import Blueprint, request, jsonify
from datetime import datetime
from database import get_db_connection
from agents.orchestrator import RealMINTOrchestrator

experiments_bp = Blueprint("experiments", __name__)
orchestrator = RealMINTOrchestrator()

ALLOWED_RISK_PROFILES = {"conservative", "balanced", "growth"}

@experiments_bp.route("/api/experiments/create_and_run", methods=["POST"])
def create_and_run():
    data = request.get_json(silent=True) or {}

    name = str(data.get("name", "Autonomous Venture Run")).strip()[:100] or "Autonomous Venture Run"
    goal = str(data.get("goal", "")).strip()[:300]
    if not goal:
        goal = "Find profitable digital product with high margin"

    try:
        budget = float(data.get("budget_limit", 50.0))
    except (ValueError, TypeError):
        return jsonify({"error": "budget_limit must be a numeric value"}), 400

    if budget < 5.0 or budget > 5000.0:
        return jsonify({"error": "budget_limit must be between $5.00 and $5,000.00"}), 400

    risk_profile = str(data.get("risk_profile", "balanced")).strip().lower()
    if risk_profile not in ALLOWED_RISK_PROFILES:
        risk_profile = "balanced"

    conn = get_db_connection()
    cur = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""
        INSERT INTO experiments (name, goal, business_model, target_audience, budget_limit, status, hypothesis, created_at, updated_at)
        VALUES (?, ?, 'evaluating', 'evaluating', ?, 'running', 'Autonomous venture funnel test', ?, ?)
    """, (name, goal, budget, now, now))
    conn.commit()
    exp_id = cur.lastrowid
    conn.close()

    # Pre-populate all 9 architecture nodes in 'waiting' state
    from database import update_agent_status
    initial_nodes = [
        ("Opportunity Scout", f"Goal: {goal}", "Waiting to scan market niches..."),
        ("Strategy Agent", "Awaiting scout candidates", "Waiting to evaluate unit economics..."),
        ("MINT Orchestrator", "Awaiting strategy selection", "Waiting to initialize execution graph..."),
        ("Content Creator", "Awaiting strategic direction", "Waiting to synthesize copy and render media..."),
        ("Quality Checker", "Awaiting generated artifacts", "Waiting to audit compliance and claims..."),
        ("Publishing Agent", "Awaiting artifact compliance check", "Waiting to verify platform credentials..."),
        ("Measurement Agent", "Awaiting product deployment", "Waiting for authentic traffic events..."),
        ("Finance Agent", "Awaiting transaction logs", "Waiting to reconcile orders and cash reserves..."),
        ("Portfolio Manager", "Awaiting net cash surplus", "Waiting to balance surplus allocation..."),
    ]
    for agent_name, task, desc in initial_nodes:
        update_agent_status(exp_id, agent_name, "waiting", input_summary=task, output_summary=desc, decision_reason="Awaiting preceding pipeline stage.")

    # Prevent starting concurrent duplicate if an experiment is actively executing
    if orchestrator.is_experiment_running(exp_id):
        return jsonify({"status": "rejected", "message": "Experiment is already actively running."}), 409

    # Trigger asynchronous background pipeline
    started = orchestrator.run_pipeline_async(exp_id, risk_profile=risk_profile)
    if not started:
        return jsonify({"status": "rejected", "message": "Pipeline already active for this experiment."}), 409

    return jsonify({
        "status": "started",
        "experiment_id": exp_id,
        "message": "Venture pipeline dispatched to background worker thread."
    })

@experiments_bp.route("/api/experiments/list")
def list_experiments():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM experiments ORDER BY id DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({"experiments": rows})
