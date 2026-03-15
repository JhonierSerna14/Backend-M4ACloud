from sqlalchemy import Column, ForeignKey, Index, Integer, String, Text, DateTime, Date
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class Nota(Base):
    """
    Nota/Lienzo de clase.
    Puede ser generada desde audio o creada manualmente.
    Soporta contenido Markdown con imágenes y enlaces.
    """
    __tablename__ = "notas"
    __table_args__ = (
        Index("ix_notas_materia_fecha", "materia_id", "fecha_clase"),
    )
    
    id = Column(Integer, primary_key=True, index=True)
    titulo = Column(String(200), index=True)
    contenido = Column(Text, nullable=True)  # Markdown enriquecido
    materia_id = Column(Integer, ForeignKey("materias.id"), index=True)
    
    # Metadata de clase
    fecha_clase = Column(Date, nullable=True, index=True)  # Fecha de la clase
    
    # Audio origen (si fue transcrita)
    origen_audio = Column(String(255), nullable=True)
    duracion_audio = Column(Integer, nullable=True)  # Duración en segundos
    idioma_detectado = Column(String(10), nullable=True)  # es, en, etc.
    transcripcion_path = Column(String(512), nullable=True)  # Ruta al archivo de transcripción guardado
    # Estado y progreso del procesamiento (para notas generadas desde audio)
    status = Column(String(20), nullable=False, default="pending", index=True)
    progreso = Column(Integer, nullable=False, default=0)
    status_message = Column(String(255), nullable=True)  # Human-readable progress message
    
    # Timestamps
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now())
    fecha_actualizacion = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relaciones
    materia = relationship("Materia", back_populates="notas")
    adjuntos = relationship("Adjunto", back_populates="nota", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Nota {self.titulo}>"


class Adjunto(Base):
    """
    Archivo adjunto a una nota (imágenes, PDFs, etc).
    Se usa para embeber imágenes en el lienzo.
    """
    __tablename__ = "adjuntos"
    
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(255))
    ruta = Column(String(512))  # Path relativo en storage
    tipo = Column(String(100))  # MIME type
    tamaño = Column(Integer, nullable=True)
    nota_id = Column(Integer, ForeignKey("notas.id"))
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relaciones
    nota = relationship("Nota", back_populates="adjuntos")
    
    def __repr__(self):
        return f"<Adjunto {self.nombre}>"