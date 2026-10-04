import json
import io
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from support.agent import dispatch, run
from support.store import Store


def response(calls=(), text='Done', iid='interaction-1'):
    return NS(steps=list(calls), output_text=text, id=iid)


def call(name='lookup_order', arguments=None, iid='call-1'):
    return NS(type='function_call', name=name, arguments=arguments or {'order_id': 'ORD-1001'}, id=iid)


class Workflows(unittest.TestCase):
    def test_api_diagnostics_do_not_echo_exception(self):
        from support.__main__ import api_failure
        error = RuntimeError('sensitive request details')
        error.status_code = 403
        message = api_failure(error)
        self.assertIn('HTTP 403', message)
        self.assertNotIn('sensitive', message)
        self.assertNotIn('sensitive', api_failure(RuntimeError('sensitive request details')))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'test.db'
        self.store = Store(self.path, date(2026, 10, 4))
        self.store.seed()

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_policy(self):
        self.assertTrue(self.store.eligibility('ORD-1001')['eligible'])
        self.assertTrue(self.store.eligibility('ORD-1005')['eligible'])
        for oid in ('ORD-1002', 'ORD-1003', 'ORD-1004'):
            self.assertFalse(self.store.eligibility(oid)['eligible'])
            with self.assertRaises(ValueError):
                self.store.prepare(oid, 'return')
        with self.assertRaises(ValueError):
            self.store.order('ORD-9999')

    def test_approval_persistence_and_duplicates(self):
        request = self.store.prepare('ORD-1001', 'damaged')
        self.assertEqual(request['state'], 'pending')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM refunds').fetchone()[0], 0)
        self.assertEqual(self.store.prepare('ORD-1001', 'again')['id'], request['id'])
        self.store.close()
        self.store = Store(self.path, date(2026, 10, 4))
        for _ in range(2):
            self.assertEqual(self.store.decide(request['id'], True)['state'], 'approved')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM refunds').fetchone()[0], 1)
        with self.assertRaises(ValueError):
            self.store.prepare('ORD-1001', 'again')

    def test_deny_is_terminal(self):
        request = self.store.prepare('ORD-1001', 'damaged')
        self.store.decide(request['id'], False)
        self.assertEqual(self.store.decide(request['id'], True)['state'], 'denied')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM refunds').fetchone()[0], 0)

    def test_recheck_at_approval(self):
        request = self.store.prepare('ORD-1005', 'return')
        self.store.today += timedelta(days=1)
        with self.assertRaises(ValueError):
            self.store.decide(request['id'], True)
        self.assertEqual(self.store.request(request['id'])['state'], 'pending')

    def test_validation(self):
        cases = [('approve', {'order_id': 'ORD-1001'}), ('lookup_order', []),
                 ('lookup_order', {'order_id': 1001}),
                 ('lookup_order', {'order_id': 'ORD-1001', 'amount': 1}),
                 ('prepare_refund_request', {'order_id': 'ORD-1001', 'reason': ' '})]
        for name, args in cases:
            with self.assertRaises(ValueError):
                dispatch(self.store, name, args)

    def test_loop_results_and_continuity(self):
        client = NS(interactions=NS(create=Mock(side_effect=[response([call()]), response(iid='final')])) )
        self.assertEqual(run(client, self.store, 'lookup', 'test', emit=lambda _: None), 'Done')
        kwargs = client.interactions.create.call_args.kwargs
        self.assertEqual(kwargs['previous_interaction_id'], 'interaction-1')
        self.assertEqual(kwargs['input'][0]['call_id'], 'call-1')
        self.assertEqual(json.loads(kwargs['input'][0]['result'][0]['text'])['id'], 'ORD-1001')
        self.assertEqual(self.store.previous('test'), 'final')

    def test_rejected_tool_returned_to_model(self):
        client = NS(interactions=NS(create=Mock(side_effect=[response([call('approve')]), response()])))
        run(client, self.store, 'approve', 'test', emit=lambda _: None)
        result = client.interactions.create.call_args.kwargs['input'][0]['result'][0]['text']
        self.assertIn('Unknown tool', result)

    def test_budgets_prevent_execution(self):
        for kwargs in ({'max_model_calls': 1}, {'max_tool_calls': 0}):
            client = NS(interactions=NS(create=Mock(return_value=response([call()]))))
            with self.assertRaises(ValueError):
                run(client, self.store, 'lookup', 'test', emit=lambda _: None, **kwargs)
            self.assertIsNone(self.store.previous('test'))

    def test_interrupted_after_preparation(self):
        step = call('prepare_refund_request', {'order_id': 'ORD-1001', 'reason': 'damaged'})
        client = NS(interactions=NS(create=Mock(side_effect=[response([step]), RuntimeError('offline')])) )
        with self.assertRaises(RuntimeError):
            run(client, self.store, 'refund', 'test', emit=lambda _: None)
        self.assertEqual(self.store.db.execute('SELECT state FROM requests').fetchone()[0], 'pending')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM refunds').fetchone()[0], 0)

    def test_two_connections_share_duplicate_protection(self):
        other = Store(self.path, self.store.today)
        try:
            first = self.store.prepare('ORD-1001', 'damaged')
            second = other.prepare('ORD-1001', 'damaged')
            self.assertEqual(first['id'], second['id'])
            self.store.decide(first['id'], True)
            other.decide(second['id'], True)
            self.assertEqual(other.db.execute('SELECT COUNT(*) FROM refunds').fetchone()[0], 1)
        finally:
            other.close()

    def test_duplicate_call_ids_rejected(self):
        client = NS(interactions=NS(create=Mock(return_value=response([call(), call()]))))
        with self.assertRaises(ValueError):
            run(client, self.store, 'lookup', 'test', emit=lambda _: None)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM events').fetchone()[0], 0)

    def test_cli_confirmation_is_required(self):
        from support.__main__ import main
        request = self.store.prepare('ORD-1001', 'damaged')
        argv = ['support', '--db', str(self.path), 'approve', request['id']]
        with patch('sys.argv', argv), patch('builtins.input', return_value='yes'), patch('sys.stdout', io.StringIO()):
            with self.assertRaises(SystemExit):
                main()
        self.assertEqual(self.store.request(request['id'])['state'], 'pending')
        with patch('sys.argv', argv), patch('builtins.input', return_value='APPROVE ' + request['id']), patch('sys.stdout', io.StringIO()):
            main()
        self.assertEqual(self.store.request(request['id'])['state'], 'approved')


if __name__ == '__main__':
    unittest.main()
