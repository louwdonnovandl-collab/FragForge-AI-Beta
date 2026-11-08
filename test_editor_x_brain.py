import unittest
from editor_x_brain import parse_instruction
class Tests(unittest.TestCase):
 def test_combat(self):
  x=parse_instruction('Create a 60-second combat intro at 2× speed. Add rock music.')
  self.assertEqual((x.activity,x.intro_seconds,x.intro_speed,x.music_genre),('combat',60,2.0,'rock'))
 def test_caption(self):
  x=parse_instruction('smooth out transitions and add caption saying "Viewpoint Chill vibes"')
  self.assertTrue(x.smooth_transitions)
  self.assertEqual(x.captions,['Viewpoint Chill vibes'])
 def test_longform(self):
  x=parse_instruction('make a 15 second intro with rock music at 2x speed, then remove pause screens and stagnant frames, make it 20 minutes')
  self.assertEqual(x.duration_seconds,1200)
  self.assertEqual(x.intro_seconds,15)
  self.assertTrue(x.remove_pauses)
  self.assertTrue(x.remove_stagnant)
 def test_preserve(self):
  self.assertTrue(parse_instruction('add a caption').preserve_existing)
  self.assertFalse(parse_instruction('start over with a new edit').preserve_existing)
if __name__=='__main__':unittest.main()
