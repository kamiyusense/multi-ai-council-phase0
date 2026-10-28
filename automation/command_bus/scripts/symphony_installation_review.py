"""Print private prepare-only review packets. No install, seal or Codex execution."""
import argparse
import json
from pathlib import Path

from ..symphony_native_binary_preparation import BinaryPlacementReview, prepare_binary_placement
from ..symphony_sqlite_preparation import prepare_sqlite_review
from ..symphony_sqlite_storage import SQLiteStorageReview, ReviewedSQLiteStorage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest='mode', required=True)
    binary = modes.add_parser('binary')
    binary.add_argument('--source', required=True)
    binary.add_argument('--destination', required=True)
    binary.add_argument('--expected-sha256', required=True)
    binary.add_argument('--source-reference', required=True)
    binary.add_argument('--protected-root', action='append', required=True)
    storage = modes.add_parser('sqlite')
    storage.add_argument('--review-json', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.mode == 'binary':
            packet = prepare_binary_placement(BinaryPlacementReview(args.source,
                args.destination, args.expected_sha256, args.source_reference,
                tuple(args.protected_root)))
        else:
            raw = json.loads(args.review_json.read_text(encoding='utf-8'))
            if set(raw) != {'root','auth_home','executable','executable_sha256',
                            'migration_sha256','workspace_roots'}:
                raise PermissionError('exact operator review inputs required')
            review = SQLiteStorageReview(Path(raw['root']), Path(raw['auth_home']),
                Path(raw['executable']), raw['executable_sha256'], raw['migration_sha256'],
                tuple(Path(p) for p in raw['workspace_roots']))
            packet = prepare_sqlite_review(ReviewedSQLiteStorage(review=review,
                installation_check=lambda _: False))
        print(json.dumps(packet, sort_keys=True))
        return 0
    except Exception:
        # Never print paths, SQLite exceptions, private rows or account details.
        print(json.dumps({'status':'BLOCKED_UNVERIFIED','mode':'PREPARE_ONLY',
            'model_dispatch':0,'production_installed':False,'seal_created':False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
