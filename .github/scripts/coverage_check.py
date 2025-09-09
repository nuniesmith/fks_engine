#!/usr/bin/env python
from __future__ import annotations
import os, sys, xml.etree.ElementTree as ET, argparse
from pathlib import Path

def file(explicit: str | None):
    for name in ([explicit] if explicit else []) + ["coverage-combined.xml", "coverage.xml"]:
        if name and Path(name).is_file():
            return Path(name)
    return None

def rate(p: Path) -> float:
    root = ET.parse(p).getroot()
    r = root.get('line-rate')
    if r is None:
        raise RuntimeError('line-rate missing')
    return float(r) * 100

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--percent-file', default=None)
    args = parser.parse_args()
    xml = file(os.getenv('COVERAGE_FILE'))
    if not xml:
        print('COVERAGE: no xml (skip)')
        return 0
    try:
        pct = rate(xml)
    except Exception as e:
        print(f'COVERAGE: parse error {e}')
        return 0
    thr_raw = os.getenv('COVERAGE_FAIL_UNDER')
    try:
        thr = float(thr_raw) if thr_raw else None
    except ValueError:
        thr = None
        print(f'COVERAGE: invalid threshold {thr_raw!r}')
    if args.percent_file:
        try:
            with open(args.percent_file, 'w') as f:
                f.write(f'{pct:.2f}\n')
        except OSError as e:
            print(f'COVERAGE: write error {e}')
    summary_path = os.getenv('GITHUB_STEP_SUMMARY')
    if summary_path:
        try:  # pragma: no cover
            with open(summary_path, 'a') as f:
                f.write(f"\n### Coverage\n\nObserved: {pct:.2f}%\n")
        except OSError:
            pass
    hard_fail = os.getenv('COVERAGE_HARD_FAIL') == '1'
    if thr is None:
        print(f'COVERAGE: observed {pct:.2f}% (soft)')
        return 0
    if pct + 1e-9 < thr:
        if hard_fail:
            print(f'COVERAGE: {pct:.2f}% below {thr:.2f}% (FAIL)')
            return 1
        print(f'COVERAGE: {pct:.2f}% below {thr:.2f}% (soft fail)')
        return 0
    print(f'COVERAGE: {pct:.2f}% meets {thr:.2f}%')
    return 0

if __name__ == '__main__':
    sys.exit(main())
