"""Explicit, selected-window screenshots with local Russian and English OCR."""
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import ctypes
from ctypes import wintypes
from io import BytesIO
import os
from pathlib import Path
import subprocess
import re
import threading
import time


class ScreenCaptureError(RuntimeError):
    pass


_capture_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='window-capture')
_capture_lock = threading.Lock()
_capture_future = None
_ocr_lock = threading.Lock()


def _api():
    if os.name != 'nt':
        raise ScreenCaptureError('Захват окон поддерживается только в Windows')
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    user.IsWindow.argtypes = [wintypes.HWND]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.IsIconic.argtypes = [wintypes.HWND]
    user.IsHungAppWindow.argtypes = [wintypes.HWND]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                 ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    return user, kernel


def validate_window_metadata(metadata):
    if not metadata.get('visible') or metadata.get('minimized'):
        raise ScreenCaptureError('Окно скрыто или свёрнуто')
    process = metadata.get('process', '').lower()
    title = metadata.get('title', '').lower()
    blocked = {'credentialuibroker.exe', 'consent.exe', 'logonui.exe', 'lsass.exe',
               'lockapp.exe', 'securityhealthsystray.exe', 'applicationframehost.security.exe'}
    sensitive = ('windows security', 'безопасность windows', 'user account control',
                 'контроль учётных записей', 'enter password', 'введите пароль', 'windows sign-in')
    if process in blocked or any(term in title for term in sensitive):
        raise ScreenCaptureError('Захват системных окон безопасности и паролей запрещён')
    if not metadata.get('title', '').strip():
        raise ScreenCaptureError('У окна нет заголовка')


def _window_metadata(window_id):
    user, kernel = _api()
    if not isinstance(window_id, int) or window_id <= 0 or not user.IsWindow(window_id):
        raise ScreenCaptureError('Выбранное окно больше не существует')
    pid = wintypes.DWORD()
    user.GetWindowThreadProcessId(window_id, ctypes.byref(pid))
    length = user.GetWindowTextLengthW(window_id)
    title = ctypes.create_unicode_buffer(length+1)
    user.GetWindowTextW(window_id, title, length+1)
    process = ''
    handle = kernel.OpenProcess(0x1000, False, pid.value)
    if handle:
        try:
            size = wintypes.DWORD(32768)
            path = ctypes.create_unicode_buffer(size.value)
            if kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
                process = Path(path.value).name
        finally:
            kernel.CloseHandle(handle)
    metadata = {'id': window_id, 'title': title.value, 'process': process,
                'pid': pid.value, 'visible': bool(user.IsWindowVisible(window_id)),
                'minimized': bool(user.IsIconic(window_id))}
    validate_window_metadata(metadata)
    if not process:
        raise ScreenCaptureError('Не удалось проверить процесс выбранного окна')
    if user.IsHungAppWindow(window_id):
        raise ScreenCaptureError('Выбранное окно не отвечает')
    return metadata


def list_windows():
    user, _ = _api()
    found = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        try:
            data = _window_metadata(int(hwnd))
            found.append({key: data[key] for key in ('id', 'title', 'process')})
        except ScreenCaptureError:
            pass
        return True
    callback = callback_type(visit)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.EnumWindows(callback, 0)
    return sorted(found, key=lambda item: item['title'].casefold())


def _capture_image(window_id):
    """PrintWindow asks the chosen HWND to render itself, excluding occluding windows."""
    from PIL import Image
    user, _ = _api()
    rect = wintypes.RECT()
    if not user.GetWindowRect(window_id, ctypes.byref(rect)):
        raise ScreenCaptureError('Не удалось получить границы окна')
    width, height = rect.right-rect.left, rect.bottom-rect.top
    if width < 16 or height < 16 or width*height > 40000000:
        raise ScreenCaptureError('Пустой или слишком большой размер окна')
    gdi = ctypes.WinDLL('gdi32', use_last_error=True)
    user.GetDC.argtypes = [wintypes.HWND]
    user.GetDC.restype = wintypes.HDC
    user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi.CreateCompatibleDC.restype = wintypes.HDC
    gdi.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi.SelectObject.restype = wintypes.HGDIOBJ
    gdi.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi.DeleteDC.argtypes = [wintypes.HDC]
    class Header(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('width', wintypes.LONG), ('height', wintypes.LONG),
                    ('planes', wintypes.WORD), ('bits', wintypes.WORD), ('compression', wintypes.DWORD),
                    ('image_size', wintypes.DWORD), ('x', wintypes.LONG), ('y', wintypes.LONG),
                    ('colors', wintypes.DWORD), ('important', wintypes.DWORD)]
    gdi.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                             wintypes.LPVOID, wintypes.LPVOID, wintypes.UINT]
    source = user.GetDC(window_id)
    if not source:
        raise ScreenCaptureError('Не удалось получить контекст окна')
    target = gdi.CreateCompatibleDC(source)
    bitmap = gdi.CreateCompatibleBitmap(source, width, height)
    old = gdi.SelectObject(target, bitmap)
    try:
        if not target or not bitmap or not user.PrintWindow(window_id, target, 2):
            raise ScreenCaptureError('Окно не поддерживает выбранный способ захвата')
        gdi.SelectObject(target, old)
        old = None
        header = Header(ctypes.sizeof(Header), width, -height, 1, 32, 0, width*height*4, 0, 0, 0, 0)
        data = ctypes.create_string_buffer(width*height*4)
        if gdi.GetDIBits(target, bitmap, 0, height, data, ctypes.byref(header), 0) != height:
            raise ScreenCaptureError('Не удалось прочитать снимок окна')
        image = Image.frombytes('RGB', (width, height), data.raw, 'raw', 'BGRX')
        extrema = image.convert('L').getextrema()
        if extrema[1]-extrema[0] < 3:
            raise ScreenCaptureError('Снимок пустой или чёрный: окно не предоставило изображение')
        return image
    finally:
        if old:
            gdi.SelectObject(target, old)
        if bitmap:
            gdi.DeleteObject(bitmap)
        if target:
            gdi.DeleteDC(target)
        user.ReleaseDC(window_id, source)


async def _winrt_ocr(png):
    from winrt.windows.globalization import Language
    from winrt.windows.graphics.imaging import BitmapDecoder, BitmapPixelFormat
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
    engines = []
    for language in ('ru-RU', 'en-US'):
        lang = Language(language)
        if not OcrEngine.is_language_supported(lang):
            raise ScreenCaptureError('Windows OCR language unavailable: ' + language)
        engines.append(OcrEngine.try_create_from_language(lang))
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    bitmap = None
    try:
        writer.write_bytes(png)
        await writer.store_async()
        writer.detach_stream()
        stream.seek(0)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        if bitmap.bitmap_pixel_format != BitmapPixelFormat.BGRA8:
            from winrt.windows.graphics.imaging import SoftwareBitmap
            converted = SoftwareBitmap.convert(bitmap, BitmapPixelFormat.BGRA8)
            bitmap.close()
            bitmap = converted
        recognized = []
        for engine in engines:
            result = await engine.recognize_async(bitmap)
            records = []
            for line in result.lines:
                text = line.text.strip()
                boxes = [word.bounding_rect for word in line.words]
                if text and boxes:
                    top, bottom = min(box.y for box in boxes), max(box.y+box.height for box in boxes)
                    left, right = min(box.x for box in boxes), max(box.x+box.width for box in boxes)
                    records.append({'text': text, 'top': top, 'height': bottom-top,
                                    'left': left, 'right': right, 'center': (top+bottom)/2})
            recognized.append(records)
        # Reconcile two readings of the same physical line. English OCR otherwise adds
        # a second, Latin transliteration of Russian text to the context.
        lines, used = [], set()
        for russian in recognized[0]:
            candidates = [(index, english) for index, english in enumerate(recognized[1])
                          if index not in used and min(russian['right'], english['right']) > max(russian['left'], english['left'])
                          and abs(russian['center']-english['center']) <= .65*max(russian['height'], english['height'])]
            matched = min(candidates, key=lambda pair: abs(pair[1]['center']-russian['center'])) if candidates else None
            chosen = russian
            if matched:
                used.add(matched[0])
                if not re.search('[А-Яа-яЁё]', russian['text']):
                    chosen = matched[1]
            lines.append(chosen)
        lines.extend(line for index, line in enumerate(recognized[1]) if index not in used)
        lines.sort(key=lambda line: (line['top'], line['left']))
        return '\n'.join(line['text'] for line in lines), 'rus+eng (Windows OCR)'
    finally:
        if bitmap:
            bitmap.close()
        writer.close()
        stream.close()


def recognize_image(image, tesseract_path=None):
    """Recognize in RAM. Missing language data is an explicit error, never guessed text."""
    payload = BytesIO()
    image.save(payload, format='PNG')
    try:
        with ThreadPoolExecutor(max_workers=1) as worker:
            async def run():
                return await asyncio.wait_for(_winrt_ocr(payload.getvalue()), timeout=30)
            return worker.submit(lambda: asyncio.run(run())).result()
    except Exception as winrt_error:
        configured = tesseract_path or os.environ.get('AQA_TESSERACT_PATH', '')
        if not configured or not Path(configured).is_file():
            raise ScreenCaptureError('Локальный Windows OCR rus+eng недоступен; укажите tesseract.exe с rus+eng. '
                                     + str(winrt_error)) from winrt_error
        try:
            with _ocr_lock:
                executable = str(Path(configured).resolve())
                options = {'capture_output': True, 'timeout': 25,
                           'creationflags': subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0}
                available = subprocess.run([executable, '--list-langs'], **options)
                if available.returncode:
                    raise ScreenCaptureError(available.stderr.decode('utf-8', errors='replace'))
                languages = available.stdout.decode('utf-8', errors='replace').splitlines()
                if not {'rus', 'eng'}.issubset(languages):
                    raise ScreenCaptureError('Tesseract требует локальные языки rus и eng')
                # PNG goes through stdin, so neither fallback nor WinRT persists the screenshot.
                result = subprocess.run([executable, 'stdin', 'stdout', '-l', 'rus+eng', '--psm', '6'],
                                        input=payload.getvalue(), **options)
                if result.returncode:
                    raise ScreenCaptureError(result.stderr.decode('utf-8', errors='replace'))
                text = result.stdout.decode('utf-8', errors='replace')
            return text.strip(), 'rus+eng (Tesseract)'
        except Exception as error:
            raise ScreenCaptureError('Ошибка локального OCR: ' + str(error)) from error


def capture_window(window_id: int, tesseract_path=None):
    global _capture_future
    before = _window_metadata(window_id)
    started = time.perf_counter()
    with _capture_lock:
        if _capture_future and not _capture_future.done():
            raise ScreenCaptureError('Предыдущий захват окна ещё выполняется')
        _capture_future = _capture_executor.submit(_capture_image, window_id)
        future = _capture_future
    try:
        image = future.result(timeout=3)
    except FutureTimeout as error:
        raise ScreenCaptureError('Окно не ответило на захват за 3 секунды') from error
    after = _window_metadata(window_id)
    if before['pid'] != after['pid'] or before['process'] != after['process']:
        raise ScreenCaptureError('Владелец окна изменился во время захвата')
    capture_ms = (time.perf_counter()-started)*1000
    started = time.perf_counter()
    text, language = recognize_image(image, tesseract_path)
    ocr_ms = (time.perf_counter()-started)*1000
    preview = image.copy()
    preview.thumbnail((1600, 1200))
    payload = BytesIO()
    preview.save(payload, format='PNG')
    return {'image_base64': base64.b64encode(payload.getvalue()).decode('ascii'),
            'width': image.width, 'height': image.height, 'text': text,
            'capture_ms': capture_ms, 'ocr_ms': ocr_ms, 'language': language}
