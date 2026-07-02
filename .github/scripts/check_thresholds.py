import json
import sys
from pathlib import Path

RESULTS_DIR = Path("evaluation/results")

# Minimum acceptable scores — CI fails if these regress
THRESHOLDS = {
    "extraction_accuracy": 0.95,
    "regime_accuracy":     0.95,
    "avg_faithfulness":    0.60,
    "avg_relevance":       0.60,
}

def main():
    result_files = sorted(RESULTS_DIR.glob("eval_*.json"))
    if not result_files:
        print("No evaluation results found.")
        sys.exit(1)

    latest = result_files[-1]
    with open(latest) as f:
        data = json.load(f)

    summary = data["summary"]
    print(f"Checking thresholds against {latest.name}\n")

    failed = []
    for metric, min_score in THRESHOLDS.items():
        actual = summary.get(metric, 0)
        status = "PASS" if actual >= min_score else "FAIL"
        print(f"  {metric:<25} {actual:.3f}  (min: {min_score})  [{status}]")
        if actual < min_score:
            failed.append(metric)

    print()
    if failed:
        print(f"Threshold check FAILED for: {', '.join(failed)}")
        sys.exit(1)
    else:
        print("All thresholds passed.")
        sys.exit(0)

if __name__ == "__main__":
    main()