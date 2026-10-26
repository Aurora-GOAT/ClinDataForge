import argparse
import json
from clinforge.artifacts import write_json_no_overwrite
from clinforge.stress import stress_eval


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="reports/stress_eval.json")
    parser.add_argument("--n", type=int, default=60)
    args = parser.parse_args(argv)
    result = stress_eval(args.n)
    write_json_no_overwrite(args.out, result)
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
