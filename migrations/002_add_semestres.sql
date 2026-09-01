-- Manual migration: add academic semesters support
-- Safe to run multiple times (uses IF NOT EXISTS / conditional checks).

CREATE TABLE IF NOT EXISTS semestres (
    id SERIAL PRIMARY KEY,
    codigo VARCHAR(7) NOT NULL,
    nombre VARCHAR(100),
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    fecha_creacion TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(usuario_id, codigo)
);

ALTER TABLE materias ADD COLUMN IF NOT EXISTS semestre_id INTEGER REFERENCES semestres(id);
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS semestre_actual_id INTEGER REFERENCES semestres(id);

-- Migrate existing data: create "2026-01" per user and assign materias
INSERT INTO semestres (codigo, nombre, usuario_id)
SELECT '2026-01', 'Semestre 2026-01', u.id
FROM usuarios u
WHERE NOT EXISTS (
    SELECT 1 FROM semestres s
    WHERE s.usuario_id = u.id AND s.codigo = '2026-01'
);

UPDATE materias m
SET semestre_id = s.id
FROM semestres s
WHERE s.usuario_id = m.usuario_id
  AND s.codigo = '2026-01'
  AND m.semestre_id IS NULL;

UPDATE usuarios u
SET semestre_actual_id = s.id
FROM semestres s
WHERE s.usuario_id = u.id
  AND s.codigo = '2026-01'
  AND u.semestre_actual_id IS NULL;

-- Only enforce NOT NULL if all materias have been assigned
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM materias WHERE semestre_id IS NULL) THEN
        ALTER TABLE materias ALTER COLUMN semestre_id SET NOT NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_materias_semestre_id ON materias(semestre_id);
CREATE INDEX IF NOT EXISTS ix_semestres_usuario_id ON semestres(usuario_id);
