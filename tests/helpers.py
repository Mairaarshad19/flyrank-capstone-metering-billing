import os
import tempfile
import unittest

from app import create_app


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.db_path)  # let init_db create it fresh

        self.app = create_app(db_path=self.db_path)
        self.client = self.app.test_client()

        self._seed_tenants()

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _seed_tenants(self):
        from app.db import get_connection

        conn = get_connection(self.db_path)
        conn.execute("INSERT INTO tenants (id, name, plan) VALUES (1, 'Free Tenant', 'free')")
        conn.execute("INSERT INTO tenants (id, name, plan) VALUES (2, 'Pro Tenant', 'pro')")
        conn.commit()
        conn.close()
