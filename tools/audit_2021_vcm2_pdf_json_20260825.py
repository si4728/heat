from pathlib import Path

import audit_2021_vcm1_pdf_json_20260825 as audit


ROOT = Path(__file__).resolve().parents[1]
audit.PDF_PATH = ROOT / "iris_test_report" / "2021_1P_VCM2.pdf"
audit.JSON_PATH = ROOT / "data" / "2021VCM2_IRIS2_all_tube_results.json"


if __name__ == "__main__":
    audit.main()
