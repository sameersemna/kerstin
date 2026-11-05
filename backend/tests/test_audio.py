from array import array

from kerstin.audio import pcm16_rms_dbfs


def test_empty_is_minus_120():
    assert pcm16_rms_dbfs(b"") == -120.0


def test_zeros_is_minus_120():
    assert pcm16_rms_dbfs(b"\x00\x00" * 16000) == -120.0


def test_full_scale_square_is_about_zero_dbfs():
    pcm = array("h", [32767, -32768] * 8000).tobytes()
    assert abs(pcm16_rms_dbfs(pcm)) < 0.5


def test_half_amplitude_square_is_about_minus_six_dbfs():
    pcm = array("h", [16384, -16384] * 8000).tobytes()
    assert abs(pcm16_rms_dbfs(pcm) + 6.02) < 0.5
