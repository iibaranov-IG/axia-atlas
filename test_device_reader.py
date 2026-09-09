import socketserver
import threading
import unittest
from device_reader import parse_response, read_device

RESPONSE = (b'VER LWRP:1.1 DEVN:"LiveMic" SYSV:1.1.1 NSRC:2/1 NDST:2\r\r\n'
            b'BEGIN\r\r\nSRC 1 PSNM:"Test mic" RTPE:1 RTPA:"239.192.5.21"\r\r\n'
            b'SRC 2 PSNM:"" RTPE:0 RTPA:"239.192.5.22"\r\r\nEND\r\r\n')


class ReaderTests(unittest.TestCase):
    def test_enabled_and_disabled_sources_and_partial_response(self):
        result = parse_response(RESPONSE)
        self.assertEqual(result['device_type'], 'LiveMic')
        self.assertTrue(result['inspection_complete'])
        self.assertEqual(result['inspection_sources'][0]['channel'], 1301)
        self.assertTrue(result['inspection_sources'][0]['enabled'])
        self.assertFalse(result['inspection_sources'][1]['enabled'])
        self.assertFalse(parse_response(RESPONSE.split(b'SRC 2')[0])['inspection_complete'])
        with self.assertRaises(ValueError):
            parse_response(b'HTTP/1.1 200 OK\r\n')

    def test_socket_sends_only_status_queries_and_handles_fragments(self):
        observed = []
        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                data = bytearray()
                while not data.endswith(b'SRC\r\n'):
                    part = self.request.recv(1024)
                    if not part:
                        return
                    data.extend(part)
                observed.append(bytes(data))
                for offset in range(0, len(RESPONSE), 7):
                    self.request.sendall(RESPONSE[offset:offset + 7])
        with socketserver.TCPServer(('127.0.0.1', 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                result = read_device('127.0.0.1', port=server.server_address[1])
                self.assertTrue(result['inspection_complete'])
                self.assertEqual(observed, [b'VER\r\nSRC\r\n'])
            finally:
                server.shutdown()

    def test_empty_driver_addresses_and_unused_engine_slots(self):
        raw = (b'VER LWRP:1.2 DEVN:"lwwd" SVER:1.2 NSRC:2\r\nBEGIN\r\n'
               b'SRC 1 PSNM:"PC 2" RTPE:0 RTPA:""\r\nSRC 2\r\nEND\r\n')
        result = parse_response(raw)
        self.assertTrue(result['inspection_complete'])
        self.assertEqual(result['version_field'], 'SVER')
        self.assertEqual(result['firmware'], '1.2')
        self.assertIsNone(result['inspection_sources'][0]['channel'])
        self.assertFalse(result['inspection_sources'][0]['enabled'])
        self.assertIsNone(result['inspection_sources'][1]['enabled'])
