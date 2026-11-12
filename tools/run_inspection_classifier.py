"""Reproducible offline training/inference for historical inspection classification."""
import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent))
from iris2.ml.inspection_classifier import train, predict_records, write_csv

def main():
    parser=argparse.ArgumentParser()
    subs=parser.add_subparsers(dest='action',required=True)
    training=subs.add_parser('train')
    training.add_argument('--source',type=Path,required=True)
    training.add_argument('--output',type=Path,required=True)
    training.add_argument('--as-of',type=date.fromisoformat,required=True)
    prediction=subs.add_parser('predict')
    prediction.add_argument('--model',type=Path,required=True)
    prediction.add_argument('--input',type=Path,required=True)
    prediction.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.action=='predict':
        import joblib
        with args.input.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
        scores=predict_records(joblib.load(args.model),rows)
        write_csv(args.output,[{**row,'historical_selection_score_full_fit':float(score)} for row,score in zip(rows,scores)])
        print(json.dumps({'predicted_rows':len(rows),'note':'Full-fit scores are not held-out evaluation metrics.'}));return
    from iris2.hx_configuration import DB_PATH
    from iris2.ml.readonly_db import readonly_connection
    with readonly_connection(DB_PATH) as conn:
        rows=[dict(r) for r in conn.execute("""SELECT h.heat_exchanger_id,e.equipment_code,e.install_date,u.unit_code,
            (SELECT COUNT(*) FROM iris_inspection i WHERE i.heat_exchanger_id=h.heat_exchanger_id) inspection_count
            FROM heat_exchanger h JOIN equipment e ON e.equipment_id=h.equipment_id
            JOIN process_unit u ON u.unit_id=e.unit_id WHERE u.unit_code IN ('VCM1','VCM2') ORDER BY h.heat_exchanger_id""")]
    print(json.dumps(train(args.source,rows,args.output,args.as_of),ensure_ascii=False,default=str))

if __name__=='__main__':main()
