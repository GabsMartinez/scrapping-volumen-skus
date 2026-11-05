# =========================================================================
# limpiar_dump.py - deja un dump de pg_dump listo para versionar:
#   - quita las líneas \restrict / \unrestrict (pg_dump >= 16.10 las agrega
#     con una clave aleatoria en cada dump: ensucian el diff de git y el
#     SQL Editor de Supabase no las entiende).
#   - normaliza fin de línea a LF.
#
# Lo usa "respaldar" de scripts/correr.ps1 y scripts/correr.sh.
# Uso: python -m db.limpiar_dump db/datos/datos.sql
# =========================================================================
import sys
from pathlib import Path

META_COMANDOS = ("\\restrict ", "\\unrestrict ")


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Uso: python -m db.limpiar_dump <archivo.sql>")
    ruta = Path(sys.argv[1])
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    limpias = [linea for linea in lineas if not linea.startswith(META_COMANDOS)]
    ruta.write_text("\n".join(limpias) + "\n", encoding="utf-8", newline="\n")
    inserts = sum(1 for linea in limpias if linea.startswith("INSERT INTO"))
    print(f"{ruta}: {inserts} filas (INSERT), {len(lineas) - len(limpias)} línea(s) \\restrict quitadas.")


if __name__ == "__main__":
    main()
