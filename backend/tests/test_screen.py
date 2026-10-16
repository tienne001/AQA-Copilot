import unittest
from unittest.mock import patch, AsyncMock
from pathlib import Path
import subprocess
import tempfile
import os
from copilot.screen import capture_window, validate_window_metadata, ScreenCaptureError, recognize_image


class ScreenTests(unittest.TestCase):
    def test_invalid_window_never_captures_desktop(self):
        with self.assertRaises(ScreenCaptureError):
            capture_window(0)

    def test_minimized_or_security_window_is_rejected(self):
        for metadata in [
            {'visible': True, 'minimized': True, 'title': 'Editor', 'process': 'notepad.exe'},
            {'visible': True, 'minimized': False, 'title': 'Windows Security', 'process': 'CredentialUIBroker.exe'},
            {'visible': False, 'minimized': False, 'title': 'Editor', 'process': 'notepad.exe'},
        ]:
            with self.assertRaises(ScreenCaptureError):
                validate_window_metadata(metadata)

    def test_ordinary_visible_window_allowed(self):
        validate_window_metadata({'visible': True, 'minimized': False,
                                  'title': 'QA notes', 'process': 'notepad.exe'})

    def test_tesseract_fallback_pipes_image_in_memory_and_requires_both_languages(self):
        class SyntheticImage:
            def save(self, stream, format):
                stream.write(b'PNG synthetic fixture')
        with tempfile.TemporaryDirectory() as folder:
            executable = Path(folder) / 'tesseract.exe'
            executable.touch()
            replies = [subprocess.CompletedProcess([], 0, b'List of available languages (2):\neng\nrus\n', b''),
                       subprocess.CompletedProcess([], 0, 'Проверка API'.encode('utf-8'), b'')]
            with patch('copilot.screen._winrt_ocr', AsyncMock(side_effect=RuntimeError('missing languages'))), \
                 patch('subprocess.run', side_effect=replies) as run:
                text, language = recognize_image(SyntheticImage(), str(executable))
                self.assertEqual(text, 'Проверка API')
                self.assertIn('rus+eng', language)
                self.assertEqual(run.call_args.kwargs['input'], b'PNG synthetic fixture')
                self.assertEqual(run.call_args.args[0][1:3], ['stdin', 'stdout'])

    @unittest.skipUnless(os.name == 'nt', 'Windows OCR integration')
    def test_real_windows_ocr_generated_russian_and_english(self):
        try:
            from winrt.windows.media.ocr import OcrEngine
            from winrt.windows.globalization import Language
            from PIL import Image, ImageDraw, ImageFont
        except ImportError as error:
            self.skipTest(str(error))
        if not all(OcrEngine.is_language_supported(Language(lang)) for lang in ('ru-RU', 'en-US')):
            self.skipTest('Russian and English Windows OCR language packs required')
        image = Image.new('RGB', (1400, 320), 'white')
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(str(Path(os.environ['WINDIR']) / 'Fonts/arial.ttf'), 44)
        draw.text((30, 40), 'Регрессионное тестирование', font=font, fill='black')
        draw.text((30, 150), 'Playwright API testing', font=font, fill='black')
        text, language = recognize_image(image)
        self.assertIn('Регрессионное тестирование', text)
        self.assertIn('Playwright API testing', text)
        self.assertIn('Windows OCR', language)
        self.assertEqual(len(text.splitlines()), 2, 'Two OCR languages must not duplicate physical lines')


if __name__ == '__main__':
    unittest.main()
