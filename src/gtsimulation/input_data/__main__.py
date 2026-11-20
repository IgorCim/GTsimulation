"""Command-line interface for reproducible GT input preparation."""
import argparse
import json
import subprocess
from .omni import download_tsyganenko_inputs
from .atmosphere import download_atmosphere_inputs
from .ta15 import download_ta15_inputs


def main():
    parser = argparse.ArgumentParser(description="Download external GT drivers: T89/T96, T15B, NRLMSIS.")
    parser.add_argument("--start", required=True, help="UTC start, inclusive (ISO 8601)")
    parser.add_argument("--end", required=True, help="UTC end, exclusive (ISO 8601)")
    parser.add_argument("--model", choices=["89", "96", "15B", "nrlmsis"], default="96")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--allow-provider-interpolation", action="store_true", help="TA15 only: accept provider quality flag 2")
    args = parser.parse_args()
    if args.allow_provider_interpolation and args.model != "15B":
        parser.error("--allow-provider-interpolation requires --model 15B")
    try:
        if args.model == "15B":
            result = download_ta15_inputs(args.start, args.end, args.output_dir, allow_interpolated=args.allow_provider_interpolation)
        elif args.model == "nrlmsis":
            result = download_atmosphere_inputs(args.start, args.end, args.output_dir)
        else:
            result = download_tsyganenko_inputs(args.start, args.end, args.output_dir, model=args.model)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Input preparation failed: {exc}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
