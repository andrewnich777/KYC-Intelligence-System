#!/usr/bin/env python3
"""Run all test cases and save results.

Usage:
    python run_all_cases.py              # Run all cases
    python run_all_cases.py --cases 4 5  # Run specific case numbers
"""
import argparse
import glob
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description="Batch runner for KYC test cases")
    parser.add_argument("--cases", nargs="*", type=int, help="Specific case numbers to run (e.g. 4 5 6 7)")
    parser.add_argument("--non-interactive", action="store_true", default=True,
                        help="Run in non-interactive mode (default: True)")
    args = parser.parse_args()

    cases = sorted(glob.glob("test_cases/case*.json"))
    if not cases:
        print("No test cases found in test_cases/")
        sys.exit(1)

    if args.cases:
        cases = [c for c in cases if any(f"case{n}" in c for n in args.cases)]

    results = []
    for case_file in cases:
        print(f"\n{'=' * 60}")
        print(f"Running: {case_file}")
        print(f"{'=' * 60}")

        cmd = [sys.executable, "main.py", "--client", case_file]
        if args.non_interactive:
            cmd.append("--non-interactive")

        result = subprocess.run(cmd)
        status = "COMPLETE" if result.returncode == 0 else f"FAILED (exit {result.returncode})"
        print(f"  {status}: {case_file}")
        results.append((case_file, result.returncode))

    # Summary
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    passed = sum(1 for _, rc in results if rc == 0)
    for case_file, rc in results:
        icon = "OK" if rc == 0 else "FAIL"
        print(f"  [{icon}] {case_file}")
    print(f"\n{passed}/{len(results)} cases completed successfully")


if __name__ == "__main__":
    main()
