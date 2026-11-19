"""Command-line interface for reproducible OMNI input preparation."""
import argparse
import json
from .omni import download_tsyganenko_inputs


def main():
    parser = argparse.ArgumentParser(description="Download NASA OMNI drivers for GT T89/T96.")
    parser.add_argument("--start", required=True, help="UTC hour, inclusive (ISO 8601)")
    parser.add_argument("--end", required=True, help="UTC hour, exclusive (ISO 8601)")
    parser.add_argument("--model", choices=["89", "96"], default="96")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    try:
        result = download_tsyganenko_inputs(args.start, args.end, args.output_dir, model=args.model)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Input preparation failed: {exc}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
