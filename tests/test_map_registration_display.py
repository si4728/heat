import unittest
from types import SimpleNamespace
from unittest.mock import patch
from iris2.application.pdf_map_display import pdf_vector_display

class MapRegistrationDisplayTests(unittest.TestCase):
    def test_pdf_placeholder_is_not_a_registered_uninspected_tube(self):
        registered = dict(tube_id=7, tube_no='1-1', row=1, column=1,
                          managed=True, current_status='IN_SERVICE',
                          inspection_status='NOT_INSPECTED', category='NOT_INSPECTED')
        with patch('iris2.application.pdf_map_display.Path.stat', return_value=SimpleNamespace(st_mtime_ns=1, st_size=1)), patch('iris2.application.pdf_map_display._centers', return_value=((0, 0), (10, 0))):
            points = pdf_vector_display('fixture.pdf', 1, 2, 'fixture', [registered])
        self.assertEqual(len(points), 2)
        self.assertEqual(points[0]['tube_id'], 7)
        self.assertEqual(points[0]['category'], 'NOT_INSPECTED')
        self.assertEqual(registered['category'], 'NOT_INSPECTED')
        placeholder = points[1]
        self.assertIsNone(placeholder['tube_id'])
        self.assertFalse(placeholder['managed'])
        self.assertEqual(placeholder['category'], 'UNREGISTERED')
        self.assertEqual(placeholder['current_status'], 'UNKNOWN')
        self.assertEqual(placeholder['inspection_status'], 'UNKNOWN')

if __name__ == '__main__':
    unittest.main()
