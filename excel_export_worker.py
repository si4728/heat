"""Isolated workbook generation, invoked only by the export service."""
from argparse import ArgumentParser
from pathlib import Path

from iris2.excel_export import build_heat_exchanger_export


def main():
    parser = ArgumentParser()
    parser.add_argument('--db', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    workbook = build_heat_exchanger_export(Path(args.db))
    Path(args.output).write_bytes(workbook.getvalue())


if __name__ == '__main__':
    main()
