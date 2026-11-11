"""
[VERSIÓN HÍBRIDA] Copia de TraductorClusterPronostico.py para el método
híbrido (clusterizacionHibrida.py). La lógica es IDÉNTICA; solo cambian las
rutas del bloque __main__:
  lee   : clusters_asignados_hibrido.xlsx
          unidades_agregadas_por_cluster_hibrido.xlsx
  escribe: clusters_con_unidad_pronostico_hibrido.xlsx
Así no pisa los archivos del método 1 ni del método N.
"""
"""
==============================================================================
PUENTE: Clustering -> Pronosticador
==============================================================================
Este módulo es PURO PEGAMENTO: solo traduce las salidas de clusterizacionVolumen.py
al formato exacto que Pronosticador (Pronósticos.py) espera recibir. No
decide comportamiento estadístico avanzado (STL, clasificación de
tendencia/estacionalidad ya calculada aquí mismo, ver sección 1) sobre
nada que Pronosticador no pueda resolver también -- pero SÍ decide, aquí,
en qué granularidad temporal se pronostica cada Cluster_Operativo (ver
GRANULARIDADES_PRONOSTICO y _decidir_granularidad_pronostico más abajo) y
convierte Lead Time a esa misma unidad, para dejarle a Pronósticos.py una
tabla ya resuelta y lista para usar sin ambigüedad.

[AJUSTE OBLIGATORIO -- CLUSTER_OPERATIVO, NO CLUSTER_COMPORTAMIENTO]
Este puente ahora pronostica sobre 'Cluster_Operativo' (Cluster_Comportamiento
+ Proveedor + Pais), no sobre 'Cluster' (= 'Cluster_Comportamiento') como
antes. La razón es de fondo, no de nomenclatura: 'Cluster' agrupa SKU con
patrón de demanda similar SIN mirar proveedor ni país (a propósito -- ver
clusterizacionVolumen.preparar_features_con_pesos), así que un mismo
'Cluster' puede mezclar SKU que se compran en China con SKU que se compran
en Canadá. Pronosticar la demanda agregada de esa mezcla está bien para
SABER cuánto se mueve en conjunto, pero automáticamente arrastra ese
problema a todo lo que dependa de ese pronóstico para tomar una decisión
de COMPRA/REABASTECIMIENTO real (cuándo pedir, a quién, cuánto por
contenedor) -- ahí sí importa, y mucho, que todos los SKU del grupo
compartan proveedor y país, porque son flujos logísticos distintos
(tránsito, aduana, ruta, moneda). 'Cluster_Operativo' ya viene resuelto
así desde clusterizacionVolumen.py (Cluster_Comportamiento partido por
Proveedor+Pais); este puente simplemente pronostica sobre esa unidad en
vez de la más gruesa.

Efecto práctico medido con datos reales: 12 Cluster_Comportamiento se
convierten en 18 Cluster_Operativo -- varios de ellos quedan con muy pocos
SKU (incluso 1 solo, ej. '1_ZYFIRE_CHINA' o '5_KIDDE_ESTADOSUNIDOS'). Eso
es exactamente lo esperado, no un error: significa que ese proveedor/país
es tan poco frecuente en el catálogo que no había con qué consolidarlo.
Un Cluster_Operativo de 1 SKU simplemente termina pronosticando a ese SKU
individualmente por esta misma vía -- sigue siendo correcto, solo que sin
compañía para promediar variabilidad.

Contrato corregido (la versión anterior de este archivo lo rompía):
Pronosticador necesita que df_clusters tenga estas columnas REALES --
NO como índice, como columnas de verdad, porque así es como las lee
internamente (self.df_clusters[self.df_clusters[cluster_col]==id][sku_col]):

    - 'Código'                (self.sku_col por defecto)
    - 'Cluster_Operativo'      (self.cluster_col -- hay que pasárselo
                                 explícito al instanciar Pronosticador,
                                 porque su default sigue siendo 'Cluster')
    - 'Lead Time (semanas)'   (self.lead_time_col por defecto)
    - 'comportamiento'        (nombre fijo, lo calcula este módulo)

La versión anterior indexaba df_clusters por 'SKU' y renombraba 'Cluster'
a 'cluster' (minúscula) -- ninguna de las dos cosas coincide con cómo
Pronosticador accede a sus datos (nunca vía índice), así que habría
fallado en la primera línea de procesar_cluster. Aquí NO se renombra nada:
se conservan los nombres tal como los produce clusterizacionVolumen.py.
'Código' y 'Lead Time (semanas)' ya coinciden con los defaults de
Pronosticador; 'Cluster_Operativo' NO coincide con el default de
Pronosticador (que es 'Cluster') -- por eso, a diferencia de sku_col y
lead_time_col, cluster_col SÍ hay que pasárselo explícito al instanciar
Pronosticador. Esa instanciación ya NO ocurre en este archivo (ver aviso
de desacoplamiento más abajo) -- queda documentada aquí como el contrato
que el script que sí instancie Pronosticador (en Pronósticos.py) debe
respetar.

Por qué el 'comportamiento' se calcula aquí y no se deja que Pronosticador
lo infiera solo: su camino de respaldo promedia fuerza_estacional /
tendencia_pendiente A NIVEL DE SKU. Esas métricas se calcularon en
clustering para caracterizar productos individuales con fines de
AGRUPACIÓN -- no la serie ya agregada del clúster, que es la que el modelo
de pronóstico realmente entrena. Aquí se calcula fuerza_estacional y
tendencia_pendiente DIRECTAMENTE sobre la serie SEMANAL agregada de cada
Cluster_Operativo (con STL, period=52 -- ciclo anual real de una serie
semanal), y se le entrega a Pronosticador el 'comportamiento' ya resuelto.
"""

import numpy as np
import pandas as pd
from statsmodels.tsa.seasonal import STL

# [DESACOPLADO A PEDIDO EXPLÍCITO] Este archivo YA NO importa Pronósticos.py
# -- deben mantenerse en módulos aparte, sin dependencia en ningún sentido.
# La granularidad de pronóstico (semanas/quincenas/meses/bimestres/
# trimestres) se decide aquí mismo (ver GRANULARIDADES_PRONOSTICO y
# _decidir_granularidad_pronostico más abajo).

# Deben coincidir con Pronosticador.UMBRAL_FUERZA_ESTACIONAL,
# Pronosticador.UMBRAL_TENDENCIA_RELATIVA y Pronosticador.PERIODO_ESTACIONAL
# (Pronósticos.py). Si esas constantes cambian allá, cambiarlas también aquí.
UMBRAL_FUERZA_ESTACIONAL = 0.15
UMBRAL_TENDENCIA_RELATIVA = 0.001
PERIODO_ESTACIONAL = 52  # semanas por año -- toda la serie que llega aquí es semanal

# Debe coincidir con las mismas constantes en Pronósticos.py.
SEMANAS_POR_ANO = 52

# [ESTRUCTURA] Todas las granularidades se definen a partir de
# SEMANAS_POR_ANO, EXCEPTO quincenas -- ver por qué justo debajo. Meses,
# bimestres y trimestres sí son exactamente equivalentes escritos así
# (52/12 == 2*52/12/2... álgebra simple: 2*(52/12) == 52/6 y 3*(52/12) ==
# 52/4), así que esta forma es solo más legible, no cambia ningún número.
SEMANAS_POR_MES = SEMANAS_POR_ANO / 12
SEMANAS_POR_BIMESTRE = SEMANAS_POR_ANO / 6
SEMANAS_POR_TRIMESTRE = SEMANAS_POR_ANO / 4

# [NO se define como SEMANAS_POR_ANO / 24] 52/24 = 2.1667 semanas
# asumiría 24 quincenas por año -- esa es la convención de "quincena =
# mitad de mes calendario" (típica en nómina), donde cada quincena mide
# ~15.17 días en promedio, no 14. Todo este pipeline trabaja sobre datos
# semanales anclados a lunes (W-MON); una quincena aquí tiene que ser
# exactamente 2 semanas calendario (14 días) para poder resamplear limpio
# con pandas ('2W') -- con 2.1667 semanas no hay una regla de resample
# limpia y la serie quincenal quedaría desalineada de cómo se construye
# en la práctica. 52 semanas / 2 semanas-por-quincena = 26 quincenas por
# año exactas (no 24) -- es la cifra correcta para este pipeline.
SEMANAS_POR_QUINCENA = 2.0

# ==========================================================================
# [NUEVO CRITERIO DE GRANULARIDAD -- REEMPLAZA EL BINARIO SEMANAS/MESES]
# ==========================================================================
# Antes la decisión era binaria (semanas si el lead time era corto, meses
# si era largo, con un único umbral de 52 semanas de horizonte mínimo). El
# problema de fondo: con un lead time realmente largo, "meses" podía
# igual terminar necesitando un horizonte de 20-25 MESES -- un pronóstico
# así de largo es enormemente ruidoso, sin importar en qué unidad esté
# expresado.
#
# El criterio nuevo fija el objetivo al revés: el horizonte de pronóstico,
# expresado en la unidad que se elija, NUNCA debe superar ~25 periodos
# (más allá de eso el pronóstico se vuelve demasiado ruidoso para ser
# útil). El horizonte mínimo exigido por el lead time es siempre
# horizonte_minimo_semanas = factor_leadtime_minimo * lead_time_max_semanas
# (factor_leadtime_minimo=5: hay que poder pronosticar al menos 5 ciclos
# de reabastecimiento completos hacia adelante). Se recorre la escalera de
# granularidades de más fina a más gruesa (semanas -> quincenas -> meses
# -> bimestres -> trimestres) y se elige la PRIMERA (la más fina posible)
# cuyo horizonte, en esa unidad, quede en <= 25 periodos. Entre más grueso
# el lead time, más gruesa la unidad -- pero SIEMPRE con el mismo tope de
# ~25 periodos de horizonte, sin importar cuán largo sea el lead time.
#
# Verificado que reproduce exactamente los umbrales pedidos: LT_max<=5
# semanas -> 'semanas' (25 periodos en el límite); LT_max entre 6 y 10 ->
# 'quincenas' (entre 15 y 25 periodos); LT_max entre 11 y 21 -> 'meses';
# LT_max entre 22 y 43 -> 'bimestres'. 'trimestres' se agrega como red de
# seguridad para lead times aún más largos (no pedido explícitamente, pero
# necesario para que la escalera nunca se quede sin una unidad más gruesa
# a la que recurrir) -- si ni siquiera trimestres alcanza el tope de 25
# periodos (lead time extremadamente largo), se usa trimestres igual y se
# avisa por consola, en vez de fallar.
GRANULARIDADES_PRONOSTICO = [
    ('semanas', SEMANAS_POR_ANO / 52),
    ('quincenas', SEMANAS_POR_QUINCENA),
    ('meses', SEMANAS_POR_MES),
    ('bimestres', SEMANAS_POR_BIMESTRE),
    ('trimestres', SEMANAS_POR_TRIMESTRE),
]

# Debe coincidir con el mismo tope que use Pronosticador en Pronósticos.py
# una vez se actualice para soportar esta misma escalera de granularidades.
MAX_PERIODOS_PRONOSTICO = 25

# [PLOMERÍA, NO DECISIÓN -- mantener sincronizado a mano con Pronosticador.
# CONFIG_POR_UNIDAD en Pronósticos.py] Regla de resample de pandas para
# cada unidad -- necesaria aquí porque, desde este rediseño, la
# clasificación de comportamiento (ver más abajo) se hace sobre la serie
# YA REAGREGADA a la unidad final de cada clúster, no siempre en semanas.
# No es una decisión de negocio (no decide nada sobre qué unidad usar,
# eso lo sigue haciendo únicamente _decidir_granularidad_pronostico) --
# es la misma clase de utilidad mecánica que cargar_unidades_agregadas_
# desde_excel: ambos módulos necesitan poder reagregar series de forma
# independiente, sin importarse entre sí.
REGLA_RESAMPLE_POR_UNIDAD = {
    'semanas': 'W-MON', 'quincenas': '2W-MON', 'meses': 'MS',
    'bimestres': '2MS', 'trimestres': '3MS',
}

# Periodo estacional (ciclos por año) de cada unidad, derivado
# automáticamente de GRANULARIDADES_PRONOSTICO -- nunca escrito a mano,
# para que no pueda desincronizarse de la definición de semanas_por_periodo.
PERIODO_ESTACIONAL_POR_UNIDAD = {
    nombre: int(round(SEMANAS_POR_ANO / semanas_por_periodo))
    for nombre, semanas_por_periodo in GRANULARIDADES_PRONOSTICO
}

# [DEMANDA INTERMITENTE -- Syntetos & Boylan, 2005] Umbral estándar de ADI
# (Average Demand Interval) para distinguir demanda "suave" (tratable con
# modelos de series continuas: ARIMA/SARIMA/Holt-Winters/ETS) de demanda
# intermitente (necesita Croston/SBA -- ver Pronosticador.obtener_modelos_
# por_comportamiento en Pronósticos.py). ADI >= 1.32 es el punto de corte
# de la clasificación de Syntetos-Boylan-Croston (SBC), el estándar en la
# literatura de pronóstico de inventarios.
UMBRAL_ADI_INTERMITENTE = 1.32


def _decidir_granularidad_pronostico(lead_time_max_semanas, factor_leadtime_minimo=5,
                                      max_periodos=MAX_PERIODOS_PRONOSTICO):
    """
    Decide en qué unidad temporal debe pronosticarse un clúster, dado su
    lead time máximo, para que el horizonte de pronóstico
    (lead_time_max * factor_leadtime_minimo, expresado en esa unidad)
    nunca supere max_periodos.

    Devuelve (nombre_unidad, semanas_por_periodo, horizonte_en_periodos):
        nombre_unidad: 'semanas' | 'quincenas' | 'meses' | 'bimestres' |
            'trimestres'.
        semanas_por_periodo: cuántas semanas equivalen a UN periodo en esa
            unidad (p.ej. 2.0 para quincenas) -- se usa para convertir
            Lead Time (que siempre viene en semanas) a la misma unidad del
            pronóstico, y para resamplear la demanda a esa unidad.
        horizonte_en_periodos: el horizonte mínimo exigido por el lead
            time, ya expresado en la unidad elegida (redondeado hacia
            arriba) -- listo para usarse como horizonte_pronostico al
            instanciar Pronosticador.
    """
    horizonte_minimo_semanas = factor_leadtime_minimo * lead_time_max_semanas

    for nombre_unidad, semanas_por_periodo in GRANULARIDADES_PRONOSTICO:
        periodos = horizonte_minimo_semanas / semanas_por_periodo
        if periodos <= max_periodos:
            return nombre_unidad, semanas_por_periodo, int(np.ceil(periodos))

    # Lead time tan largo que ni siquiera la unidad más gruesa de la
    # escalera (trimestres) baja de max_periodos -- se usa esa de todas
    # formas (es lo mejor disponible) y se avisa, en vez de fallar.
    nombre_unidad, semanas_por_periodo = GRANULARIDADES_PRONOSTICO[-1]
    periodos = horizonte_minimo_semanas / semanas_por_periodo
    print(f"   ⚠️ Lead time máximo de {lead_time_max_semanas:.1f} semanas exige "
          f"{periodos:.1f} {nombre_unidad} -- supera el tope de {max_periodos} "
          f"periodos incluso en la unidad más gruesa disponible ({nombre_unidad}). "
          f"Se usa igual, pero considera revisar ese lead time.")
    return nombre_unidad, semanas_por_periodo, int(np.ceil(periodos))


# ==========================================================================
# 1. INTERMITENCIA, FUERZA ESTACIONAL Y TENDENCIA -- SOBRE LA SERIE YA
#    REAGREGADA A LA UNIDAD FINAL DE CADA CLÚSTER (no siempre semanal, ver
#    el aviso en clasificar_todos_los_clusters para el porqué)
# ==========================================================================

def calcular_intermitencia(serie, umbral_adi=UMBRAL_ADI_INTERMITENTE):
    """
    [DEMANDA INTERMITENTE -- CLASIFICACIÓN SYNTETOS-BOYLAN-CROSTON (SBC)]
    Se evalúa ANTES que estacionalidad/tendencia, y si la serie resulta
    intermitente, esa clasificación tiene PRIORIDAD sobre lo que diría STL
    -- una serie con muchos ceros y picos esporádicos (ej. 0,0,0,25,0,0,
    40,0,...) puede salir "estacionaria" según fuerza_estacional/tendencia
    (no hay una tendencia clara ni un patrón estacional limpio), pero eso
    NO significa que sea una demanda normal estacionaria -- es intermitente,
    y ARIMA/SARIMA/Holt-Winters/ETS (pensados para demanda que ocurre en
    casi todos los periodos) pueden comportarse mal ahí. Ver
    Pronosticador.obtener_modelos_por_comportamiento en Pronósticos.py,
    que para 'intermitente'/'intermitente+tendencia' usa SBA (Syntetos-
    Boylan Approximation) en vez de esos 4 modelos clásicos.

    ADI (Average Demand Interval) = número de periodos / número de
    periodos con demanda > 0 -- cuántos periodos pasan, en promedio, entre
    una ocurrencia de demanda y la siguiente.

    CV² = (desviación estándar / media)² de los TAMAÑOS de demanda cuando
    ocurre (excluye los ceros) -- se calcula y se devuelve como
    diagnóstico adicional, pero NO decide por sí solo aquí; solo ADI
    activa la clasificación intermitente (el umbral de Syntetos-Boylan
    para CV² separa "intermitente" de "errática/grumosa" dentro de las
    series YA intermitentes -- un refinamiento que queda disponible para
    revisión manual, no automatizado en esta primera versión).

    Devuelve (es_intermitente, adi, cv2).
    """
    y = serie.astype(float).values
    n = len(y)
    idx_demanda = np.where(y > 0)[0]

    if len(idx_demanda) == 0:
        return True, np.inf, np.nan

    adi = n / len(idx_demanda)
    tamanos = y[idx_demanda]
    media_tamanos = tamanos.mean()
    cv2 = float((tamanos.std() / media_tamanos) ** 2) if media_tamanos > 0 else np.nan

    return bool(adi >= umbral_adi), float(adi), cv2


def calcular_fuerza_estacional_y_tendencia(serie, periodo_estacional=PERIODO_ESTACIONAL):
    """
    Descompone una serie con STL (tendencia + estacional + residuo) y
    devuelve (fuerza_estacional, tendencia_pendiente, media).
    'periodo_estacional' es genérico: 52 para una serie semanal, 26 para
    quincenal, 12 mensual, 6 bimestral, 4 trimestral -- ver
    PERIODO_ESTACIONAL_POR_UNIDAD.

    fuerza_estacional: 1 - Var(residuo) / Var(estacional + residuo), acotada
        en [0, 1] (Hyndman & Athanasopoulos).

    tendencia_pendiente: pendiente de una regresión lineal simple sobre el
        componente de tendencia extraído por STL -- unidades por PERIODO
        de la serie recibida (semana, quincena, mes, etc.).

    Requiere al menos 2 ciclos anuales completos (2*periodo_estacional
    periodos). Si la serie es más corta, se devuelve fuerza_estacional=0.0
    -- el clúster caerá en 'estacionario' o 'tendencia' según su
    pendiente, nunca en un falso 'estacional' basado en muy poca historia.
    """
    serie = serie.astype(float)
    media = float(serie.mean())

    if len(serie) < 2 * periodo_estacional:
        print(f"   ⚠️ Serie con solo {len(serie)} periodos (< {2*periodo_estacional} "
              f"necesarios para STL confiable en esta unidad) -- fuerza_estacional se fija en 0.0")
        t = np.arange(len(serie))
        pendiente = float(np.polyfit(t, serie.values, 1)[0]) if len(serie) >= 2 else 0.0
        return 0.0, pendiente, media

    stl = STL(serie, period=periodo_estacional, robust=True)
    resultado = stl.fit()

    resid = resultado.resid
    seasonal = resultado.seasonal
    var_resid = np.var(resid)
    var_seasonal_resid = np.var(seasonal + resid)
    fuerza_estacional = 0.0 if var_seasonal_resid == 0 else max(
        0.0, 1 - var_resid / var_seasonal_resid
    )

    t = np.arange(len(serie))
    pendiente = float(np.polyfit(t, resultado.trend.values, 1)[0])

    return float(fuerza_estacional), pendiente, media


def clasificar_comportamiento(fuerza_estacional, tendencia_pendiente, media,
                               umbral_estacional=UMBRAL_FUERZA_ESTACIONAL,
                               umbral_tendencia_rel=UMBRAL_TENDENCIA_RELATIVA):
    """
    Cascada de decisión estacional/tendencia -- se llama SOLO para series
    que calcular_intermitencia ya descartó como no-intermitentes (ver
    clasificar_todos_los_clusters).
    """
    es_estacional = fuerza_estacional > umbral_estacional
    tendencia_significativa = abs(tendencia_pendiente) > umbral_tendencia_rel * media

    if es_estacional and tendencia_significativa:
        return 'estacional+tendencia'
    elif es_estacional:
        return 'estacional'
    elif tendencia_significativa:
        return 'tendencia'
    else:
        return 'estacionario'


def clasificar_todos_los_clusters(series_por_unidad, periodo_estacional_por_cluster):
    """
    [REDISEÑO -- CLASIFICA EN LA FRECUENCIA FINAL, NO SIEMPRE EN SEMANAS]
    Antes esta función recibía la serie SEMANAL cruda de cada clúster y
    corría STL con period=52 sin importar en qué unidad terminaría
    pronosticándose ese clúster (semanas/quincenas/meses/bimestres/
    trimestres, decidido después por enriquecer_resultado_con_unidad_
    pronostico). Eso deja una pregunta metodológica abierta: ¿la
    estacionalidad detectada en semanas sigue siendo válida una vez que el
    modelo pronostica, por ejemplo, en meses?

    La respuesta que se adopta aquí: se clasifica DIRECTAMENTE sobre la
    serie YA reagregada a la unidad final de ese clúster (ver
    preparar_insumos_para_pronosticador, que arma series_por_unidad
    resampleando con REGLA_RESAMPLE_POR_UNIDAD ANTES de llamar a esta
    función) -- así "¿es estacional/tiene tendencia?" se responde sobre
    los mismos datos, a la misma resolución, que el modelo va a entrenar.
    Un ciclo anual real sobrevive a la reagregación (semanal con period=52
    o mensual con period=12 miden el mismo ciclo, solo que más grueso), así
    que esto no pierde el patrón -- y de paso resuelve otro efecto
    colateral útil: reagregar a una unidad más gruesa reduce ADI de forma
    natural (varias semanas en cero pueden sumar una venta real dentro del
    mismo mes), así que la detección de intermitencia (ver
    calcular_intermitencia) tampoco marca como intermitente un clúster que,
    en la unidad en la que de verdad se va a pronosticar, ya dejó de serlo.

    series_por_unidad: dict {cluster_id: Serie ya reagregada a la unidad
        de ESE clúster}.
    periodo_estacional_por_cluster: dict {cluster_id: periodo_estacional
        correspondiente a esa misma unidad} (ver PERIODO_ESTACIONAL_POR_UNIDAD).

    Devuelve dict {cluster_id: comportamiento}, comportamiento uno de:
    'intermitente', 'intermitente+tendencia', 'estacionario', 'tendencia',
    'estacional', 'estacional+tendencia'.
    """
    comportamiento_por_cluster = {}
    for cluster_id, serie in series_por_unidad.items():
        periodo_estacional = periodo_estacional_por_cluster[cluster_id]
        print(f"🔹 Clasificando comportamiento del Cluster {cluster_id} "
              f"({len(serie)} periodos de historia, periodo_estacional={periodo_estacional})...")

        es_intermitente, adi, cv2 = calcular_intermitencia(serie)

        if es_intermitente:
            media = float(serie.astype(float).mean())
            t = np.arange(len(serie))
            pendiente = float(np.polyfit(t, serie.astype(float).values, 1)[0]) if len(serie) >= 2 else 0.0
            tendencia_significativa = abs(pendiente) > UMBRAL_TENDENCIA_RELATIVA * media if media else False
            comportamiento = 'intermitente+tendencia' if tendencia_significativa else 'intermitente'
            comportamiento_por_cluster[cluster_id] = comportamiento
            print(f"   ADI={adi:.2f} (>= {UMBRAL_ADI_INTERMITENTE}) | CV²={cv2:.2f} | "
                  f"tendencia_pendiente={pendiente:.3f} -> comportamiento='{comportamiento}'")
            continue

        fuerza_est, pendiente, media = calcular_fuerza_estacional_y_tendencia(serie, periodo_estacional)
        comportamiento = clasificar_comportamiento(fuerza_est, pendiente, media)
        comportamiento_por_cluster[cluster_id] = comportamiento
        print(f"   ADI={adi:.2f} (< {UMBRAL_ADI_INTERMITENTE}, no intermitente) | "
              f"fuerza_estacional={fuerza_est:.3f} | tendencia_pendiente={pendiente:.3f} "
              f"| media={media:.1f} -> comportamiento='{comportamiento}'")
    return comportamiento_por_cluster


# ==========================================================================
# 2. ARMAR df_clusters -- SIN renombrar, SIN indexar. Columnas reales:
#    'Código', 'Cluster_Operativo', 'Lead Time (semanas)', + 'comportamiento'.
# ==========================================================================

def construir_df_clusters(df_resultado, comportamiento_por_cluster,
                           col_sku='Código', col_cluster='Cluster_Operativo',
                           col_lead_time='Lead Time (semanas)'):
    """
    df_resultado: salida de ejecutar_clustering_completo -- una fila por
        producto, con columnas col_sku, col_cluster y col_lead_time. Por
        defecto col_cluster='Cluster_Operativo' (NO 'Cluster'): la columna
        que agrupa por comportamiento de demanda Y proveedor+país a la vez
        (ver el aviso al inicio del archivo). Si alguna vez necesitas
        volver a trabajar sobre el clúster de comportamiento puro, basta
        con llamar esta función pasando col_cluster='Cluster'.

    comportamiento_por_cluster: dict {cluster_id: comportamiento}, salida
        de clasificar_todos_los_clusters.

    Devuelve un DataFrame con las columnas 'Código', col_cluster y
    'Lead Time (semanas)' (nada renombrado, nada como índice) más una
    columna nueva 'comportamiento'. Este es el objeto que se pasa tal cual
    a Pronosticador(dataset, df_clusters, cluster_col=col_cluster, ...).
    """
    columnas_esperadas = (col_sku, col_cluster, col_lead_time)
    faltantes = [c for c in columnas_esperadas if c not in df_resultado.columns]
    if faltantes:
        raise ValueError(f"❌ df_resultado no tiene las columnas esperadas: {faltantes}")

    df_clusters = df_resultado[[col_sku, col_cluster, col_lead_time]].copy()
    df_clusters['comportamiento'] = df_clusters[col_cluster].map(comportamiento_por_cluster)

    sin_comportamiento = df_clusters['comportamiento'].isna().sum()
    if sin_comportamiento > 0:
        clusters_faltantes = sorted(
            df_clusters.loc[df_clusters['comportamiento'].isna(), col_cluster].unique()
        )
        raise ValueError(
            f"❌ {sin_comportamiento} SKUs quedaron sin 'comportamiento' -- "
            f"faltan estos cluster_id en comportamiento_por_cluster: {clusters_faltantes}. "
            f"Verifica que datos_por_cluster (usado en clasificar_todos_los_clusters) "
            f"cubra los mismos clústeres que aparecen en df_resultado['{col_cluster}']."
        )

    return df_clusters.reset_index(drop=True)


# ==========================================================================
# 3. ARMAR datos_por_cluster PARA Pronosticador (columna 'y', semanal)
# ==========================================================================

def construir_datos_por_cluster_para_pronostico(datos_por_cluster_clustering):
    """
    datos_por_cluster_clustering: dict {cluster_id: Serie 'Unidades_Agregadas'
        semanal}, salida de preparar_unidades_agregadas_por_cluster
        (clusterizacionVolumen.py), llamada con cluster_col='Cluster_Operativo'.

    Devuelve dict {cluster_id: DataFrame con una sola columna 'y'}, índice
    de fechas semanal -- el formato exacto que Pronosticador.procesar_cluster
    espera recibir como 'df_agregado'. Se entrega siempre en semanas, sin
    excepción: si Pronosticador decide que un clúster va en meses (por su
    lead time), es él quien la reagrega, dentro de procesar_cluster -- este
    puente nunca se adelanta a esa decisión.
    """
    datos_por_cluster = {}
    for cluster_id, serie in datos_por_cluster_clustering.items():
        df = serie.rename('y').to_frame()
        df.index.name = None
        datos_por_cluster[cluster_id] = df
    return datos_por_cluster


# ==========================================================================
# 4. ARMAR EL dataset TRANSACCIONAL (columnas SKU, Fecha, Unidades)
# ==========================================================================

def construir_dataset_transaccional(df_featuring_raw, col_sku='Código',
                                     col_fecha='Fecha', col_unidades='Unidades'):
    """
    df_featuring_raw: el Excel crudo (la misma fuente que usa
        cargar_datos_desde_featuring y preparar_unidades_agregadas_por_cluster
        en clusterizacionVolumen.py) -- una fila por SKU y semana.

    Pronosticador.procesar_cluster reconstruye la historia de cada SKU con
    self.dataset[self.dataset[self.sku_col] == sku][['Fecha','Unidades']],
    donde self.sku_col por defecto es 'Código' -- NO 'SKU'. Por eso la
    columna del SKU se deja tal cual viene (col_sku, 'Código' por defecto);
    solo se renombran 'Fecha' y 'Unidades' si el origen las llama distinto.
    Este dataset transaccional es siempre a nivel de SKU individual -- no
    depende de si se está trabajando con Cluster_Comportamiento o
    Cluster_Operativo, así que no necesita ningún parámetro de clúster.
    """
    faltantes = [c for c in (col_sku, col_fecha, col_unidades) if c not in df_featuring_raw.columns]
    if faltantes:
        raise ValueError(f"❌ df_featuring_raw no tiene las columnas esperadas: {faltantes}")

    dataset = df_featuring_raw[[col_sku, col_fecha, col_unidades]].copy()
    dataset = dataset.rename(columns={col_fecha: 'Fecha', col_unidades: 'Unidades'})
    dataset['Fecha'] = pd.to_datetime(dataset['Fecha'])
    return dataset


# ==========================================================================
# 5. ETIQUETAR df_resultado (la tabla de clustering, 'Productos_con_cluster')
#    CON LA UNIDAD DE PRONÓSTICO QUE LE TOCARÁ A CADA SKU: 'semanas' o
#    'meses'. NO decide nada nuevo: reutiliza Pronosticador.decidir_unidad_
#    temporal -- el mismo cálculo que hará Pronosticador al procesar cada
#    clúster -- para que la tabla de clustering ya muestre, desde antes de
#    pronosticar, cómo se va a manejar cada Cluster_Operativo.
# ==========================================================================

def enriquecer_resultado_con_unidad_pronostico(df_resultado, col_cluster='Cluster_Operativo',
                                                col_lead_time='Lead Time (semanas)',
                                                factor_leadtime_minimo=5,
                                                max_periodos_pronostico=MAX_PERIODOS_PRONOSTICO):
    """
    df_resultado: salida de ejecutar_clustering_completo (columnas
        'Cluster_Operativo' y 'Lead Time (semanas)' incluidas).

    factor_leadtime_minimo y max_periodos_pronostico deben coincidir con
    los que use Pronósticos.py -- si cambian allá, cámbialos también aquí,
    para que la etiqueta sea consistente con lo que en verdad va a
    ejecutar el pronosticador.

    Devuelve una COPIA de df_resultado con columnas nuevas:

    - 'Unidad_Pronostico': 'semanas' | 'quincenas' | 'meses' | 'bimestres'
        | 'trimestres' -- ver _decidir_granularidad_pronostico. Es una
        propiedad del Cluster_Operativo, no del SKU: TODOS los SKU de un
        mismo Cluster_Operativo comparten la misma unidad (el pronóstico
        se construye a nivel de esa unidad operacional, no por SKU).

    - 'Lead_Time_Max_En_Unidad_Pronostico': el LEAD TIME MÁXIMO del
        Cluster_Operativo (el mismo que decidió la unidad y el horizonte
        -- lead_time_max_por_cluster, NO el lead time individual de cada
        SKU) convertido a la unidad de 'Unidad_Pronostico'. [CORREGIDO]
        La primera versión de esta columna convertía el lead time propio
        de CADA SKU -- eso mezclaba dos fuentes distintas para números que
        deben ser consistentes entre sí: la unidad y el horizonte salen
        del lead time MÁXIMO del clúster, así que el lead time convertido
        que se muestre también debe salir de esa misma cifra, no del lead
        time particular de cada SKU. Ahora las tres columnas
        (Unidad_Pronostico, Lead_Time_Max_En_Unidad_Pronostico,
        Horizonte_Pronostico_Periodos) son consistentes entre sí y
        idénticas para todos los SKU de un mismo Cluster_Operativo -- es
        una propiedad del clúster, no del SKU individual. El original
        'Lead Time (semanas)' (por SKU, en semanas) se conserva intacto;
        esta es una columna nueva y aparte, nunca se sobreescribe la
        original.

    - 'Horizonte_Pronostico_Periodos': el horizonte mínimo exigido por el
        lead time máximo del clúster (lead_time_max * factor_leadtime_minimo),
        ya expresado en la unidad de 'Unidad_Pronostico' y redondeado hacia
        arriba -- listo para usarse como horizonte_pronostico al instanciar
        Pronosticador, sin tener que recalcularlo aparte.

    [Cluster_Operativo vs Cluster_Comportamiento] El lead time máximo se
    calcula por Cluster_Operativo, no por Cluster_Comportamiento. Como
    Cluster_Operativo ya viene fijado a un único proveedor y país, en la
    práctica el lead time dentro de cada grupo suele ser más homogéneo que
    antes -- pero puede seguir habiendo más de un valor dentro de un mismo
    Cluster_Operativo, así que se sigue tomando el máximo.
    """
    faltantes = [c for c in (col_cluster, col_lead_time) if c not in df_resultado.columns]
    if faltantes:
        raise ValueError(f"❌ df_resultado no tiene las columnas esperadas: {faltantes}")

    lead_time_max_por_cluster = df_resultado.groupby(col_cluster)[col_lead_time].max()

    info_por_cluster = {
        cluster_id: _decidir_granularidad_pronostico(
            lead_time_max_semanas=lead_time_max,
            factor_leadtime_minimo=factor_leadtime_minimo,
            max_periodos=max_periodos_pronostico,
        )
        for cluster_id, lead_time_max in lead_time_max_por_cluster.items()
    }
    unidad_por_cluster = {cid: info[0] for cid, info in info_por_cluster.items()}
    semanas_por_periodo_por_cluster = {cid: info[1] for cid, info in info_por_cluster.items()}
    horizonte_por_cluster = {cid: info[2] for cid, info in info_por_cluster.items()}

    # [CORREGIDO] Lead_Time_Max_En_Unidad_Pronostico sale del lead time
    # MÁXIMO del clúster (lead_time_max_por_cluster) -- la misma cifra que
    # ya decidió unidad_por_cluster y horizonte_por_cluster -- convertido a
    # la unidad de ese clúster. Es UN solo valor por Cluster_Operativo,
    # repetido igual en todas sus filas (todas sus SKU), no un valor por
    # SKU individual.
    lead_time_max_en_unidad_por_cluster = {
        cid: round(lead_time_max_por_cluster[cid] / semanas_por_periodo_por_cluster[cid], 2)
        for cid in lead_time_max_por_cluster.index
    }

    df_enriquecido = df_resultado.copy()
    df_enriquecido['Unidad_Pronostico'] = df_enriquecido[col_cluster].map(unidad_por_cluster)
    df_enriquecido['Lead_Time_Max_En_Unidad_Pronostico'] = (
        df_enriquecido[col_cluster].map(lead_time_max_en_unidad_por_cluster)
    )
    df_enriquecido['Horizonte_Pronostico_Periodos'] = df_enriquecido[col_cluster].map(horizonte_por_cluster)

    conteo_unidades = pd.Series(unidad_por_cluster).value_counts()
    resumen = ", ".join(f"{n} en {u}" for u, n in conteo_unidades.items())
    print(f"   🏷️  Unidad de pronóstico por Cluster_Operativo ({len(unidad_por_cluster)} clústeres): {resumen}.")

    return df_enriquecido


# ==========================================================================
# 6. FUNCIÓN DE CONVENIENCIA: ARMA TODOS LOS INSUMOS DE UNA SOLA VEZ
# ==========================================================================

def preparar_insumos_para_pronosticador(df_resultado, datos_por_cluster_clustering,
                                         df_featuring_raw, col_sku='Código',
                                         col_cluster='Cluster_Operativo', col_fecha='Fecha',
                                         col_unidades='Unidades',
                                         col_lead_time='Lead Time (semanas)',
                                         factor_leadtime_minimo=5,
                                         max_periodos_pronostico=MAX_PERIODOS_PRONOSTICO):
    """
    Envuelve los pasos anteriores en una sola llamada. Devuelve
    (dataset, df_clusters, datos_por_cluster, skus_por_cluster,
     df_resultado_enriquecido) -- este es el "hand-off" completo hacia
    Pronósticos.py, que se usa (en un script APARTE, ver más abajo por qué
    ya no se llama desde aquí) así:

        pronosticador = Pronosticador(
            dataset, df_clusters,
            cluster_col=col_cluster,  # 'Cluster_Operativo' por defecto --
                                       # OBLIGATORIO pasarlo: el default de
                                       # Pronosticador sigue siendo 'Cluster'
            horizonte_pronostico=...,  # usa 'Horizonte_Pronostico_Periodos'
                                       # de df_resultado_enriquecido, por
                                       # clúster -- ya viene resuelto
            factor_leadtime_minimo=factor_leadtime_minimo,
        )
        resultados = pronosticador.ejecutar_pipeline_pronosticos(
            skus_por_cluster, datos_por_cluster
        )

    Este módulo NO ejecuta ese paso (ver aviso de desacoplamiento al
    inicio del archivo) -- solo deja todo listo y lo guarda en
    'clusters_con_unidad_pronostico.xlsx' (incluye 'comportamiento',
    'Unidad_Pronostico', 'Lead_Time_Max_En_Unidad_Pronostico' y
    'Horizonte_Pronostico_Periodos') para que Pronósticos.py lo lea de
    forma independiente, sin que ningún módulo importe al otro.

    df_resultado_enriquecido es la tabla de clustering con esas columnas
    nuevas -- es el archivo que Pronósticos.py debe leer para correr el
    pronóstico real.

    col_cluster por defecto es 'Cluster_Operativo' (ver el aviso al inicio
    del archivo). Pásale col_cluster='Cluster' si en algún momento
    necesitas volver a pronosticar sobre el clúster de comportamiento puro
    -- pero entonces recuerda pasar cluster_col='Cluster' (no
    'Cluster_Operativo') a Pronosticador también, para que ambos coincidan.
    """
    print("=" * 70)
    print("PUENTE CLUSTERING -> PRONOSTICADOR")
    print(f"   (trabajando sobre '{col_cluster}')")
    print("=" * 70)

    # [REORDENADO -- CLASIFICAR EN LA FRECUENCIA FINAL] La unidad de cada
    # clúster se decide PRIMERO (no depende de 'comportamiento', solo del
    # lead time) para poder reagregar su serie a esa unidad ANTES de
    # clasificar estacionalidad/tendencia/intermitencia -- ver el aviso
    # completo en clasificar_todos_los_clusters.
    df_resultado_enriquecido = enriquecer_resultado_con_unidad_pronostico(
        df_resultado, col_cluster=col_cluster, col_lead_time=col_lead_time,
        factor_leadtime_minimo=factor_leadtime_minimo,
        max_periodos_pronostico=max_periodos_pronostico,
    )
    unidad_por_cluster = (
        df_resultado_enriquecido.drop_duplicates(subset=[col_cluster])
        .set_index(col_cluster)['Unidad_Pronostico']
        .to_dict()
    )

    series_por_unidad = {}
    periodo_estacional_por_cluster = {}
    for cluster_id, serie_semanal in datos_por_cluster_clustering.items():
        unidad = unidad_por_cluster[cluster_id]
        regla = REGLA_RESAMPLE_POR_UNIDAD[unidad]
        serie_en_unidad = serie_semanal if unidad == 'semanas' else serie_semanal.resample(regla).sum()
        series_por_unidad[cluster_id] = serie_en_unidad
        periodo_estacional_por_cluster[cluster_id] = PERIODO_ESTACIONAL_POR_UNIDAD[unidad]

    comportamiento_por_cluster = clasificar_todos_los_clusters(
        series_por_unidad, periodo_estacional_por_cluster
    )

    df_clusters = construir_df_clusters(
        df_resultado, comportamiento_por_cluster,
        col_sku=col_sku, col_cluster=col_cluster, col_lead_time=col_lead_time
    )
    datos_por_cluster = construir_datos_por_cluster_para_pronostico(datos_por_cluster_clustering)
    dataset = construir_dataset_transaccional(
        df_featuring_raw, col_sku=col_sku, col_fecha=col_fecha, col_unidades=col_unidades
    )

    skus_por_cluster = {
        cluster_id: grupo[col_sku].tolist()
        for cluster_id, grupo in df_clusters.groupby(col_cluster)
    }

    print(f"\n✅ Listo: {dataset[col_sku].nunique()} SKUs, "
          f"{len(skus_por_cluster)} '{col_cluster}' distintos, "
          f"comportamientos: {comportamiento_por_cluster}")

    return dataset, df_clusters, datos_por_cluster, skus_por_cluster, df_resultado_enriquecido


# ==========================================================================
# 7. EJEMPLO DE USO COMPLETO (clustering -> pronóstico, de punta a punta)
# ==========================================================================

def cargar_unidades_agregadas_desde_excel(ruta='unidades_agregadas_por_cluster.xlsx'):
    """
    Relee 'unidades_agregadas_por_cluster.xlsx' (generado por
    clusterizacionVolumen.py, ya agrupado por Cluster_Operativo) y
    reconstruye el mismo formato dict {cluster_id: Serie semanal} que
    devuelve preparar_unidades_agregadas_por_cluster() -- para reutilizarlo
    en vez de recalcularlo aquí. Usa la hoja 'Indice' del archivo (mapea
    Cluster_Operativo -> nombre de hoja real) porque el nombre de hoja
    puede venir truncado respecto al Cluster_Operativo real (límite de 31
    caracteres de Excel) -- sin el índice no habría forma confiable de
    saber a qué clúster corresponde cada hoja.
    """
    indice = pd.read_excel(ruta, sheet_name='Indice')
    datos_por_cluster = {}
    for _, fila in indice.iterrows():
        serie = pd.read_excel(ruta, sheet_name=fila['Hoja'], index_col=0)['Unidades_Agregadas']
        serie.index = pd.to_datetime(serie.index)
        datos_por_cluster[fila['Cluster_Operativo']] = serie
    return datos_por_cluster


# ==========================================================================
# 7. EJECUCIÓN -- SOLO EL PUENTE. El pronóstico real se corre por separado,
#    desde Pronósticos.py, que lee 'clusters_con_unidad_pronostico.xlsx'
#    (el archivo que este bloque genera) -- ver el aviso de desacoplamiento
#    al inicio del archivo.
# ==========================================================================

if __name__ == "__main__":
    import os
    # Funciona igual si se ejecuta desde la raíz del proyecto (como paquete
    # 'services') o directamente desde dentro de la carpeta services.
    try:
        from services.clusterizacionHibrida import (
            cargar_datos_desde_featuring,
            ejecutar_clustering_completo,
            preparar_unidades_agregadas_por_cluster,
        )
    except ModuleNotFoundError:
        from clusterizacionHibrida import (
            cargar_datos_desde_featuring,
            ejecutar_clustering_completo,
            preparar_unidades_agregadas_por_cluster,
        )

    # --- 1. Clustering ---
    # [ARQUITECTURA] Si 'clusters_asignados_completo.xlsx' ya existe, se
    # reutiliza tal cual (solo se lee la hoja 'Productos_con_cluster') y el
    # clustering NO se recalcula. Pon FORZAR_RECALCULAR_CLUSTERS = True para
    # volver a correr los 4 métodos desde cero (por ejemplo, si cambió
    # df_featuring.xlsx o quieres probar otros k_min/k_max). Cualquiera de
    # los dos caminos ya trae 'Cluster_Operativo' calculado -- se agrega
    # dentro de ejecutar_clustering_completo, así que no hace falta
    # reconstruirlo aquí.
    RUTA_CLUSTERS = 'clusters_asignados_hibrido.xlsx'
    FORZAR_RECALCULAR_CLUSTERS = False

    if not FORZAR_RECALCULAR_CLUSTERS and os.path.exists(RUTA_CLUSTERS):
        print(f"📂 Usando el clustering ya calculado en '{RUTA_CLUSTERS}' -- "
              f"no se recalcula. (FORZAR_RECALCULAR_CLUSTERS=True para "
              f"volver a correr los 4 métodos de clustering desde cero.)")
        df_resultado = pd.read_excel(RUTA_CLUSTERS, sheet_name='Productos_con_cluster')
    else:
        df_productos = cargar_datos_desde_featuring('df_featuring.xlsx')
        df_resultado, df_perfil, df_granularidad = ejecutar_clustering_completo(
            df_productos, k_min=8, k_max=15, ruta_salida=RUTA_CLUSTERS
        )

    df_featuring_raw = pd.read_excel('df_featuring.xlsx')

    # --- 1b. Unidades agregadas por Cluster_Operativo ---
    # [CORREGIDO -- YA NO SE RECALCULA SI clusterizacionVolumen.py YA LO
    # HIZO] clusterizacionVolumen.py ya calcula y guarda
    # 'unidades_agregadas_por_cluster.xlsx' agrupado por Cluster_Operativo
    # en su propio __main__ (mismo trabajo caro: alinear historia común
    # sobre todo df_featuring). Antes este archivo lo recalculaba desde
    # cero sin ninguna necesidad -- ahora, si ese Excel ya existe, se relee
    # (cargar_unidades_agregadas_desde_excel) en vez de repetir el cálculo.
    # Igual que con FORZAR_RECALCULAR_CLUSTERS, hay un flag para forzar el
    # recálculo si hace falta (ej. cambió df_featuring.xlsx después de la
    # última corrida de clusterizacionVolumen.py).
    RUTA_AGREGADOS = 'unidades_agregadas_por_cluster_hibrido.xlsx'
    FORZAR_RECALCULAR_AGREGADOS = False

    if not FORZAR_RECALCULAR_AGREGADOS and os.path.exists(RUTA_AGREGADOS):
        print(f"📂 Usando las unidades agregadas ya calculadas en '{RUTA_AGREGADOS}' -- "
              f"no se recalculan. (FORZAR_RECALCULAR_AGREGADOS=True para "
              f"volver a alinear y agregar las series desde cero.)")
        datos_por_cluster_clustering = cargar_unidades_agregadas_desde_excel(RUTA_AGREGADOS)
    else:
        datos_por_cluster_clustering = preparar_unidades_agregadas_por_cluster(
            df_clusters=df_resultado,
            df_semanal=df_featuring_raw,
            fecha_col='Fecha',
            sku_col='Código',
            cluster_col='Cluster_Operativo'
        )

    # --- 2. Puente: traducir al formato de Pronosticador ---
    # [CORREGIDO] factor_leadtime_minimo=5 y max_periodos_pronostico=25
    # reemplazan el viejo umbral_semanas_horizonte_mensual=52 -- ver el
    # nuevo criterio de granularidad (GRANULARIDADES_PRONOSTICO más arriba
    # en este archivo) para el porqué.
    factor_leadtime_minimo = 5
    max_periodos_pronostico = MAX_PERIODOS_PRONOSTICO

    # col_cluster ya es 'Cluster_Operativo' por defecto en esta función --
    # se deja explícito aquí solo para que quede visible en el flujo.
    (dataset, df_clusters, datos_por_cluster, skus_por_cluster,
     df_resultado_enriquecido) = preparar_insumos_para_pronosticador(
        df_resultado, datos_por_cluster_clustering, df_featuring_raw,
        col_cluster='Cluster_Operativo',
        factor_leadtime_minimo=factor_leadtime_minimo,
        max_periodos_pronostico=max_periodos_pronostico,
    )

    # [CORREGIDO] Se incorpora 'comportamiento' (calculado en df_clusters)
    # a df_resultado_enriquecido antes de guardar -- antes el archivo
    # exportado solo traía 'Unidad_Pronostico', sin 'comportamiento'. Como
    # este módulo ya NO instancia Pronosticador (ver aviso de
    # desacoplamiento al inicio del archivo), 'clusters_con_unidad_pronostico.xlsx'
    # tiene que quedar AUTOSUFICIENTE: debe traer todo lo que Pronósticos.py
    # necesita para correr el pronóstico por su cuenta, en un script
    # separado, sin que ningún módulo importe al otro.
    mapa_comportamiento = df_clusters.set_index('Código')['comportamiento']
    df_resultado_enriquecido['comportamiento'] = (
        df_resultado_enriquecido['Código'].map(mapa_comportamiento)
    )

    df_resultado_enriquecido.to_excel('clusters_con_unidad_pronostico_hibrido.xlsx', index=False)
    print("💾 Tabla de clustering etiquetada (con 'comportamiento' y "
          "'Unidad_Pronostico') guardada en 'clusters_con_unidad_pronostico_hibrido.xlsx'.")
    print("   Para correr el pronóstico real, ejecuta NuevoPronosticoHibrido.py por separado --")
    print("   ese script lee este mismo archivo de forma independiente.")
