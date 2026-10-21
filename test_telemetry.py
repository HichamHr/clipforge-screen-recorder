import tempfile
import unittest
from unittest.mock import MagicMock, patch

from clipforge_telemetry import Telemetry


class TelemetryTests(unittest.TestCase):
    def test_http_allowed_only_for_loopback(self):
        client = Telemetry.__new__(Telemetry)
        for endpoint in ('http://localhost:3000/api', 'http://127.0.0.1:3000/api',
                         'http://[::1]:3000/api', 'https://clipforge.hichamhr.com/api'):
            client.endpoint = endpoint
            self.assertTrue(client.configured, endpoint)
        for endpoint in ('http://example.com/api', 'http://localhost.evil.example/api',
                         'https://user:password@example.com/api', ''):
            client.endpoint = endpoint
            self.assertFalse(client.configured, endpoint)

    def test_opt_in_event_posts_to_api_and_clears_outbox(self):
        with tempfile.TemporaryDirectory() as directory, patch('clipforge_telemetry.threading.Thread'):
            client = Telemetry(directory, '1.3.0', 'http://localhost:3000/api', enabled=True)
            self.assertTrue(client.track('app_opened'))
            response = MagicMock()
            response.__enter__.return_value.status = 202
            with patch('clipforge_telemetry.urllib.request.urlopen', return_value=response) as send:
                client.flush()
            self.assertEqual(send.call_args.args[0].full_url, 'http://localhost:3000/api/v1/events')
            with client.connect() as db:
                self.assertEqual(db.execute('select count(*) from outbox').fetchone()[0], 0)
            client.close()

    def test_analytics_off_does_not_queue_launches(self):
        with tempfile.TemporaryDirectory() as directory, patch('clipforge_telemetry.threading.Thread'):
            client = Telemetry(directory, '1.3.0', 'http://localhost:3000/api', enabled=False)
            self.assertFalse(client.track('app_opened'))
            client.close()


if __name__ == '__main__':
    unittest.main()
