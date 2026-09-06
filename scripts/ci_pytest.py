"""Run every test file in exactly one CI shard, retaining bounded failure details."""
import argparse
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard", type=int, required=True)
    parser.add_argument("--shards", type=int, default=4)
    args = parser.parse_args()
    if not 0 <= args.shard < args.shards:
        parser.error("shard must be in [0, shards)")
    root = Path(__file__).resolve().parents[1]
    files = sorted(root.joinpath("tests").glob("test_*.py"))[args.shard::args.shards]
    if not files:
        parser.error("shard has no test files")
    output = root / ".verification"
    output.mkdir(exist_ok=True)
    report = output / f"pytest-{args.shard}.xml"
    command = [sys.executable, "-u", "-m", "pytest", "-vv", "--maxfail=1",
               "--tb=short", "--durations=10", f"--junitxml={report}",
               *[str(path.relative_to(root)) for path in files]]
    with (
        (output / f"pytest-{args.shard}.log").open("w", encoding="utf-8") as log,
        subprocess.Popen(command, cwd=root, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                         errors="replace") as process,
    ):
        for line in process.stdout:
            print(line, end="", flush=True)
            log.write(line)
            log.flush()
        code = process.wait()
    if report.exists():
        for case in ET.parse(report).iter("testcase"):
            for result in case:
                if result.tag in {"failure", "error"}:
                    detail = f"{case.get('classname')}::{case.get('name')}: {result.text}"[:3000]
                    detail = detail.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
                    print(f"::error title=Python test failure::{detail}", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
