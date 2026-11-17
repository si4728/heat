"""Provision only the specification SELECT grants required for fluid grouping."""
import argparse
from grant_text_to_sql_tube_history import apply


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', required=True)
    parser.parse_args()
    try:
        apply(tables=('heat_exchanger_spec_revision', 'heat_exchanger_side_spec'))
    except Exception as exc:
        print(f'Fluid specification grant update failed ({type(exc).__name__}).')
        raise SystemExit(1)
