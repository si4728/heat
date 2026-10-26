from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import select

# Reuse the existing suite's disposable database and configuration.
from iris2 import test_app as fixtures
from iris2.app import create_app
from iris2.application.organization_service import save_organization_code
from iris2.hx_configuration import DB_PATH
from iris2.iris_v2_database import init_v2_db, session_scope
from iris2.iris_v2_models import Equipment, HeatExchanger, OrganizationCode, Plant


class OrganizationCodesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app({"TESTING": True, "SECRET_KEY": "organization-test"})
        cls.client = cls.app.test_client()

    def root_id(self):
        with session_scope(DB_PATH) as session:
            return session.scalar(select(OrganizationCode.organization_code_id).where(
                OrganizationCode.kind == "PLANT", OrganizationCode.code == "P1"))

    def test_labels_are_used_by_equipment_pages_and_survive_initialization(self):
        team_id = save_organization_code({"kind": "TEAM", "parent_id": self.root_id(),
                                         "code": "LABEL-TEAM", "label": "표시용 생산팀"})
        process_id = save_organization_code({"kind": "PROCESS", "parent_id": team_id,
                                            "code": "LABEL-PROCESS", "label": "표시용 공정"})
        with session_scope(DB_PATH) as session:
            hx = session.scalar(select(HeatExchanger).order_by(HeatExchanger.heat_exchanger_id))
            equipment = session.get(Equipment, hx.equipment_id)
            exchanger_id, equipment_id = hx.heat_exchanger_id, equipment.equipment_id
            old = equipment.production_team_code, equipment.process_code
            equipment.production_team_code = "LABEL-TEAM"
            equipment.process_code = "LABEL-PROCESS"
        try:
            save_organization_code({"label": "변경된 공정 설명"}, process_id)
            init_v2_db(DB_PATH)
            for path in ("/exchangers?team=LABEL-TEAM&process=LABEL-PROCESS",
                         f"/exchangers/{exchanger_id}", f"/exchangers/{exchanger_id}/edit"):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assertIn("울산공장", html)
                self.assertIn("표시용 생산팀", html)
                self.assertIn("변경된 공정 설명", html)
            with session_scope(DB_PATH) as session:
                self.assertEqual(session.get(Equipment, equipment_id).process_code, "LABEL-PROCESS")
        finally:
            with session_scope(DB_PATH) as session:
                equipment = session.get(Equipment, equipment_id)
                equipment.production_team_code, equipment.process_code = old

    def test_hierarchy_validation_and_duplicate_process_context(self):
        root = self.root_id()
        with self.assertRaises(ValueError):
            save_organization_code({"kind": "PROCESS", "parent_id": root,
                                    "code": "BAD", "label": "잘못된 상위 조직"})
        ids = []
        for team in ("CONTEXT-A", "CONTEXT-B"):
            parent = save_organization_code({"kind": "TEAM", "parent_id": root,
                                            "code": team, "label": team})
            ids.append(save_organization_code({"kind": "PROCESS", "parent_id": parent,
                                              "code": "SAME", "label": team + " 공정"}))
        self.assertNotEqual(*ids)
        with self.assertRaises(ValueError):
            save_organization_code({"kind": "PLANT", "code": "P1", "label": "중복 공장"})

    def test_code_screen_edits_labels_without_changing_codes(self):
        root = self.root_id()
        response = self.client.post(f"/master-data/organization-codes/{root}", data={
            "label": "울산공장 표시 테스트", "code": "P999", "kind": "PROCESS",
        }, follow_redirects=True)
        try:
            self.assertEqual(response.status_code, 200)
            self.assertIn("울산공장 표시 테스트", self.client.get("/exchangers").get_data(as_text=True))
            with session_scope(DB_PATH) as session:
                self.assertEqual(session.get(OrganizationCode, root).code, "P1")
                self.assertEqual(session.scalar(select(Plant.plant_name).where(Plant.plant_code == "P1")), "울산공장 표시 테스트")
        finally:
            save_organization_code({"label": "울산공장"}, root)

    def test_access_control_and_csrf(self):
        app = create_app({"TESTING": True, "AUTH_DISABLED": False, "CSRF_ENABLED": False})
        client = app.test_client()
        with client.session_transaction() as session:
            session["user_id"] = 99
        with patch("iris2.services.user_count", return_value=1), patch(
            "iris2.services.user_access_profile", return_value={"is_admin": False}
        ), patch("iris2.services.user_can", side_effect=lambda profile, screen, edit=False: not edit):
            self.assertEqual(client.get("/master-data/organization-codes").status_code, 200)
            self.assertEqual(client.post("/master-data/organization-codes", data={}).status_code, 403)
        csrf_app = create_app({"TESTING": True, "CSRF_ENABLED": True})
        self.assertEqual(csrf_app.test_client().post("/master-data/organization-codes", data={}).status_code, 400)

    def test_equipment_form_rejects_process_from_another_factory(self):
        from iris2 import services
        root = save_organization_code({"kind": "PLANT", "code": "P99", "label": "검증 공장"})
        team = save_organization_code({"kind": "TEAM", "parent_id": root,
                                      "code": "FORM-TEAM", "label": "검증 생산팀"})
        process = save_organization_code({"kind": "PROCESS", "parent_id": team,
                                         "code": "FORM-PROCESS", "label": "검증 공정"})
        form = fixtures.IrisSystemTest.mandatory_exchanger_form(
            equipment_code="INVALID-ORG-TEST", organization_process_id=str(process))
        with self.assertRaisesRegex(ValueError, "소속 공장"):
            services.save_exchanger(form, enforce_master_mandatory=True)
        with session_scope(DB_PATH) as session:
            self.assertIsNone(session.scalar(select(Equipment).where(
                Equipment.equipment_code == "INVALID-ORG-TEST")))


if __name__ == "__main__":
    unittest.main()
