"""
Rutas para gestión de eventos académicos.
CRUD completo con filtros por materia, tipo, estado y fecha.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date, timedelta

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.semestre import get_semestre_actual, get_materia_editable, require_editable_semestre
from app.core.sync_events import build_sync_event
from app.core.user_ws import broadcast_user
from app.models.usuario import Usuario
from app.models.materia import Materia
from app.models.tarea import Tarea
from app.models.enums import TareaEstado, EventoTipo
from app.schemas.tarea import TareaCreate, TareaUpdate, TareaResponse, TareaEstadoEnum, EventoTipoEnum

router = APIRouter(prefix="/tareas", tags=["tareas"])


def _serialize_tarea(tarea: Tarea) -> dict:
    return TareaResponse.model_validate(tarea).model_dump(mode="json")


@router.post("/", response_model=TareaResponse, status_code=status.HTTP_201_CREATED)
def create_tarea(
    tarea_data: TareaCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Crea un nuevo evento académico (tarea, parcial, entrega, etc)."""
    materia = get_materia_editable(db, current_user, tarea_data.materia_id)
    
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

    background_tasks.add_task(
        broadcast_user,
        current_user.id,
        build_sync_event(
            action="created",
            entity="tarea",
            entity_id=new_tarea.id,
            payload=_serialize_tarea(new_tarea),
            affected_collections=["tareas", "dashboard", "calendario", "materias", f"tarea:{new_tarea.id}"],
        ),
    )
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
    semestre = get_semestre_actual(db, current_user)
    query = db.query(Tarea).join(Materia).filter(
        Materia.usuario_id == current_user.id,
        Materia.semestre_id == semestre.id,
    )
    
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
        Materia.semestre_id == get_semestre_actual(db, current_user).id,
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
        Materia.semestre_id == get_semestre_actual(db, current_user).id,
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
        Materia.usuario_id == current_user.id,
        Materia.semestre_id == get_semestre_actual(db, current_user).id,
    ).first()
    
    if not tarea:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    return tarea


@router.put("/{tarea_id}", response_model=TareaResponse)
def update_tarea(
    tarea_id: int,
    tarea_data: TareaUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Actualiza una tarea."""
    semestre = get_semestre_actual(db, current_user)
    require_editable_semestre(db, current_user, semestre)

    tarea = db.query(Tarea).join(Materia).filter(
        Tarea.id == tarea_id,
        Materia.usuario_id == current_user.id,
        Materia.semestre_id == semestre.id,
    ).first()
    
    if not tarea:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    
    update_data = tarea_data.model_dump(exclude_unset=True)
    
    # Validar materia si se cambia
    if "materia_id" in update_data:
        get_materia_editable(db, current_user, update_data["materia_id"])
    
    # Convertir enums si presentes
    if "estado" in update_data and update_data["estado"]:
        update_data["estado"] = TareaEstado[update_data["estado"].name]
    if "tipo" in update_data and update_data["tipo"]:
        update_data["tipo"] = EventoTipo[update_data["tipo"].name]
    
    for key, value in update_data.items():
        setattr(tarea, key, value)
    
    db.commit()
    db.refresh(tarea)

    background_tasks.add_task(
        broadcast_user,
        current_user.id,
        build_sync_event(
            action="updated",
            entity="tarea",
            entity_id=tarea.id,
            payload=_serialize_tarea(tarea),
            affected_collections=["tareas", "dashboard", "calendario", "materias", f"tarea:{tarea.id}"],
        ),
    )
    return tarea


@router.post('/reorder', status_code=status.HTTP_200_OK)
def reorder_tareas(
    ids: List[int],
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Reordena tareas según lista de ids en el orden deseado."""
    if not ids:
        return None

    semestre = get_semestre_actual(db, current_user)
    require_editable_semestre(db, current_user, semestre)

    tareas = db.query(Tarea).filter(Tarea.id.in_(ids)).join(Materia).filter(
        Materia.usuario_id == current_user.id,
        Materia.semestre_id == semestre.id,
    ).all()
    tarea_map = {t.id: t for t in tareas}

    for index, tid in enumerate(ids):
        tarea = tarea_map.get(tid)
        if tarea:
            tarea.orden = index

    db.commit()

    background_tasks.add_task(
        broadcast_user,
        current_user.id,
        build_sync_event(
            action="reordered",
            entity="tarea",
            entity_id=None,
            payload={"ordered_ids": ids},
            affected_collections=["tareas", "dashboard", "calendario"],
        ),
    )
    return {"ok": True, "ids": ids, "updated": len(tareas)}


@router.delete("/{tarea_id}", status_code=status.HTTP_200_OK)
def delete_tarea(
    tarea_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Elimina una tarea."""
    semestre = get_semestre_actual(db, current_user)
    require_editable_semestre(db, current_user, semestre)

    tarea = db.query(Tarea).join(Materia).filter(
        Tarea.id == tarea_id,
        Materia.usuario_id == current_user.id,
        Materia.semestre_id == semestre.id,
    ).first()
    
    if not tarea:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    
    materia_id = tarea.materia_id
    estado = tarea.estado.value
    db.delete(tarea)
    db.commit()

    background_tasks.add_task(
        broadcast_user,
        current_user.id,
        build_sync_event(
            action="deleted",
            entity="tarea",
            entity_id=tarea_id,
            payload={"id": tarea_id, "materia_id": materia_id, "estado": estado},
            affected_collections=["tareas", "dashboard", "calendario", "materias", f"tarea:{tarea_id}"],
        ),
    )
    return {"ok": True, "id": tarea_id, "materia_id": materia_id}