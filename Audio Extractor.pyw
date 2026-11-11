import runpy, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
runpy.run_module('audio_extractor', run_name='__main__')

