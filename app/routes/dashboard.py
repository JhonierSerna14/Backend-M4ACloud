"""
Rutas de Dashboard.
Vista resumen para la pantalla principal del frontend.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date, timedelta

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.usuario import Usuario
from app.models.materia import Materia
from app.models.nota import Nota
from app.models.tarea import Tarea
from app.models.enums import TareaEstado


router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/")
def get_dashboard(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Vista resumen del usuario.
    
    Incluye:
    - Estadísticas generales
    - Próximos eventos
    - Notas recientes
    """
    hoy = date.today()
    fin_semana = hoy + timedelta(days=7)
    
    # --- Estadísticas ---
    total_materias = db.query(func.count(Materia.id)).filter(
        Materia.usuario_id == current_user.id
    ).scalar()
    
    total_notas = db.query(func.count(Nota.id)).join(Materia).filter(
        Materia.usuario_id == current_user.id
    ).scalar()
    
    total_tareas = db.query(func.count(Tarea.id)).join(Materia).filter(
        Materia.usuario_id == current_user.id
    ).scalar()
    
    tareas_pendientes = db.query(func.count(Tarea.id)).join(Materia).filter(
        Materia.usuario_id == current_user.id,
        Tarea.estado != TareaEstado.COMPLETADA
    ).scalar()
    
    # --- Eventos próximos (7 días) ---
    proximos_eventos = db.query(Tarea).join(Materia).filter(
        Materia.usuario_id == current_user.id,
        Tarea.estado != TareaEstado.COMPLETADA,
        Tarea.fecha_limite >= hoy,
        Tarea.fecha_limite <= fin_semana
    ).order_by(Tarea.fecha_limite.asc()).limit(5).all()
    
    # --- Notas recientes ---
    notas_recientes = db.query(Nota).join(Materia).filter(
        Materia.usuario_id == current_user.id
    ).order_by(Nota.fecha_actualizacion.desc().nullslast(), Nota.fecha_creacion.desc()).limit(5).all()
    
    return {
        "usuario": {
            "nombre": current_user.nombre,
            "email": current_user.email
        },
        "total_materias": total_materias,
        "total_notas": total_notas,
        "total_tareas": total_tareas,
        "tareas_pendientes": tareas_pendientes,
        "proximas_tareas": [
            {
                "id": t.id,
                "titulo": t.titulo,
                "descripcion": t.descripcion,
                "fecha_limite": t.fecha_limite.isoformat() if t.fecha_limite else None,
                "hora_limite": t.hora_limite,
                "estado": t.estado.value,
                "prioridad": t.prioridad,
                "tipo": t.tipo.value,
                "materia_id": t.materia_id,
                "fecha_creacion": t.fecha_creacion.isoformat() if t.fecha_creacion else None,
                "materia": {
                    "id": t.materia.id,
                    "nombre": t.materia.nombre,
                    "color": t.materia.color
                } if t.materia else None
            }
            for t in proximos_eventos
        ],
        "notas_recientes": [
            {
                "id": n.id,
                "titulo": n.titulo,
                "fecha_clase": n.fecha_clase.isoformat() if n.fecha_clase else None,
                "es_de_audio": n.origen_audio is not None,
                "materia_id": n.materia_id,
                "fecha_creacion": (n.fecha_actualizacion or n.fecha_creacion).isoformat() if (n.fecha_actualizacion or n.fecha_creacion) else None,
                "fecha_actualizacion": n.fecha_actualizacion.isoformat() if n.fecha_actualizacion else None,
                "materia": {
                    "id": n.materia.id,
                    "nombre": n.materia.nombre,
                    "color": n.materia.color
                } if n.materia else None
            }
            for n in notas_recientes
        ]
    }


@router.get("/hoy")
def get_hoy(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Vista de "Hoy".
    
    Qué tiene pendiente el usuario para hoy y mañana.
    """
    hoy = date.today()
    manana = hoy + timedelta(days=1)
    
    # Eventos de hoy
    eventos_hoy = db.query(Tarea).join(Materia).filter(
        Materia.usuario_id == current_user.id,
        Tarea.estado != TareaEstado.COMPLETADA,
        Tarea.fecha_limite == hoy
    ).order_by(Tarea.hora_limite.asc().nullslast(), Tarea.prioridad.desc()).all()
    
    # Eventos de mañana
    eventos_manana = db.query(Tarea).join(Materia).filter(
        Materia.usuario_id == current_user.id,
        Tarea.estado != TareaEstado.COMPLETADA,
        Tarea.fecha_limite == manana
    ).order_by(Tarea.hora_limite.asc().nullslast(), Tarea.prioridad.desc()).all()
    
    def format_evento(t):
        return {
            "id": t.id,
            "titulo": t.titulo,
            "tipo": t.tipo.value,
            "hora_limite": t.hora_limite,
            "prioridad": t.prioridad,
            "materia_id": t.materia_id,
            "estado": t.estado.value
        }
    
    return {
        "fecha": hoy.isoformat(),
        "hoy": [format_evento(t) for t in eventos_hoy],
        "manana": [format_evento(t) for t in eventos_manana],
        "total_pendientes_hoy": len(eventos_hoy),
        "total_pendientes_manana": len(eventos_manana)
    }
