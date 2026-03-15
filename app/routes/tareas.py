"""
Rutas para gestión de eventos académicos.
CRUD completo con filtros por materia, tipo, estado y fecha.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date, timedelta

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.usuario import Usuario
from app.models.materia import Materia
from app.models.tarea import Tarea
from app.models.enums import TareaEstado, EventoTipo
from app.schemas.tarea import TareaCreate, TareaUpdate, TareaResponse, TareaEstadoEnum, EventoTipoEnum

router = APIRouter(prefix="/tareas", tags=["tareas"])


@router.post("/", response_model=TareaResponse, status_code=status.HTTP_201_CREATED)
def create_tarea(
    tarea_data: TareaCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Crea un nuevo evento académico (tarea, parcial, entrega, etc)."""
    materia = db.query(Materia).filter(
        Materia.id == tarea_data.materia_id,
        Materia.usuario_id == current_user.id
    ).first()
    
    if not materia:
        raise HTTPException(status_code=404, detail="Materia no encontrada")
    
    new_tarea = Tarea(
        titulo=tarea_data.titulo,
        descripcion=tarea_data.descripcion,
        tipo=EventoTipo[tarea_data.tipo.name],
        estado=TareaEstado[tarea_data.estado.name],
        prioridad=tarea_data.prioridad,
        fecha_limite=tarea_data.fecha_limite,
        hora_limite=tarea_data.hora_limite,
        materia_id=tarea_data.materia_id,
        nota_id=tarea_data.nota_id
    )
    db.add(new_tarea)
    db.commit()
    db.refresh(new_tarea)
    return new_tarea


@router.get("/", response_model=List[TareaResponse])
def get_tareas(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    materia_id: Optional[int] = None,
    tipo: Optional[EventoTipoEnum] = None,
    estado: Optional[TareaEstadoEnum] = None,
    proximas: bool = Query(False, description="Solo eventos con fecha futura"),
    semana: bool = Query(False, description="Eventos de esta semana"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Lista eventos con filtros opcionales."""
    query = db.query(Tarea).join(Materia).filter(Materia.usuario_id == current_user.id)
    
    if materia_id:
        query = query.filter(Tarea.materia_id == materia_id)
    if tipo:
        query = query.filter(Tarea.tipo == EventoTipo[tipo.name])
    if estado:
        query = query.filter(Tarea.estado == TareaEstado[estado.name])
    if proximas:
        query = query.filter(Tarea.fecha_limite >= date.today())
    if semana:
        fin_semana = date.today() + timedelta(days=7)
        query = query.filter(
            Tarea.fecha_limite >= date.today(),
            Tarea.fecha_limite <= fin_semana
        )
    
    return query.order_by(
        Tarea.orden.asc(),
        Tarea.fecha_limite.asc().nullslast(),
        Tarea.prioridad.desc()
    ).offset(skip).limit(limit).all()


@router.get("/pendientes", response_model=List[TareaResponse])
def get_pendientes(
    materia_id: Optional[int] = None,
    tipo: Optional[EventoTipoEnum] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene eventos pendientes ordenados por urgencia.
    Se pueden filtrar por `materia_id` y `tipo` simultáneamente."""
    query = db.query(Tarea).join(Materia).filter(
        Materia.usuario_id == current_user.id,
        Tarea.estado != TareaEstado.COMPLETADA
    )

    if materia_id:
        query = query.filter(Tarea.materia_id == materia_id)
    if tipo:
        query = query.filter(Tarea.tipo == EventoTipo[tipo.name])

    return query.order_by(
        Tarea.orden.asc(),
        Tarea.fecha_limite.asc().nullslast(),
        Tarea.prioridad.desc()
    ).limit(20).all()


@router.get("/calendario")
def get_calendario(
    mes: int = Query(..., ge=1, le=12),
    anio: int = Query(..., ge=2020, le=2100),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene eventos de un mes para vista calendario."""
    from calendar import monthrange
    
    primer_dia = date(anio, mes, 1)
    ultimo_dia = date(anio, mes, monthrange(anio, mes)[1])
    
    eventos = db.query(Tarea).join(Materia).filter(
        Materia.usuario_id == current_user.id,
        Tarea.fecha_limite >= primer_dia,
        Tarea.fecha_limite <= ultimo_dia
    ).all()
    
    # Agrupar por día
    calendario = {}
    for evento in eventos:
        dia = evento.fecha_limite.day
        if dia not in calendario:
            calendario[dia] = []
        calendario[dia].append({
            "id": evento.id,
            "titulo": evento.titulo,
            "tipo": evento.tipo.value,
            "estado": evento.estado.value,
            "prioridad": evento.prioridad,
            "hora": evento.hora_limite,
            "materia_color": evento.materia.color if evento.materia else None
        })
    
    return {"mes": mes, "anio": anio, "eventos": calendario}

@router.get("/{tarea_id}", response_model=TareaResponse)
def get_tarea(
    tarea_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene una tarea por ID."""
    tarea = db.query(Tarea).join(Materia).filter(
        Tarea.id == tarea_id,
        Materia.usuario_id == current_user.id
    ).first()
    
    if not tarea:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    return tarea


@router.put("/{tarea_id}", response_model=TareaResponse)
def update_tarea(
    tarea_id: int,
    tarea_data: TareaUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Actualiza una tarea."""
    tarea = db.query(Tarea).join(Materia).filter(
        Tarea.id == tarea_id,
        Materia.usuario_id == current_user.id
    ).first()
    
    if not tarea:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    
    update_data = tarea_data.model_dump(exclude_unset=True)
    
    # Validar materia si se cambia
    if "materia_id" in update_data:
        materia = db.query(Materia).filter(
            Materia.id == update_data["materia_id"],
            Materia.usuario_id == current_user.id
        ).first()
        if not materia:
            raise HTTPException(status_code=404, detail="Materia no encontrada")
    
    # Convertir enums si presentes
    if "estado" in update_data and update_data["estado"]:
        update_data["estado"] = TareaEstado[update_data["estado"].name]
    if "tipo" in update_data and update_data["tipo"]:
        update_data["tipo"] = EventoTipo[update_data["tipo"].name]
    
    for key, value in update_data.items():
        setattr(tarea, key, value)
    
    db.commit()
    db.refresh(tarea)
    return tarea


@router.post('/reorder', status_code=status.HTTP_204_NO_CONTENT)
def reorder_tareas(
    ids: List[int],
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Reordena tareas según lista de ids en el orden deseado."""
    if not ids:
        return None

    tareas = db.query(Tarea).filter(Tarea.id.in_(ids)).join(Materia).filter(Materia.usuario_id == current_user.id).all()
    tarea_map = {t.id: t for t in tareas}

    for index, tid in enumerate(ids):
        tarea = tarea_map.get(tid)
        if tarea:
            tarea.orden = index

    db.commit()
    return None


@router.delete("/{tarea_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tarea(
    tarea_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Elimina una tarea."""
    tarea = db.query(Tarea).join(Materia).filter(
        Tarea.id == tarea_id,
        Materia.usuario_id == current_user.id
    ).first()
    
    if not tarea:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    
    db.delete(tarea)
    db.commit()
    return None