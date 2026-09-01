from sqlalchemy import Column, ForeignKey, Integer, String, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class Semestre(Base):
    __tablename__ = "semestres"
    __table_args__ = (
        UniqueConstraint("usuario_id", "codigo", name="uq_semestres_usuario_codigo"),
    )

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(7), nullable=False, index=True)
    nombre = Column(String(100), nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now())

    usuario = relationship("Usuario", back_populates="semestres", foreign_keys=[usuario_id])
    materias = relationship("Materia", back_populates="semestre", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Semestre {self.codigo}>"
