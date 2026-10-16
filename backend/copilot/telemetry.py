import asyncio
import csv
import io
import os
import subprocess
import time


class GpuMonitor:
    def __init__(self):
        self.value = {'available': False}
        self.updated = 0.
        self.lock = asyncio.Lock()

    async def read(self):
        async with self.lock:
            if time.monotonic()-self.updated > 1:
                self.value = await asyncio.to_thread(self._read)
                self.updated = time.monotonic()
            return self.value

    @staticmethod
    def _read():
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            result = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total,memory.used,memory.free',
                                     '--format=csv,noheader,nounits'], capture_output=True, text=True,
                                    timeout=3, creationflags=flags, check=True)
            row = next(csv.reader(io.StringIO(result.stdout)))
            return {'available': True, 'name': row[0].strip(), 'total_mb': int(row[1]),
                    'used_mb': int(row[2]), 'free_mb': int(row[3])}
        except Exception as error:
            return {'available': False, 'error': str(error)}

    async def require_free(self, minimum):
        gpu = await self.read()
        if not gpu.get('available'):
            raise RuntimeError('NVIDIA GPU недоступен: ' + gpu.get('error', 'нет телеметрии'))
        if gpu['free_mb'] < minimum:
            raise RuntimeError(f"Недостаточно свободной VRAM: {gpu['free_mb']} MiB, требуется {minimum} MiB. Закрой GPU-приложения или выбери CPU.")
