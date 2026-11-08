import unittest
from unittest.mock import patch
import local_director

class RecoveryTests(unittest.TestCase):
    def test_empty_response_recovers(self):
        with patch.object(local_director, '_generate', return_value='') as generate:
            plan, reply = local_director.make_plan('trim my gameplay')
            self.assertEqual(plan['source'], 'fallback')
            self.assertEqual(generate.call_count, 2)
            self.assertIn('review', reply)
    def test_second_response_valid(self):
        with patch.object(local_director, '_generate', side_effect=['', '{"effects":true,"reply":"Ready"}']):
            plan, reply = local_director.make_plan('add effects')
            self.assertTrue(plan['effects'])
            self.assertEqual(reply, 'Ready')
    def test_invalid_json_recovers(self):
        with patch.object(local_director, '_generate', return_value='not json'):
            plan, _ = local_director.make_plan('make a montage')
            self.assertEqual(plan['source'], 'fallback')
