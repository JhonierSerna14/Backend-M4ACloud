from sqlalchemy import Boolean, Column, Integer, String, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base

class Usuario(Base):
    __tablename__ = "usuarios"
    
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), index=True)
    email = Column(String(100), unique=True, index=True)
    password_hash = Column(String(255))
    is_active = Column(Boolean, default=True)
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now())
    fecha_actualizacion = Column(DateTime(timezone=True), onupdate=func.now())
    semestre_actual_id = Column(Integer, ForeignKey("semestres.id"), nullable=True)
    
    # Relaciones
    materias = relationship("Materia", back_populates="usuario", cascade="all, delete-orphan")
    semestres = relationship(
        "Semestre",
        back_populates="usuario",
        cascade="all, delete-orphan",
        foreign_keys="Semestre.usuario_id",
    )
    semestre_actual = relationship("Semestre", foreign_keys=[semestre_actual_id])
    
    def __repr__(self):
        return f"<Usuario {self.nombre}>"