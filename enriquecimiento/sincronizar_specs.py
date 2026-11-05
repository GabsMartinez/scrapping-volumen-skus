# =========================================================================
# sincronizar_specs.py - copia las specs estructuradas del mejor scrape
# de cada código (vista scrapes_ultimo) a productos_criticos, que guarda
# una copia de conveniencia para consultarlas sin JOIN (ver db/schema.sql).
#
# Solo LLENA lo que en productos_criticos sigue vacío (COALESCE): nunca
# pisa un valor ya cargado, ni los que completaron a mano los scripts
# completar_*.py. Por eso es idempotente y se puede correr las veces que
# haga falta. En la secuencia de enriquecimiento va después de
# extraer_specs.py / phd_pesos_*.py (que escriben en scrapes) y antes de
# completar_*.py (que leen/escriben productos_criticos).
#
# Uso:
#   python main.py enriquecer sincronizar_specs
#   (o directo: docker compose exec scraper python enriquecimiento/sincronizar_specs.py)
# =========================================================================
import psycopg2

from scraper_precios.config import CONEXION

COLUMNAS = [
    "material", "acabado", "aprobaciones", "funcion_texto", "tamano",
    "k_factor", "specs_adicionales", "peso_lbs", "peso_kg",
    "dimensiones_texto", "dimensiones_fuente",
]


def main():
    sets = ",\n    ".join(f"{c} = COALESCE(p.{c}, s.{c})" for c in COLUMNAS)
    hay_algo_que_llenar = " OR ".join(f"(p.{c} IS NULL AND s.{c} IS NOT NULL)" for c in COLUMNAS)
    sql = f"""
UPDATE productos_criticos p SET
    {sets}
FROM scrapes_ultimo s
WHERE s.codigo = p.codigo
  AND s.estado = 'ok'
  AND ({hay_algo_que_llenar})
"""
    conexion = psycopg2.connect(**CONEXION)
    with conexion, conexion.cursor() as cur:
        cur.execute(sql)
        print(f"{cur.rowcount} código(s) con specs completadas desde scrapes_ultimo.")
    conexion.close()


if __name__ == "__main__":
    main()
