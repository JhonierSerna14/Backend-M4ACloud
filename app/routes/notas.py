"""
Rutas para gestión de notas/lienzos de clase.
CRUD completo con adjuntos, búsqueda por fecha y exportación PDF.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Query, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, func
from typing import List, Optional
from datetime import date
import uuid
import shutil
import os
from pathlib import Path
import tempfile
from loguru import logger

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.config import settings
from app.core.ws import broadcast
from app.models.usuario import Usuario
from app.models.materia import Materia
from app.models.nota import Nota, Adjunto
from app.schemas.nota import NotaCreate, NotaUpdate, NotaResponse, NotaDetail, AdjuntoResponse

router = APIRouter(prefix="/notas", tags=["notas"])

# Tipos MIME permitidos para adjuntos
ALLOWED_ADJUNTO_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "application/pdf"}


@router.post("/", response_model=NotaResponse, status_code=status.HTTP_201_CREATED)
def create_nota(
    nota_data: NotaCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Crea una nueva nota/lienzo de clase."""
    materia = db.query(Materia).filter(
        Materia.id == nota_data.materia_id,
        Materia.usuario_id == current_user.id
    ).first()
    
    if not materia:
        raise HTTPException(status_code=404, detail="Materia no encontrada")
    
    nota = Nota(
        titulo=nota_data.titulo,
        contenido=nota_data.contenido,
        materia_id=nota_data.materia_id,
        fecha_clase=nota_data.fecha_clase
    )
    db.add(nota)
    db.commit()
    db.refresh(nota)
    return nota


@router.get("/", response_model=List[NotaResponse])
def get_notas(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    materia_id: Optional[int] = None,
    search: Optional[str] = Query(None, min_length=2),
    fecha_desde: Optional[date] = Query(None, description="Notas desde esta fecha"),
    fecha_hasta: Optional[date] = Query(None, description="Notas hasta esta fecha"),
    desde_audio: Optional[bool] = Query(None, description="True=solo de audio, False=solo manuales"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Lista notas con filtros por materia, texto y fecha."""
    query = db.query(Nota).join(Materia).options(joinedload(Nota.materia)).filter(Materia.usuario_id == current_user.id)
    
    if materia_id:
        query = query.filter(Nota.materia_id == materia_id)
    if search:
        query = query.filter(or_(
            Nota.titulo.ilike(f"%{search}%"),
            Nota.contenido.ilike(f"%{search}%")
        ))
    if fecha_desde:
        query = query.filter(Nota.fecha_clase >= fecha_desde)
    if fecha_hasta:
        query = query.filter(Nota.fecha_clase <= fecha_hasta)
    if desde_audio is not None:
        if desde_audio:
            query = query.filter(Nota.origen_audio.isnot(None))
        else:
            query = query.filter(Nota.origen_audio.is_(None))
    
    return query.order_by(Nota.fecha_clase.desc().nullslast(), Nota.fecha_creacion.desc()).offset(skip).limit(limit).all()


@router.get("/recientes", response_model=List[NotaResponse])
def get_recientes(
    limit: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Últimas notas creadas/actualizadas."""
    return db.query(Nota).join(Materia).options(joinedload(Nota.materia)).filter(
        Materia.usuario_id == current_user.id
    ).order_by(Nota.fecha_actualizacion.desc().nullslast(), Nota.fecha_creacion.desc()).limit(limit).all()


@router.get("/stats")
def get_notas_stats(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Estadísticas de notas."""
    total = db.query(func.count(Nota.id)).join(Materia).filter(
        Materia.usuario_id == current_user.id
    ).scalar()
    
    audio_count = db.query(func.count(Nota.id)).join(Materia).filter(
        Materia.usuario_id == current_user.id,
        Nota.origen_audio.isnot(None)
    ).scalar()
    
    by_materia = db.query(
        Materia.id, Materia.nombre, func.count(Nota.id).label("count")
    ).outerjoin(Nota).filter(
        Materia.usuario_id == current_user.id
    ).group_by(Materia.id, Materia.nombre).all()
    
    return {
        "total": total,
        "from_audio": audio_count,
        "manual": total - audio_count,
        "by_materia": [{"id": m.id, "nombre": m.nombre, "notas": m.count} for m in by_materia]
    }


@router.get("/{nota_id}", response_model=NotaDetail)
def get_nota(
    nota_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene una nota con sus adjuntos."""
    nota = db.query(Nota).join(Materia).options(
        joinedload(Nota.materia), joinedload(Nota.adjuntos)
    ).filter(
        Nota.id == nota_id,
        Materia.usuario_id == current_user.id
    ).first()
    
    if not nota:
        raise HTTPException(status_code=404, detail="Nota no encontrada")
    
    result = NotaDetail(
        id=nota.id,
        titulo=nota.titulo,
        contenido=nota.contenido,
        materia_id=nota.materia_id,
        fecha_clase=nota.fecha_clase,
        origen_audio=nota.origen_audio,
        duracion_audio=nota.duracion_audio,
        idioma_detectado=nota.idioma_detectado,
        status=nota.status,
        progreso=nota.progreso,
        fecha_creacion=nota.fecha_creacion,
        fecha_actualizacion=nota.fecha_actualizacion,
        adjuntos=[AdjuntoResponse.model_validate(a) for a in nota.adjuntos],
        materia_nombre=nota.materia.nombre,
        materia_color=nota.materia.color if nota.materia else None
    )
    return result


@router.get("/{nota_id}/status")
def get_nota_status(
    nota_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene el estado y progreso de una nota (útil para polling o UI)."""
    nota = db.query(Nota).join(Materia).filter(
        Nota.id == nota_id,
        Materia.usuario_id == current_user.id
    ).first()

    if not nota:
        raise HTTPException(status_code=404, detail="Nota no encontrada")

    return {"id": nota.id, "status": nota.status, "progress": nota.progreso, "message": nota.status_message}


@router.post("/{nota_id}/reprocess", response_model=NotaResponse)
def reprocess_nota(
    nota_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Encola una nota para reprocesamiento por el worker local.
    El worker retomará el audio existente y regenerará transcripción + resumen.
    """
    nota = db.query(Nota).join(Materia).options(joinedload(Nota.materia)).filter(
        Nota.id == nota_id,
        Materia.usuario_id == current_user.id
    ).first()

    if not nota:
        raise HTTPException(status_code=404, detail="Nota no encontrada")

    if not nota.origen_audio:
        raise HTTPException(status_code=400, detail="Solo se pueden reprocesar notas generadas desde audio")

    if nota.status in ("processing", "queued"):
        raise HTTPException(status_code=409, detail="La nota ya está siendo procesada o en cola")

    nota.status = "queued"
    nota.progreso = 0
    nota.status_message = "En cola para reprocesar"
    nota.contenido = "# ⏳ En Cola para Reprocesar\n\nEsperando al worker para regenerar la transcripción y el resumen."
    db.commit()
    db.refresh(nota)

    logger.info(f"🔄 Nota {nota.id} encolada para reprocesamiento")
    return nota


@router.put("/{nota_id}", response_model=NotaResponse)
def update_nota(
    nota_id: int,
    nota_data: NotaUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Actualiza una nota."""
    nota = db.query(Nota).join(Materia).filter(
        Nota.id == nota_id,
        Materia.usuario_id == current_user.id
    ).first()
    
    if not nota:
        raise HTTPException(status_code=404, detail="Nota no encontrada")
    
    if nota_data.materia_id:
        materia = db.query(Materia).filter(
            Materia.id == nota_data.materia_id,
            Materia.usuario_id == current_user.id
        ).first()
        if not materia:
            raise HTTPException(status_code=404, detail="Materia no encontrada")
    
    for key, value in nota_data.model_dump(exclude_unset=True).items():
        setattr(nota, key, value)
    
    db.commit()
    db.refresh(nota)
    return nota


@router.get("/{nota_id}/pdf")
def export_nota_pdf(
    nota_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Exporta una nota a PDF.
    Convierte el contenido HTML a PDF incluyendo imágenes embebidas.
    """
    nota = db.query(Nota).join(Materia).filter(
        Nota.id == nota_id,
        Materia.usuario_id == current_user.id
    ).first()
    
    if not nota:
        raise HTTPException(status_code=404, detail="Nota no encontrada")
    
    try:
        from weasyprint import HTML, CSS
        import re
        import base64
        import mimetypes
    except (ImportError, OSError) as e:
        logger.error(f"Error al cargar WeasyPrint: {e}")
        raise HTTPException(
            status_code=501,
            detail=(
                "Exportación PDF no disponible: WeasyPrint requiere librerías nativas de GTK/Cairo. "
                "En Linux instale: `apt-get update && apt-get install -y libcairo2 libpango-1.0-0 "
                "libgdk-pixbuf2.0-0 libgobject-2.0-0 shared-mime-info`. "
                "En Windows instale el 'GTK for Windows Runtime' desde "
                "https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases"
            )
        )
    
    contenido = nota.contenido or ""
    
    # Detectar si el contenido ya es HTML o es Markdown
    is_html = bool(re.search(r'<(h[1-6]|p|div|table|ul|ol|pre|code)\b', contenido, re.IGNORECASE))
    
    if is_html:
        # El contenido ya es HTML (generado por IA)
        contenido_html = contenido
    else:
        # Convertir Markdown a HTML solo si es necesario
        try:
            from markdown import markdown
            contenido_html = markdown(contenido, extensions=['tables', 'fenced_code', 'nl2br'])
        except ImportError:
            # Si no hay markdown, usar el contenido como está
            contenido_html = f"<pre>{contenido}</pre>"
    
    # Procesar imágenes: convertir rutas relativas a base64 para embeber en PDF
    upload_path = Path(settings.UPLOAD_DIR)
    
    def embed_image(match):
        """Convierte imágenes a base64 para embeber en el PDF."""
        src = match.group(1)
        
        # Si ya es base64 o URL externa, mantener
        if src.startswith(('data:', 'http://', 'https://')):
            return match.group(0)
        
        # Limpiar la ruta (quitar /api/uploads/ si existe)
        clean_src = re.sub(r'^/?api/uploads/', '', src)
        
        # Buscar el archivo
        abs_path = upload_path / clean_src
        
        if abs_path.exists():
            try:
                mime_type, _ = mimetypes.guess_type(str(abs_path))
                if not mime_type:
                    mime_type = 'image/png'
                
                with open(abs_path, 'rb') as img_file:
                    img_data = base64.b64encode(img_file.read()).decode('utf-8')
                    return f'src="data:{mime_type};base64,{img_data}"'
            except Exception as e:
                # Si falla, usar file:// como fallback
                return f'src="file://{abs_path.absolute()}"'
        
        return match.group(0)
    
    contenido_html = re.sub(r'src="([^"]+)"', embed_image, contenido_html)
    
    # Crear HTML completo con estilos profesionales
    fecha_str = nota.fecha_clase.strftime("%d/%m/%Y") if nota.fecha_clase else "Sin fecha"
    html_completo = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="utf-8">
        <title>{nota.titulo}</title>
        <style>
            @page {{ 
                size: A4; 
                margin: 2cm; 
                @bottom-center {{
                    content: "Página " counter(page) " de " counter(pages);
                    font-size: 9pt;
                    color: #6b7280;
                }}
            }}
            
            body {{ 
                font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif; 
                font-size: 11pt; 
                line-height: 1.6; 
                color: #1f2937;
                max-width: 100%;
            }}
            
            .header {{ 
                border-bottom: 3px solid #2563eb; 
                padding-bottom: 15px; 
                margin-bottom: 25px; 
            }}
            .header h1 {{ 
                color: #1e40af; 
                margin: 0 0 8px 0; 
                font-size: 22pt;
                font-weight: 700;
            }}
            .header .meta {{ 
                color: #4b5563; 
                font-size: 11pt;
            }}
            .header .meta strong {{
                color: #1e40af;
            }}
            
            h1 {{ font-size: 18pt; color: #1e40af; margin-top: 25px; margin-bottom: 10px; page-break-after: avoid; }}
            h2 {{ font-size: 14pt; color: #2563eb; margin-top: 20px; margin-bottom: 8px; page-break-after: avoid; }}
            h3 {{ font-size: 12pt; color: #3b82f6; margin-top: 15px; margin-bottom: 6px; }}
            
            p {{ margin: 8px 0; text-align: justify; }}
            
            code {{ 
                background: #f1f5f9; 
                padding: 2px 6px; 
                border-radius: 4px; 
                font-family: 'Consolas', 'Monaco', monospace; 
                font-size: 10pt;
                color: #0f172a;
            }}
            
            pre {{ 
                background: #1e293b; 
                color: #e2e8f0; 
                padding: 15px 20px; 
                border-radius: 8px; 
                overflow-x: auto;
                font-size: 9pt;
                line-height: 1.4;
                page-break-inside: avoid;
            }}
            pre code {{ 
                background: none; 
                color: inherit; 
                padding: 0;
            }}
            
            table {{ 
                border-collapse: collapse; 
                width: 100%; 
                margin: 15px 0;
                page-break-inside: avoid;
            }}
            th, td {{ 
                border: 1px solid #d1d5db; 
                padding: 10px 12px; 
                text-align: left;
                font-size: 10pt;
            }}
            th {{ 
                background: #f1f5f9; 
                font-weight: 600;
                color: #1e40af;
            }}
            tr:nth-child(even) {{
                background: #f9fafb;
            }}
            
            img {{ 
                max-width: 100%; 
                height: auto; 
                border-radius: 8px; 
                margin: 15px 0;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            }}
            
            blockquote {{ 
                border-left: 4px solid #2563eb; 
                margin: 15px 0; 
                padding: 10px 20px;
                background: #f8fafc;
                color: #374151;
                font-style: italic;
            }}
            
            ul, ol {{ 
                margin: 10px 0; 
                padding-left: 25px; 
            }}
            li {{ 
                margin: 6px 0; 
            }}
            
            /* Checkboxes para listas de tareas */
            input[type="checkbox"] {{
                width: 14px;
                height: 14px;
                margin-right: 8px;
                accent-color: #2563eb;
            }}
            
            /* Separadores */
            hr {{
                border: none;
                border-top: 1px solid #e5e7eb;
                margin: 20px 0;
            }}
            
            /* Emojis */
            .emoji {{
                font-size: 1.1em;
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>{nota.titulo}</h1>
            <div class="meta">
                <strong>{nota.materia.nombre}</strong> • {fecha_str}
            </div>
        </div>
        {contenido_html}
    </body>
    </html>
    """
    
    # Generar PDF
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        HTML(string=html_completo).write_pdf(tmp.name)
        safe_titulo = "".join(c for c in nota.titulo if c.isalnum() or c in (' ', '-', '_')).strip()
        background_tasks.add_task(os.unlink, tmp.name)
        return FileResponse(
            path=tmp.name,
            filename=f"{safe_titulo[:50]}.pdf",
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{safe_titulo[:50]}.pdf"'}
        )


@router.post("/{nota_id}/adjuntos", response_model=AdjuntoResponse, status_code=status.HTTP_201_CREATED)
async def upload_adjunto(
    nota_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Sube una imagen u otro archivo a una nota."""
    nota = db.query(Nota).join(Materia).filter(
        Nota.id == nota_id,
        Materia.usuario_id == current_user.id
    ).first()
    
    if not nota:
        raise HTTPException(status_code=404, detail="Nota no encontrada")
    
    # Validar tipo (solo imágenes y PDFs)
    if file.content_type not in ALLOWED_ADJUNTO_TYPES:
        raise HTTPException(status_code=400, detail="Solo imágenes (jpg, png, gif, webp) y PDFs")
    
    # Crear directorio
    upload_dir = Path(settings.UPLOAD_DIR) / str(current_user.id) / "adjuntos" / str(nota_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    # Guardar archivo
    unique_name = f"{uuid.uuid4()}{Path(file.filename).suffix}"
    file_path = upload_dir / unique_name
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Crear registro
    adjunto = Adjunto(
        nombre=file.filename,
        ruta=str(Path(str(current_user.id)) / "adjuntos" / str(nota_id) / unique_name),
        tipo=file.content_type,
        tamaño=file_path.stat().st_size,
        nota_id=nota_id
    )
    db.add(adjunto)
    db.commit()
    db.refresh(adjunto)

    # Serializar con Pydantic y devolver JSON con URL normalizada
    ruta_normalizada = adjunto.ruta.replace('\\', '/')
    url = f"/api/uploads/{ruta_normalizada}"
    # Devolver la representación serializada con URL normalizada
    adjunto_dict = AdjuntoResponse.model_validate(adjunto).model_dump()
    adjunto_dict['url'] = url
    return adjunto_dict


@router.delete("/{nota_id}/adjuntos/{adjunto_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_adjunto(
    nota_id: int,
    adjunto_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Elimina un adjunto de una nota."""
    adjunto = db.query(Adjunto).join(Nota).join(Materia).filter(
        Adjunto.id == adjunto_id,
        Adjunto.nota_id == nota_id,
        Materia.usuario_id == current_user.id
    ).first()
    
    if not adjunto:
        raise HTTPException(status_code=404, detail="Adjunto no encontrado")
    
    # Eliminar archivo físico
    file_path = Path(settings.UPLOAD_DIR) / adjunto.ruta
    if file_path.exists():
        file_path.unlink()
    
    db.delete(adjunto)
    db.commit()
    return None


@router.delete("/{nota_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_nota(
    nota_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Elimina una nota y sus adjuntos."""
    nota = db.query(Nota).join(Materia).filter(
        Nota.id == nota_id,
        Materia.usuario_id == current_user.id
    ).first()
    
    if not nota:
        raise HTTPException(status_code=404, detail="Nota no encontrada")
    
    # Los adjuntos se eliminan por cascade, pero hay que borrar archivos físicos
    for adjunto in nota.adjuntos:
        file_path = Path(settings.UPLOAD_DIR) / adjunto.ruta
        if file_path.exists():
            file_path.unlink()
    
    db.delete(nota)
    db.commit()
    return None