#!/usr/bin/env python3
"""CLI giriş noktası.

Kullanım:
  python scripts/run.py generate --project ankara
  python scripts/run.py publish  --project ankara
  python scripts/run.py dry-run  --project ankara
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import pipeline  # noqa: E402

# .env dosyasını (varsa) yerel testler için otomatik yükle.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass


def main() -> None:
    parser = argparse.ArgumentParser(description="RSS -> LLM -> Görsel -> Instagram pipeline")
    parser.add_argument("stage", choices=["generate", "publish", "dry-run"])
    parser.add_argument("--project", required=True, help="projects/<isim>/config.yaml")
    args = parser.parse_args()

    if args.stage == "generate":
        pipeline.generate(args.project)
    elif args.stage == "publish":
        pipeline.publish(args.project)
    elif args.stage == "dry-run":
        pipeline.dry_run(args.project)


if __name__ == "__main__":
    main()
