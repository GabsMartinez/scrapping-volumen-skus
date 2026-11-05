# =========================================================================
# main.py - punto de entrada único del proyecto.
#
#   python main.py estado                 conteos de la base (qué tan completa está)
#   python main.py excel                  genera salidas/excel/reporte_scraper_precios.xlsx
#   python main.py seed                   carga data/entrada/codigos_criticos_dominios.xlsx
#   python main.py crawl  [nombre|todos]  recorre el catálogo de los fabricantes
#   python main.py match  [nombre|todos]  cruza códigos internos <-> catálogo
#   python main.py enriquecer [paso|todos]  specs, peso y volumen
#   python main.py pipeline               todo lo anterior en orden (base vacía)
#   python main.py listar                 crawlers, matchers y pasos disponibles
#
# Dentro de Docker:  docker compose exec scraper python main.py <comando>
# Atajos:            scripts/correr.ps1 <comando>  |  scripts/correr.sh <comando>
#
# Cada paso corre como su propio proceso (python -m <modulo>), igual que si
# se corriera a mano, así un script que falla no deja estado raro en los demás.
# =========================================================================
import argparse
import os
import subprocess
import sys
import time

from scraper_precios.config import RAIZ, conectar

# --- Pasos disponibles (en el orden en que se corren con "todos") -----------
# crawl: llena catalogo_fabricante. MECH usa Scrapy+Playwright; Reliable y
# PHD son scripts aparte (ver docs/HISTORIAL.md: el WAF de Reliable bloquea
# a Scrapy y a Playwright, PHD renderiza el número de figura con JS).
CRAWLERS = {
    "mech": ["-m", "scrapy", "crawl", "mech_catalogo"],
    "reliable": ["-m", "crawlers.reliable_crawler"],
    "phd": ["-m", "crawlers.phd_crawler"],
}

# match: cada matcher BORRA y vuelve a insertar los scrapes de su dominio.
# mech va antes que meide (meide cubre lo que fu-mech.com no publica).
MATCHERS = [
    "mech", "meide", "tyco", "reliable", "erico", "anvil", "globe",
    "simplex", "phd", "wilson_cousins", "tyler_union", "star_pipe",
]

# enriquecer: el orden importa. Los primeros escriben en scrapes, la
# sincronización los copia a productos_criticos, y los completar_* rellenan
# productos_criticos (algunos AGREGAN texto a specs_adicionales, por eso no
# son idempotentes: correrlos dos veces duplica notas).
ENRIQUECIMIENTO = [
    "extraer_specs",
    "phd_pesos_dimensiones",
    "phd_pesos_extra",
    "sincronizar_specs",
    "completar_tamano",
    "completar_material_mech",
    "completar_erico",
    "completar_kfactor",
    "completar_volumen",
    "completar_ronda2",
    "completar_volumen_mech",
]


# --- utilidades -------------------------------------------------------------
def correr(nombre: str, args_python: list[str]) -> None:
    """Corre `python <args>` desde la raíz del proyecto y aborta si falla."""
    entorno = dict(os.environ)
    entorno["PYTHONPATH"] = os.pathsep.join(filter(None, [str(RAIZ), entorno.get("PYTHONPATH")]))
    entorno.setdefault("PYTHONIOENCODING", "utf-8")
    print(f"\n=== {nombre} ===", flush=True)
    inicio = time.time()
    resultado = subprocess.run([sys.executable, *args_python], cwd=RAIZ, env=entorno)
    if resultado.returncode != 0:
        raise SystemExit(f"\n[ERROR] '{nombre}' terminó con código {resultado.returncode}. Se detiene aquí.")
    print(f"--- {nombre}: listo ({time.time() - inicio:.0f}s)", flush=True)


def elegir(valor: str, disponibles, tipo: str) -> list[str]:
    if valor == "todos":
        return list(disponibles)
    if valor not in disponibles:
        raise SystemExit(f"{tipo} desconocido: '{valor}'. Opciones: todos, {', '.join(disponibles)}")
    return [valor]


def contar_scrapes() -> int:
    conexion = conectar()
    try:
        with conexion.cursor() as cur:
            cur.execute("SELECT count(*) FROM scrapes")
            return cur.fetchone()[0]
    finally:
        conexion.close()


def exigir_forzar(args, que_hace: str) -> None:
    """Los matchers y el enriquecimiento reescriben datos que en la base
    actual llevan correcciones manuales: si ya hay scrapes, pide --forzar."""
    if args.forzar:
        return
    n = contar_scrapes()
    if n == 0:
        return
    raise SystemExit(
        f"La base ya tiene {n} scrapes (con correcciones manuales curadas).\n"
        f"'{que_hace}' los reescribe y se pueden perder esas correcciones.\n"
        f"  1) Respalda primero:  scripts/correr.ps1 respaldar   (o scripts/correr.sh respaldar)\n"
        f"  2) Repite con --forzar si de verdad quieres reconstruir."
    )


# --- comandos ---------------------------------------------------------------
def cmd_estado(_args):
    conexion = conectar()
    with conexion.cursor() as cur:
        cur.execute("""
            SELECT count(*),
                   count(*) FILTER (WHERE s.estado = 'ok'),
                   count(p.material), count(p.peso_kg), count(p.volumen_cm3),
                   count(*) FILTER (WHERE coalesce(s.precio, '') <> '')
            FROM productos_criticos p LEFT JOIN scrapes_ultimo s USING (codigo)
        """)
        total, ok, material, peso, volumen, precio = cur.fetchone()
        cur.execute("SELECT count(*) FROM scrapes")
        n_scrapes = cur.fetchone()[0]
        cur.execute("SELECT dominio, count(*) FROM catalogo_fabricante GROUP BY 1 ORDER BY 2 DESC")
        catalogo = cur.fetchall()
    conexion.close()

    print(f"Productos críticos: {total}")
    for etiqueta, valor in [("con match ok", ok), ("con material", material), ("con peso", peso),
                            ("con volumen", volumen), ("con precio", precio)]:
        pct = f"{valor / total:.0%}" if total else "-"
        print(f"  {etiqueta:<14} {valor:>4}  ({pct})")
    print(f"Scrapes (historial): {n_scrapes}")
    print(f"Catálogo fabricante: {sum(n for _, n in catalogo)} páginas")
    for dominio, n in catalogo:
        print(f"  {dominio:<28} {n:>4}")


def cmd_excel(args):
    extra = ["--salida", args.salida] if args.salida else []
    correr("excel", ["-m", "reportes.exportar_excel", *extra])


def cmd_seed(_args):
    correr("seed", ["-m", "db.seed_productos"])


def cmd_crawl(args):
    for nombre in elegir(args.nombre, CRAWLERS, "Crawler"):
        correr(f"crawl {nombre}", CRAWLERS[nombre])


def cmd_match(args):
    nombres = elegir(args.nombre, MATCHERS, "Matcher")
    exigir_forzar(args, f"match {args.nombre}")
    for nombre in nombres:
        correr(f"match {nombre}", ["-m", f"matchers.{nombre}_matcher"])


def cmd_enriquecer(args):
    pasos = elegir(args.paso, ENRIQUECIMIENTO, "Paso")
    if pasos != ["sincronizar_specs"]:  # el único idempotente, no necesita --forzar
        exigir_forzar(args, f"enriquecer {args.paso}")
    for paso in pasos:
        correr(f"enriquecer {paso}", ["-m", f"enriquecimiento.{paso}"])


def cmd_pipeline(args):
    exigir_forzar(args, "pipeline")
    args.forzar = True  # ya se confirmó arriba, no volver a preguntar por paso
    cmd_seed(args)
    args.nombre = "todos"
    cmd_crawl(args)
    cmd_match(args)
    args.paso = "todos"
    cmd_enriquecer(args)
    args.salida = None
    cmd_excel(args)


def cmd_listar(_args):
    print("Crawlers  :", ", ".join(CRAWLERS))
    print("Matchers  :", ", ".join(MATCHERS))
    print("Enriquecer:", " -> ".join(ENRIQUECIMIENTO))


def main():
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="Scraper de precios/specs de los códigos críticos en los sitios de sus fabricantes.",
    )
    sub = parser.add_subparsers(dest="comando", required=True, metavar="comando")

    sub.add_parser("estado", help="conteos de la base").set_defaults(func=cmd_estado)

    p = sub.add_parser("excel", help="genera el reporte Excel")
    p.add_argument("--salida", help="ruta del .xlsx (default: salidas/excel/reporte_scraper_precios.xlsx)")
    p.set_defaults(func=cmd_excel)

    sub.add_parser("seed", help="carga el Excel de códigos críticos a la base").set_defaults(func=cmd_seed)

    p = sub.add_parser("crawl", help="recorre el catálogo de los fabricantes")
    p.add_argument("nombre", nargs="?", default="todos", help=f"todos | {' | '.join(CRAWLERS)}")
    p.set_defaults(func=cmd_crawl)

    p = sub.add_parser("match", help="cruza códigos internos contra el catálogo")
    p.add_argument("nombre", nargs="?", default="todos", help=f"todos | {' | '.join(MATCHERS)}")
    p.add_argument("--forzar", action="store_true", help="reescribir aunque la base ya tenga datos")
    p.set_defaults(func=cmd_match)

    p = sub.add_parser("enriquecer", help="specs, peso y volumen")
    p.add_argument("paso", nargs="?", default="todos", help=f"todos | {' | '.join(ENRIQUECIMIENTO)}")
    p.add_argument("--forzar", action="store_true", help="reescribir aunque la base ya tenga datos")
    p.set_defaults(func=cmd_enriquecer)

    p = sub.add_parser("pipeline", help="seed + crawl + match + enriquecer + excel")
    p.add_argument("--forzar", action="store_true", help="reconstruir aunque la base ya tenga datos")
    p.set_defaults(func=cmd_pipeline)

    sub.add_parser("listar", help="muestra los pasos disponibles").set_defaults(func=cmd_listar)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
