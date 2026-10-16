"""Explicit offline GPU/CPU comparison on identical WAVs; never opens a microphone.

Synthetic speech checks regressions, not accuracy on a human speaker. Results
include raw transcripts so improvements from decoding and aliasing stay separate.
"""
import argparse
import json
from pathlib import Path
import re
import sys
import time
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from copilot.bootstrap import configure_runtime
configure_runtime()
import numpy as np
from copilot.audio import SpeechEngine, to_mono_16k
from copilot.speech_vocabulary import AQA_HOTWORDS, normalize_technical_terms

OLD_HOTWORDS = ('QA, AQA, API, HTTP, GET, POST, PUT, PATCH, DELETE, SQL, Kafka, '
                'consumer group, offset, Playwright, TypeScript, JavaScript, REST, JSON, '
                'Docker, Kubernetes, Git, CI/CD')


def contains(text, term):
    return bool(re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', text, re.IGNORECASE))


def decode(model, samples, hotwords, beam_size):
    started = time.perf_counter()
    segments, _ = model.transcribe(samples, language='ru', beam_size=beam_size, temperature=0,
        hotwords=hotwords, condition_on_previous_text=False, vad_filter=True,
        vad_parameters={'min_speech_duration_ms': 128, 'min_silence_duration_ms': 480},
        no_speech_threshold=.6, hallucination_silence_threshold=1.)
    raw = ' '.join(segment.text.strip() for segment in segments
                   if segment.no_speech_prob < .6 and segment.text.strip())
    return raw, round((time.perf_counter() - started) * 1000, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True, type=Path)
    parser.add_argument('--fixtures', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--device', choices=('cuda', 'cpu'), default='cuda')
    parser.add_argument('--beam-size', type=int, default=3)
    args = parser.parse_args()
    engine = SpeechEngine(str(args.model), args.device, 'int8_float16' if args.device == 'cuda' else 'int8')
    loaded = engine.load()
    hotword_tokens = len(engine.model.hf_tokenizer.encode(' ' + AQA_HOTWORDS, add_special_tokens=False).ids)
    assert hotword_tokens <= engine.model.max_length // 2 - 1, 'Hotword prompt would be truncated'
    print(json.dumps({'loaded': loaded, 'hotword_tokens': hotword_tokens}), flush=True)
    cases = json.loads((args.fixtures / 'asr_cases.json').read_text(encoding='utf-8-sig'))
    report = {'model': str(args.model.resolve()), 'synthetic': True,
              'voice': 'Microsoft Irina Desktop - Russian', 'device': args.device,
              'beam_size': args.beam_size, 'hotword_tokens': hotword_tokens, 'cases': []}
    totals = {'expected': 0, 'baseline': 0, 'baseline_normalized': 0, 'hints': 0, 'corrected': 0}
    try:
        for case in cases:
            with wave.open(str(args.fixtures / (case['id'] + '.wav')), 'rb') as wav:
                assert wav.getsampwidth() == 2
                samples = np.frombuffer(wav.readframes(wav.getnframes()), np.int16).astype(np.float32) / 32768.
                samples = to_mono_16k(samples.reshape(-1, wav.getnchannels()), wav.getframerate())
            baseline, baseline_ms = decode(engine.model, samples, OLD_HOTWORDS, args.beam_size)
            baseline_normalized, _ = normalize_technical_terms(baseline)
            hints, hints_ms = decode(engine.model, samples, AQA_HOTWORDS, args.beam_size)
            corrected, changes = normalize_technical_terms(hints)
            hits = {key: [term for term in case['terms'] if contains(text, term)]
                    for key, text in [('baseline', baseline), ('baseline_normalized', baseline_normalized),
                                      ('hints', hints), ('corrected', corrected)]}
            forbidden = [term for term in case.get('forbidden', []) if contains(corrected, term)]
            row = {**case, 'audio_seconds': round(len(samples) / 16000, 2), 'baseline': baseline,
                   'baseline_normalized': baseline_normalized, 'hints': hints, 'corrected': corrected, 'corrections': changes,
                   'hits': hits, 'false_terms': forbidden, 'baseline_ms': baseline_ms, 'hints_ms': hints_ms}
            report['cases'].append(row)
            totals['expected'] += len(case['terms'])
            for key in ('baseline', 'baseline_normalized', 'hints', 'corrected'):
                totals[key] += len(hits[key])
            print(json.dumps(row, ensure_ascii=False), flush=True)
        for name, samples in [('silence', np.zeros(48000, np.float32)),
                              ('noise', np.random.default_rng(7).normal(0, .005, 48000).astype(np.float32))]:
            raw, elapsed = decode(engine.model, samples, AQA_HOTWORDS, args.beam_size)
            report['cases'].append({'id': name, 'hints': raw, 'hints_ms': elapsed, 'passed': not raw.strip()})
        report['totals'] = totals
    finally:
        engine.unload(5)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'totals': totals, 'output': str(args.output)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
