import math
import os
import tempfile
import unittest
import wave
from array import array
from audio_intelligence import analyze_audio, suggest_audio_policy

class AudioTests(unittest.TestCase):
    def test_detect_silence_and_loudness(self):
        with tempfile.TemporaryDirectory() as folder:
            path=os.path.join(folder,'sample.wav')
            with wave.open(path,'wb') as f:
                f.setnchannels(1);f.setsampwidth(2);f.setframerate(8000)
                quiet=array('h',[0]*8000)
                loud=array('h',[int(15000*math.sin(2*math.pi*440*i/8000)) for i in range(8000)])
                f.writeframes(quiet.tobytes()+loud.tobytes())
            data=analyze_audio(path)
            self.assertTrue(data[0]['silent'])
            self.assertFalse(data[-1]['silent'])
            self.assertTrue(any(x['transient_candidate'] for x in data))
    def test_no_random_cut_cues(self):
        clips=[{'label':'Director transition cue — source cut','auto_sfx':True}, {'label':'gameplay'}]
        result=suggest_audio_policy(clips)
        self.assertEqual(result['automatic_sfx_count'],1)
        self.assertFalse(result['cut_sfx_enabled'])

if __name__=='__main__':unittest.main()
