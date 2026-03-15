from sqlalchemy import Column, ForeignKey, Integer, String, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base

class Archivo(Base):
    __tablename__ = "archivos"
    
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(255), index=True)
    ruta = Column(String(512))
    tipo = Column(String(100))  # Tipo MIME del archivo
    tamaño = Column(Integer, nullable=True)  # Tamaño en bytes
    materia_id = Column(Integer, ForeignKey("materias.id"))
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relaciones
    materia = relationship("Materia", back_populates="archivos")
    
    def __repr__(self):
        return f"<Archivo {self.nombre}>"