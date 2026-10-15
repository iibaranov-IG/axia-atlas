"""Offline acceptance faults. TCP endpoints bind to loopback only; no device writes."""
import socketserver
import threading
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from routing import read_destinations, parse_destinations
from scenarios import ScenarioJob, preflight

VER = b'VER LWRP:1.1 DEVN:LiveIO NDST:2\r\nBEGIN\r\n'
ONE = b'DST 1 ADDR:"239.192.0.1" NAME:"Monitor"\r\n'
TWO = b'DST 2 ADDR:"239.192.0.2" NAME:"Reserve"\r\n'

@contextmanager
def node_reply(reply):
    requests=[]
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.settimeout(1)
            data=b''
            while not data.endswith(b'DST\r\n'):
                part=self.request.recv(1024)
                if not part:return
                data+=part
            requests.append(data)
            try:self.request.sendall(reply)
            except (BrokenPipeError, ConnectionResetError):pass
    with socketserver.TCPServer(('127.0.0.1',0),Handler) as server:
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True)
        thread.start()
        try:yield server.server_address[1], requests
        finally:server.shutdown();thread.join(2)

class OfflineFaultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_disconnect_keeps_partial_observation_not_success(self):
        with node_reply(VER+ONE) as (port,requests):
            result=read_destinations('127.0.0.1',port=port,deadline_seconds=.5)
        self.assertFalse(result['complete'])
        self.assertEqual(len(result['destinations']),1)
        self.assertEqual(result['raw'],(VER+ONE).hex())
        self.assertEqual(requests,[b'VER\r\nDST\r\n'])
        plan=dict(name='Reserve',steps=[dict(ip='192.0.2.1',output=1,primary=1,backup=2)])
        with self.assertRaisesRegex(ValueError,'Partial'):
            preflight(plan,'backup',reader=lambda _:result)

    def test_end_marker_does_not_hide_missing_outputs(self):
        result=parse_destinations(VER+ONE+b'END\r\n')
        self.assertFalse(result['complete'])

    def test_device_rejection_is_not_empty_success(self):
        with node_reply(b'ERROR access denied\r\n') as (port,_):
            with self.assertRaises(ValueError):
                read_destinations('127.0.0.1',port=port,deadline_seconds=.5)

    def test_empty_response_is_not_zero_output_device(self):
        with node_reply(b'') as (port,_):
            with self.assertRaises(ValueError):
                read_destinations('127.0.0.1',port=port,deadline_seconds=.5)

    def test_large_response_is_bounded(self):
        with node_reply(b' ' * 270000) as (port,_):
            with self.assertRaisesRegex(ValueError,'too large'):
                read_destinations('127.0.0.1',port=port,deadline_seconds=1)

    def test_earlier_assignment_failure_stops_following_steps(self):
        steps=[dict(ip='192.0.2.1',output=i,before='239.192.0.1',after='239.192.0.2') for i in (1,2,3)]
        credentials={'192.0.2.1':'fixture-secret'}
        job=ScenarioJob(steps=steps,credentials=credentials)
        results=[];errors=[]
        job.completed.connect(results.append);job.failed.connect(errors.append)
        with patch('scenarios.apply_assignment',side_effect=[ 'Verified', OSError('connection lost')]) as apply:
            job.run()
        self.assertFalse(errors)
        self.assertEqual(apply.call_count,2)
        self.assertEqual(results[0][0]['result'],'Verified')
        self.assertIn('Unverified',results[0][1]['result'])
        self.assertIn('Not executed',results[0][2]['result'])
        self.assertEqual(credentials,{})
        self.assertNotIn('fixture-secret',str(results))

    def test_duplicate_destination_is_rejected(self):
        with self.assertRaises(ValueError):parse_destinations(VER+ONE+ONE+b'END\r\n')
