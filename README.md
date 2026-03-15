# M4A - Academic Management System

Enterprise-grade backend application for academic management featuring intelligent audio transcription, AI-powered summarization, and comprehensive task organization for educational institutions and students.

## Core Features

- **JWT Authentication System** - Secure user registration, login, and token refresh mechanism
- **Academic Subject Management** - Comprehensive organization and tracking of academic subjects
- **Task Management System** - Advanced task creation with deadline tracking and status management
- **Digital Note Management** - Text-based note creation and organization with search capabilities
- **File Management** - Secure file upload and association with academic subjects
- **Audio Transcription Engine** - High-precision speech-to-text conversion using Faster-Whisper
- **AI-Powered Summarization** - Intelligent academic content summarization using Groq (Llama 3)
- **Structured Academic Reports** - Optimized summary generation for educational content

## System Requirements

- Python 3.10 or higher
- PostgreSQL database server
- CUDA-compatible GPU (optional, for enhanced performance)

## Project Architecture

```
/app                    # Core application modules
  /core                 # System configuration and utilities
    config.py           # Environment configuration management
    database.py         # Database connection and session handling
    auth.py             # Authentication middleware and utilities
    security.py         # Security helpers and password management
    logging.py          # Centralized logging configuration
  /models               # SQLAlchemy database models
    usuario.py          # User entity model
    materia.py          # Subject entity model
    tarea.py            # Task entity model
    nota.py             # Note entity model
    archivo.py          # File entity model
    enums.py            # System enumerations
  /routes               # REST API endpoint definitions
    auth.py             # Authentication endpoints
    materias.py         # Subject management endpoints
    tareas.py           # Task management endpoints
    notas.py            # Note management endpoints
    archivos.py         # File management endpoints
    audio.py            # Audio processing endpoints
  /schemas              # Pydantic validation schemas
    usuario.py          # User data validation models
    materia.py          # Subject data validation models
    tarea.py            # Task data validation models
    nota.py             # Note data validation models
    archivo.py          # File data validation models
    token.py            # Authentication token models
  /services             # Business logic services
    ai_service.py       # AI summarization service
    enhanced_transcription_service.py    # Advanced transcription with chunking
  /utils                # Utility modules
    whisper_utils.py    # Whisper model management
  /uploads              # File storage directory
  main.py               # FastAPI application entry point
/alembic                # Database migration management
  /versions             # Migration version files
  env.py                # Alembic environment configuration
run_app.py              # Application startup script
requirements.txt        # Python dependencies
alembic.ini             # Alembic configuration
```

## Installation and Setup

### 1. Repository Setup

```bash
git clone <repository-url>
cd m4a
```

### 2. Environment Configuration

Create a `.env` file in the project root with the following configuration:

```env
# Database Configuration
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/m4a_db

# JWT Authentication Settings
JWT_SECRET=supersecretkey
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# AI Service Configuration
SUMMARY_PROVIDER=groq
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile

# Google Gemini (Fallback - tier gratuito generoso)
# Obtener en: https://aistudio.google.com/apikey
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-1.5-flash

# Proveedores alternativos opcionales
# (Together y OpenRouter han sido eliminados del proyecto)

# Audio Transcription Settings (Faster-Whisper)
# Model sizes: tiny | base | small | medium | large | large-v2 | large-v3
WHISPER_MODEL_SIZE=large-v3
# Device selection: auto | cuda | cpu
WHISPER_DEVICE=auto
# Compute precision: float32 | float16 | int8_float16 | int8_float32 | int8
WHISPER_COMPUTE_TYPE=int8_float16
# Audio processing configuration
CHUNK_DURATION_MINUTES=10
CHUNK_OVERLAP_SECONDS=30
MAX_PARALLEL_CHUNKS=1
```

### 3. GPU Optimization Configuration

#### Performance Optimization by Hardware

**RTX 3050 / GTX 1660 (4GB VRAM)**
```env
WHISPER_MODEL_SIZE=medium
WHISPER_COMPUTE_TYPE=int8
CHUNK_DURATION_MINUTES=5
MAX_PARALLEL_CHUNKS=1
```

**RTX 3060 / RTX 2060 (6-8GB VRAM)**
```env
WHISPER_MODEL_SIZE=large-v3
WHISPER_COMPUTE_TYPE=int8_float16
CHUNK_DURATION_MINUTES=10
MAX_PARALLEL_CHUNKS=2
```

**RTX 3090 / RTX 4090 (12GB+ VRAM)**
```env
WHISPER_MODEL_SIZE=large-v3
WHISPER_COMPUTE_TYPE=float16
CHUNK_DURATION_MINUTES=15
MAX_PARALLEL_CHUNKS=3
```

**CPU Processing (No GPU)**
```env
WHISPER_MODEL_SIZE=small
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
CHUNK_DURATION_MINUTES=3
MAX_PARALLEL_CHUNKS=1
```

### 4. Memory Management and Error Handling

The system implements automatic fallback mechanisms for CUDA memory limitations:

- **Automatic compute type reduction**: Falls back from `float16` to `int8`
- **Model size optimization**: Automatically reduces model size when memory constraints are detected
- **CPU fallback**: Switches to CPU processing as last resort
- **Memory cleanup**: Automatic CUDA cache clearing between processing chunks

### 5. Python Environment Setup

```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows:
.venv\Scripts\activate
# Linux/Mac:
# source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 6. Database Configuration

Ensure PostgreSQL is installed and create the database:

```bash
# Connect to PostgreSQL
psql -U postgres

# Create database
CREATE DATABASE m4a_db;

# Exit
\q
```

### 7. Database Migration

```bash
alembic upgrade head
```

### 8. Application Startup

```bash
python run_app.py
```

### 9. AI Service Setup

The system uses a multi-provider AI architecture with intelligent fallback:

**Provider Priority:**
1. **Groq** (Primary) - Ultra-fast inference, generous free tier
2. **Gemini** (Fallback) - When Groq's rate-limit retry-after > 30s, automatically switches to Gemini

**API Key Setup:**

```bash
# Groq (Required - Primary)
# Get your key at: https://console.groq.com
GROQ_API_KEY=gsk_...

# Gemini (Recommended - Best fallback)
# Get your key at: https://aistudio.google.com/apikey
# Free tier: 15 RPM, 1M tokens/min
GEMINI_API_KEY=AIza...
# Modelo por defecto recomendado: gemini-1.5-flash
# Si obtienes un HTTP 404 ("modelo no encontrado"), obtén la lista de modelos soportados:
#   curl "https://generativelanguage.googleapis.com/v1beta/models?key=YOUR_KEY"
# y configura GEMINI_MODEL con uno de los nombres listados (p.ej. gemini-1.5-flash)
GEMINI_MODEL=gemini-1.5-flash

# Optional fallbacks
# (Together and OpenRouter were removed from the project; use GEMINI as the supported fallback)
```

**Smart Fallback System:**
- Automatically detects rate limits and switches providers
- When Groq's retry-after exceeds 30 seconds, immediately switches to Gemini
- Tracks rate-limit status per provider to avoid repeated failures
- Detailed logging of all provider switches and retry attempts

## API Documentation and Usage

Once the application is running, access the following endpoints:

- **API Documentation**: http://localhost:8000/docs (Swagger UI)
- **Alternative Documentation**: http://localhost:8000/redoc (ReDoc)
- **Health Check**: http://localhost:8000/health

### Primary Workflow

1. **User Registration**: `POST /api/v1/auth/register`
2. **User Authentication**: `POST /api/v1/auth/login`
3. **Subject Creation**: `POST /api/v1/materias`
4. **Task Management**: `POST /api/v1/tareas`
5. **File Upload**: `POST /api/v1/archivos/upload`
6. **Audio Processing**: `POST /api/v1/notas/audio/upload`

### Audio Processing Features

- **Automatic Transcription** using Faster-Whisper engine
- **AI-Powered Summarization** with Groq (Llama 3)
- **Structured Academic Format** with clear sections and content organization
- **Precision-Focused Content** relevant for educational purposes
- **Clean Interface** without technical metadata exposure

## Database Migrations

Create new migration:

```bash
alembic revision --autogenerate -m "Description of changes"
```

Apply migrations:

```bash
alembic upgrade head
```

## API Endpoints Reference

### Authentication Endpoints

- `POST /api/v1/auth/register` - Register new user account
- `POST /api/v1/auth/login` - User authentication and token generation
- `POST /api/v1/auth/refresh` - Refresh authentication token
- `GET /api/v1/auth/me` - Retrieve current user information

### Subject Management

- `GET /api/v1/materias` - List user subjects
- `POST /api/v1/materias` - Create new subject
- `GET /api/v1/materias/{id}` - Get specific subject details
- `PUT /api/v1/materias/{id}` - Update subject information
- `DELETE /api/v1/materias/{id}` - Delete subject

### Task Management

- `GET /api/v1/tareas` - List tasks with filtering options
- `POST /api/v1/tareas` - Create new task
- `GET /api/v1/tareas/{id}` - Get specific task details
- `PUT /api/v1/tareas/{id}` - Update task information
- `DELETE /api/v1/tareas/{id}` - Delete task

### Note Management

- `GET /api/v1/notas` - List notes with search capabilities
- `POST /api/v1/notas` - Create new note
- `GET /api/v1/notas/{id}` - Get specific note details
- `PUT /api/v1/notas/{id}` - Update note content
- `DELETE /api/v1/notas/{id}` - Delete note

### File Management

- `POST /api/v1/archivos/upload` - Upload and associate files with subjects
- `GET /api/v1/archivos` - List uploaded files
- `GET /api/v1/archivos/{id}` - Get specific file details
- `DELETE /api/v1/archivos/{id}` - Delete file

### Audio Processing

- `POST /api/v1/notas/audio/upload` - Upload audio file for transcription and AI summarization

## Technology Stack

- **FastAPI**: High-performance web framework for building APIs
- **SQLAlchemy**: Advanced Object-Relational Mapping (ORM) library
- **Alembic**: Database migration management system
- **Pydantic**: Data validation and serialization library
- **Faster-Whisper**: High-precision speech-to-text transcription engine
- **Groq (Llama 3)**: Advanced AI model for intelligent content summarization
- **PostgreSQL**: Enterprise-grade relational database system
- **JWT**: JSON Web Token for secure authentication
- **Passlib + bcrypt**: Password hashing and security utilities

## Performance Optimizations

### Audio Processing

- **qwen2.5:7b Integration**: Enhanced AI model for superior summarization accuracy
- **Intelligent Validation**: Advanced content verification to prevent AI hallucinations
- **Academic Format Structure**: Optimized output formatting for educational content
- **Clean Processing Pipeline**: Streamlined workflow without technical metadata exposure

### System Performance

- **Optimized Database Schema**: Efficient storage strategy focusing on summaries rather than raw transcriptions
- **Asynchronous Processing**: Background audio processing for improved user experience
- **Conservative Configuration**: Fine-tuned AI parameters optimized for accuracy over speed
- **Memory Management**: Intelligent GPU memory allocation and cleanup
- **Automatic Fallback**: Multi-tier fallback system for hardware compatibility

### Scalability Features

- **Chunked Audio Processing**: Large file handling through intelligent segmentation
- **Parallel Processing Control**: Configurable concurrent processing limits
- **Format Compatibility**: Support for multiple audio formats (M4A, MP3, WAV, etc.)
- **Error Recovery**: Robust error handling with automatic retry mechanisms

## License

This project is licensed under the MIT License.