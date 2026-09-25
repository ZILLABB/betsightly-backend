"""Read-only Builder settlement reconciliation for 2026-09-15 through 24."""

import argparse
import json
import sys

from leagues.builder_reconciliation import reconcile_builder_predictions


def main() -> int:
    # No --apply option by design.  A repair path requires separately reviewed
    # production results and explicit authorisation.
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(json.dumps(reconcile_builder_predictions(), indent=2,
                     sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
