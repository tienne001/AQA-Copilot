import numpy as np
import pytest
from pydantic import ValidationError
from copilot.audio import StreamingSegmenter,SpeechEngine
from copilot.settings import Settings,save_settings,load_settings

def test_four_second_pause_is_saved_and_reloaded(tmp_path):
    settings=Settings(pause_ms=4000)
    save_settings(tmp_path,settings)
    assert load_settings(tmp_path).pause_ms==4000
    assert StreamingSegmenter(pause_ms=4000).pause==64000
    assert SpeechEngine('unused-local-test-model',pause_ms=4000).pause_ms==4000

@pytest.mark.parametrize('value',[159,5001])
def test_pause_bounds_match(value):
    with pytest.raises(ValidationError):Settings(pause_ms=value)
    with pytest.raises(ValueError):StreamingSegmenter(pause_ms=value)

def test_waits_for_four_full_seconds_of_silence():
    segmenter=StreamingSegmenter(pause_ms=4000)
    voice=np.full(512,.1,np.float32);quiet=np.zeros(512,np.float32)
    for index in range(12):assert segmenter.feed(voice,.9,index*.032) is None
    for index in range(124):assert segmenter.feed(quiet,0.,.384+index*.032) is None
    result=segmenter.feed(quiet,0.,.384+124*.032)
    assert result is not None
    assert result['endpoint_ms']==pytest.approx(4000)

def test_speech_after_three_second_pause_continues_same_segment():
    segmenter=StreamingSegmenter(pause_ms=4000)
    first=np.full(512,.1,np.float32);second=np.full(512,.2,np.float32);quiet=np.zeros(512,np.float32)
    frames=[(first,.9)]*12+[(quiet,0.)]*96+[(second,.9)]*10+[(quiet,0.)]*125
    results=[]
    for index,(frame,probability) in enumerate(frames):
        result=segmenter.feed(frame,probability,index*.032)
        if result is not None:results.append(result)
    assert len(results)==1
    assert np.count_nonzero(results[0]['samples']==np.float32(.1))==12*512
    assert np.count_nonzero(results[0]['samples']==np.float32(.2))==10*512
    assert results[0]['endpoint_ms']==pytest.approx(4000)
