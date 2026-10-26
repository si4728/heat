from pathlib import Path

import audit_2020_vcm1_pdf_json_20260825 as audit


ROOT = Path(__file__).resolve().parents[1]
audit.PDF_PATH = ROOT / "iris_test_report" / "2020_1P_PE.pdf"
audit.JSON_PATH = ROOT / "data" / "2020PE_IRIS2_all_tube_results.json"


if __name__ == "__main__":
    audit.main()
