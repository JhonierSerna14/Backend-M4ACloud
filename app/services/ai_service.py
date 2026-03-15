"""
Servicio de generación de resúmenes académicos con IA.
Genera notas de estudio detalladas en formato HTML.
Soporta Groq y Gemini con fallback automático entre proveedores.
"""
import asyncio
import random
import time
from typing import Optional, Dict, Callable
from dataclasses import dataclass
from enum import Enum

import httpx
from loguru import logger

from app.core.config import settings


# ---------------------------------------------------------------------------
# Proveedores
# ---------------------------------------------------------------------------


class AIProvider(Enum):
    """Proveedores de IA disponibles."""

    GROQ = "groq"
    GEMINI = "gemini"
    DISABLED = "disabled"


@dataclass
class ProviderConfig:
    """Configuración de un proveedor de IA."""

    name: str
    api_url: str
    api_key_attr: str
    default_model: str
    model_attr: str
    max_tokens: int
    max_input_chars: int = 30000  # Máx. caracteres para procesamiento en una sola fase


PROVIDERS: Dict[AIProvider, ProviderConfig] = {
    AIProvider.GROQ: ProviderConfig(
        name="Groq",
        api_url="https://api.groq.com/openai/v1/chat/completions",
        api_key_attr="GROQ_API_KEY",
        default_model="llama-3.3-70b-versatile",
        model_attr="GROQ_MODEL",
        max_tokens=16384,
        max_input_chars=30000,
    ),
    AIProvider.GEMINI: ProviderConfig(
        name="Gemini",
        api_url="https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        api_key_attr="GEMINI_API_KEY",
        default_model="gemini-2.5-flash",
        model_attr="GEMINI_MODEL",
        max_tokens=32768,
        max_input_chars=500000,
    ),
}

# Tiempo máximo (s) que se espera un rate-limit antes de cambiar de proveedor.
RATE_LIMIT_WAIT_THRESHOLD = 120.0


# ---------------------------------------------------------------------------
# Prompts unificados
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "Eres un asistente académico especializado en crear apuntes de clase a partir de "
    "transcripciones de audio. Tu trabajo es EXTRAER y ORGANIZAR fielmente el contenido "
    "real de la clase, NO generar contenido genérico de libro de texto.\n\n"
    "REGLA FUNDAMENTAL: Solo incluye temas, conceptos, ejemplos, ejercicios y tareas que "
    "realmente se mencionaron en la transcripción. Si el profesor mencionó un concepto "
    "brevemente, puedes agregar una definición corta entre paréntesis para clarificar, "
    "pero NUNCA inventes secciones enteras con contenido que no se discutió en clase. "
    "La transcripción proviene de audio y puede contener errores de reconocimiento de voz; "
    "interpreta inteligentemente las palabras mal transcritas según el contexto académico. "
    "Produces HTML válido y bien estructurado."
)

# Instrucciones compartidas de formato HTML que se inyectan en todos los prompts.
HTML_FORMAT_RULES = """
REGLAS DE FORMATO (HTML puro, sin Markdown ni bloques de código):
- Usa <h1> para el título principal, <h2> para secciones, <h3> para subsecciones.
- Escribe párrafos explicativos (<p>) ricos en contenido; evita el abuso de listas.
- Usa <table> solo para datos comparativos o cronogramas.
- Usa <strong>, <em> y <code> para resaltar términos clave.
- NO incluyas ```html, ```, ni estilos inline (style="...").
""".strip()

TASK_DETECTION_RULES = """
DETECCIÓN DE CARGA ACADÉMICA (MUY IMPORTANTE — analiza con extremo cuidado):
- Busca CUALQUIER mención a: talleres, trabajos, ejercicios, tareas, exámenes, parciales,
  quices, entregas, "para la próxima clase", "tienen que hacer", "van a entregar",
  "quiero que hagan", "me verifican", paneles de discusión, presentaciones, lecturas
  asignadas, documentos para revisar, o cualquier actividad que el estudiante deba realizar.
- Las transcripciones de audio son informales. Busca indicios implícitos como "esto lo van
  a hacer ustedes", "me entregan", "para el próximo día", "van a implementar", etc.
- Si las encuentras, crea una sección <h2>📝 Carga Académica y Fechas Importantes</h2> con una tabla
  (columnas: Actividad | Fecha/Plazo | Descripción detallada / Instrucciones del profesor).
  Incluye TODOS los detalles y contexto que dio el profesor sobre cada actividad.
- Si NO hay absolutamente ninguna mención, escribe:
  <p><strong>No se mencionaron tareas, exámenes ni fechas de entrega en esta clase.</strong></p>
""".strip()


def _build_single_phase_prompt(transcript: str, *, materia_nombre: str = "") -> str:
    """Prompt para transcripciones cortas (una sola llamada)."""
    materia_ctx = f"\nMATERIA: {materia_nombre}\nContextualiza el contenido dentro de esta asignatura.\n" if materia_nombre else ""
    return f"""Crea notas de estudio detalladas a partir de la siguiente transcripción de clase.

REGLA PRINCIPAL — FIDELIDAD AL CONTENIDO REAL:
- SOLO incluye temas, conceptos, ejemplos y ejercicios que aparezcan en la transcripción.
- NO generes párrafos genéricos de libro de texto sobre el tema general.
- Captura los detalles específicos: nombres de algoritmos, herramientas, software,
  fórmulas, recursos (URLs, notebooks), ejemplos concretos que usó el profesor.
- Si el profesor mencionó un concepto sin explicarlo, agrega UNA oración aclaratoria
  entre paréntesis, no párrafos enteros de teoría general.
- La transcripción proviene de audio y puede tener errores de reconocimiento de voz.
  Interpreta inteligentemente palabras mal transcritas según el contexto académico.
{materia_ctx}
INSTRUCCIONES:
1. EXTRACCIÓN FIEL: Identifica todos los temas que el profesor realmente discutió y
   organízalos en un orden lógico.
2. DETALLES CONCRETOS: Preserva nombres propios, herramientas, recursos, códigos y
   cualquier detalle específico mencionado en clase.
3. ÉNFASIS DEL PROFESOR: Si el profesor repitió algo, lo enfatizó o dijo que era
   importante, destácalo con <strong>.
4. EJERCICIOS Y ACTIVIDADES: Extrae TODAS las actividades asignadas o realizadas en
   clase con sus instrucciones específicas tal como las dio el profesor.
5. LIMPIEZA: Elimina muletillas y repeticiones pero preserva todo el contenido relevante.

ESTRUCTURA (HTML puro):
<h1>📚 [Título específico basado en los temas REALES de la clase, no genérico]</h1>
<h2>🚀 Resumen Ejecutivo</h2>
<p>[2-3 párrafos que describan fielmente qué se cubrió en esta sesión de clase,
 qué actividades se realizaron y qué se espera del estudiante.]</p>
<h2>📖 Desarrollo Temático</h2>
[Subcapítulos (h3) por cada tema real discutido en clase. Para cada tema, incluye
 lo que el profesor explicó, los ejemplos que usó y las demostraciones que hizo.
 NO inventes contenido adicional que no se haya discutido.]
<h2>🛠 Herramientas y Recursos</h2>
[Solo si el profesor mencionó herramientas, simuladores, notebooks, URLs o recursos.
 Lista cada recurso con su propósito específico. Si no mencionó ninguno, omite esta sección.]
[Sección de carga académica — ver instrucciones abajo.]
<h2>🧠 Preguntas de Repaso</h2>
[5 preguntas basadas en el contenido REAL de ESTA clase. Las preguntas deben referirse
 a los temas específicos que se discutieron, no a la materia en general.
 Deben requerir análisis, comparación o aplicación de lo visto en clase.]

{HTML_FORMAT_RULES}

{TASK_DETECTION_RULES}

TRANSCRIPCIÓN:
{transcript}"""


def _build_chunk_prompt(chunk: str, section_num: int, total_sections: int, *, materia_nombre: str = "") -> str:
    """Prompt para Fase 1: resumir una sección individual."""
    materia_ctx = f"\nMATERIA: {materia_nombre}\n" if materia_nombre else ""
    return f"""Extrae notas de estudio detalladas y fieles de esta sección de una transcripción de clase.
{materia_ctx}
INSTRUCCIONES CRÍTICAS:
1. FIDELIDAD: Solo incluye lo que realmente se discutió en este fragmento.
   NO agregues teoría genérica que no aparezca en la transcripción.
2. DETALLES: Preserva nombres específicos de algoritmos, herramientas, ejemplos,
   ejercicios, URLs, notebooks y cualquier recurso mencionado.
3. LIMPIEZA: Elimina muletillas y repeticiones pero preserva todo el contenido relevante.
4. TONO: Académico y claro. Usa párrafos explicativos y listas cuando sea apropiado.
5. TAREAS: Si detectas menciones a tareas, ejercicios, entregas, fechas o actividades
   asignadas, extráelas en una subsección aparte con todos los detalles del profesor.
6. ERRORES DE AUDIO: La transcripción puede tener errores de reconocimiento de voz.
   Interpreta inteligentemente según el contexto académico.

{HTML_FORMAT_RULES}

SECCIÓN {section_num}/{total_sections}:
{chunk}"""


def _build_unification_prompt(combined_summaries: str, *, materia_nombre: str = "") -> str:
    """Prompt para Fase 2: unificar resúmenes parciales en un documento final."""
    materia_ctx = f"\nMATERIA: {materia_nombre}\nContextualiza las notas dentro de esta asignatura.\n" if materia_nombre else ""
    return f"""Unifica los siguientes borradores de secciones de una clase en un
DOCUMENTO DE NOTAS DE CLASE COHESIVO en formato HTML.
{materia_ctx}
INSTRUCCIONES:
1. FIDELIDAD: El documento final debe reflejar SOLO lo que se discutió en clase.
   No agregues contenido genérico de libro de texto que no esté en los borradores.
2. NARRATIVA FLUIDA: El texto debe leerse como un documento continuo, no como
   fragmentos pegados. Usa conectores lógicos y transiciones suaves.
3. FUSIÓN INTELIGENTE: Elimina redundancias. Si un tema aparece en varias partes,
   crea una única sección con toda la información combinada.
4. PRESERVAR DETALLES: No pierdas nombres, herramientas, recursos, ejercicios ni
   instrucciones específicas del profesor al unificar.
5. EXTENSIÓN: Genera un documento completo. No recortes contenido relevante.

ESTRUCTURA REQUERIDA:
<h1>📚 [Título específico basado en los temas reales de la clase]</h1>
<h2>🚀 Resumen Ejecutivo</h2>
<p>[2-3 párrafos que sinteticen fielmente lo cubierto en clase, las actividades
 realizadas y lo que se espera del estudiante.]</p>
<h2>📖 Desarrollo Temático</h2>
[Subcapítulos (h3) por cada tema real discutido. Párrafos detallados con los
 ejemplos y explicaciones del profesor.]
<h2>🛠 Herramientas y Recursos</h2>
[Solo si se mencionaron herramientas, simuladores, notebooks o recursos. Omitir si no aplica.]
[Sección de carga académica — ver instrucciones abajo.]
<h2>🧠 Preguntas de Repaso</h2>
[5 preguntas basadas en el contenido real de esta clase específica.
 Deben requerir análisis, comparación o aplicación de lo visto.]

{HTML_FORMAT_RULES}

{TASK_DETECTION_RULES}

BORRADORES A UNIFICAR:
{combined_summaries}"""


# ---------------------------------------------------------------------------
# Servicio principal
# ---------------------------------------------------------------------------


class AcademicAIService:
    """
    Servicio para generar resúmenes académicos usando múltiples proveedores de IA.
    Soporta transcripciones largas mediante procesamiento en dos fases.
    Incluye fallback automático entre proveedores cuando hay rate limits.
    """

    def __init__(self):
        self.primary_provider = self._detect_provider()
        self.fallback_providers = self._build_fallback_list()
        self.rate_limit_until: Dict[AIProvider, float] = {}

        logger.info(f"AI Service iniciado | proveedor={self.primary_provider.value}")
        if self.fallback_providers:
            logger.info(f"  Fallbacks: {[p.value for p in self.fallback_providers]}")

    # ------------------------------------------------------------------
    # Detección y selección de proveedores
    # ------------------------------------------------------------------

    def _detect_provider(self) -> AIProvider:
        """Detecta el proveedor principal según configuración."""
        provider_name = (settings.SUMMARY_PROVIDER or "groq").lower()

        if provider_name == "disabled":
            return AIProvider.DISABLED

        # Proveedor configurado explícitamente
        if provider_name == "groq" and settings.GROQ_API_KEY:
            return AIProvider.GROQ
        if provider_name == "gemini" and getattr(settings, "GEMINI_API_KEY", None):
            return AIProvider.GEMINI

        # Fallback: usar el primero con API key disponible
        if settings.GROQ_API_KEY:
            return AIProvider.GROQ
        if getattr(settings, "GEMINI_API_KEY", None):
            return AIProvider.GEMINI

        logger.error("No hay API keys configuradas para ningún proveedor de IA")
        return AIProvider.DISABLED

    def _build_fallback_list(self) -> list[AIProvider]:
        """Construye la lista de proveedores de fallback (Gemini prioritario)."""
        fallbacks = []
        for provider in [AIProvider.GEMINI, AIProvider.GROQ]:
            if provider == self.primary_provider:
                continue
            key = self._get_api_key(provider)
            if key:
                fallbacks.append(provider)
        return fallbacks

    def _get_api_key(self, provider: AIProvider) -> str:
        """Obtiene la API key para un proveedor."""
        config = PROVIDERS.get(provider)
        if not config:
            return ""
        return getattr(settings, config.api_key_attr, "") or ""

    def _get_model(self, provider: AIProvider) -> str:
        """Obtiene el modelo configurado para un proveedor."""
        config = PROVIDERS.get(provider)
        if not config:
            return ""
        return getattr(settings, config.model_attr, config.default_model) or config.default_model

    def _is_rate_limited(self, provider: AIProvider) -> bool:
        """Verifica si un proveedor está en rate limit."""
        if provider in self.rate_limit_until:
            if time.time() < self.rate_limit_until[provider]:
                return True
            del self.rate_limit_until[provider]
        return False

    def _select_available_provider(self) -> Optional[AIProvider]:
        """Selecciona un proveedor disponible (no rate-limited)."""
        if not self._is_rate_limited(self.primary_provider):
            return self.primary_provider
        for provider in self.fallback_providers:
            if not self._is_rate_limited(provider):
                logger.info(f"Cambiando a proveedor alternativo: {provider.value}")
                return provider
        return None

    # ------------------------------------------------------------------
    # Llamadas a proveedores
    # ------------------------------------------------------------------

    async def _call_ai(self, prompt: str, max_retries: int = 5) -> Optional[str]:
        """Llama al proveedor disponible con fallback automático."""
        provider = self._select_available_provider()

        if not provider:
            # Todos en rate-limit: esperar al que expire primero
            if self.rate_limit_until:
                min_wait = min(self.rate_limit_until.values()) - time.time()
                if min_wait > 0:
                    logger.info(f"Todos los proveedores en rate-limit. Esperando {min_wait:.0f}s...")
                    await asyncio.sleep(min_wait + 1)
                    provider = self._select_available_provider()

        if not provider:
            logger.error("No hay proveedores de IA disponibles")
            return None

        return await self._call_provider(provider, prompt, max_retries)

    async def _call_provider(
        self,
        provider: AIProvider,
        prompt: str,
        max_retries: int = 5,
    ) -> Optional[str]:
        """Ejecuta la llamada HTTP al proveedor con reintentos y manejo de rate-limit."""
        if provider == AIProvider.DISABLED:
            return None
        if provider == AIProvider.GEMINI:
            return await self._call_gemini(prompt, max_retries)

        config = PROVIDERS.get(provider)
        if not config:
            return None

        api_key = self._get_api_key(provider)
        if not api_key:
            logger.error(f"No hay API key para {provider.value}")
            return None

        model = self._get_model(provider)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": settings.AI_TEMPERATURE,
            "max_tokens": config.max_tokens,
        }

        for attempt in range(max_retries):
            try:
                logger.debug(f"{provider.value}: intento {attempt + 1}/{max_retries}")

                async with httpx.AsyncClient(timeout=float(settings.AI_REQUEST_TIMEOUT)) as client:
                    response = await client.post(config.api_url, json=payload, headers=headers)

                    if response.status_code == 429:
                        result = await self._handle_rate_limit(
                            provider, response, attempt, max_retries, prompt
                        )
                        if result:
                            return result
                        continue

                    response.raise_for_status()
                    data = response.json()

                    if "choices" in data and data["choices"]:
                        return data["choices"][0]["message"]["content"].strip()
                    return None

            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP {e.response.status_code} [{provider.value}]: {e.response.text[:200]}")
                if e.response.status_code == 413:
                    return None
                # Errores 4xx (excepto 429) no se reintentan
                if 400 <= e.response.status_code < 500:
                    return None

            except httpx.TimeoutException:
                logger.warning(f"Timeout [{provider.value}] intento {attempt + 1}")
                await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"Error [{provider.value}]: {type(e).__name__}: {e}")
                await asyncio.sleep(2)

        logger.error(f"{provider.value}: agotados {max_retries} reintentos")
        return None

    async def _call_gemini(self, prompt: str, max_retries: int = 3) -> Optional[str]:
        """Llamada específica para Google Gemini (API REST diferente a OpenAI)."""
        api_key = self._get_api_key(AIProvider.GEMINI)
        if not api_key:
            logger.error("No hay GEMINI_API_KEY configurada")
            return None

        config = PROVIDERS[AIProvider.GEMINI]
        model = self._get_model(AIProvider.GEMINI)
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )

        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": settings.AI_TEMPERATURE,
                "maxOutputTokens": config.max_tokens,
            },
        }

        for attempt in range(max_retries):
            try:
                logger.debug(f"Gemini: intento {attempt + 1}/{max_retries} (modelo={model})")

                async with httpx.AsyncClient(timeout=float(settings.AI_REQUEST_TIMEOUT)) as client:
                    response = await client.post(
                        url, json=payload, headers={"Content-Type": "application/json"}
                    )

                    if response.status_code == 429:
                        retry_after = float(response.headers.get("retry-after", "60"))
                        delay = min(retry_after + 1.0, 60.0)
                        logger.warning(f"Rate limit [Gemini] — esperando {delay:.0f}s")
                        self.rate_limit_until[AIProvider.GEMINI] = time.time() + delay
                        await asyncio.sleep(delay)
                        continue

                    if response.status_code == 404:
                        logger.error(f"Gemini: modelo '{model}' no encontrado (404)")
                        return None

                    response.raise_for_status()
                    data = response.json()

                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            text = parts[0].get("text", "")
                            if text:
                                return text.strip()

                    logger.warning("Gemini: respuesta vacía o malformada")
                    return None

            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP {e.response.status_code} [Gemini]: {e.response.text[:200]}")
                if 400 <= e.response.status_code < 500:
                    return None

            except Exception as e:
                logger.error(f"Error [Gemini]: {type(e).__name__}: {e}")
                await asyncio.sleep(2)

        return None

    async def _handle_rate_limit(
        self,
        provider: AIProvider,
        response: httpx.Response,
        attempt: int,
        max_retries: int,
        prompt: str,
    ) -> Optional[str]:
        """Maneja respuestas 429 con espera o cambio de proveedor."""
        retry_after = response.headers.get("retry-after", "")
        try:
            wait_seconds = float(retry_after) + 1.0
        except ValueError:
            wait_seconds = (5 * (2 ** attempt)) + random.uniform(1, 3)

        self.rate_limit_until[provider] = time.time() + wait_seconds

        logger.warning(
            f"Rate limit [{provider.value}] | espera={wait_seconds:.0f}s | "
            f"intento {attempt + 1}/{max_retries}"
        )

        if wait_seconds <= RATE_LIMIT_WAIT_THRESHOLD:
            await asyncio.sleep(wait_seconds)
            return None  # Señal para reintentar en el loop

        # Espera larga: intentar con proveedor alternativo
        alt = self._select_available_provider()
        if alt and alt != provider:
            logger.info(f"Cambiando a {alt.value} por espera larga en {provider.value}")
            return await self._call_provider(alt, prompt, max_retries - attempt)

        # Sin alternativas: esperar el threshold máximo
        logger.warning(f"Sin proveedores alternativos. Esperando {RATE_LIMIT_WAIT_THRESHOLD:.0f}s...")
        await asyncio.sleep(RATE_LIMIT_WAIT_THRESHOLD)
        return None

    # ------------------------------------------------------------------
    # Generación de resúmenes
    # ------------------------------------------------------------------

    @staticmethod
    def _split_transcript(transcript: str, max_chars: int = 12000) -> list[str]:
        """Divide la transcripción en chunks respetando límites de palabras."""
        words = transcript.split()
        chunks: list[str] = []
        current: list[str] = []
        length = 0

        for word in words:
            wlen = len(word) + 1
            if length + wlen > max_chars and current:
                chunks.append(" ".join(current))
                current = [word]
                length = wlen
            else:
                current.append(word)
                length += wlen

        if current:
            chunks.append(" ".join(current))
        return chunks

    async def _generate_two_phase(
        self, transcript: str, progress_callback: Optional[Callable] = None,
        *, materia_nombre: str = ""
    ) -> str:
        """
        Genera resumen en dos fases para transcripciones largas.
        Fase 1: Resume cada sección individualmente.
        Fase 2: Unifica los resúmenes en un documento cohesivo.
        """
        chunks = self._split_transcript(transcript)
        total = len(chunks)
        delay = settings.GROQ_REQUEST_DELAY

        logger.info(
            f"Procesamiento en dos fases | {len(transcript):,} chars | "
            f"{total} secciones | delay={delay}s"
        )

        # — Fase 1: resumir cada sección —
        partial_summaries: list[str] = []

        for i, chunk in enumerate(chunks):
            section = i + 1

            if progress_callback:
                pct = (i / total) * 70  # 0-70% para fase 1
                await progress_callback(pct, f"Procesando sección {section} de {total}")

            prompt = _build_chunk_prompt(chunk, section, total, materia_nombre=materia_nombre)
            summary = await self._call_ai(prompt)

            if summary:
                partial_summaries.append(summary)
                logger.info(f"Sección {section}/{total} completada ({len(summary):,} chars)")
            else:
                partial_summaries.append("<p><em>[Sección no procesada]</em></p>")
                logger.warning(f"Sección {section}/{total} no pudo ser procesada")

            if i < total - 1:
                await asyncio.sleep(delay)

        valid_count = sum(1 for s in partial_summaries if "[Sección no procesada]" not in s)
        if valid_count == 0:
            logger.error("Ninguna sección pudo ser procesada")
            return self._fallback_summary(transcript)

        # — Fase 2: unificar —
        logger.info(f"Fase 1 completada: {valid_count}/{total} secciones. Unificando...")

        if progress_callback:
            await progress_callback(80, "Combinando resúmenes...")

        # Pausa para respetar rate-limits antes de la llamada de unificación
        await asyncio.sleep(min(delay * 3, 30.0))

        combined = "\n\n".join(
            f"<!-- Sección {i + 1} -->\n{s}" for i, s in enumerate(partial_summaries)
        )
        final_prompt = _build_unification_prompt(combined, materia_nombre=materia_nombre)
        final = await self._call_ai(final_prompt)

        if final:
            logger.info(f"Documento final generado: {len(final):,} chars")
            return self._clean_html(final)

        # Si falla la unificación, concatenar las partes válidas
        logger.warning("Unificación falló; concatenando resúmenes parciales")
        return self._format_partials(partial_summaries)

    async def generate_academic_summary(
        self, transcript: str, progress_callback: Optional[Callable] = None,
        *, materia_nombre: str = ""
    ) -> str:
        """
        Genera un resumen académico detallado de la transcripción.

        Args:
            transcript: Texto de la transcripción.
            progress_callback: Callback async(percent, message) para reportar progreso.
            materia_nombre: Nombre de la materia para contextualizar los prompts.

        Returns:
            Resumen en formato HTML.
        """
        if not transcript or len(transcript.strip()) < 50:
            return self._fallback_summary(transcript)

        if self.primary_provider == AIProvider.DISABLED:
            return self._fallback_summary(transcript)

        # Seleccionar proveedor y determinar umbral de chunking según sus capacidades
        provider = self._select_available_provider()
        if not provider or provider == AIProvider.DISABLED:
            return self._fallback_summary(transcript)

        config = PROVIDERS.get(provider)
        max_single = config.max_input_chars if config else settings.MAX_TRANSCRIPT_SIZE_SINGLE

        logger.info(
            f"Generando resumen | {len(transcript):,} chars | "
            f"proveedor={provider.value} | umbral_single={max_single:,}"
        )

        if len(transcript) > max_single:
            logger.info(f"Modo dos fases (> {max_single:,} chars)")
            return await self._generate_two_phase(transcript, progress_callback, materia_nombre=materia_nombre)

        # Transcripción corta: una sola llamada
        if progress_callback:
            await progress_callback(20, "Generando resumen...")

        prompt = _build_single_phase_prompt(transcript, materia_nombre=materia_nombre)
        result = await self._call_ai(prompt)

        if result:
            logger.info(f"Resumen generado: {len(result):,} chars")
            return self._clean_html(result)

        logger.warning("No se pudo generar resumen; usando fallback")
        return self._fallback_summary(transcript)

    # ------------------------------------------------------------------
    # Utilidades de formato
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_html(text: str) -> str:
        """Limpia el HTML generado por la IA."""
        text = text.strip()

        # Remover bloques de código markdown
        for marker in ("```html", "```"):
            text = text.replace(marker, "")
        text = text.strip()

        # Asegurar que empiece con una etiqueta HTML
        if not text.startswith("<"):
            text = f"<h1>📚 Resumen de Clase</h1>\n{text}"
        return text

    @staticmethod
    def _format_partials(partials: list[str]) -> str:
        """Formatea resúmenes parciales cuando falla la unificación."""
        valid = [s for s in partials if "[Sección no procesada]" not in s]
        if not valid:
            return AcademicAIService._fallback_summary("")

        body = "\n<hr>\n".join(valid)
        return (
            "<h1>📚 Resumen de Clase</h1>\n"
            "<h2>Contenido</h2>\n"
            f"{body}\n"
            "<hr>\n"
            "<p><em>Resumen generado automáticamente (sin unificar).</em></p>"
        )

    @staticmethod
    def _fallback_summary(transcript: str) -> str:
        """Genera resumen básico cuando la IA no está disponible."""
        word_count = len(transcript.split()) if transcript else 0
        duration = word_count / 150

        return f"""<h1>📚 Resumen de Clase</h1>

<h2>📋 Información</h2>
<ul>
  <li><strong>Duración estimada:</strong> {duration:.0f} minutos</li>
  <li><strong>Palabras:</strong> {word_count:,}</li>
</ul>

<h2>📝 Acciones Requeridas</h2>
<p>No fue posible generar el resumen con IA. Revisa la transcripción para:</p>
<ul>
  <li>Identificar tareas y fechas de entrega</li>
  <li>Extraer conceptos clave</li>
  <li>Documentar procedimientos</li>
</ul>

<hr>
<p><em>Resumen automático — revisar transcripción para detalles.</em></p>"""


# ---------------------------------------------------------------------------
# Singleton y helper público
# ---------------------------------------------------------------------------

_ai_service: Optional[AcademicAIService] = None


def get_ai_service() -> AcademicAIService:
    """Obtiene la instancia singleton del servicio de IA."""
    global _ai_service
    if _ai_service is None:
        _ai_service = AcademicAIService()
    return _ai_service


async def summarize_transcript(
    transcript: str, progress_callback: Optional[Callable] = None,
    *, materia_nombre: str = ""
) -> str:
    """
    Helper público para generar un resumen académico.

    Args:
        transcript: Texto de la transcripción.
        progress_callback: Callback async(percent, message) para reportar progreso.
        materia_nombre: Nombre de la materia (para contextualizar el prompt).

    Returns:
        Resumen en formato HTML.
    """
    service = get_ai_service()
    return await service.generate_academic_summary(transcript, progress_callback, materia_nombre=materia_nombre)
