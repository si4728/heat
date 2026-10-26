import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from iris2.server import create_listener


class ExclusiveServerTests(unittest.TestCase):
    def test_second_listener_cannot_share_the_port(self):
        first = create_listener('127.0.0.1', 0)
        try:
            first.listen(1)
            with self.assertRaises(OSError):
                create_listener('127.0.0.1', first.getsockname()[1])
        finally:
            first.close()
