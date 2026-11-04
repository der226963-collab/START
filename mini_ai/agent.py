"""General-agent scaffold: retrieve, reason, call a tool, observe.

This is a beginning, not AGI. It is a small, auditable loop in the
ReAct pattern (Yao et al., 2022): Thought, Action, Observation,
repeated until the agent has enough to answer or hits its step
limit. The router here is rule-based and transparent, not a
language model pretending to decide: keywords route to a named
tool, the tool result is recorded verbatim in the trace, and the
final answer says what is still unknown.

What this agent can do:
  - retrieve: search local data/*.txt for passages, with file names
  - call planning tools: food balance, soil, climate backtest,
    plan-limits check, electricity allocation
  - keep a short working memory of past questions and answers
  - self-critique: flag breaches, unknowns, and missing data

What it cannot do, by design:
  - decide a plan, allocate to a real community, or approve an edit
  - run code, change files, contact anyone, or spend anything
  - present retrieved text or a tool result as its own knowledge
    without the source in the trace

Every answer from this agent carries needs_human_decision=True
when it touches a plan, an allocation, or a limit. A human
assembly decides. This module checks and explains.
"""
import json
import re
from pathlib import Path

from mini_ai.planning import (
    backtest_climate,
    check_plan_limits,
    climate_trend,
    electricity_allocation,
    food_balance,
    load_snapshot,
    soil_summary,
)

STOPWORDS = {"the", "a", "an", "is", "are", "what", "how", "why", "does", "do", "of", "in", "on", "to", "for", "and", "or"}


def _words(text):
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS]


def retrieve(query, data_dir="data", top_k=3):
    """Keyword retrieval over local .txt files, stdlib only.

    Scores a paragraph by shared-word count, with a small bonus
    for rare words (a crude IDF). Returns file, paragraph, score.
    This is not semantic search; it finds words, not meanings.
    """
    query_words = set(_words(query))
    if not query_words:
        return []
    # First pass: document frequency for IDF weighting.
    files = sorted(Path(data_dir).glob("*.txt"))
    paragraphs = []
    for f in files:
        for para in f.read_text().split("\n\n"):
            para = para.strip()
            if len(para) > 40:
                paragraphs.append((f.name, para))
    df = {}
    for _, para in paragraphs:
        for w in set(_words(para)):
            df[w] = df.get(w, 0) + 1
    scored = []
    for fname, para in paragraphs:
        words = set(_words(para))
        shared = query_words & words
        if not shared:
            continue
        import math

        score = sum(math.log(1 + len(paragraphs) / (1 + df[w])) for w in shared)
        scored.append({"file": fname, "text": para[:600], "score": round(score, 2)})
    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored[:top_k]


class Memory:
    """Short working memory, kept in a local JSON file if asked.

    This is not a person's memory and not a database of users.
    It stores questions, tool calls, and answers from this agent's
    own runs, so a later run can see what it already checked.
    """

    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.records = []
        if self.path and self.path.exists():
            self.records = json.loads(self.path.read_text())

    def add(self, question, answer, tools_used):
        self.records.append({"question": question, "answer": answer, "tools_used": tools_used})
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.records, indent=2))

    def recent(self, n=5):
        return self.records[-n:]


def _parse_number(text, word):
    match = re.search(rf"(\d+(?:\.\d+)?)\s*(?:tg|million|billion)?\s*{word}", text.lower())
    return float(match.group(1)) if match else None


class Agent:
    def __init__(self, data_dir="data", memory=None):
        self.data_dir = data_dir
        self.memory = memory or Memory()
        self.rows = load_snapshot(f"{data_dir}/real_planning_data.csv")

    def run(self, question, max_steps=5):
        trace = []
        tools_used = []
        q = question.lower()
        answer_parts = []

        def step(thought, action, observation):
            trace.append({"thought": thought, "action": action, "observation": observation})
            tools_used.append(action)

        # Step 1: always retrieve first, so answers are grounded.
        if len(trace) < max_steps:
            passages = retrieve(question, self.data_dir, top_k=2)
            step("I need evidence from local data before answering, not a guess.",
                 "retrieve",
                 passages if passages else "No passage found. Say so, do not invent one.")
            if passages:
                answer_parts.append("Retrieved from: " + ", ".join(p["file"] for p in passages))

        # Step 2: route to a planning tool by keyword, transparently.
        if "phosphorus" in q or "limit" in q:
            value = _parse_number(q, "phosphorus")
            plan = {"phosphorus_application_tg_per_year": value if value is not None else 18.2}
            result = check_plan_limits(plan, self.rows)
            step("Phosphorus has a stored boundary, so check the plan against it.",
                 "check_plan_limits", result)
            answer_parts.append(f"Plan-limits check: passes={result['passes_checked_limits']}, failed={result['failed_count']}.")
        elif "food" in q or "kcal" in q:
            result = food_balance(self.rows)
            step("Food needs arithmetic, not language, so use the calculation layer.",
                 "food_balance", result)
            answer_parts.append(f"Food balance: supply {result['supply_kcal_per_capita_per_day_2022']} kcal/day vs need {result['planning_need_kcal_per_capita_per_day_assumption']} kcal/day (assumption), surplus {result['surplus_kcal_per_capita_per_day']} kcal/day on global average only.")
        elif "soil" in q:
            result = soil_summary(self.rows)
            step("Soil needs the nutrient summary, with its boundary figures.",
                 "soil_summary", result)
            answer_parts.append(f"Soil: phosphorus excess {result['phosphorus_excess_tg_per_year']} Tg/year over a {result['phosphorus_regional_boundary_tg_per_year']} Tg boundary.")
        elif "backtest" in q or "predict" in q:
            result = backtest_climate()
            step("A predictive claim needs a backtest on held-out years first.",
                 "backtest_climate", result)
            answer_parts.append(f"Backtest: temperature RMSE {result['temperature_anomaly']['rmse']}, bias {result['temperature_anomaly']['bias_mean_predicted_minus_actual']}. Linear extrapolation under-predicts.")
        elif "climate" in q or "temperature" in q or "co2" in q:
            result = climate_trend()
            step("Climate needs the full series, not a single year.",
                 "climate_trend", result)
            answer_parts.append(f"Climate trend: CO2 {result['co2_1959_ppm']} ppm in 1959 to {result['co2_2025_ppm']} ppm in 2025, increase {result['co2_increase_ppm_1959_2025']} ppm.")
        elif "electricity" in q or "energy" in q:
            mix = {"coal": 0.10, "gas": 0.15, "solar": 0.30, "wind": 0.20, "hydro": 0.15, "nuclear": 0.10}
            result = electricity_allocation(30000, mix)
            step("Energy needs an allocation calculation with stated intensities.",
                 "electricity_allocation", result)
            answer_parts.append(f"Low-carbon example on 30,000 TWh: {result['total_co2_million_tonnes']} Mt CO2 (illustrative mix, not a measured grid).")

        # Self-critique step, always.
        critique = []
        if not answer_parts:
            critique.append("No tool result matched this question. Do not answer from language alone.")
        if any(isinstance(t.get("observation"), dict) and t["observation"].get("passes_checked_limits") is False for t in trace):
            critique.append("A checked limit failed. Flag it, do not soften it.")
        if any(isinstance(t.get("observation"), dict) and "unknown" in str(t["observation"]) for t in trace):
            critique.append("Some limits are unknown. Report them as unknown.")
        trace.append({"thought": "Critique my own answer before finishing.", "action": "self_critique", "observation": critique or ["No breach found in the checked limits."]})

        final = " ".join(answer_parts) if answer_parts else "I do not have a tool result for this question, so I will not guess an answer."
        final += " Human decision required for any plan, allocation, or limit change."
        self.memory.add(question, final, tools_used)
        return {
            "question": question,
            "trace": trace,
            "answer": final,
            "needs_human_decision": True,
            "is_agi": False,
            "note": "General-agent scaffold only: retrieve, calculate, critique, and stop. Not AGI, not a decider.",
        }


if __name__ == "__main__":
    import sys

    agent = Agent()
    result = agent.run(" ".join(sys.argv[1:]) or "What is the phosphorus limit?")
    print(json.dumps(result, indent=2))
