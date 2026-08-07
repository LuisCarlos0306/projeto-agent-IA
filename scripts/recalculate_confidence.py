from __future__ import annotations

import argparse
import json

from app.db.base import ensure_database_schema
from app.services.confidence_backfill import backfill_confidence


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recalcula a confiança das investigações usando evidências já persistidas."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Grava as mudanças no PostgreSQL. Sem esta opção executa somente uma simulação.",
    )
    args = parser.parse_args()

    ensure_database_schema()
    result = backfill_confidence(apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
