from sqlalchemy import Column, ForeignKey, Integer, String, Text, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base

class Materia(Base):
    __tablename__ = "materias"
    
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), index=True)
    descripcion = Column(Text, nullable=True)
    contenido_html = Column(Text, nullable=True)  # Contenido enriquecido con editor
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now())
    fecha_actualizacion = Column(DateTime(timezone=True), onupdate=func.now())
    color = Column(String(7), nullable=True, index=True)

    # Relaciones
    usuario = relationship("Usuario", back_populates="materias")
    tareas = relationship("Tarea", back_populates="materia", cascade="all, delete-orphan")
    notas = relationship("Nota", back_populates="materia", cascade="all, delete-orphan")
    archivos = relationship("Archivo", back_populates="materia", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Materia {self.nombre}>"