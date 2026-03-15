from sqlalchemy import Column, ForeignKey, Integer, String, Text, DateTime, Enum, Date
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.enums import TareaEstado, EventoTipo


class Tarea(Base):
    """
    Evento académico: tarea, parcial, entrega, etc.
    Representa cualquier cosa con fecha límite.
    """
    __tablename__ = "tareas"
    
    id = Column(Integer, primary_key=True, index=True)
    titulo = Column(String(200), index=True)
    descripcion = Column(Text, nullable=True)
    
    # Tipo y estado
    tipo = Column(Enum(EventoTipo), default=EventoTipo.TAREA, index=True)
    estado = Column(Enum(TareaEstado), default=TareaEstado.PENDIENTE, index=True)
    prioridad = Column(Integer, default=0)  # 0=normal, 1=importante, 2=urgente
    
    # Fechas
    fecha_limite = Column(Date, nullable=True, index=True)
    hora_limite = Column(String(5), nullable=True)  # HH:MM formato
    
    # Relación
    materia_id = Column(Integer, ForeignKey("materias.id"))
    nota_id = Column(Integer, ForeignKey("notas.id"), nullable=True)  # Vincular a una clase
    
    # Timestamps
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now())
    fecha_actualizacion = Column(DateTime(timezone=True), onupdate=func.now())
    # Orden personalizado para reordenamiento por el usuario
    orden = Column(Integer, default=0, index=True)
    
    # Relaciones
    materia = relationship("Materia", back_populates="tareas")
    nota = relationship("Nota")  # Clase relacionada (opcional)
    
    def __repr__(self):
        return f"<Tarea {self.titulo}>"