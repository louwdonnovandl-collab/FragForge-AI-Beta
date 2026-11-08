import unittest
from unittest.mock import patch
import director_plan_fallback as d

class DirectorTests(unittest.TestCase):
    def test_empty(self):
        with self.assertRaises(ValueError): d._extract_json('')
    def test_fenced(self):
        self.assertEqual(d._extract_json('```json\n{"steps":["cut"]}\n```')['steps'], ['cut'])
    def test_thinking(self):
        self.assertEqual(d._extract_json('<think>ignore</think>{"steps":["cut"]}')['steps'], ['cut'])
    def test_valid(self):
        self.assertEqual(d._validate({'steps':['cut']})['source'], 'ollama')
    def test_fallback(self):
        p = d.fallback_plan('add captions effects intro')
        self.assertEqual(p['source'], 'fallback')
        self.assertEqual(len(p['steps']), 6)
    def test_retry(self):
        with patch.object(d, '_ollama', side_effect=[ValueError('empty'), {'steps':[{'action':'cut'}], 'source':'ollama'}]) as f:
            p = d.generate_director_plan('cut')
            self.assertEqual(p['attempt'], 2)
            self.assertEqual(f.call_count, 2)
    def test_both_fail(self):
        with patch.object(d, '_ollama', side_effect=ValueError('empty')):
            self.assertEqual(d.generate_director_plan('edit')['source'], 'fallback')

if __name__ == '__main__': unittest.main()
