# Importación de los schemas
from app.schemas.usuario import UsuarioBase, UsuarioCreate, UsuarioUpdate, UsuarioResponse
from app.schemas.materia import MateriaBase, MateriaCreate, MateriaUpdate, MateriaResponse, MateriaDetail
from app.schemas.tarea import TareaBase, TareaCreate, TareaUpdate, TareaResponse, TareaEstadoEnum, EventoTipoEnum
from app.schemas.nota import NotaBase, NotaCreate, NotaUpdate, NotaResponse, NotaDetail, AdjuntoResponse
from app.schemas.archivo import ArchivoBase, ArchivoCreate, ArchivoUpdate, ArchivoResponse
from app.schemas.token import Token, RefreshToken, TokenPayload
