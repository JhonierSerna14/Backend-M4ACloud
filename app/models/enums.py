"""Enumeraciones para el modelo de datos."""
import enum


class TareaEstado(enum.Enum):
    """Estado de una tarea o evento."""
    PENDIENTE = "pendiente"
    EN_PROGRESO = "en_progreso"
    COMPLETADA = "completada"


class EventoTipo(enum.Enum):
    """Tipo de evento académico."""
    TAREA = "TAREA"           # Tarea para entregar
    PARCIAL = "PARCIAL"       # Examen parcial
    FINAL = "FINAL"           # Examen final
    QUIZ = "QUIZ"             # Quiz o evaluación corta
    ENTREGA = "ENTREGA"       # Entrega de proyecto/trabajo
    EXPOSICION = "EXPOSICION" # Presentación oral
    LECTURA = "LECTURA"       # Lectura asignada
    OTRO = "OTRO"             # Otro tipo de evento