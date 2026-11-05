# =============================================================================
# features.py - características para clustering de inventarios
# =============================================================================
# Versión con semilla fija para reproducibilidad total.
# Todas las operaciones que dependan de números aleatorios (simulación,
# futuros módulos de imputación o clustering) usarán la misma secuencia.
#
# CORREGIDO respecto a la versión anterior:
#
# 1. Demanda_Promedio ya NO se rellena con 0 cuando un SKU tiene menos de
#    min_semanas puntos. Antes, cualquier SKU con muy poca historia (algo
#    posible ahora que el archivo puede empezar en cualquier fecha, no solo
#    2009) perdía su demanda real y quedaba en 0 -- lo que lo hacía parecer,
#    de cara al clustering, un producto sin ninguna demanda. Ahora se calcula
#    la media real de los datos disponibles; solo la tendencia (que sí
#    necesita varios puntos para estimarse con algo de confianza) se deja en
#    0 cuando hay muy poca historia, y el CV se calcula de forma simple
#    (sin detrend) en ese caso, en vez de forzarlo también a 0.
#
# 2. std() sobre arrays de numpy ahora usa ddof=1 (muestral) explícitamente,
#    para ser consistente con el resto del pipeline (pandas usa ddof=1 por
#    defecto en limpieza_de_datos.py). Antes, al llamar .std() directamente
#    sobre un array de numpy (no una Series de pandas), se usaba ddof=0
#    (poblacional) sin que fuera intencional -- distorsionaba un poco
#    Demanda_std_residuos y CV_Normalizado, sobre todo en series cortas.
#
# [NUEVO] 3. Caracterización estadística independiente de la demanda semanal
#    por SKU (función clasificar_comportamiento y funciones auxiliares _*):
#      - Intermitencia / variabilidad: ADI y CV² de las demandas positivas
#        -> Clase_Demanda (Suave / Errática / Intermitente / Irregular (lumpy))
#        con umbrales ADI = 1,32 y CV² = 0,49 (Syntetos-Boylan).
#      - Tendencia: prueba de Mann-Kendall + cambio relativo mínimo (20 %),
#        con ajuste por autocorrelación de orden 1.
#      - Estacionalidad: STL robusto, periodo 52, umbral de fuerza 0,50,
#        mínimo 104 semanas consecutivas.
#      - Estacionariedad: ADF + KPSS (alfa = 0,05), con regla de decisión
#        que distingue estacionaria / no estacionaria / inconcluso / no
#        evaluable.
#    Cada dimensión se evalúa por separado: que un SKU sea intermitente ya
#    NO impide evaluar tendencia, estacionalidad y estacionariedad.
#    Estados posibles de cada dimensión: detectada / no detectada /
#    no evaluable / inconcluso. La falta de información NUNCA se interpreta
#    como ausencia de la característica.
#    Las nuevas columnas NO se incorporan al clustering (eso lo decide el
#    módulo de clustering); aquí solo se calculan y se exportan.
#
# [NUEVO] 4. calcular_cv_normalizado ahora ordena cada SKU cronológicamente
#    antes de calcular (la tendencia usa np.arange(len(y)) como eje de
#    tiempo, así que dependía del orden de las filas de entrada).
#    Los demás cálculos existentes no se tocaron.
#
# [NUEVO] 5. Periodo estacional N por SKU (función _detectar_periodo_n):
#    cada cuántas SEMANAS se repite el patrón estacional (4, 13, 26, 52...).
#      - Se quita la tendencia con una diferencia de primer orden y se
#        calcula la autocorrelación (ACF) de la serie semanal.
#      - N es el periodo candidato cuya ACF es un pico local, supera la banda
#        de significancia (~95 %: 2/sqrt(n)) y es la mayor entre los candidatos.
#      - Un periodo candidato p solo se evalúa si el SKU tiene al menos
#        MIN_CICLOS_N ciclos completos de historia (len >= MIN_CICLOS_N * p).
#    Columnas nuevas:
#      Periodo_N        : N en semanas. 0 = se evaluó y NO se detectó
#                         estacionalidad. Vacío (NaN) = No evaluable/Inconcluso.
#      Periodo_N_ACF    : valor de la ACF en el N detectado (vacío si no hay).
#      Periodo_N_estado : Detectada / No detectada / Inconcluso / No evaluable.
#    Igual que en el resto de dimensiones: Periodo_N = 0 solo se afirma cuando
#    el SKU SÍ pudo evaluarse; la falta de información no se convierte en 0.
#    Requiere semanas consecutivas sin huecos (las semanas faltantes no se
#    asumen como demanda 0).
# =============================================================================

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.tsa.seasonal import seasonal_decompose, STL
from statsmodels.tsa.stattools import adfuller, kpss, acf
import warnings
import random  # para fijar semilla del generador estándar

warnings.filterwarnings('ignore')

# -----------------------------------------------------------------------------
# Semilla global (puede modificarse llamando a ejecutar_features con semilla=...)
# -----------------------------------------------------------------------------
SEMILLA_GLOBAL = 42
random.seed(SEMILLA_GLOBAL)
np.random.seed(SEMILLA_GLOBAL)

# -----------------------------------------------------------------------------
# [NUEVO] Parámetros de la caracterización de la demanda
# -----------------------------------------------------------------------------
ALFA = 0.05                       # nivel de significancia (Kendall, ADF, KPSS)
ADI_UMBRAL = 1.32                 # Syntetos-Boylan: intermitente si ADI >= 1,32
CV2_UMBRAL = 0.49                 # Syntetos-Boylan: errática/irregular si CV² >= 0,49
CAMBIO_REL_MIN = 0.20             # cambio relativo mínimo para declarar tendencia
PERIODO_ANUAL = 52                # semanas por ciclo estacional
MIN_SEMANAS_ESTAC = 2 * PERIODO_ANUAL   # 104 semanas (dos ciclos completos)
UMBRAL_FUERZA_ESTAC = 0.50        # fuerza estacional mínima (Wang et al., 2006)
# ADVERTENCIA (validado por simulación): con pocos ciclos anuales la fuerza STL
# de una serie SIN estacionalidad ya es alta, porque cada semana del año se
# estima con solo 2-3 datos. Con ruido normal y umbral 0,50, la fracción de
# falsos 'Sí' fue ~100 % a 104 semanas, ~44 % a 156, ~1 % a 208 y ~0 % desde
# 260 semanas (series intermitentes/de cola pesada: 0-83 %, muy variable).
# Si se prioriza evitar falsos positivos, subir min_semanas_estacionalidad
# (p. ej. 208 = 4 ciclos) o exigir además una prueba de significancia.
MIN_SEMANAS_TENDENCIA = 10        # mínimo de observaciones para Mann-Kendall
MIN_SEMANAS_ESTACIONARIEDAD = 52  # mínimo de semanas consecutivas para ADF/KPSS
MIN_DEMANDAS_POSITIVAS = 5        # piso de semanas con venta para inferir algo

# [NUEVO] Periodo estacional N (en SEMANAS)
# PERIODOS_N: lista cerrada de periodos candidatos; el N detectado se ajusta al
# más cercano (±TOL_PERIODO_N semanas). Pon PERIODOS_N = None para N libre
# (cualquier lag entre 2 y MAX_LAG_LIBRE_N), aunque eso tiende a generar muchos
# valores distintos por ruido.
PERIODOS_N = [4, 13, 26, 52]
TOL_PERIODO_N = 1
MAX_LAG_LIBRE_N = 52
# Ciclos completos mínimos de historia para evaluar un periodo candidato.
# 3 (y no 2) por la advertencia de arriba: con pocos ciclos, un patrón
# estacional aparente es muy fácil de obtener por azar.
MIN_CICLOS_N = 3

# Estados posibles de cada característica
EST_NO_EVAL = 'No evaluable'
EST_INCONCLUSO = 'Inconcluso'
EST_DETECTADA = 'Detectada'
EST_NO_DETECTADA = 'No detectada'

# Columnas nuevas (ADI ya existía y no se repite aquí)
COLUMNAS_CARACTERIZACION = [
    'Clase_Demanda', 'CV2_demanda',
    'Tipo_Tendencia', 'Cambio_relativo', 'Tendencia_p_valor',
    'Tendencia_p_valor_MK', 'Tendencia_rho1',
    'Es_Estacional', 'Estacionalidad_STL',
    'Periodo_N', 'Periodo_N_ACF', 'Periodo_N_estado',
    'Estacionariedad', 'ADF_p_valor', 'KPSS_p_valor',
    'N_semanas', 'Semanas_faltantes',
    'Comportamiento', 'Notas_evaluacion'
]


# -----------------------------------------------------------------------------
# 1. Coeficiente de Variación Normalizado (eliminando tendencia)
# -----------------------------------------------------------------------------

def calcular_cv_normalizado(df_series, col_fecha='Fecha', col_codigo='Código',
                            col_unidades='Unidades', min_semanas=4):
    """
    Calcula el CV normalizado para cada producto, eliminando el efecto de la
    tendencia mediante regresión lineal contra el tiempo (semanas).
    Retorna un DataFrame con una fila por producto.

    min_semanas es el mínimo de puntos para estimar una TENDENCIA de forma
    confiable (una recta con muy pocos puntos es ruido, no señal). No es un
    mínimo para calcular la demanda promedio -- esa se calcula siempre que
    haya al menos un dato, sea cual sea la longitud de la historia del SKU.
    """
    def _calc(grupo):
        # [NUEVO] orden cronológico garantizado (la pendiente depende del orden)
        grupo = grupo.sort_values(col_fecha, kind='mergesort')
        y = grupo[col_unidades].values.astype(float)

        if len(y) == 0:
            return pd.Series({
                'Demanda_Promedio': np.nan,
                'CV_Normalizado': np.nan,
                'Tendencia_pendiente': np.nan,
                'Demanda_std_residuos': np.nan,
                'ADI': np.nan
            })

        # [NUEVO] ADI (Average Demand Interval): número promedio de periodos
        # (semanas) entre dos periodos consecutivos con demanda real. Es la
        # métrica estándar de INTERMITENCIA en pronóstico de inventarios
        # (junto con el CV, es la base de la clasificación de Syntetos-Boylan
        # -- suave / intermitente / errática / grumosa -- que se usa
        # justamente para decidir qué SKU pueden compartir una misma
        # política de reabastecimiento). ADI=1 significa demanda todas las
        # semanas; ADI=4 significa que en promedio pasan 4 semanas entre
        # una venta y la siguiente. Se calcula sobre TODA la historia
        # semanal del SKU (con o sin suficientes puntos para tendencia,
        # a diferencia de CV/Tendencia esto no necesita una recta).
        n_periodos_con_demanda = int((y > 0).sum())
        adi = (len(y) / n_periodos_con_demanda) if n_periodos_con_demanda > 0 else np.nan

        demanda_prom = y.mean()

        if len(y) < min_semanas:
            # Muy poca historia para ajustar una recta de tendencia con
            # confianza -- pero la demanda promedio SÍ se calcula con lo que
            # hay (nunca se rellena con 0 mientras exista al menos un dato).
            # El CV se calcula sin quitar tendencia (aproximación razonable
            # cuando no hay suficientes puntos para separarla del ruido).
            std_simple = y.std(ddof=1) if len(y) > 1 else 0.0
            cv_simple = std_simple / (demanda_prom + 1e-6) if demanda_prom > 0 else 0.0
            return pd.Series({
                'Demanda_Promedio': demanda_prom,
                'CV_Normalizado': cv_simple,
                'Tendencia_pendiente': 0.0,
                'Demanda_std_residuos': std_simple,
                'ADI': adi
            })

        if y.std(ddof=1) == 0:
            return pd.Series({
                'Demanda_Promedio': demanda_prom,
                'CV_Normalizado': 0.0,
                'Tendencia_pendiente': 0.0,
                'Demanda_std_residuos': 0.0,
                'ADI': adi
            })

        x = np.arange(len(y))
        coef = np.polyfit(x, y, 1)
        tendencia = np.polyval(coef, x)
        residuos = y - tendencia
        std_residuos = residuos.std(ddof=1)
        cv_norm = std_residuos / (demanda_prom + 1e-6)
        return pd.Series({
            'Demanda_Promedio': demanda_prom,
            'CV_Normalizado': cv_norm,
            'Tendencia_pendiente': coef[0],
            'Demanda_std_residuos': std_residuos,
            'ADI': adi
        })

    resultados = df_series.groupby(col_codigo, sort=True).apply(_calc).reset_index()
    return resultados


# -----------------------------------------------------------------------------
# 2. Estacionalidad (opcional) -- columna original Estacionalidad_fuerza
# -----------------------------------------------------------------------------
# NOTA: esta función se conserva tal cual para no alterar la columna
# Estacionalidad_fuerza ni lo que dependa de ella. Asume semanas consecutivas
# (no verifica huecos). La evaluación rigurosa, con verificación de semanas
# consecutivas y STL robusto, está en clasificar_comportamiento().

def calcular_estacionalidad(df_series, col_fecha='Fecha', col_codigo='Código',
                            col_unidades='Unidades', min_semanas=2*52):
    """
    Calcula la fuerza de la estacionalidad para cada producto.
    (Por defecto desactivado por su costo computacional)
    """
    def _calc(grupo):
        grupo = grupo.sort_values(col_fecha)
        y = grupo[col_unidades].values.astype(float)
        if len(y) < min_semanas:
            return np.nan
        idx = pd.date_range(start=grupo[col_fecha].min(), periods=len(y), freq='W-MON')
        serie = pd.Series(y, index=idx)
        try:
            descomp = seasonal_decompose(serie, model='additive', period=52, extrapolate_trend='freq')
            var_seasonal = descomp.seasonal.var()
            var_total = serie.var()
            if var_total == 0:
                return 0.0
            return var_seasonal / var_total
        except Exception:
            return np.nan

    resultados = df_series.groupby(col_codigo, sort=True).apply(_calc).reset_index(name='Estacionalidad_fuerza')
    return resultados


# -----------------------------------------------------------------------------
# 2b. [NUEVO] Caracterización independiente del comportamiento de la demanda
# -----------------------------------------------------------------------------

def _preparar_serie_semanal(grupo, col_fecha, col_unidades):
    """
    Ordena cronológicamente la serie de un SKU y construye:
      - y_obs / x_obs : observaciones válidas (no NaN) y su posición temporal
        en semanas (entero si las fechas caen en una grilla semanal).
      - grid          : arreglo con una posición por semana entre la primera y
        la última observación, con NaN en las semanas SIN dato. Una semana
        faltante es NaN, nunca 0 (no se confunde falta de dato con demanda
        cero). None si las fechas no están alineadas a múltiplos de 7 días.
      - n_faltantes   : semanas sin dato dentro de ese rango.
    Si hay varias filas con la misma fecha, sus unidades se suman.
    """
    g = grupo[[col_fecha, col_unidades]].copy()
    g[col_fecha] = pd.to_datetime(g[col_fecha]).dt.normalize()
    g = g.sort_values(col_fecha, kind='mergesort')
    g = g.groupby(col_fecha, as_index=False)[col_unidades].sum(min_count=1)
    g = g.dropna(subset=[col_unidades])
    if g.empty:
        return None

    dias = (g[col_fecha] - g[col_fecha].iloc[0]).dt.days.values
    y_obs = g[col_unidades].values.astype(float)
    if np.all(dias % 7 == 0):
        pos = (dias // 7).astype(int)
        grid = np.full(pos[-1] + 1, np.nan)
        grid[pos] = y_obs
        return {'y_obs': y_obs, 'x_obs': pos.astype(float), 'grid': grid,
                'n_faltantes': int(np.isnan(grid).sum())}
    # Fechas no alineadas a una grilla semanal: solo se puede usar el eje real
    return {'y_obs': y_obs, 'x_obs': dias / 7.0, 'grid': None,
            'n_faltantes': np.nan}


def _mann_kendall(y, x):
    """
    Prueba de Mann-Kendall (bilateral) con corrección por empates y
    corrección de continuidad. La serie debe venir ordenada cronológicamente.

    Autocorrelación: la prueba supone observaciones independientes; con
    autocorrelación positiva la varianza de S se subestima y la prueba
    declara tendencias que no existen. Se estima la autocorrelación de orden
    1 (rho1) de los residuos de la recta; si es positiva y significativa
    (rho1 > 1,96/sqrt(n)), se infla Var(S) por (1+rho1)/(1-rho1)
    (equivalente a reducir el tamaño de muestra efectivo, Bayley-Hammersley).
    Es una aproximación: solo contempla el rezago 1.
    Retorna None si la prueba no está definida (serie constante).
    """
    n = len(y)
    signos = np.sign(y[None, :] - y[:, None])
    S = float(np.triu(signos, k=1).sum())
    _, cuentas = np.unique(y, return_counts=True)
    var_s = (n * (n - 1) * (2 * n + 5)
             - np.sum(cuentas * (cuentas - 1) * (2 * cuentas + 5))) / 18.0
    if var_s <= 0:
        return None
    z = 0.0 if S == 0 else (S - np.sign(S)) / np.sqrt(var_s)
    p_mk = float(2 * stats.norm.sf(abs(z)))

    coef = np.polyfit(x, y, 1)
    e = y - np.polyval(coef, x)
    den = float(np.sum(e ** 2))
    rho1 = float(np.sum(e[:-1] * e[1:]) / den) if den > 0 else 0.0

    p_corr = p_mk
    corregido = False
    if rho1 > 1.96 / np.sqrt(n):
        r = min(rho1, 0.99)
        factor = (1 + r) / (1 - r)
        p_corr = float(2 * stats.norm.sf(abs(z) / np.sqrt(factor)))
        corregido = True
    return {'S': S, 'p_mk': p_mk, 'p': p_corr, 'rho1': rho1,
            'pendiente': float(coef[0]), 'corregido': corregido}


def _fuerza_estacional_stl(y_grid, periodo=PERIODO_ANUAL):
    """
    Fuerza estacional con STL robusto (Wang, Smith y Hyndman, 2006):
        Fs = max(0, 1 - Var(resto) / Var(estacional + resto))
    Va de 0 (sin estacionalidad) a 1 (muy estacional).
    """
    res = STL(y_grid, period=periodo, robust=True).fit()
    var_r = np.var(res.resid, ddof=1)
    var_sr = np.var(res.seasonal + res.resid, ddof=1)
    if var_sr <= 0:
        return np.nan
    return float(max(0.0, 1.0 - var_r / var_sr))


def _detectar_periodo_n(y_grid, periodos=PERIODOS_N, tol=TOL_PERIODO_N,
                        min_ciclos=MIN_CICLOS_N, max_lag_libre=MAX_LAG_LIBRE_N):
    """
    [NUEVO] Periodo estacional N (en semanas) de una serie semanal SIN huecos.

    Método:
      - Se quita la tendencia con una diferencia de primer orden.
      - Se calcula la ACF de la serie diferenciada.
      - Para cada periodo candidato p se busca el máximo de la ACF en
        [p - tol, p + tol]; el candidato cuenta si ese máximo es un pico local
        y supera la banda de significancia (~95 %: 2/sqrt(n)).
      - Gana el candidato con mayor ACF.
      - Un candidato solo se evalúa si len(serie) >= min_ciclos * p.
      - periodos=None -> N libre (lags 2..max_lag_libre, sin tolerancia).

    Retorna un diccionario:
      estado        : 'Detectada' / 'No detectada' / 'No evaluable'
      n             : N detectado (semanas); 0 si 'No detectada'; NaN si no evaluable
      acf           : ACF en el N detectado (NaN si no hay)
      no_evaluables : candidatos que no se pudieron evaluar por historia corta

    Limitación: se prueban varios candidatos a la vez, así que la probabilidad
    de un falso positivo en una serie sin estacionalidad es mayor que la de un
    solo contraste al 5 %. Las series muy intermitentes (casi todo ceros)
    tienen una ACF muy ruidosa; la detección en ellas es poco confiable.
    """
    y_grid = np.asarray(y_grid, dtype=float)

    if periodos is None:
        candidatos = list(range(2, max_lag_libre + 1))
        tol = 0
    else:
        candidatos = list(periodos)

    evaluables = [p for p in candidatos if len(y_grid) >= min_ciclos * p]
    no_evaluables = [p for p in candidatos if p not in evaluables]

    if not evaluables:
        return {'estado': EST_NO_EVAL, 'n': np.nan, 'acf': np.nan,
                'no_evaluables': no_evaluables}

    # Quitar tendencia
    y = np.diff(y_grid)

    if len(y) < 8 or np.std(y) == 0:
        # Rampa perfecta o serie demasiado corta: no hay patrón que detectar
        return {'estado': EST_NO_DETECTADA, 'n': 0, 'acf': np.nan,
                'no_evaluables': no_evaluables}

    max_lag = min(max(evaluables) + tol + 1, len(y) - 2)
    if max_lag < 3:
        return {'estado': EST_NO_EVAL, 'n': np.nan, 'acf': np.nan,
                'no_evaluables': no_evaluables}

    r = acf(y, nlags=max_lag, fft=True)
    umbral = 2 / np.sqrt(len(y))

    mejor_n = 0
    mejor_r = umbral

    for p in evaluables:

        lo = max(p - tol, 2)
        hi = min(p + tol, max_lag - 1)

        if lo > hi:
            continue

        lag = lo + int(np.argmax(r[lo:hi + 1]))

        es_pico = (
            r[lag] >= r[lag - 1]
            and
            r[lag] >= r[lag + 1]
        )

        if es_pico and r[lag] > mejor_r:
            mejor_n = p
            mejor_r = r[lag]

    if mejor_n > 0:
        return {'estado': EST_DETECTADA, 'n': int(mejor_n),
                'acf': float(mejor_r), 'no_evaluables': no_evaluables}

    return {'estado': EST_NO_DETECTADA, 'n': 0, 'acf': np.nan,
            'no_evaluables': no_evaluables}


def _pruebas_estacionariedad(y_grid, alfa=ALFA):
    """
    ADF y KPSS sobre la serie semanal completa (sin huecos).

    Especificación (documentada):
      - Términos determinísticos: SOLO constante (regression='c') en ambas.
        Se busca estacionariedad en NIVEL (media constante). Una serie con
        tendencia determinística, por tanto, no resulta 'Estacionaria' (la
        tendencia se reporta aparte en Tipo_Tendencia).
      - ADF: H0 = raíz unitaria (no estacionaria). Rezagos por AIC
        (autolag='AIC') con maxlag por defecto de statsmodels,
        12*(n/100)^(1/4) (regla de Schwert).
      - KPSS: H0 = estacionaria. Rezagos nlags='auto' (Hobijn et al., 1998).
        statsmodels interpola su p-valor entre 0,01 y 0,10: valores fuera de
        ese rango se truncan en los extremos.
    Regla de decisión conjunta (alfa = 0,05):
      ADF rechaza  y KPSS no rechaza -> Estacionaria
      ADF no rechaza y KPSS rechaza  -> No estacionaria
      ambas rechazan                 -> Inconcluso (señales contradictorias)
      ninguna rechaza                -> Inconcluso (poca potencia)
    """
    adf_p = float(adfuller(y_grid, regression='c', autolag='AIC')[1])
    kpss_p = float(kpss(y_grid, regression='c', nlags='auto')[1])
    adf_rechaza = adf_p < alfa
    kpss_rechaza = kpss_p < alfa
    if adf_rechaza and not kpss_rechaza:
        estado = 'Estacionaria'
    elif (not adf_rechaza) and kpss_rechaza:
        estado = 'No estacionaria'
    else:
        estado = EST_INCONCLUSO
    return estado, adf_p, kpss_p


def _describir_comportamiento(clase, tipo_tend, es_est, estac):
    """Texto interpretable con las características DETECTADAS."""
    partes = []
    if clase != EST_NO_EVAL:
        partes.append(clase)
    if tipo_tend == 'Creciente':
        partes.append('tendencia creciente')
    elif tipo_tend == 'Decreciente':
        partes.append('tendencia decreciente')
    if es_est == 'Sí':
        partes.append('estacional')
    if estac == 'Estacionaria':
        partes.append('estacionaria')
    elif estac == 'No estacionaria':
        partes.append('no estacionaria')

    texto = ' + '.join(partes)
    if texto:
        texto = texto[0].upper() + texto[1:]

    # "No detectada" solo se afirma cuando la dimensión SÍ pudo evaluarse
    if tipo_tend == 'No significativa' and es_est == 'No':
        texto += ' (sin tendencia ni estacionalidad detectadas)'

    no_eval = [nombre for nombre, v in (
        ('clase de demanda', clase), ('tendencia', tipo_tend),
        ('estacionalidad', es_est), ('estacionariedad', estac)) if v == EST_NO_EVAL]
    incon = [nombre for nombre, v in (
        ('tendencia', tipo_tend), ('estacionalidad', es_est),
        ('estacionariedad', estac)) if v == EST_INCONCLUSO]
    if no_eval:
        texto += ' [no evaluable: ' + ', '.join(no_eval) + ']'
    if incon:
        texto += ' [inconcluso: ' + ', '.join(incon) + ']'
    return texto.strip()


def _caracterizar_sku(grupo, col_fecha, col_unidades, alfa, adi_umbral,
                      cv2_umbral, cambio_rel_min, umbral_estac,
                      min_sem_estac, min_sem_tend, min_sem_estacionariedad,
                      min_positivas, periodos_n=PERIODOS_N,
                      tol_n=TOL_PERIODO_N, min_ciclos_n=MIN_CICLOS_N):
    notas = []
    out = {
        'ADI': np.nan, 'CV2_demanda': np.nan, 'Clase_Demanda': EST_NO_EVAL,
        'Tipo_Tendencia': EST_NO_EVAL, 'Cambio_relativo': np.nan,
        'Tendencia_p_valor': np.nan, 'Tendencia_p_valor_MK': np.nan,
        'Tendencia_rho1': np.nan,
        'Es_Estacional': EST_NO_EVAL, 'Estacionalidad_STL': np.nan,
        'Periodo_N': np.nan, 'Periodo_N_ACF': np.nan,
        'Periodo_N_estado': EST_NO_EVAL,
        'Estacionariedad': EST_NO_EVAL, 'ADF_p_valor': np.nan,
        'KPSS_p_valor': np.nan, 'N_semanas': 0, 'Semanas_faltantes': np.nan,
        'Comportamiento': '', 'Notas_evaluacion': ''
    }

    # ADI con exactamente la misma fórmula de calcular_cv_normalizado
    y_raw = grupo.sort_values(col_fecha, kind='mergesort')[col_unidades].values.astype(float)
    n_pos_raw = int((y_raw > 0).sum())
    if len(y_raw) > 0 and n_pos_raw > 0:
        out['ADI'] = len(y_raw) / n_pos_raw

    serie = _preparar_serie_semanal(grupo, col_fecha, col_unidades)
    if serie is None:
        out['Comportamiento'] = 'Sin datos [no evaluable: todas las dimensiones]'
        out['Notas_evaluacion'] = 'Sin observaciones válidas'
        return out

    y_obs, x_obs, grid = serie['y_obs'], serie['x_obs'], serie['grid']
    n_obs = len(y_obs)
    out['N_semanas'] = n_obs
    out['Semanas_faltantes'] = serie['n_faltantes']
    if serie['n_faltantes'] and serie['n_faltantes'] > 0:
        notas.append(f"{serie['n_faltantes']} semana(s) sin dato (no se tratan como demanda 0)")
    if grid is None:
        notas.append('fechas no alineadas a semanas de 7 días')

    positivas = y_obs[y_obs > 0]
    n_pos = len(positivas)

    # ---- Sin demanda positiva: nada es evaluable -------------------------
    if n_pos == 0:
        out['Comportamiento'] = 'Sin demanda positiva [no evaluable: todas las dimensiones]'
        out['Notas_evaluacion'] = '; '.join(notas + ['Sin demanda positiva'])
        return out

    constante = bool(np.ptp(y_obs) == 0)
    if constante:
        notas.append('Serie constante')

    # ---- Intermitencia y variabilidad: Clase ADI-CV² ---------------------
    if n_pos >= 2:
        media_pos = positivas.mean()
        cv2 = float((positivas.std(ddof=1) / media_pos) ** 2)
        out['CV2_demanda'] = cv2
        intermitente = out['ADI'] >= adi_umbral
        variable = cv2 >= cv2_umbral
        if not intermitente and not variable:
            out['Clase_Demanda'] = 'Suave'
        elif not intermitente and variable:
            out['Clase_Demanda'] = 'Errática'
        elif intermitente and not variable:
            out['Clase_Demanda'] = 'Intermitente'
        else:
            out['Clase_Demanda'] = 'Irregular (lumpy)'
    else:
        notas.append('Clase_Demanda: menos de 2 demandas positivas (CV² no definido)')

    # ---- Tendencia: Mann-Kendall + cambio relativo -----------------------
    if constante:
        pass  # ya anotado
    elif n_pos < min_positivas:
        notas.append(f'Tendencia: menos de {min_positivas} demandas positivas')
    elif n_obs < min_sem_tend:
        notas.append(f'Tendencia: menos de {min_sem_tend} observaciones')
    else:
        mk = _mann_kendall(y_obs, x_obs)
        if mk is None:
            notas.append('Tendencia: prueba no definida')
        else:
            media = y_obs.mean()
            cambio = mk['pendiente'] * (x_obs[-1] - x_obs[0]) / media
            out['Cambio_relativo'] = float(cambio)
            out['Tendencia_p_valor_MK'] = mk['p_mk']
            out['Tendencia_p_valor'] = mk['p']
            out['Tendencia_rho1'] = mk['rho1']
            magnitud = abs(cambio) >= cambio_rel_min
            if mk['p_mk'] < alfa and magnitud and mk['p'] >= alfa:
                # Significativa solo si se ignora la autocorrelación
                out['Tipo_Tendencia'] = EST_INCONCLUSO
                notas.append('Tendencia: significativa solo sin corregir autocorrelación')
            elif mk['p'] < alfa and magnitud:
                if np.sign(mk['S']) == np.sign(cambio):
                    out['Tipo_Tendencia'] = 'Creciente' if cambio > 0 else 'Decreciente'
                else:
                    out['Tipo_Tendencia'] = EST_INCONCLUSO
                    notas.append('Tendencia: Kendall y pendiente de signo contrario')
            else:
                out['Tipo_Tendencia'] = 'No significativa'

    # ---- Estacionalidad: STL robusto -------------------------------------
    if constante:
        pass
    elif n_pos < min_positivas:
        notas.append(f'Estacionalidad: menos de {min_positivas} demandas positivas')
    elif n_obs < min_sem_estac:
        notas.append(f'Estacionalidad: menos de {min_sem_estac} semanas de historia')
    elif grid is None or serie['n_faltantes'] > 0:
        notas.append('Estacionalidad: requiere semanas consecutivas sin huecos')
    else:
        try:
            fs = _fuerza_estacional_stl(grid)
            if np.isnan(fs):
                out['Es_Estacional'] = EST_INCONCLUSO
                notas.append('Estacionalidad: fuerza no definida')
            else:
                out['Estacionalidad_STL'] = fs
                out['Es_Estacional'] = 'Sí' if fs >= umbral_estac else 'No'
        except Exception as exc:
            out['Es_Estacional'] = EST_INCONCLUSO
            notas.append(f'Estacionalidad: falló STL ({type(exc).__name__})')

    # ---- [NUEVO] Periodo estacional N: ACF sobre la serie sin tendencia ----
    if constante:
        pass
    elif n_pos < min_positivas:
        notas.append(f'Periodo_N: menos de {min_positivas} demandas positivas')
    elif grid is None or serie['n_faltantes'] > 0:
        notas.append('Periodo_N: requiere semanas consecutivas sin huecos')
    else:
        try:
            det = _detectar_periodo_n(
                grid,
                periodos=periodos_n,
                tol=tol_n,
                min_ciclos=min_ciclos_n
            )
            out['Periodo_N_estado'] = det['estado']
            out['Periodo_N'] = det['n']
            out['Periodo_N_ACF'] = det['acf']

            if det['estado'] == EST_NO_EVAL:
                notas.append(
                    f'Periodo_N: menos de {min_ciclos_n} ciclos completos '
                    f'para todos los periodos candidatos'
                )
            elif det['no_evaluables']:
                notas.append(
                    f"Periodo_N: periodos no evaluables por historia corta: "
                    f"{det['no_evaluables']}"
                )
        except Exception as exc:
            out['Periodo_N_estado'] = EST_INCONCLUSO
            out['Periodo_N'] = np.nan
            notas.append(f'Periodo_N: falló el cálculo ({type(exc).__name__})')

    # ---- Estacionariedad: ADF + KPSS --------------------------------------
    if constante:
        pass
    elif n_pos < min_positivas:
        notas.append(f'Estacionariedad: menos de {min_positivas} demandas positivas')
    elif n_obs < min_sem_estacionariedad:
        notas.append(f'Estacionariedad: menos de {min_sem_estacionariedad} semanas de historia')
    elif grid is None or serie['n_faltantes'] > 0:
        notas.append('Estacionariedad: requiere semanas consecutivas sin huecos')
    else:
        try:
            estado, adf_p, kpss_p = _pruebas_estacionariedad(grid, alfa)
            out['Estacionariedad'] = estado
            out['ADF_p_valor'] = adf_p
            out['KPSS_p_valor'] = kpss_p
        except Exception as exc:
            out['Estacionariedad'] = EST_INCONCLUSO
            notas.append(f'Estacionariedad: fallaron las pruebas ({type(exc).__name__})')

    out['Comportamiento'] = _describir_comportamiento(
        out['Clase_Demanda'], out['Tipo_Tendencia'],
        out['Es_Estacional'], out['Estacionariedad'])
    if constante:
        out['Comportamiento'] = out['Comportamiento'].replace(
            ' [no evaluable', ' (serie constante) [no evaluable', 1) \
            if ' [no evaluable' in out['Comportamiento'] \
            else out['Comportamiento'] + ' (serie constante)'
    out['Notas_evaluacion'] = '; '.join(notas)
    return out


def clasificar_comportamiento(df_series, col_fecha='Fecha', col_codigo='Código',
                              col_unidades='Unidades', alfa=ALFA,
                              adi_umbral=ADI_UMBRAL, cv2_umbral=CV2_UMBRAL,
                              cambio_rel_min=CAMBIO_REL_MIN,
                              umbral_estacionalidad=UMBRAL_FUERZA_ESTAC,
                              min_semanas_estacionalidad=MIN_SEMANAS_ESTAC,
                              min_semanas_tendencia=MIN_SEMANAS_TENDENCIA,
                              min_semanas_estacionariedad=MIN_SEMANAS_ESTACIONARIEDAD,
                              min_demandas_positivas=MIN_DEMANDAS_POSITIVAS,
                              periodos_n=PERIODOS_N,
                              tol_periodo_n=TOL_PERIODO_N,
                              min_ciclos_n=MIN_CICLOS_N):
    """
    Caracteriza el comportamiento de la demanda semanal de cada SKU.
    Retorna un DataFrame con una fila por producto. Cada dimensión se evalúa
    de forma independiente (la intermitencia no impide evaluar tendencia ni
    estacionalidad):

      Clase_Demanda    : Suave / Errática / Intermitente / Irregular (lumpy)
                         (ADI >= 1,32 y CV² >= 0,49 sobre demandas positivas)
      Tipo_Tendencia   : Creciente / Decreciente / No significativa /
                         Inconcluso / No evaluable
      Es_Estacional    : Sí / No / Inconcluso / No evaluable
      Periodo_N        : cada cuántas semanas se repite el patrón estacional
                         (0 = no detectado; vacío = no evaluable/inconcluso)
      Periodo_N_estado : Detectada / No detectada / Inconcluso / No evaluable
      Estacionariedad  : Estacionaria / No estacionaria / Inconcluso /
                         No evaluable
      Comportamiento   : texto interpretable (p. ej. 'Intermitente + tendencia
                         creciente', 'Estacional + tendencia decreciente')

    'No evaluable' significa que la información no alcanza (serie corta,
    constante, sin demanda positiva, semanas faltantes); nunca equivale a
    'No detectada'.
    """
    filas = []
    for codigo, grupo in df_series.groupby(col_codigo, sort=True):
        fila = _caracterizar_sku(
            grupo, col_fecha, col_unidades, alfa, adi_umbral, cv2_umbral,
            cambio_rel_min, umbral_estacionalidad, min_semanas_estacionalidad,
            min_semanas_tendencia, min_semanas_estacionariedad,
            min_demandas_positivas, periodos_n, tol_periodo_n, min_ciclos_n)
        fila[col_codigo] = codigo
        filas.append(fila)

    columnas = ([col_codigo, 'Clase_Demanda', 'CV2_demanda', 'ADI',
                 'Tipo_Tendencia', 'Cambio_relativo', 'Tendencia_p_valor',
                 'Tendencia_p_valor_MK', 'Tendencia_rho1',
                 'Es_Estacional', 'Estacionalidad_STL',
                 'Periodo_N', 'Periodo_N_ACF', 'Periodo_N_estado',
                 'Estacionariedad', 'ADF_p_valor', 'KPSS_p_valor',
                 'N_semanas', 'Semanas_faltantes',
                 'Comportamiento', 'Notas_evaluacion'])
    if not filas:
        return pd.DataFrame(columns=columnas)
    return pd.DataFrame(filas)[columnas]


# -----------------------------------------------------------------------------
# 3. Función principal que agrega features al DataFrame original
# -----------------------------------------------------------------------------

def agregar_features(df_base, calcular_estacionalidad_flag=False, caracterizar=True):
    """
    Toma el DataFrame base (serie semanal) y retorna el mismo DataFrame
    con columnas adicionales de features por producto.

    caracterizar (nuevo, opcional): agrega las columnas de
    clasificar_comportamiento() (Clase_Demanda, tendencia, estacionalidad STL,
    Periodo_N, estacionariedad, Comportamiento, ...). calcular_estacionalidad_flag
    sigue controlando únicamente la columna original Estacionalidad_fuerza.
    """
    # 1. Calcular métricas temporales por producto
    df_cv = calcular_cv_normalizado(
        df_base,
        col_fecha='Fecha',
        col_codigo='Código',
        col_unidades='Unidades'
    )

    # 2. (Opcional) Estacionalidad
    if calcular_estacionalidad_flag:
        df_est = calcular_estacionalidad(
            df_base,
            col_fecha='Fecha',
            col_codigo='Código',
            col_unidades='Unidades'
        )
        df_metricas = df_cv.merge(df_est, on='Código', how='left')
    else:
        df_metricas = df_cv

    # 2b. [NUEVO] Caracterización independiente del comportamiento
    if caracterizar:
        df_car = clasificar_comportamiento(
            df_base, col_fecha='Fecha', col_codigo='Código',
            col_unidades='Unidades')
        # ADI ya viene de calcular_cv_normalizado (misma fórmula); no se duplica
        df_car = df_car.drop(columns=['ADI'])
        df_metricas = df_metricas.merge(df_car, on='Código', how='left')
        n_huecos = int((df_car['Semanas_faltantes'].fillna(0) > 0).sum())
        if n_huecos:
            print(f"⚠️ {n_huecos} SKU(s) con semanas faltantes: para ellos la "
                  f"estacionalidad, el Periodo_N y la estacionariedad quedan "
                  f"'No evaluable' (las semanas faltantes no se asumen como "
                  f"demanda 0).")

        # [NUEVO] Resumen de Periodo_N
        print("📐 Periodo_N -- estado por SKU:")
        for estado, cantidad in df_car['Periodo_N_estado'].value_counts().items():
            print(f"   {estado}: {cantidad:,} SKU")
        detectados = (
            df_car.loc[df_car['Periodo_N_estado'] == EST_DETECTADA, 'Periodo_N']
            .value_counts()
            .sort_index()
        )
        if len(detectados):
            print("   Periodos detectados (semanas):",
                  {int(k): int(v) for k, v in detectados.items()})

    # 3. Rellenar NaN residuales. Después del cambio en calcular_cv_normalizado
    # esto ya casi nunca debería activarse para Demanda_Promedio (solo si un
    # SKU llega aquí con CERO filas, lo cual no debería pasar tras el pipeline
    # de lectura) -- se deja como salvaguarda, no como comportamiento esperado.
    df_metricas['CV_Normalizado'] = df_metricas['CV_Normalizado'].fillna(0)
    df_metricas['Tendencia_pendiente'] = df_metricas['Tendencia_pendiente'].fillna(0)
    df_metricas['Demanda_std_residuos'] = df_metricas['Demanda_std_residuos'].fillna(0)
    # ADI (ver calcular_cv_normalizado) solo sale NaN si el SKU nunca tuvo
    # ninguna semana con demanda real -- no se rellena con 0 ni con ningún
    # otro valor inventado (0 significaría "demanda todas las semanas", que
    # es literalmente lo opuesto de lo que implica no tener ninguna venta).
    # Se deja NaN, visible, para no fabricar una intermitencia falsa.
    if df_metricas['ADI'].isna().any():
        n_sin_adi = df_metricas['ADI'].isna().sum()
        print(f"⚠️ {n_sin_adi} SKU(s) sin ninguna semana de demanda real -- "
              f"ADI queda en NaN para esos casos (no se rellena, para no "
              f"inventar un valor de intermitencia).")
    if df_metricas['Demanda_Promedio'].isna().any():
        n_afectados = df_metricas['Demanda_Promedio'].isna().sum()
        print(f"⚠️ {n_afectados} SKU(s) llegaron sin ninguna fila a calcular_cv_normalizado "
              f"-- revisa el pipeline de lectura, no debería ocurrir. Se dejan como NaN "
              f"(no se rellenan con 0) para que sean visibles y no se confundan con demanda real cero.")
    if 'Estacionalidad_fuerza' in df_metricas.columns:
        df_metricas['Estacionalidad_fuerza'] = df_metricas['Estacionalidad_fuerza'].fillna(0)

    # 4. Unir las métricas al DataFrame original (merge por Código)
    columnas_features = ['Código', 'Demanda_Promedio', 'CV_Normalizado',
                         'Tendencia_pendiente', 'Demanda_std_residuos', 'ADI']
    if 'Estacionalidad_fuerza' in df_metricas.columns:
        columnas_features.append('Estacionalidad_fuerza')
    if caracterizar:
        columnas_features.extend(COLUMNAS_CARACTERIZACION)

    df_features = df_metricas[columnas_features]
    df_resultado = df_base.merge(df_features, on='Código', how='left')

    return df_resultado


# -----------------------------------------------------------------------------
# 4. Función para exportar el DataFrame completo con features
# -----------------------------------------------------------------------------

# Descripción de las columnas de features (por nombre)
DESCRIPCION_FEATURES = {
    'Demanda_Promedio': 'Demanda promedio semanal (unidades)',
    'CV_Normalizado': 'Coeficiente de variación normalizado (sin tendencia)',
    'Tendencia_pendiente': 'Pendiente de la tendencia lineal (crecimiento semanal)',
    'Demanda_std_residuos': 'Desviación estándar de los residuos (ruido)',
    'ADI': 'ADI: semanas promedio entre una venta y la siguiente (intermitencia)',
    'Estacionalidad_fuerza': 'Fuerza de estacionalidad (proporción de varianza explicada) - opcional',
    'Clase_Demanda': 'Clasificación ADI-CV²: Suave (ADI<1,32 y CV²<0,49), Errática (ADI<1,32 y CV²>=0,49), '
                     'Intermitente (ADI>=1,32 y CV²<0,49), Irregular (lumpy) (ADI>=1,32 y CV²>=0,49); '
                     '"No evaluable" si hay menos de 2 demandas positivas. Independiente de tendencia y estacionalidad',
    'CV2_demanda': 'CV² de las demandas positivas: (desv. estándar muestral / media)² solo sobre semanas con demanda > 0',
    'Tipo_Tendencia': 'Tendencia: Creciente / Decreciente (Mann-Kendall p<0,05 y |cambio relativo|>=20 %), '
                      'No significativa, Inconcluso (p sensible a la autocorrelación o signos contradictorios), '
                      'No evaluable (historia insuficiente, serie constante o sin demanda)',
    'Cambio_relativo': 'Cambio relativo de la recta ajustada entre la primera y la última semana, '
                       'dividido por la demanda promedio (0,25 = +25 %)',
    'Tendencia_p_valor': 'p-valor de Mann-Kendall usado en la decisión (con corrección por autocorrelación '
                         'de orden 1 cuando es positiva y significativa)',
    'Tendencia_p_valor_MK': 'p-valor de Mann-Kendall sin corrección por autocorrelación',
    'Tendencia_rho1': 'Autocorrelación de orden 1 de los residuos de la recta (diagnóstico de la prueba de tendencia)',
    'Es_Estacional': 'Estacionalidad: Sí (fuerza STL>=0,50) / No / Inconcluso / No evaluable '
                     '(menos de 104 semanas, semanas faltantes, serie constante o sin demanda)',
    'Estacionalidad_STL': 'Fuerza estacional con STL robusto, periodo 52: max(0, 1 - Var(resto)/Var(estacional+resto)); '
                          'vacío si no evaluable',
    'Periodo_N': 'Periodo estacional N en SEMANAS (cada cuántas semanas se repite el patrón), por ACF de la serie '
                 'sin tendencia sobre los periodos candidatos (4, 13, 26, 52 por defecto). 0 = se evaluó y no se '
                 'detectó estacionalidad; VACÍO = no evaluable o inconcluso (no equivale a 0)',
    'Periodo_N_ACF': 'Autocorrelación de la serie sin tendencia en el lag N detectado (vacío si no se detectó N)',
    'Periodo_N_estado': 'Estado del cálculo de N: Detectada / No detectada / Inconcluso / No evaluable '
                        '(menos de 3 ciclos completos para todos los candidatos, semanas faltantes, serie constante '
                        'o sin demanda positiva suficiente)',
    'Estacionariedad': 'Estacionariedad (ADF + KPSS, alfa 0,05, constante): Estacionaria / No estacionaria / '
                       'Inconcluso (resultados contradictorios o sin potencia) / No evaluable (<52 semanas o huecos)',
    'ADF_p_valor': 'p-valor de ADF (H0: raíz unitaria; constante; rezagos por AIC)',
    'KPSS_p_valor': 'p-valor de KPSS (H0: estacionaria; constante; nlags auto); statsmodels lo trunca entre 0,01 y 0,10',
    'N_semanas': 'Número de semanas con dato válido del SKU',
    'Semanas_faltantes': 'Semanas sin dato entre la primera y la última observación (no se tratan como demanda 0)',
    'Comportamiento': 'Descripción interpretable de las características detectadas, p. ej. '
                      '"Intermitente + tendencia creciente"; lista aparte lo no evaluable o inconcluso',
    'Notas_evaluacion': 'Motivos por los que alguna característica no pudo evaluarse o quedó inconclusa',
}

# Descripciones posicionales de las columnas base (orden original del archivo)
_DESCRIPCION_BASE = [
    'Identificador único del producto',
    'Fecha de la semana (inicio de semana)',
    'Subtotal (ventas en moneda)',
    'Unidades vendidas en esa semana',
    'Volumen o tamaño del producto',
    'Lead Time en semanas desde pedido hasta recepción',
    'Familia o categoría del producto',
    'País de origen del producto',
    'Costo unitario en moneda local',
    'Nombre del producto',
    'Proveedor',
]


def exportar_df_features(df_con_features, ruta_salida='df_featuring.xlsx'):
    """
    Guarda el DataFrame completo con todas las filas y las nuevas columnas
    de features en un archivo Excel.
    """
    with pd.ExcelWriter(ruta_salida, engine='openpyxl') as writer:
        df_con_features.to_excel(writer, sheet_name='Datos_con_features', index=False)

        # Hoja de descripción de columnas: las columnas de features se
        # describen por nombre; las demás, por posición (como antes).
        columnas = list(df_con_features.columns)
        columnas_base = [c for c in columnas if c not in DESCRIPCION_FEATURES]
        mapa_base = {c: (_DESCRIPCION_BASE[i] if i < len(_DESCRIPCION_BASE) else '')
                     for i, c in enumerate(columnas_base)}
        descripciones = [DESCRIPCION_FEATURES.get(c, mapa_base.get(c, '')) for c in columnas]

        descripcion = pd.DataFrame({
            'Columna': columnas,
            'Tipo': df_con_features.dtypes.astype(str).values,
            'Descripción': descripciones
        })
        descripcion.to_excel(writer, sheet_name='Descripción', index=False)

    print(f"✅ Archivo guardado: {ruta_salida} con {len(df_con_features)} filas y {len(df_con_features.columns)} columnas.")


# -----------------------------------------------------------------------------
# 5. Función principal de ejecución (con parámetro de semilla)
# -----------------------------------------------------------------------------

def ejecutar_features(ruta_excel=None, df_base=None, calcular_estacionalidad=False,
                      ruta_salida='df_featuring.xlsx', semilla=SEMILLA_GLOBAL,
                      caracterizar=True):
    """
    Carga los datos desde un archivo Excel o usa un DataFrame en memoria,
    calcula features y guarda el resultado completo en un Excel.

    Parámetros:
    -----------
    ruta_excel : str, opcional
        Ruta al archivo Excel con los datos de df_base.
    df_base : pd.DataFrame, opcional
        DataFrame ya cargado (si no se proporciona ruta).
    calcular_estacionalidad : bool, default=False
        Activar cálculo de la columna original Estacionalidad_fuerza (más lento).
    ruta_salida : str, default='df_featuring.xlsx'
        Archivo de salida con todas las filas y features.
    semilla : int, default=SEMILLA_GLOBAL
        Semilla para garantizar reproducibilidad en cualquier operación aleatoria
        (simulación, futuros módulos de imputación o clustering).
    caracterizar : bool, default=True
        Agrega la caracterización de la demanda (clasificar_comportamiento),
        que incluye el Periodo_N por SKU.
    """
    # Fijar la semilla localmente para esta ejecución
    random.seed(semilla)
    np.random.seed(semilla)

    # Cargar datos
    if ruta_excel is not None:
        print(f"Cargando datos desde {ruta_excel}...")
        df_base = pd.read_excel(ruta_excel, engine='openpyxl')
        df_base['Fecha'] = pd.to_datetime(df_base['Fecha'])
        df_base['Unidades'] = pd.to_numeric(df_base['Unidades'], errors='coerce')
        df_base['Código'] = df_base['Código'].astype(str).str.strip()
    elif df_base is not None:
        print("Usando DataFrame proporcionado en memoria.")
        # Asegurar tipos
        df_base = df_base.copy()
        df_base['Fecha'] = pd.to_datetime(df_base['Fecha'])
        df_base['Unidades'] = pd.to_numeric(df_base['Unidades'], errors='coerce')
        df_base['Código'] = df_base['Código'].astype(str).str.strip()
    else:
        raise ValueError("Debe proporcionar ruta_excel o df_base.")

    # Calcular features y agregar al DataFrame original
    df_con_features = agregar_features(df_base, calcular_estacionalidad, caracterizar)
    print(f"Features calculados para {df_con_features['Código'].nunique()} productos.")

    # Exportar completo
    exportar_df_features(df_con_features, ruta_salida)

    return df_con_features


# =============================================================================
# EJEMPLO DE USO (ejecución directa)
# =============================================================================
if __name__ == "__main__":
    # Si tienes el archivo 'df_base.xlsx' generado por el pipeline principal
    # ejecuta:
    # df_featuring = ejecutar_features(ruta_excel='df_base.xlsx', ruta_salida='df_featuring.xlsx')

    # Si prefieres pasar el DataFrame directamente desde el entorno:
    # df_featuring = ejecutar_features(df_base=df_base, ruta_salida='df_featuring.xlsx')

    # Simulación para pruebas (si no existe el archivo)
    import os
    if os.path.exists('df_base.xlsx'):
        # Usamos la semilla por defecto (42) para que los resultados sean siempre iguales
        df_featuring = ejecutar_features(ruta_excel='df_base.xlsx', ruta_salida='df_featuring.xlsx')
    else:
        print("No se encontró 'df_base.xlsx'. Generando datos simulados para prueba...")
        # También usamos la semilla global para que los datos simulados sean siempre los mismos
        np.random.seed(SEMILLA_GLOBAL)
        random.seed(SEMILLA_GLOBAL)

        fechas = pd.date_range('2020-01-01', periods=100, freq='W-MON')
        codigos = [f'PROD_{i}' for i in range(10)]
        datos = []
        for cod in codigos:
            base = np.random.randint(50, 150)
            tendencia = np.linspace(0, 30, 100)
            ruido = np.random.normal(0, 10, 100)
            unidades = base + tendencia + ruido
            unidades = np.maximum(unidades, 0)
            for i, fecha in enumerate(fechas):
                datos.append({
                    'Código': cod,
                    'Fecha': fecha,
                    'Unidades': unidades[i],
                    'Volumen': np.random.choice([100, 200, 300]),
                    'Lead Time (semanas)': np.random.choice([2, 4, 6, 8]),
                    'Denominacion familia': np.random.choice(['TUBERIA', 'ACCESORIOS', 'VALVULAS']),
                    'Pais': np.random.choice(['CHINA', 'ESTADOS UNIDOS', 'CANADÁ']),
                    'Costo Unitario': np.random.uniform(10, 100),
                    'Subtotal': unidades[i] * np.random.uniform(5, 15)
                })
        df_base = pd.DataFrame(datos)
        df_featuring = ejecutar_features(df_base=df_base, ruta_salida='df_featuring_simulado.xlsx')
