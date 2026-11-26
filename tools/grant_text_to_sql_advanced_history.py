"""Add only the two SELECT grants required for advanced equipment history."""
import argparse
from grant_text_to_sql_tube_history import apply


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true',required=True)
    parser.parse_args()
    try:apply(tables=('iris_inspection_summary_history','tube_plugging_event'))
    except Exception as exc:
        print(f'Advanced history SELECT grant update failed ({type(exc).__name__}).')
        raise SystemExit(1)
