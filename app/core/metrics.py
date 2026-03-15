"""Métricas Prometheus (opcional).
Si `prometheus_client` no está instalado, se crean stubs no-op.
"""
try:
    from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
    PROM_AVAILABLE = True
except Exception:
    PROM_AVAILABLE = False

if PROM_AVAILABLE:
    TRANSCRIPTIONS_IN_PROGRESS = Gauge('m4a_transcriptions_in_progress', 'Número de transcripciones en progreso')
    TRANSCRIPTIONS_TOTAL = Counter('m4a_transcriptions_total', 'Total de transcripciones', ['status'])
    TRANSCRIPTION_DURATION = Histogram('m4a_transcription_duration_seconds', 'Duración de transcripción en segundos')
    GPU_MEMORY_USED = Gauge('m4a_gpu_memory_used_bytes', 'GPU memory used in bytes', [])
else:
    class _Noop:
        def __getattr__(self, _):
            return lambda *a, **k: None
    TRANSCRIPTIONS_IN_PROGRESS = _Noop()
    TRANSCRIPTIONS_TOTAL = _Noop()
    TRANSCRIPTION_DURATION = _Noop()
    GPU_MEMORY_USED = _Noop()
    generate_latest = lambda: b''
    CONTENT_TYPE_LATEST = 'text/plain; version=0.0.4; charset=utf-8'


def get_metrics_payload():
    if PROM_AVAILABLE:
        return generate_latest(), CONTENT_TYPE_LATEST
    return b'', CONTENT_TYPE_LATEST
