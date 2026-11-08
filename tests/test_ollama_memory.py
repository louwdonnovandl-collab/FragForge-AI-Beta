import unittest
from unittest.mock import patch, MagicMock
import json
from ollama_memory import release_model, release_models

class TestOllamaMemory(unittest.TestCase):
    @patch('ollama_memory.urllib.request.urlopen')
    def test_unload_request(self, mock_open):
        response=MagicMock()
        response.__enter__.return_value=response
        response.read.return_value=b'{"done":true,"done_reason":"unload"}'
        mock_open.return_value=response
        ok,_=release_model('qwen3-vl:2b')
        self.assertTrue(ok)
        req=mock_open.call_args.args[0]
        self.assertEqual(json.loads(req.data), {'model':'qwen3-vl:2b','keep_alive':0})

    def test_reject_empty(self):
        self.assertFalse(release_model('')[0])

    @patch('ollama_memory.release_model',return_value=(True,'ok'))
    def test_unique_models(self, mock_release):
        result=release_models(['qwen3-vl:2b','qwen3-vl:2b','qwen3:4b'])
        self.assertEqual(len(result),2)
        self.assertEqual(mock_release.call_count,2)
