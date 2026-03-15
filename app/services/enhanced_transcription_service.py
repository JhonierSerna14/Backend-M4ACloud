"""
Servicio de transcripción optimizado para audios largos.
Utiliza faster-whisper con soporte GPU y procesamiento paralelo.

Características:
- Chunking automático de audio para manejar archivos grandes
- Procesamiento paralelo con ThreadPoolExecutor
- Detección y filtrado de alucinaciones
- Fallback automático si hay errores de memoria
"""
import os
import shutil
import tempfile
import time
import asyncio
from typing import Dict, Any, Callable, Optional, List
from concurrent.futures import ThreadPoolExecutor

import torch
from loguru import logger
from faster_whisper import WhisperModel
from pydub import AudioSegment

from app.core.config import settings


class EnhancedTranscriptionService:
    """
    Servicio de transcripción de audio optimizado para GPU.
    Soporta archivos de audio largos mediante chunking.
    """
    
    def __init__(self, model_size: str = None):
        """
        Inicializa el servicio con la configuración del .env.
        
        Args:
            model_size: Tamaño del modelo Whisper (tiny, base, small, medium, large-v2, large-v3)
        """
        self.model_size = model_size or settings.WHISPER_MODEL_SIZE
        self.model = None
        self.device = self._detect_device()
        
        # Configuración de chunking
        self.chunk_duration = max(60, settings.CHUNK_DURATION_MINUTES * 60)
        self.overlap_duration = max(0, settings.CHUNK_OVERLAP_SECONDS)
        self.max_workers = max(1, settings.MAX_PARALLEL_CHUNKS)
        
        # Directorio temporal
        self.temp_dir = tempfile.mkdtemp(prefix="m4a_chunks_")
        # Semáforo para limitar transcripciones concurrentes y evitar OOM
        self._semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_TRANSCRIPTIONS)
        
        self._load_model()
    
    def _detect_device(self) -> str:
        """Detecta el dispositivo óptimo (GPU/CPU)."""
        desired = (settings.WHISPER_DEVICE or "auto").lower()
        
        if desired == "cpu":
            return "cpu"
        
        # Verificar GPU con ctranslate2
        try:
            import ctranslate2
            if ctranslate2.get_cuda_device_count() > 0:
                return "cuda"
        except Exception:
            pass
        
        # Fallback a PyTorch
        if torch.cuda.is_available():
            return "cuda"
        
        return "cpu"
    
    def _load_model(self):
        """Carga el modelo Whisper con la configuración óptima."""
        download_root = os.path.join(os.path.expanduser("~"), ".cache", "whisper")
        compute_type = settings.WHISPER_COMPUTE_TYPE
        
        logger.info(f"🎤 Cargando Whisper: model={self.model_size}, device={self.device}, compute={compute_type}")
        
        try:
            cpu_threads = max(4, os.cpu_count() or 4)

            if self.device == "cuda":
                # Validar compute_type para GPU
                if compute_type not in ["float16", "float32", "int8_float16", "int8_float32", "int8"]:
                    compute_type = "float16"
                
                self.model = WhisperModel(
                    self.model_size,
                    device="cuda",
                    compute_type=compute_type,
                    cpu_threads=cpu_threads,
                    num_workers=2,
                    download_root=download_root,
                )
                logger.info(f"✅ Whisper cargado en GPU ({self.model_size}, {compute_type})")
            else:
                if compute_type not in ["int8", "int8_float32", "float32"]:
                    compute_type = "int8"
                
                self.model = WhisperModel(
                    self.model_size,
                    device="cpu",
                    compute_type=compute_type,
                    cpu_threads=cpu_threads,
                    num_workers=1,
                    download_root=download_root,
                )
                logger.info(f"✅ Whisper cargado en CPU ({self.model_size}, {compute_type})")
                
        except Exception as e:
            error_msg = str(e).lower()
            if "out of memory" in error_msg or "cuda" in error_msg:
                self._load_fallback_model(download_root)
            else:
                raise RuntimeError(f"Error cargando modelo Whisper: {e}")
    
    def _load_fallback_model(self, download_root: str):
        """Intenta cargar un modelo más pequeño si hay error de memoria."""
        fallback_order = ["small", "base", "tiny"]
        cpu_threads = max(4, os.cpu_count() or 4)
        
        for model_size in fallback_order:
            try:
                self.model_size = model_size
                self.model = WhisperModel(
                    model_size,
                    device=self.device,
                    compute_type="int8",
                    cpu_threads=cpu_threads,
                    num_workers=1,
                    download_root=download_root,
                )
                logger.warning(f"Usando modelo fallback: {model_size}")
                return
            except Exception:
                continue
        
        # Último recurso: CPU con tiny
        self.device = "cpu"
        self.model_size = "tiny"
        self.model = WhisperModel(
            "tiny",
            device="cpu",
            compute_type="int8",
            download_root=download_root,
        )
        logger.error("Fallback a CPU con modelo tiny")
    
    def _extract_audio_chunks(self, audio_path: str) -> List[str]:
        """
        Divide el audio en chunks físicos para procesamiento paralelo.
        
        Args:
            audio_path: Ruta al archivo de audio
            
        Returns:
            Lista de rutas a los archivos de chunks
        """
        logger.info(f"📦 Dividiendo audio en chunks...")
        
        audio = AudioSegment.from_file(audio_path)
        total_duration_ms = len(audio)
        total_duration_min = total_duration_ms / 1000 / 60
        
        chunk_duration_ms = self.chunk_duration * 1000
        overlap_ms = self.overlap_duration * 1000
        
        chunk_files = []
        chunk_start_ms = 0
        chunk_idx = 0
        
        while chunk_start_ms < total_duration_ms:
            chunk_end_ms = min(chunk_start_ms + chunk_duration_ms, total_duration_ms)
            chunk_audio = audio[chunk_start_ms:chunk_end_ms]
            
            chunk_file = os.path.join(self.temp_dir, f"chunk_{chunk_idx:04d}.wav")
            chunk_audio.export(chunk_file, format="wav")
            chunk_files.append(chunk_file)
            
            chunk_idx += 1
            chunk_start_ms = chunk_end_ms - overlap_ms
            
            if chunk_start_ms >= total_duration_ms - overlap_ms:
                break
        
        logger.info(
            f"📊 AUDIO DIVIDIDO\n"
            f"   📏 Duración total: {total_duration_min:.1f} minutos\n"
            f"   📦 Número de secciones: {len(chunk_files)}\n"
            f"   ⏱️ Duración por chunk: {self.chunk_duration // 60} min\n"
            f"   🔄 Overlap: {self.overlap_duration}s"
        )
        
        return chunk_files
    
    def _is_hallucination(self, text: str) -> bool:
        """
        Detecta si un segmento de texto es una alucinación.
        
        Criterios:
        - Más del 25% de palabras consecutivas repetidas
        - Frases repetidas más de 4 veces
        - Diversidad léxica menor al 35%
        """
        if not text or len(text.strip()) < 10:
            return True
        
        words = text.lower().split()
        if len(words) < 2:
            return False
        
        # Palabras consecutivas repetidas
        consecutive_repeats = sum(1 for i in range(len(words) - 1) if words[i] == words[i + 1])
        if len(words) > 0 and (consecutive_repeats / len(words)) > 0.25:
            return True
        
        # Frases repetidas (bigramas)
        phrase_counts = {}
        for i in range(len(words) - 1):
            phrase = f"{words[i]} {words[i+1]}"
            phrase_counts[phrase] = phrase_counts.get(phrase, 0) + 1
        
        if any(count > 4 for count in phrase_counts.values()):
            return True
        
        # Diversidad léxica
        unique_words = set(words)
        if len(unique_words) / len(words) < 0.35 and len(words) > 8:
            return True
        
        return False
    
    def _transcribe_chunk(self, chunk_file: str, chunk_id: int, total_chunks: int = 0) -> Dict:
        """
        Transcribe un chunk de audio individual.
        
        Args:
            chunk_file: Ruta al archivo de chunk
            chunk_id: ID del chunk para ordenamiento
            total_chunks: Total de chunks para logging
            
        Returns:
            Diccionario con id, texto y confianza
        """
        chunk_start = time.time()
        logger.debug(
            f"🎤 TRANSCRIBIENDO SECCIÓN {chunk_id + 1}" + 
            (f"/{total_chunks}" if total_chunks else "")
        )
        
        try:
            segments, info = self.model.transcribe(
                chunk_file,
                language=settings.WHISPER_LANGUAGE,
                beam_size=settings.WHISPER_BEAM_SIZE,
                best_of=settings.WHISPER_BEST_OF,
                temperature=settings.WHISPER_TEMPERATURE,
                compression_ratio_threshold=settings.WHISPER_COMPRESSION_RATIO,
                log_prob_threshold=-1.0,
                no_speech_threshold=settings.WHISPER_NO_SPEECH_THRESHOLD,
                condition_on_previous_text=False,  # Desactivado para evitar bucles de repetición del prompt
                initial_prompt="Transcripción de clase universitaria clara y precisa.",
                repetition_penalty=settings.WHISPER_REPETITION_PENALTY,
                word_timestamps=False,
                vad_filter=settings.VAD_FILTER_ENABLED,
                vad_parameters=dict(
                    min_silence_duration_ms=settings.VAD_MIN_SPEECH_DURATION_MS,
                    speech_pad_ms=settings.VAD_SPEECH_PAD_MS
                )
            )
            
            chunk_text = ""
            total_confidence = 0
            segment_count = 0
            
            for segment in segments:
                segment_text = segment.text.strip()
                
                if self._is_hallucination(segment_text):
                    continue
                
                chunk_text += segment_text + " "
                total_confidence += getattr(segment, 'avg_logprob', 0.8)
                segment_count += 1
            
            # Detectar idioma si info lo provee
            language = None
            try:
                language = getattr(info, 'language', None) or (info.get('language') if isinstance(info, dict) else None)
            except Exception:
                language = None
            
            avg_confidence = total_confidence / segment_count if segment_count > 0 else 0.0
            
            chunk_duration = time.time() - chunk_start
            logger.debug(
                f"   ✅ Sección {chunk_id + 1} completada\n"
                f"      📝 Caracteres: {len(chunk_text):,}\n"
                f"      🔊 Segmentos: {segment_count}\n"
                f"      ⏱️ Tiempo: {chunk_duration:.1f}s\n"
                f"      📊 Confianza: {avg_confidence:.2f}"
            )
            
            return {
                'chunk_id': chunk_id,
                'text': chunk_text.strip(),
                'confidence': avg_confidence,
                'language': language,
            }
            
        except Exception as e:
            logger.error(
                f"   ❌ ERROR en sección {chunk_id + 1}\n"
                f"      💥 Error: {type(e).__name__}: {e}"
            )
            return {
                'chunk_id': chunk_id,
                'text': '',
                'confidence': 0.0,
                'language': None
            }
    
    def _merge_transcripts(self, transcripts: List[Dict]) -> str:
        """
        Combina las transcripciones de todos los chunks.
        
        Args:
            transcripts: Lista de resultados de transcripción
            
        Returns:
            Texto completo combinado
        """
        if not transcripts:
            return ""
        
        merged_text = ""
        
        for i, transcript in enumerate(transcripts):
            text = transcript['text'].strip()
            
            if not text:
                continue
            
            # Separador cada 5 chunks (~25 min con chunks de 5 min)
            if i > 0 and i % 5 == 0:
                merged_text += f"\n\n--- Parte {i//5 + 1} ---\n\n"
            
            merged_text += text + " "
        
        return merged_text.strip()
    
    def _cleanup_chunks(self, chunk_files: List[str]):
        """Elimina los archivos temporales de chunks."""
        for chunk_file in chunk_files:
            try:
                if os.path.exists(chunk_file):
                    os.remove(chunk_file)
            except Exception:
                pass
    
    async def transcribe_long_audio(
        self, 
        audio_path: str, 
        progress_callback: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """
        Transcribe un archivo de audio largo con procesamiento paralelo.
        
        Args:
            audio_path: Ruta al archivo de audio
            progress_callback: Función async para reportar progreso
            
        Returns:
            Diccionario con transcripción y metadatos
        """
        async with self._semaphore:
            start_time = time.time()
            logger.info(
                f"🎙️ INICIANDO TRANSCRIPCIÓN\n"
                f"   📁 Archivo: {os.path.basename(audio_path)}\n"
                f"   📏 Tamaño: {os.path.getsize(audio_path) / 1024 / 1024:.1f} MB\n"
                f"   🤖 Modelo: {self.model_size}\n"
                f"   💻 Dispositivo: {self.device}"
            )
            
            try:
                loop = asyncio.get_running_loop()
                
                # Dividir audio en chunks (run in executor to avoid blocking)
                if progress_callback:
                    await progress_callback(2, "Analizando y dividiendo audio...")
                    
                chunk_files = await loop.run_in_executor(None, self._extract_audio_chunks, audio_path)
                total_chunks = len(chunk_files)
                
                if progress_callback:
                    await progress_callback(5, f"Audio dividido en {total_chunks} partes")
                
                # Procesar chunks en paralelo
                transcripts = []
                completed = 0
                
                logger.info(
                    f"⚡ INICIANDO PROCESAMIENTO PARALELO\n"
                    f"   📦 Total secciones: {total_chunks}\n"
                    f"   🔧 Workers paralelos: {self.max_workers}"
                )
                
                # Use executor for CPU-bound transcription tasks
                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    # Submit all tasks to the executor and wrap as awaitable objects
                    tasks = []
                    for i, chunk_file in enumerate(chunk_files):
                        tasks.append(
                            loop.run_in_executor(
                                executor, 
                                self._transcribe_chunk, 
                                chunk_file, 
                                i, 
                                total_chunks
                            )
                        )
                    
                    # Process results as they complete
                    for task in asyncio.as_completed(tasks):
                        result = await task
                        transcripts.append(result)
                        completed += 1
                        
                        if progress_callback:
                            progress = 5 + (completed / total_chunks) * 85  # 5% to 90%
                            await progress_callback(progress, f"Transcribiendo: {completed}/{total_chunks}")
                
                # Limpiar archivos temporales
                await loop.run_in_executor(None, self._cleanup_chunks, chunk_files)
                
                # Ordenar y combinar transcripciones
                transcripts.sort(key=lambda x: x['chunk_id'])
                full_transcript = self._merge_transcripts(transcripts)
                
                # Obtener duración del audio
                try:
                    import librosa
                    import warnings
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        audio_duration = librosa.get_duration(path=audio_path)
                except Exception:
                    audio_duration = total_chunks * self.chunk_duration
                
                # Detectar idioma dominante si está disponible por chunk
                languages = [t.get('language') for t in transcripts if t.get('language')]
                detected_language = None
                if languages:
                    from collections import Counter
                    detected_language = Counter(languages).most_common(1)[0][0]
                
                processing_time = time.time() - start_time
                rtf = processing_time / audio_duration if audio_duration > 0 else 0
                
                logger.info(
                    f"✅ TRANSCRIPCIÓN COMPLETADA\n"
                    f"   📝 Total caracteres: {len(full_transcript):,}\n"
                    f"   📦 Secciones procesadas: {len(transcripts)}/{total_chunks}\n"
                    f"   📏 Duración audio: {audio_duration/60:.1f} min\n"
                    f"   ⏱️ Tiempo procesamiento: {processing_time:.1f}s\n"
                    f"   📊 Factor tiempo real: {rtf:.2f}x"
                )
                
                if progress_callback:
                    await progress_callback(100, "Transcripción completada")
                
                # Instrumentar uso de GPU si es posible
                try:
                    from app.core.metrics import GPU_MEMORY_USED
                    if torch.cuda.is_available():
                        mem = torch.cuda.memory_allocated(0)
                        GPU_MEMORY_USED.set(mem)
                except Exception:
                    pass
                
                return {
                    'transcript': full_transcript,
                    'chunks_processed': len(transcripts),
                    'total_duration': audio_duration,
                    'processing_time': processing_time,
                    'model_used': self.model_size,
                    'device_used': self.device,
                    'detected_language': detected_language
                }
                
            except Exception as e:
                logger.error(
                    f"❌ ERROR EN TRANSCRIPCIÓN\n"
                    f"   💥 Tipo: {type(e).__name__}\n"
                    f"   📋 Mensaje: {e}"
                )
                raise
    
    def __del__(self):
        """Limpieza al destruir el servicio."""
        try:
            if hasattr(self, 'temp_dir') and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
        except Exception:
            pass


# Singleton del servicio
_transcription_service: Optional[EnhancedTranscriptionService] = None


def get_enhanced_transcription_service(model_size: str = None) -> EnhancedTranscriptionService:
    """
    Factory para obtener el servicio de transcripción (singleton).
    
    Args:
        model_size: Tamaño del modelo (opcional, usa .env por defecto)
        
    Returns:
        Instancia del servicio de transcripción
    """
    global _transcription_service
    
    if model_size is None:
        model_size = settings.WHISPER_MODEL_SIZE
    
    if _transcription_service is None or _transcription_service.model_size != model_size:
        _transcription_service = EnhancedTranscriptionService(model_size)
    
    return _transcription_service
