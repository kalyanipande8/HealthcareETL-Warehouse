"""End-to-end pipeline runner:

  1. Simulate raw extracts from 3 source systems (sources/simulate_sources.py)
  2. Extract   -- read each source's raw file in its native schema
  3. Transform -- standardize into a common warehouse vocabulary
  4. Validate  -- automated data quality checks, computes real accuracy %
  5. Load      -- load dims + facts into the SQLite star-schema warehouse
  6. Run example analytics queries against the finished warehouse

Usage: python run_all.py
"""
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from sources import simulate_sources
from etl import extract, quality, transform, load, analytics_queries

DATA_DIR = BASE_DIR / "data"


def main():
    print("=" * 70)
    print("STEP 1/5: Simulating raw extracts from 3 source systems")
    print("=" * 70)
    simulate_sources.main()

    print("\n" + "=" * 70)
    print("STEP 2/5: Extracting raw source files")
    print("=" * 70)
    raw = extract.extract_all()
    for source, rows in raw.items():
        print(f"  {source}: {len(rows)} records extracted")

    print("\n" + "=" * 70)
    print("STEP 3/5: Validating data quality")
    print("=" * 70)
    validated, report = quality.run_validation(raw)
    quality.save_report(report)
    for source, stats in report["sources"].items():
        print(f"  {source}: {stats['passed']}/{stats['total_records']} passed "
              f"({stats['accuracy_pct']}% accuracy)")
    print(f"  OVERALL: {report['total_passed']}/{report['total_records']} passed "
          f"({report['overall_accuracy_pct']}% accuracy)")

    print("\n" + "=" * 70)
    print("STEP 4/5: Transforming + loading into warehouse")
    print("=" * 70)
    standardized = transform.transform_all(validated)
    load_stats = load.load_all(standardized, report)
    print(f"  Warehouse: {DATA_DIR / 'warehouse.db'}")
    for k, v in load_stats.items():
        print(f"  {k}: {v}")

    print("\n" + "=" * 70)
    print("STEP 5/5: Running example analytics queries")
    print("=" * 70)
    analytics_queries.run_all_queries()

    summary = {
        "quality_report": report,
        "load_stats": load_stats,
    }
    with open(DATA_DIR / "run_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print("\n" + "=" * 70)
    print(f"DONE. Overall data quality accuracy: {report['overall_accuracy_pct']}%")
    print(f"Warehouse at: {DATA_DIR / 'warehouse.db'}")
    print("=" * 70)


if __name__ == "__main__":
    main()
