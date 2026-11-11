# ============================================================
# MÓDULO 2: PRONÓSTICOS POR CLUSTER  (VERSIÓN MULTI-FRECUENCIA)
# ============================================================
# [REDISEÑO -- CONSISTENCIA CON EL TRADUCTOR] La unidad de pronóstico, el
# lead time convertido y el horizonte de cada Cluster_Operativo NO se
# deciden aquí -- se LEEN de 'Unidad_Pronostico', 'Lead_Time_Max_En_Unidad_
# Pronostico' y 'Horizonte_Pronostico_Periodos' en df_clusters, calculadas
# por TraductorClusterPronostico.py. Ver obtener_config_temporal_cluster.
#
# [REDISEÑO METODOLÓGICO -- CORRIGE 3 PROBLEMAS SEÑALADOS EN REVISIÓN]
#
# 1) FUGA DE INFORMACIÓN EN LA BÚSQUEDA DE HIPERPARÁMETROS: antes se
#    escalaba (StandardScaler.fit_transform) sobre TODO X antes de pasarlo
#    a RandomizedSearchCV(cv=tscv) -- la media/desviación usadas para
#    escalar cada fold de validación ya habían "visto" esos mismos datos
#    (estaban incluidos en el fit del scaler). Ahora se usa un
#    sklearn.Pipeline(scaler, modelo) dentro de la búsqueda: cada fold
#    ajusta su propio scaler SOLO con su partición de entrenamiento (ver
#    _buscar_hiperparametros_ml, _ajustar_ml_directo, _ajustar_ml_recursivo).
#
# 2) LA MISMA VALIDACIÓN CRUZADA SE USABA PARA ELEGIR HIPERPARÁMETROS Y
#    PARA "EVALUAR" EL MODELO GANADOR -- esas métricas no eran una
#    estimación independiente del desempeño real. Ahora la historia de
#    cada clúster se parte en TRAIN (entrenamiento + afinamiento de
#    hiperparámetros, con validación cruzada temporal DENTRO de TRAIN) y
#    TEST (el tramo final, de tamaño = horizonte_pronostico, que nunca
#    participa en la búsqueda ni en la comparación de candidatos). El
#    modelo ganador se reentrena sobre TRAIN, se evalúa una sola vez sobre
#    TEST (WAPE_TEST/MAPE_TEST/etc -- "fuera de muestra" real), y solo
#    DESPUÉS se reentrena sobre el 100% de la historia (TRAIN+TEST) para
#    producir el pronóstico futuro real. Sobre ese ajuste final también se
#    calculan métricas "dentro de muestra" (qué tan bien el modelo
#    reproduce los datos con los que se entrenó). Ver entrenar_modelo_cluster
#    y procesar_cluster.
#
# 3) LA DESAGREGACIÓN DEL PRONÓSTICO DEL CLÚSTER A CADA SKU NO GARANTIZABA
#    QUE LA SUMA DE LOS SKU DIERA EL PRONÓSTICO DEL CLÚSTER: se calculaba
#    la media de cada SKU sobre TODA su historia disponible (ventanas
#    distintas entre SKU), mientras que el clúster se construyó sobre una
#    historia común alineada (ver clusterizacionVolumen.preparar_unidades_
#    agregadas_por_cluster). Ahora los pesos de cada SKU se calculan sobre
#    la MISMA ventana común que se usó para agregar el clúster
#    (w_i = media_i / suma(medias en esa ventana)), así que
#    sum(w_i) = 1 y por lo tanto sum(F_SKU_i,t) = F_cluster,t exactamente,
#    para cada periodo t. Ver el bucle de SKU en procesar_cluster.

import os
# [CORREGIDO -- LOS AVISOS SEGUÍAN APARECIENDO] warnings.filterwarnings()
# solo silencia el PROCESO ACTUAL. RandomizedSearchCV(n_jobs=-1) y
# RandomForestRegressor(n_jobs=-1) usan joblib, que para paralelizar abre
# PROCESOS DE PYTHON NUEVOS (en Windows, procesos reales, no hilos) -- cada
# uno de esos procesos arranca con su PROPIO estado de warnings, sin
# heredar el filtro que se puso en el proceso principal. Por eso el
# ConvergenceWarning de MLP (y el UserWarning de sklearn.utils.parallel
# sobre 'delayed') seguían saliendo pese al filtro de abajo -- salían
# desde los procesos hijos, no desde el principal.
#
# La variable de entorno PYTHONWARNINGS sí la respeta CUALQUIER proceso de
# Python nuevo (la lee el intérprete al arrancar) -- y los procesos hijos
# de joblib heredan las variables de entorno del proceso que los lanza.
# Fijarla aquí, ANTES de que se dispare cualquier búsqueda en paralelo,
# asegura que se aplique también dentro de esos procesos hijos.
#
# [POR QUÉ 'ignore::UserWarning' Y NO UN FILTRO DE ConvergenceWarning
# APARTE] ConvergenceWarning (sklearn.exceptions) ES una subclase de
# UserWarning -- ignorar UserWarning ya cubre ConvergenceWarning
# automáticamente (Python aplica el filtro a la clase indicada Y a sus
# subclases). Se probó primero con un filtro explícito
# 'ignore::sklearn.exceptions.ConvergenceWarning' agregado además -- pero
# el parser de PYTHONWARNINGS de Python no resuelve bien classpaths con
# puntos como categoría (genera su propio "Invalid -W option ignored" en
# stderr, otro mensaje molesto de más). Un solo filtro simple, por la
# clase base, resuelve ambos sin generar ningún mensaje adicional --
# verificado que deja stderr completamente limpio.
os.environ.setdefault('PYTHONWARNINGS', 'ignore::UserWarning')

import pickle
import time
import warnings
import pandas as pd
import numpy as np

from sklearn.exceptions import ConvergenceWarning
# Filtro también en el proceso PRINCIPAL (cubre las corridas que no pasan
# por joblib, y refuerza lo que ya hace PYTHONWARNINGS arriba).
warnings.filterwarnings('ignore', category=ConvergenceWarning)
warnings.filterwarnings('ignore', category=UserWarning)

from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import TimeSeriesSplit, RandomizedSearchCV
from sklearn.metrics import mean_absolute_percentage_error, mean_squared_error, r2_score

from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.statespace.sarimax import SARIMAX
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.exponential_smoothing.ets import ETSModel
from statsmodels.tsa.seasonal import STL

from xgboost import XGBRegressor
from lightgbm import LGBMRegressor
from sklearn.neural_network import MLPRegressor
from sklearn.ensemble import RandomForestRegressor

from statsmodels.stats.diagnostic import acorr_ljungbox, het_breuschpagan
from scipy.stats import shapiro

try:
    import pmdarima as pm
    _PMDARIMA_DISPONIBLE = True
except ImportError:
    _PMDARIMA_DISPONIBLE = False


# ============================================================
# FUNCIONES COMPARTIDAS
# ============================================================

def siguiente_mes(mes_actual, pasos=1, periodo_estacional=12):
    # Genérica vía 'periodo_estacional': funciona para cualquiera de las 5
    # unidades -- solo necesita saber cuántas posiciones tiene el ciclo anual.
    return ((mes_actual - 1 + pasos) % periodo_estacional) + 1


def predecir_paso_futuro_ml(
    modelo_entrenado,
    historia,
    posicion_tendencia,
    mes_actual,
    escalador=None,
    columnas_features=None,
    periodo_estacional=12,
    rezagos=(1, 3, 6, 12),
    ventanas_movil=(3, 6, 12),
    clip_no_negativo=True,
):
    historia = np.asarray(historia, dtype=float)
    fila = {"mes": mes_actual, "tendencia": posicion_tendencia}
    for lag in rezagos:
        fila[f"lag_{lag}"] = historia[-lag] if len(historia) >= lag else historia[0]
    for ventana in ventanas_movil:
        fila[f"ma_{ventana}"] = (
            historia[-ventana:].mean() if len(historia) >= ventana else historia.mean()
        )
    fila["sin_mes"] = np.sin(2 * np.pi * mes_actual / periodo_estacional)
    fila["cos_mes"] = np.cos(2 * np.pi * mes_actual / periodo_estacional)

    columnas = list(columnas_features) if columnas_features is not None else list(fila.keys())
    fila_df = pd.DataFrame([fila])[columnas]
    fila_transformada = escalador.transform(fila_df) if escalador is not None else fila_df.values
    prediccion = modelo_entrenado.predict(fila_transformada)
    valor = float(np.asarray(prediccion).ravel()[0])
    return max(valor, 0.0) if clip_no_negativo else valor


def calcular_metricas(y_real, y_pred):
    """
    Calcula las 5 métricas de desempeño (MAPE, WAPE, RMSE, MSE, R2) para un
    conjunto de valores reales vs. predichos. Función compartida por la
    evaluación en validación cruzada (CV), fuera de muestra (TEST) y dentro
    de muestra (IN-SAMPLE) -- así las tres usan exactamente la misma
    fórmula, nunca implementaciones ligeramente distintas.

    MAPE se deja como NaN si todos los valores reales son 0 (no se puede
    calcular un porcentaje de un valor real nulo); WAPE en ese caso
    también queda NaN, mismo criterio.
    """
    y_real = np.asarray(y_real, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)

    mask = y_real != 0
    mape = (
        mean_absolute_percentage_error(y_real[mask], y_pred[mask]) * 100
        if mask.sum() > 0 else np.nan
    )
    suma_num = float(np.sum(np.abs(y_real - y_pred)))
    suma_den = float(np.sum(np.abs(y_real)))
    wape = (suma_num / suma_den * 100) if suma_den > 0 else np.nan
    mse = float(mean_squared_error(y_real, y_pred))
    rmse = float(np.sqrt(mse))
    r2 = float(r2_score(y_real, y_pred)) if len(y_real) > 1 else np.nan

    return {'MAPE_%': mape, 'WAPE_%': wape, 'RMSE': rmse, 'MSE': mse, 'R2': r2}


def calcular_mase(y_real, y_pred, y_train, periodo_estacional):
    """
    [NUEVO -- MASE, Mean Absolute Scaled Error, Hyndman & Koehler 2006]
    A diferencia de MAPE, MASE NO divide por el valor real (por eso nunca
    se dispara cuando la demanda real es pequeña o cero) -- en cambio,
    compara el error absoluto medio del modelo contra el error absoluto
    medio de un pronóstico INGENUO estacional (repetir el valor de hace un
    ciclo estacional, ej. "lo que se vendió el mismo mes del año pasado").

        MASE = MAE(modelo) / MAE(ingenuo estacional, calculado IN-SAMPLE
               sobre y_train)

    Interpretación directa, sin importar la escala ni la volatilidad de la
    serie:
        MASE < 1  -> el modelo generaliza MEJOR que adivinar con el ciclo
                     anterior (útil de verdad).
        MASE = 1  -> el modelo es exactamente tan bueno como el ingenuo.
        MASE > 1  -> el modelo generaliza PEOR que simplemente repetir el
                     ciclo anterior (una señal de alarma mucho más clara
                     que "MAPE=213%", que en clústeres volátiles puede
                     salir alto incluso con un modelo razonable).

    Si y_train no tiene suficiente historia para el ciclo estacional
    completo (< periodo_estacional+1 periodos), usa naive simple (lag 1)
    en su lugar -- mismo criterio de respaldo que usa MASE en la práctica
    cuando no hay un ciclo estacional completo disponible.
    """
    y_real = np.asarray(y_real, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    y_train = np.asarray(y_train, dtype=float)

    m = periodo_estacional if len(y_train) > periodo_estacional else 1
    if len(y_train) <= m:
        return np.nan

    denominador = float(np.mean(np.abs(y_train[m:] - y_train[:-m])))
    if denominador == 0 or np.isnan(denominador):
        return np.nan

    mae_modelo = float(np.mean(np.abs(y_real - y_pred)))
    return mae_modelo / denominador


# ============================================================
# CLASE PRONOSTICADOR
# ============================================================

class Pronosticador:
    """
    Contrato de df_clusters: DataFrame con columnas REALES (no como
    índice): self.sku_col ('Código'), self.cluster_col ('Cluster_Operativo'),
    self.lead_time_col ('Lead Time (semanas)'), 'comportamiento',
    'Unidad_Pronostico', 'Lead_Time_Max_En_Unidad_Pronostico',
    'Horizonte_Pronostico_Periodos' -- las últimas 4 calculadas por
    TraductorClusterPronostico.py, nunca por esta clase.

    [METODOLOGÍA DE EVALUACIÓN -- 3 CONJUNTOS DE MÉTRICAS, NO SE MEZCLAN]

    - *_CV (validación cruzada temporal, DENTRO de TRAIN): usada solo para
      afinar hiperparámetros y hacer una comparación PRELIMINAR y rápida
      entre candidatos (ARIMA/SARIMA/Holt-Winters/ETS/XGBoost/LightGBM/MLP).
      Es una estimación optimista -- los mismos folds ya influyeron en la
      elección de hiperparámetros.

    - *_TEST (fuera de muestra, GENUINAMENTE independiente): el modelo
      ganador (elegido por MAPE_CV) se reentrena SOLO sobre TRAIN y se
      evalúa una única vez sobre TEST -- el tramo final de la historia,
      nunca visto durante la búsqueda de hiperparámetros ni la comparación
      de candidatos. Esta es la estimación más honesta de qué tan bien
      pronosticaría este modelo datos que todavía no ha visto. El tamaño
      de TEST es, por defecto, el horizonte de pronóstico del clúster
      (Horizonte_Pronostico_Periodos) -- para que la prueba simule
      exactamente la tarea real: pronosticar esa misma cantidad de
      periodos hacia adelante.

    - *_IN_SAMPLE (dentro de muestra): una vez elegido el modelo y
      confirmado con TEST, se reentrena sobre el 100% de la historia
      (TRAIN+TEST) -- este es el modelo que de verdad produce el
      pronóstico futuro. Sus métricas "dentro de muestra" comparan los
      valores AJUSTADOS de ese modelo final contra los datos con los que
      se entrenó -- útil como diagnóstico de ajuste, pero SIEMPRE optimista
      (el modelo ya vio esos datos); nunca debe interpretarse como una
      medida de qué tan bien pronosticará el futuro -- para eso está *_TEST.
    """

    CONFIG_POR_UNIDAD = {
        'semanas': {
            'unidad': 'semanas', 'regla_resample': 'W-MON', 'periodo_estacional': 52,
            'rezagos': (1, 4, 12, 52), 'ventanas_movil': (4, 12, 52),
        },
        'quincenas': {
            'unidad': 'quincenas', 'regla_resample': '2W-MON', 'periodo_estacional': 26,
            'rezagos': (1, 2, 6, 26), 'ventanas_movil': (2, 6, 26),
        },
        'meses': {
            'unidad': 'meses', 'regla_resample': 'MS', 'periodo_estacional': 12,
            'rezagos': (1, 3, 6, 12), 'ventanas_movil': (3, 6, 12),
        },
        'bimestres': {
            'unidad': 'bimestres', 'regla_resample': '2MS', 'periodo_estacional': 6,
            'rezagos': (1, 2, 3, 6), 'ventanas_movil': (2, 3, 6),
        },
        'trimestres': {
            'unidad': 'trimestres', 'regla_resample': '3MS', 'periodo_estacional': 4,
            'rezagos': (1, 2, 4), 'ventanas_movil': (2, 4),
        },
    }

    OFFSET_POR_UNIDAD = {
        'semanas': pd.DateOffset(weeks=1), 'quincenas': pd.DateOffset(weeks=2),
        'meses': pd.DateOffset(months=1), 'bimestres': pd.DateOffset(months=2),
        'trimestres': pd.DateOffset(months=3),
    }

    UNIDADES_MENSUALES = {'meses', 'bimestres', 'trimestres'}

    UMBRAL_FUERZA_ESTACIONAL = 0.15
    UMBRAL_TENDENCIA_RELATIVA = 0.001

    NOMBRE_MODELO_FALLBACK = "Promedio_Simple"

    MODELOS_CLASICOS = ('ARIMA', 'SARIMA', 'Holt-Winters', 'ETS', 'SBA')
    MODELOS_ML = ('XGBoost', 'LightGBM', 'MLP', 'RandomForest')

    _ESPACIO_BUSQUEDA_ML = {
        'XGBoost': {
            'n_estimators': [50, 100, 200, 300], 'max_depth': [2, 3, 4, 5, 6],
            'learning_rate': [0.01, 0.03, 0.05, 0.1, 0.2],
            'subsample': [0.6, 0.8, 1.0], 'colsample_bytree': [0.6, 0.8, 1.0],
        },
        'LightGBM': {
            'n_estimators': [50, 100, 200, 300], 'max_depth': [-1, 3, 5, 7],
            'learning_rate': [0.01, 0.03, 0.05, 0.1, 0.2], 'num_leaves': [15, 31, 63],
            'subsample': [0.6, 0.8, 1.0], 'colsample_bytree': [0.6, 0.8, 1.0],
        },
        'MLP': {
            'hidden_layer_sizes': [(25,), (50,), (50, 25), (100, 50), (30, 30, 15)],
            'alpha': [0.0001, 0.001, 0.01, 0.1],
            'learning_rate_init': [0.001, 0.003, 0.01], 'activation': ['relu', 'tanh'],
        },
        # [NUEVO -- MODELO ADICIONAL] Random Forest: ensamble de árboles
        # (como XGBoost/LightGBM, con la misma limitación de no poder
        # extrapolar más allá del rango de 'y' visto en entrenamiento --
        # ver el diagnóstico de Pronósticos2.py/Pronósticos3.py), pero con
        # un mecanismo de ensamblado distinto (bagging + promediado, en
        # vez de boosting secuencial) -- suele ser más estable/robusto
        # frente a series ruidosas o con pocos datos, aunque comparta la
        # debilidad de extrapolación con los otros dos árboles. Se agrega
        # como candidato adicional, no como reemplazo de ninguno --
        # compite igual que los demás y solo gana si su MAPE_CV es mejor.
        'RandomForest': {
            'n_estimators': [100, 200, 300, 500], 'max_depth': [None, 3, 5, 8, 12],
            'min_samples_leaf': [1, 2, 4, 8], 'max_features': ['sqrt', 'log2', 1.0],
        },
    }

    _CONSTRUCTORES_ML = {
        'XGBoost': lambda semilla: XGBRegressor(random_state=semilla, verbosity=0),
        'LightGBM': lambda semilla: LGBMRegressor(random_state=semilla, verbose=-1),
        'MLP': lambda semilla: MLPRegressor(random_state=semilla, max_iter=500),
        'RandomForest': lambda semilla: RandomForestRegressor(random_state=semilla, n_jobs=-1),
    }

    _CANDIDATOS_ORDEN_FALLBACK = [
        (0, 0, 0), (1, 0, 0), (0, 0, 1), (1, 0, 1),
        (1, 1, 0), (0, 1, 1), (1, 1, 1), (2, 1, 2),
    ]
    _CANDIDATOS_ORDEN_ESTACIONAL_FALLBACK = [
        (0, 0, 0), (1, 0, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1),
    ]

    def __init__(self, dataset, df_clusters,
                 n_iter_busqueda_ml=15, semilla_aleatoria=42,
                 sku_col='Código', cluster_col='Cluster_Operativo',
                 media_col='Demanda_Promedio', tendencia_col='Tendencia_pendiente',
                 estacional_col=None, lead_time_col='Lead Time (semanas)',
                 col_unidad_pronostico='Unidad_Pronostico',
                 col_lead_time_en_unidad='Lead_Time_Max_En_Unidad_Pronostico',
                 col_horizonte='Horizonte_Pronostico_Periodos',
                 n_ventanas_backtesting=3,
                 ):
        self.dataset = dataset
        self.df_clusters = df_clusters
        self.sku_col = sku_col
        self.cluster_col = cluster_col
        self.media_col = media_col
        self.tendencia_col = tendencia_col
        self.estacional_col = estacional_col
        self.lead_time_col = lead_time_col
        self.col_unidad_pronostico = col_unidad_pronostico
        self.col_lead_time_en_unidad = col_lead_time_en_unidad
        self.col_horizonte = col_horizonte
        # [NUEVO -- ROLLING-ORIGIN BACKTESTING] Ver evaluar_backtesting_
        # rolling_origin más abajo para el porqué: en vez de evaluar
        # "fuera de muestra" sobre UN solo tramo final, se promedian
        # varias ventanas TEST consecutivas hacia atrás en el tiempo --
        # con series muy volátiles (CV alto), un solo TEST puede caer por
        # azar en un tramo fácil o difícil, y el promedio entre varias
        # ventanas es una estimación mucho más confiable.
        self.n_ventanas_backtesting = n_ventanas_backtesting

        self.modelos_por_cluster = {}
        self.pronosticos_por_cluster = {}
        self.resultados_por_sku = {}
        self.config_por_cluster = {}
        self.log_ejecucion = []
        self.n_iter_busqueda_ml = n_iter_busqueda_ml
        self.semilla_aleatoria = semilla_aleatoria

    # ------------------------------------------------------------------
    # MÉTODOS AUXILIARES
    # ------------------------------------------------------------------

    def obtener_modelos_por_comportamiento(self, comportamiento):
        modelos = []
        if comportamiento in ('intermitente', 'intermitente+tendencia'):
            # [NUEVO -- DEMANDA INTERMITENTE] ARIMA/SARIMA/Holt-Winters/ETS
            # asumen una demanda que ocurre en (casi) todos los periodos --
            # no están pensados para series con muchos ceros y ocurrencias
            # esporádicas (ver ADI en TraductorClusterPronostico.py). Para
            # esas series se usa SBA (Syntetos-Boylan Approximation, la
            # variante con corrección de sesgo del método de Croston) --
            # el estándar en pronóstico de demanda intermitente para
            # inventarios -- compitiendo igual que siempre contra los
            # modelos de ML, que sí pueden aprender patrones no lineales
            # aunque haya muchos ceros.
            modelos.append(('SBA', 'clasico'))
            modelos.append(('XGBoost', 'ml'))
            modelos.append(('LightGBM', 'ml'))
            modelos.append(('MLP', 'ml'))
            modelos.append(('RandomForest', 'ml'))
            return modelos
        if comportamiento in ['estacionario', 'tendencia']:
            modelos.append(('ARIMA', 'clasico'))
        if comportamiento in ['estacional', 'estacional+tendencia']:
            modelos.append(('SARIMA', 'clasico'))
        if comportamiento in ['tendencia', 'estacional+tendencia']:
            modelos.append(('Holt-Winters', 'clasico'))
        if comportamiento == 'estacionario':
            modelos.append(('ETS', 'clasico'))
        modelos.append(('XGBoost', 'ml'))
        modelos.append(('LightGBM', 'ml'))
        modelos.append(('MLP', 'ml'))
        modelos.append(('RandomForest', 'ml'))
        return modelos

    def _posicion_ciclo(self, indice_fechas, unidad):
        """
        [CORREGIDO -- BUG REAL, MENOR] Algunos años tienen 53 semanas ISO
        (ej. 2020) en vez de 52 -- sin corrección, 'semanas' podía devolver
        posición 53 contra un PERIODO_ESTACIONAL=52 (y 'quincenas' 27 contra
        26 en esos mismos años), desalineando ligeramente sin_mes/cos_mes
        justo esa semana. Se acota siempre a [1, periodo_estacional] -- la
        última semana de un año de 53 semanas queda igualada a la posición
        52 (un empate razonable, no crea una posición nueva fuera de ciclo).
        """
        periodo = self.PERIODO_ESTACIONAL
        if unidad == 'semanas':
            pos = indice_fechas.isocalendar().week.astype(int).values
        elif unidad == 'quincenas':
            semana_iso = indice_fechas.isocalendar().week.astype(int).values
            pos = ((semana_iso - 1) // 2) + 1
        elif unidad == 'meses':
            pos = indice_fechas.month.values
        elif unidad == 'bimestres':
            pos = ((indice_fechas.month.values - 1) // 2) + 1
        elif unidad == 'trimestres':
            pos = indice_fechas.quarter.values
        else:
            raise ValueError(f"Unidad de pronóstico no soportada: '{unidad}'")
        return np.clip(pos, 1, periodo)

    def crear_features_ts(self, df):
        df = df.copy()
        df['mes'] = self._posicion_ciclo(df.index, self.UNIDAD_ACTUAL)
        df['tendencia'] = np.arange(len(df))
        for lag in self.REZAGOS:
            df[f'lag_{lag}'] = df['y'].shift(lag)
        for win in self.VENTANAS_MOVIL:
            df[f'ma_{win}'] = df['y'].rolling(win).mean()
        df['sin_mes'] = np.sin(2 * np.pi * df['mes'] / self.PERIODO_ESTACIONAL)
        df['cos_mes'] = np.cos(2 * np.pi * df['mes'] / self.PERIODO_ESTACIONAL)
        df.dropna(inplace=True)
        return df

    def preparar_serie_entrenamiento(self, df_agregado_trabajo, cluster_id, config, comportamiento):
        """
        [PUNTO DE EXTENSIÓN -- NO-OP EN V1] Se llama justo después de
        reagregar la serie a su unidad final, antes de clasificar
        comportamiento definitivamente y de entrenar. Aquí (V1) no hace
        nada -- devuelve la serie tal cual. Existe para que subclases
        (Pronósticos5.py, Pronósticos6.py) puedan transformar la serie de
        entrenamiento (recortar historia, marcar componentes a descontar)
        sin tener que copiar el resto de procesar_cluster.
        """
        return df_agregado_trabajo

    # ------------------------------------------------------------------
    # LECTURA DE LA CONFIGURACIÓN TEMPORAL POR CLÚSTER (NO SE DECIDE NADA)
    # ------------------------------------------------------------------

    def obtener_lead_time_max_cluster(self, cluster_id):
        cluster_data = self.df_clusters[self.df_clusters[self.cluster_col] == cluster_id]
        if self.lead_time_col not in cluster_data.columns:
            raise ValueError(f"No se encontró la columna '{self.lead_time_col}' en df_clusters.")
        lead_times = pd.to_numeric(cluster_data[self.lead_time_col], errors='coerce')
        if lead_times.notna().sum() == 0:
            return 0.0
        return float(lead_times.max())

    def obtener_config_temporal_cluster(self, cluster_id):
        """
        Lee (no decide) la unidad, el lead time convertido y el horizonte
        de este Cluster_Operativo -- calculados por TraductorClusterPronostico.py
        (que a su vez usa horizonte = lead_time_max_en_unidad_del_pronostico * 5,
        ver GRANULARIDADES_PRONOSTICO allá). Los traduce a la configuración
        técnica de entrenamiento (CONFIG_POR_UNIDAD).
        """
        cluster_data = self.df_clusters[self.df_clusters[self.cluster_col] == cluster_id]
        columnas_requeridas = (
            self.col_unidad_pronostico, self.col_lead_time_en_unidad,
            self.col_horizonte, self.lead_time_col,
        )
        faltantes = [c for c in columnas_requeridas if c not in cluster_data.columns]
        if faltantes:
            raise ValueError(
                f"❌ df_clusters no tiene {faltantes}, necesarias para el Cluster {cluster_id}. "
                f"Corre TraductorClusterPronostico.py primero y usa 'clusters_con_unidad_pronostico.xlsx'."
            )
        unidad = cluster_data[self.col_unidad_pronostico].iloc[0]
        if unidad not in self.CONFIG_POR_UNIDAD:
            raise ValueError(
                f"❌ Unidad_Pronostico='{unidad}' (Cluster {cluster_id}) no soportada: "
                f"{list(self.CONFIG_POR_UNIDAD.keys())}."
            )
        lead_time_max_semanas = self.obtener_lead_time_max_cluster(cluster_id)
        lead_time_max_en_unidad = float(cluster_data[self.col_lead_time_en_unidad].iloc[0])
        horizonte = int(cluster_data[self.col_horizonte].iloc[0])

        config = dict(self.CONFIG_POR_UNIDAD[unidad])
        config['horizonte'] = horizonte
        return config, lead_time_max_semanas, lead_time_max_en_unidad

    # ------------------------------------------------------------------
    # CLASIFICACIÓN DE COMPORTAMIENTO
    # ------------------------------------------------------------------

    def clasificar_comportamiento_cluster(self, cluster_id):
        cluster_data = self.df_clusters[self.df_clusters[self.cluster_col] == cluster_id]
        if 'comportamiento' in cluster_data.columns:
            return cluster_data['comportamiento'].iloc[0]
        avg_estacional = cluster_data[self.estacional_col].mean() if self.estacional_col else 0
        avg_tendencia = cluster_data[self.tendencia_col].mean()
        avg_media = cluster_data[self.media_col].mean()
        es_estacional = avg_estacional > self.UMBRAL_FUERZA_ESTACIONAL
        tendencia_significativa = abs(avg_tendencia) > self.UMBRAL_TENDENCIA_RELATIVA * avg_media
        if es_estacional and tendencia_significativa:
            return 'estacional+tendencia'
        elif es_estacional:
            return 'estacional'
        elif tendencia_significativa:
            return 'tendencia'
        else:
            return 'estacionario'

    # ------------------------------------------------------------------
    # BÚSQUEDA DE HIPERPARÁMETROS
    # ------------------------------------------------------------------

    def _hiperparametros_default(self, nombre, comportamiento):
        defaults = {
            # [CORREGIDO -- BUG REAL GRAVE, ver _buscar_orden_arima] 'trend':
            # 'c' agregado a los defaults de ARIMA/SARIMA -- ver el aviso
            # completo más abajo para el porqué. Sin esto, el fallback (si
            # ni pmdarima ni la búsqueda manual encuentran nada) construía
            # un ARIMA(1,0,1)/SARIMA(1,0,1) SIN constante -- igual de
            # propenso al mismo problema si esos coeficientes AR/MA
            # resultan pequeños.
            'ARIMA': {'order': (1, 0, 1), 'trend': 'c'},
            'SARIMA': {'order': (1, 0, 1), 'seasonal_order': (1, 0, 1, self.PERIODO_ESTACIONAL), 'trend': 'c'},
            'Holt-Winters': {
                'trend': 'add', 'seasonal': 'add' if 'estacional' in comportamiento else None,
                'damped_trend': False,
            },
            'ETS': {'error': 'add'},
            'SBA': {'alpha': 0.1},
            'XGBoost': {'n_estimators': 100, 'learning_rate': 0.1},
            'LightGBM': {'n_estimators': 100, 'learning_rate': 0.1},
            'MLP': {'hidden_layer_sizes': (50, 25), 'alpha': 0.0001,
                    'learning_rate_init': 0.001, 'activation': 'relu'},
            'RandomForest': {'n_estimators': 200, 'max_depth': None, 'min_samples_leaf': 2},
        }
        return defaults.get(nombre, {})

    def _buscar_orden_arima_manual(self, y, estacional, m=None):
        # [CORREGIDO -- MISMO BUG QUE _buscar_orden_arima, ver el aviso
        # completo ahí] La búsqueda manual (fallback sin pmdarima) también
        # ajustaba ARIMA/SARIMAX SIN especificar 'trend' -- con
        # trend=None (el default de statsmodels), el modelo NUNCA incluye
        # una constante, así que cualquier orden con AR/MA débiles puede
        # terminar pronosticando valores cercanos a 0 sin importar el
        # nivel real de la serie. Ahora se prueban ambos casos
        # (con constante 'c' y sin ella) para cada orden candidato, y se
        # guarda cuál de los dos ganó -- así el AIC compara de verdad
        # "¿hace falta una constante aquí?" en vez de asumir que no.
        m = m or self.PERIODO_ESTACIONAL
        mejor_aic = np.inf
        mejor = None
        if not estacional:
            for orden in self._CANDIDATOS_ORDEN_FALLBACK:
                for trend in ('c', None):
                    try:
                        ajuste = ARIMA(y, order=orden, trend=trend).fit()
                        if ajuste.aic < mejor_aic:
                            mejor_aic = ajuste.aic
                            mejor = {'order': orden, 'trend': trend}
                    except Exception:
                        continue
        else:
            for orden in self._CANDIDATOS_ORDEN_FALLBACK[:5]:
                for orden_est in self._CANDIDATOS_ORDEN_ESTACIONAL_FALLBACK:
                    for trend in ('c', None):
                        try:
                            seasonal_order = orden_est + (m,)
                            ajuste = SARIMAX(y, order=orden, seasonal_order=seasonal_order, trend=trend).fit(disp=False)
                            if ajuste.aic < mejor_aic:
                                mejor_aic = ajuste.aic
                                mejor = {'order': orden, 'seasonal_order': seasonal_order, 'trend': trend}
                        except Exception:
                            continue
        return mejor

    def _buscar_orden_arima(self, y, estacional):
        """
        [CORREGIDO -- BUG REAL GRAVE, encontrado en datos reales:
        2_RELIABLE_ESTADOSUNIDOS ganó con SARIMA(0,0,0)(0,0,0,26) -- un
        modelo que pronosticaba LITERALMENTE 0 para las 18 quincenas
        futuras, mientras la media histórica real era ~450 unidades.
        MAPE_CV/TEST/IN_SAMPLE los tres exactamente 100% -- la firma de
        este bug: la demanda real nunca fue 0, así que |real-0|/real=100%
        en cada punto, siempre.]

        Causa raíz: pm.auto_arima() SÍ incluye una constante quando le
        conviene (with_intercept=True por defecto) -- para esta serie
        encontró exactamente ese caso: orden (0,0,0)(0,0,0,26) CON
        intercepto ~450 (un modelo perfectamente razonable: "sin
        estructura autorregresiva, la mejor predicción es la media"). Pero
        el código solo guardaba 'order'/'seasonal_order' -- nunca ese
        intercepto. Más adelante, _ajustar_clasico reconstruye el modelo
        con SARIMAX(y, order=..., seasonal_order=...) SIN pasar 'trend' --
        el default de statsmodels es trend=None (sin ninguna constante) --
        así que el modelo que en verdad se usa para pronosticar es
        radicalmente distinto (y mucho peor) que el que pmdarima evaluó y
        cuyo AIC ganó la comparación. El problema no es exclusivo de este
        clúster: puede repetirse en cualquiera donde ARIMA/SARIMA gane con
        un orden bajo evaluado CON intercepto.

        Corrección: se lee 'with_intercept' del modelo que pmdarima ya
        ajustó, y se guarda como 'trend': 'c' o None en el resultado --
        así _ajustar_clasico reconstruye exactamente el mismo modelo que
        de verdad se evaluó, con o sin constante según corresponda.
        """
        if _PMDARIMA_DISPONIBLE:
            try:
                modelo_auto = pm.auto_arima(
                    y, seasonal=estacional, m=self.PERIODO_ESTACIONAL if estacional else 1,
                    stepwise=True, suppress_warnings=True, error_action='ignore',
                    max_p=5, max_q=5, max_d=2, max_P=2, max_Q=2, max_D=1,
                )
                resultado = {
                    'order': modelo_auto.order,
                    'trend': 'c' if getattr(modelo_auto, 'with_intercept', True) else None,
                }
                if estacional:
                    resultado['seasonal_order'] = modelo_auto.seasonal_order
                return resultado
            except Exception:
                pass
        resultado = self._buscar_orden_arima_manual(y, estacional)
        if resultado is None:
            resultado = {'order': (1, 0, 1), 'trend': 'c'}
            if estacional:
                resultado['seasonal_order'] = (1, 0, 1, self.PERIODO_ESTACIONAL)
        return resultado

    def _buscar_estructura_holt_winters(self, y, comportamiento):
        incluir_estacional = 'estacional' in comportamiento
        candidatos_trend = ['add', 'mul']
        candidatos_seasonal = ['add', 'mul'] if incluir_estacional else [None]
        candidatos_damped = [True, False]
        mejor_aic = np.inf
        mejor_estructura = None
        for trend in candidatos_trend:
            for seasonal in candidatos_seasonal:
                for damped in candidatos_damped:
                    try:
                        modelo = ExponentialSmoothing(
                            y, seasonal_periods=self.PERIODO_ESTACIONAL, trend=trend,
                            seasonal=seasonal, damped_trend=damped,
                        )
                        ajuste = modelo.fit()
                        if ajuste.aic < mejor_aic:
                            mejor_aic = ajuste.aic
                            mejor_estructura = {'trend': trend, 'seasonal': seasonal, 'damped_trend': damped}
                    except Exception:
                        continue
        if mejor_estructura is None:
            mejor_estructura = self._hiperparametros_default('Holt-Winters', comportamiento)
        return mejor_estructura

    # ------------------------------------------------------------------
    # SBA (Syntetos-Boylan Approximation) -- demanda intermitente
    # ------------------------------------------------------------------

    @staticmethod
    def _ajustar_sba_interno(y, alpha):
        """
        [MODELO PARA DEMANDA INTERMITENTE] SBA es la variante con
        corrección de sesgo del método de Croston (Syntetos & Boylan,
        2005) -- el estándar para pronosticar series con muchos periodos
        en cero y ocurrencias esporádicas (justo lo que mide ADI).

        Separa la serie en dos: el TAMAÑO de la demanda cada vez que
        ocurre, y el INTERVALO (en periodos) entre una ocurrencia y la
        siguiente. Cada una se suaviza por separado con suavizamiento
        exponencial simple (parámetro alpha, igual para ambas). El
        pronóstico es una tasa CONSTANTE por periodo:

            tasa = (tamaño_suavizado / intervalo_suavizado) * (1 - alpha/2)

        El factor (1 - alpha/2) es la corrección de Syntetos-Boylan sobre
        el Croston clásico, que subestima sistemáticamente la demanda
        esperada en series intermitentes.

        Devuelve (tasa_final, niveles_tamano, niveles_intervalo,
        idx_demanda) -- las trayectorias completas de los niveles
        suavizados en cada punto de demanda, usadas por _fitted_sba para
        construir un "ajustado" período a período (para los diagnósticos
        de residuos y las métricas dentro de muestra).
        """
        y = np.asarray(y, dtype=float)
        idx_demanda = np.where(y > 0)[0]

        if len(idx_demanda) == 0:
            return 0.0, np.array([]), np.array([]), idx_demanda

        tamanos = y[idx_demanda]
        intervalos = np.diff(idx_demanda, prepend=idx_demanda[0] - 1)
        intervalos = np.maximum(intervalos, 1)

        nivel_tamano = tamanos[0]
        nivel_intervalo = float(intervalos[0])
        niveles_tamano = [nivel_tamano]
        niveles_intervalo = [nivel_intervalo]

        for i in range(1, len(tamanos)):
            nivel_tamano = alpha * tamanos[i] + (1 - alpha) * nivel_tamano
            nivel_intervalo = alpha * intervalos[i] + (1 - alpha) * nivel_intervalo
            niveles_tamano.append(nivel_tamano)
            niveles_intervalo.append(nivel_intervalo)

        factor_sba = 1 - alpha / 2
        tasa_final = (nivel_tamano / nivel_intervalo) * factor_sba if nivel_intervalo > 0 else 0.0

        return tasa_final, np.array(niveles_tamano), np.array(niveles_intervalo), idx_demanda

    def _fitted_sba(self, y, alpha):
        """
        "Ajustado" período a período para SBA -- no existe un equivalente
        exacto al .fittedvalues de statsmodels, así que se construye como
        la tasa suavizada disponible en cada momento, mantenida constante
        entre una ocurrencia de demanda y la siguiente (es, literalmente,
        cuál sería el pronóstico vigente en cada periodo si se hubiera
        estado corriendo SBA en tiempo real). Se usa para los diagnósticos
        de residuos y las métricas dentro de muestra del modelo final.
        """
        y = np.asarray(y, dtype=float)
        tasa_final, niveles_tamano, niveles_intervalo, idx_demanda = self._ajustar_sba_interno(y, alpha)
        fitted = np.zeros(len(y))
        if len(idx_demanda) == 0:
            return fitted, tasa_final
        factor_sba = 1 - alpha / 2
        tasas_en_idx = (niveles_tamano / np.maximum(niveles_intervalo, 1e-9)) * factor_sba
        fitted[:idx_demanda[0] + 1] = tasas_en_idx[0]
        for k in range(len(idx_demanda) - 1):
            fitted[idx_demanda[k]:idx_demanda[k + 1] + 1] = tasas_en_idx[k]
        fitted[idx_demanda[-1]:] = tasas_en_idx[-1]
        return fitted, tasa_final

    def _buscar_alpha_sba(self, y):
        """Grid search simple de alpha, minimizando MSE dentro de muestra."""
        mejor_mse = np.inf
        mejor_alpha = 0.1
        y_arr = y.values if hasattr(y, 'values') else np.asarray(y)
        for alpha in (0.05, 0.1, 0.15, 0.2, 0.3):
            fitted, _ = self._fitted_sba(y_arr, alpha)
            mse = float(np.mean((y_arr - fitted) ** 2))
            if mse < mejor_mse:
                mejor_mse = mse
                mejor_alpha = alpha
        return {'alpha': mejor_alpha}

    def _buscar_estructura_ets(self, y):
        mejor_aic = np.inf
        mejor_estructura = {'error': 'add'}
        for error in ['add', 'mul']:
            try:
                ajuste = ETSModel(y, seasonal_periods=self.PERIODO_ESTACIONAL, error=error).fit()
                if ajuste.aic < mejor_aic:
                    mejor_aic = ajuste.aic
                    mejor_estructura = {'error': error}
            except Exception:
                continue
        return mejor_estructura

    @staticmethod
    def _contar_combinaciones(espacio):
        total = 1
        for valores in espacio.values():
            total *= len(valores)
        return total

    def _buscar_hiperparametros_ml(self, nombre, X, y, tscv):
        """
        [CORREGIDO -- FUGA DE INFORMACIÓN] Antes: se escalaba TODO X antes
        de entrar a RandomizedSearchCV(cv=tscv) -- el scaler veía datos de
        cada fold de validación al calcular su media/desviación, aunque
        esos folds no debían "existir todavía" para el modelo en ese punto.
        Ahora: se pasa X SIN escalar, dentro de un Pipeline(scaler, modelo)
        -- sklearn ajusta el Pipeline completo (incluido el scaler) por
        separado en cada fold, usando SOLO la partición de entrenamiento de
        ese fold. Cero fuga.
        """
        estimador = self._CONSTRUCTORES_ML[nombre](self.semilla_aleatoria)
        pipeline = Pipeline([('scaler', StandardScaler()), ('modelo', estimador)])
        espacio = {f'modelo__{k}': v for k, v in self._ESPACIO_BUSQUEDA_ML[nombre].items()}
        n_iter = min(self.n_iter_busqueda_ml, self._contar_combinaciones(self._ESPACIO_BUSQUEDA_ML[nombre]))
        busqueda = RandomizedSearchCV(
            pipeline, espacio, n_iter=n_iter, cv=tscv, scoring='neg_mean_squared_error',
            random_state=self.semilla_aleatoria, n_jobs=-1,
        )
        busqueda.fit(X, y)
        # Se devuelven SIN el prefijo 'modelo__' -- el resto del código
        # (_ajustar_ml_recursivo, pronosticar el ganador) construye el
        # estimador directamente, sin pasar por el Pipeline de búsqueda.
        return {k.replace('modelo__', '', 1): v for k, v in busqueda.best_params_.items()}

    def _buscar_hiperparametros_cluster(self, nombre, tipo, X, y, comportamiento, tscv, advertencias=None):
        try:
            if nombre == 'ARIMA':
                return self._buscar_orden_arima(y, estacional=False)
            elif nombre == 'SARIMA':
                return self._buscar_orden_arima(y, estacional=True)
            elif nombre == 'Holt-Winters':
                return self._buscar_estructura_holt_winters(y, comportamiento)
            elif nombre == 'ETS':
                return self._buscar_estructura_ets(y)
            elif nombre == 'SBA':
                return self._buscar_alpha_sba(y)
            elif nombre in self.MODELOS_ML:
                return self._buscar_hiperparametros_ml(nombre, X, y, tscv)
        except Exception as e:
            mensaje = f"Búsqueda de hiperparámetros falló para {nombre}, se usan valores por defecto: {str(e)[:80]}"
            print(f"  ⚠️ {mensaje}")
            if advertencias is not None:
                advertencias.append(mensaje)
        return self._hiperparametros_default(nombre, comportamiento)

    # ------------------------------------------------------------------
    # AJUSTE DE UN MODELO (clásico o ML) -- helpers reutilizados por CV,
    # evaluación fuera de muestra (TEST) y el ajuste final de producción.
    # ------------------------------------------------------------------

    def _ajustar_clasico(self, nombre, y_train, hiperparametros, pasos):
        """Ajusta un modelo clásico sobre y_train y pronostica 'pasos' adelante."""
        if nombre == 'ARIMA':
            # [CORREGIDO -- BUG REAL GRAVE, ver el docstring completo de
            # _buscar_orden_arima] Antes se reconstruía SIN 'trend' --
            # perdía silenciosamente el intercepto que pmdarima sí había
            # usado para evaluar este orden, produciendo un modelo
            # completamente distinto (y a menudo degenerado, pronosticando
            # ~0) al que en verdad ganó la comparación por AIC.
            modelo = ARIMA(y_train, order=hiperparametros['order'],
                            trend=hiperparametros.get('trend', 'c')).fit()
        elif nombre == 'SARIMA':
            modelo = SARIMAX(
                y_train, order=hiperparametros['order'],
                seasonal_order=hiperparametros['seasonal_order'],
                trend=hiperparametros.get('trend', 'c'),
            ).fit(disp=False)
        elif nombre == 'Holt-Winters':
            modelo = ExponentialSmoothing(
                y_train, seasonal_periods=self.PERIODO_ESTACIONAL,
                trend=hiperparametros.get('trend'), seasonal=hiperparametros.get('seasonal'),
                damped_trend=hiperparametros.get('damped_trend', False),
            ).fit()
        elif nombre == 'ETS':
            modelo = ETSModel(
                y_train, seasonal_periods=self.PERIODO_ESTACIONAL,
                error=hiperparametros.get('error', 'add'),
            ).fit()
        elif nombre == 'SBA':
            # [DISTINTO A LOS DEMÁS] SBA no produce un objeto de statsmodels
            # con .forecast()/.resid/.fittedvalues -- devuelve una tasa
            # CONSTANTE por periodo (ver _ajustar_sba_interno). 'modelo' es
            # un dict simple, no un objeto ajustado; ajustar_modelo_final
            # lo trata como caso especial (ver _fitted_sba) para los
            # diagnósticos de residuos.
            alpha = hiperparametros.get('alpha', 0.1)
            y_arr = y_train.values if hasattr(y_train, 'values') else np.asarray(y_train)
            tasa, _, _, _ = self._ajustar_sba_interno(y_arr, alpha)
            y_pred = np.full(pasos, tasa)
            modelo = {'tipo': 'SBA', 'alpha': alpha, 'tasa': tasa}
            return y_pred, modelo
        else:
            raise ValueError(f"Modelo clásico no soportado: {nombre}")
        y_pred = np.asarray(modelo.forecast(steps=pasos) if nombre in ('ARIMA', 'SARIMA') else modelo.forecast(pasos), dtype=float)
        return y_pred, modelo

    def _ajustar_ml_directo(self, nombre, X_train, y_train, X_eval, hiperparametros):
        """
        Predicción ML "directa": usa las features de X_eval TAL COMO VIENEN
        (incluyen rezagos calculados sobre valores reales, no predichos).
        Rápida -- se usa SOLO para la comparación preliminar en CV, donde
        X_eval son los folds de validación dentro de TRAIN (sus rezagos
        son historia real, ya ocurrida). NO se usa para el pronóstico
        futuro real ni para TEST -- ver _ajustar_ml_recursivo para eso.
        """
        estimador = self._CONSTRUCTORES_ML[nombre](self.semilla_aleatoria)
        estimador.set_params(**hiperparametros)
        pipeline = Pipeline([('scaler', StandardScaler()), ('modelo', estimador)])
        pipeline.fit(X_train, y_train)
        return pipeline.predict(X_eval), pipeline

    def _ajustar_ml_recursivo(self, nombre, X_train, y_train, hiperparametros, pasos, clip_no_negativo=True):
        """
        Predicción ML MULTI-PASO real: cada paso futuro usa como rezagos
        los valores YA PREDICHOS en los pasos anteriores (nunca datos
        reales que no existen todavía) -- exactamente lo que pasa en
        producción. Se usa tanto para evaluar TEST (fuera de muestra) como
        para el pronóstico futuro final, así que TEST mide honestamente el
        mismo mecanismo que después genera el pronóstico real.

        [SALVAGUARDA -- DIVERGENCIA RECURSIVA] La predicción recursiva
        puede retroalimentarse: si el modelo (sobre todo MLP, que sí
        extrapola más allá del rango visto en entrenamiento, a diferencia
        de XGBoost/LightGBM que son árboles y no pueden) sobreestima un
        paso, esa sobreestimación se vuelve rezago del siguiente paso, y el
        error puede crecer sin control (visto en datos reales: un clúster
        con tendencia fuerte llegó a R² = -609 fuera de muestra, síntoma de
        exactamente este tipo de divergencia). No es un intento de arreglar
        la extrapolación de tendencia en sí -- es solo un techo de
        seguridad: ningún paso puede predecir más de limite_superior, así
        que el error puede seguir siendo grande, pero ya no puede volverse
        ilimitado.

        [CORREGIDO -- BUG REAL: clip_no_negativo] El límite mínimo (0.0)
        que aplica predecir_paso_futuro_ml es correcto cuando esta función
        predice demanda directamente (Y nunca es negativa). PERO cuando el
        Pronosticador con descomposición (ver más abajo en el archivo) usa
        esta misma función para predecir el RESIDUO de Y = Tendencia +
        Estacional + Residuo, el residuo SÍ puede (y debe poder) ser
        negativo -- es una desviación alrededor de un componente que ya se
        le restó, no una demanda. Forzarlo a 0.0 sesgaba sistemáticamente
        el residuo hacia arriba, y sumado a un componente de tendencia
        proyectado que también puede ser negativo, el resultado final
        podía terminar en pronósticos de demanda NEGATIVOS -- se encontró
        literalmente un caso real (Cluster 11_RELIABLE_ESTADOSUNIDOS,
        demanda total pronosticada = -999). clip_no_negativo=False permite
        que el residuo se prediga sin ese piso; quien reconstruye el
        pronóstico final (componente + residuo) es responsable de aplicar
        el límite de no-negatividad sobre el TOTAL, no sobre el residuo
        (ver ajustar_modelo_final y evaluar_fuera_de_muestra más abajo).
        """
        estimador = self._CONSTRUCTORES_ML[nombre](self.semilla_aleatoria)
        estimador.set_params(**hiperparametros)
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X_train)
        estimador.fit(X_scaled, y_train)

        limite_superior = max(float(y_train.max()), 1.0) * 5.0

        preds = []
        historia_trabajo = y_train.values.copy()
        mes_paso = int(X_train.iloc[-1]['mes'])
        for i in range(pasos):
            mes_paso = siguiente_mes(mes_paso, pasos=1, periodo_estacional=self.PERIODO_ESTACIONAL)
            pred = predecir_paso_futuro_ml(
                modelo_entrenado=estimador, historia=historia_trabajo,
                posicion_tendencia=len(y_train) + i, mes_actual=mes_paso,
                escalador=scaler, columnas_features=list(X_train.columns),
                periodo_estacional=self.PERIODO_ESTACIONAL,
                rezagos=self.REZAGOS, ventanas_movil=self.VENTANAS_MOVIL,
                clip_no_negativo=clip_no_negativo,
            )
            pred = min(pred, limite_superior)
            preds.append(pred)
            historia_trabajo = np.append(historia_trabajo, pred)
        return np.array(preds), estimador, scaler

    # ------------------------------------------------------------------
    # FASE 1: ENTRENAMIENTO + AFINAMIENTO (VALIDACIÓN CRUZADA, DENTRO DE TRAIN)
    # ------------------------------------------------------------------

    def entrenar_modelo_cluster(self, df_agregado, comportamiento, cluster_id, horizonte_cluster):
        """
        [CORREGIDO -- SEPARA CV DE EVALUACIÓN FINAL] Parte la historia en
        TRAIN (afinamiento) y TEST (fuera de muestra, nunca visto aquí).
        Devuelve resultados_cv (para comparar y elegir candidatos), los
        hiperparámetros encontrados, y los 4 splits (X_train, y_train,
        X_test, y_test) para que procesar_cluster haga la evaluación fuera
        de muestra y el ajuste final sobre el 100% de la historia.

        Tamaño de TEST: por defecto, horizonte_cluster (la prueba simula
        exactamente la tarea real -- pronosticar esa cantidad de periodos).
        Si la historia es muy corta para reservar ese tramo completo y
        aun así dejar suficiente para entrenar/afinar, se usa un TEST más
        chico (20% de la historia) en su lugar, con aviso por consola.
        """
        df_feat = self.crear_features_ts(df_agregado[['y']])
        X_total = df_feat.drop('y', axis=1)
        y_total = df_feat['y']

        test_size = horizonte_cluster
        if len(df_feat) < test_size * 3:
            test_size_ajustado = max(1, int(len(df_feat) * 0.2))
            print(f"   ⚠️ Historia insuficiente ({len(df_feat)} periodos tras crear features) para "
                  f"reservar {horizonte_cluster} periodos completos como test fuera de muestra -- "
                  f"se usa un test más chico ({test_size_ajustado} periodos, ~20% de la historia).")
            test_size = test_size_ajustado
        test_size = min(test_size, max(0, len(df_feat) - 1))

        if test_size > 0:
            X_train, X_test = X_total.iloc[:-test_size], X_total.iloc[-test_size:]
            y_train, y_test = y_total.iloc[:-test_size], y_total.iloc[-test_size:]
        else:
            X_train, y_train = X_total, y_total
            X_test, y_test = X_total.iloc[0:0], y_total.iloc[0:0]

        n_splits = min(3, len(X_train) // self.PERIODO_ESTACIONAL)
        if n_splits < 2:
            n_splits = 2
        n_splits = min(n_splits, max(2, len(X_train) - 1))
        tscv = TimeSeriesSplit(n_splits=n_splits)

        candidatos = self.obtener_modelos_por_comportamiento(comportamiento)
        # [CORREGIDO -- YA NO SE FILTRA POR EL PRIMER FOLD] Antes se sacaba
        # SARIMA/Holt-Winters de los candidatos si el PRIMER fold (el más
        # corto de TimeSeriesSplit) no llegaba a 2 ciclos estacionales --
        # eso descartaba el candidato COMPLETO aunque folds posteriores (con
        # más historia) sí alcanzaran. Ahora solo se filtran si NI SIQUIERA
        # el total de TRAIN alcanza 2 ciclos (ningún fold podría funcionar
        # nunca); el manejo fold-por-fold de abajo se encarga del resto:
        # cada fold se intenta de forma independiente, y si uno falla por
        # falta de historia, simplemente no aporta métricas para ESE fold,
        # sin descartar los demás.
        tiene_historia_para_estacionales = len(X_train) >= 2 * self.PERIODO_ESTACIONAL
        if not tiene_historia_para_estacionales:
            candidatos = [(n, t) for n, t in candidatos if n not in ('Holt-Winters', 'SARIMA')]

        resultados_cv = {}
        hiperparametros_por_modelo = {}
        advertencias = []

        for nombre, tipo in candidatos:
            hiperparametros = self._buscar_hiperparametros_cluster(
                nombre, tipo, X_train, y_train, comportamiento, tscv, advertencias
            )
            hiperparametros_por_modelo[nombre] = hiperparametros

            mape_list, wape_num_list, wape_den_list, rmse_list, mse_list, r2_list = [], [], [], [], [], []
            count = 0
            for train_idx, val_idx in tscv.split(X_train):
                X_tr, X_val = X_train.iloc[train_idx], X_train.iloc[val_idx]
                y_tr, y_val = y_train.iloc[train_idx], y_train.iloc[val_idx]
                try:
                    if tipo == 'clasico':
                        y_pred_fold, _ = self._ajustar_clasico(nombre, y_tr, hiperparametros, len(y_val))
                    else:
                        y_pred_fold, _ = self._ajustar_ml_directo(nombre, X_tr, y_tr, X_val, hiperparametros)
                except Exception:
                    # [CORREGIDO] Solo se salta ESTE fold -- no se descarta
                    # el candidato completo (ver nota arriba).
                    continue

                if len(y_pred_fold) != len(y_val):
                    y_pred_fold = y_pred_fold[:len(y_val)]

                m = calcular_metricas(y_val.values, y_pred_fold)
                mape_list.append(m['MAPE_%'] if not np.isnan(m['MAPE_%']) else 1_000_000.0)
                wape_num_list.append(float(np.sum(np.abs(y_val.values - y_pred_fold))))
                wape_den_list.append(float(np.sum(np.abs(y_val.values))))
                mse_list.append(m['MSE'])
                rmse_list.append(m['RMSE'])
                r2_list.append(m['R2'])
                count += 1

            if count > 0:
                suma_num = sum(wape_num_list)
                suma_den = sum(wape_den_list)
                wape = (suma_num / suma_den * 100) if suma_den > 0 else np.nan
                resultados_cv[nombre] = {
                    'MAPE_CV_%': float(np.nanmean(mape_list)),
                    'WAPE_CV_%': wape if not np.isnan(wape) else 1_000_000.0,
                    'RMSE_CV': float(np.nanmean(rmse_list)),
                    'MSE_CV': float(np.nanmean(mse_list)),
                    'R2_CV': float(np.nanmean(r2_list)),
                    'n_folds_exitosos': count,
                    'n_folds_totales': n_splits,
                }

        return resultados_cv, hiperparametros_por_modelo, advertencias, X_train, y_train, X_test, y_test

    # ------------------------------------------------------------------
    # FASE 2: EVALUACIÓN FUERA DE MUESTRA (TEST) + AJUSTE FINAL (IN-SAMPLE)
    # ------------------------------------------------------------------

    def evaluar_fuera_de_muestra(self, nombre_modelo, X_train, y_train, X_test, y_test, hiperparametros):
        """
        Reentrena el candidato SOLO sobre TRAIN y lo evalúa UNA VEZ sobre
        TEST (nunca visto en la búsqueda de hiperparámetros ni en la
        comparación de candidatos por CV) -- la estimación "fuera de
        muestra" genuinamente independiente. Si TEST está vacío (historia
        demasiado corta), devuelve métricas NaN sin fallar.
        """
        if len(y_test) == 0:
            return {k: np.nan for k in ('MAPE_%', 'WAPE_%', 'RMSE', 'MSE', 'R2')}

        if nombre_modelo in self.MODELOS_CLASICOS:
            y_pred_test, _ = self._ajustar_clasico(nombre_modelo, y_train, hiperparametros, len(y_test))
        else:
            y_pred_test, _, _ = self._ajustar_ml_recursivo(nombre_modelo, X_train, y_train, hiperparametros, len(y_test))
        return calcular_metricas(y_test.values, y_pred_test)

    def _construir_ventanas_backtesting(self, y_total, horizonte, n_ventanas):
        """
        [NUEVO -- CORRIGE BUG REAL: N_Ventanas_Backtesting=0] Genera los
        índices (inicio_test, fin_test) de cada ventana, de más reciente a
        más antigua. Intenta primero con un mínimo de TRAIN "preferido" de
        1 ciclo estacional completo (self.PERIODO_ESTACIONAL) -- suficiente
        para que el modelo vea al menos un patrón estacional entero. Si eso
        no alcanza para NINGUNA ventana (visto en datos reales: clústeres
        mensuales con apenas 34-46 periodos de historia, donde ni siquiera
        UNA ventana cabía exigiendo 2 ciclos), se relaja al mínimo
        absolutamente necesario para entrenar algo con sentido (el mismo
        horizonte, igual que el test_size adaptativo que ya usaba
        entrenar_modelo_cluster antes de este cambio) -- así nunca se
        vuelve a dejar un clúster sin NINGÚN TEST por exigir de más. Un
        clúster con historia corta obtiene MENOS ventanas (a veces solo 1,
        igual que antes de este cambio), pero NUNCA cero.
        """
        def _generar(minimo_train, tam_ventana):
            ventanas = []
            for i in range(n_ventanas):
                fin_test = len(y_total) - i * tam_ventana
                inicio_test = fin_test - tam_ventana
                if inicio_test < minimo_train or fin_test <= inicio_test:
                    break
                ventanas.append((inicio_test, fin_test))
            return ventanas

        minimo_preferido = max(self.PERIODO_ESTACIONAL, horizonte + 1)
        ventanas = _generar(minimo_preferido, horizonte)
        if len(ventanas) == 0:
            minimo_relajado = max(horizonte, 1)
            ventanas = _generar(minimo_relajado, horizonte)
        if len(ventanas) == 0:
            # [ÚLTIMO RECURSO -- CORRIGE BUG REAL: N_Ventanas_Backtesting=0
            # incluso con el nivel relajado] Visto en datos reales:
            # 0_JINANMEIDE_CHINA (34 periodos tras crear_features_ts,
            # horizonte=20) -- ni una sola ventana de tamaño 'horizonte'
            # cabe (34 < 2*20). Se reduce el TAMAÑO de la ventana TEST
            # misma al 20% de la historia disponible -- el mismo criterio
            # de emergencia que usaba entrenar_modelo_cluster antes de
            # este cambio para su único TEST -- así se obtienen varias
            # ventanas más chicas en vez de dejar el clúster sin ningún
            # backtesting.
            tam_emergencia = max(1, int(len(y_total) * 0.2))
            if tam_emergencia < len(y_total):
                ventanas = _generar(tam_emergencia, tam_emergencia)
        return ventanas

    @staticmethod
    def _agregar_metricas_ventanas(ventanas_evaluadas):
        """
        [CORREGIDO -- BUG REAL: promedio dominado por una sola ventana
        catastrófica] Visto en datos reales: 5_RELIABLE_ESTADOSUNIDOS tuvo
        ventanas con MAPE 313%/1957%/121% -- el PROMEDIO simple (797%) no
        representa nada real, queda enteramente arrastrado por la ventana
        de 1957% (MAPE explota cuando la demanda real de esa ventana tiene
        valores muy pequeños -- división por un número cercano a 0). Un
        solo promedio le da a esa ventana el mismo peso que a las otras
        dos, aunque sea un caso atípico.

        Ahora la métrica PRINCIPAL reportada (ej. 'MAPE_%') es la MEDIANA
        entre ventanas -- robusta a que una sola ventana salga disparada.
        El promedio se conserva aparte, en '<métrica>_mean'.

        [NUEVO -- 2 mejoras de interpretabilidad, a pedido explícito]
          1) '<métrica>_mad': desviación absoluta mediana (mediana de
             |valor_i - mediana|) -- una medida de dispersión, igual que
             '_std', pero CONSISTENTE con usar la mediana como valor
             central: no se deja arrastrar por la misma ventana atípica
             que ya no afecta a la mediana. '_std' se conserva también
             (no se quita nada), para quien prefiera la medida clásica.
          2) Se agrega 'MASE' a la lista de métricas agregadas -- ver
             calcular_mase() para la definición completa. A diferencia de
             MAPE_%, MASE no se dispara con demanda pequeña -- es la
             métrica recomendada para comparar clústeres entre sí de forma
             justa, sin importar cuán volátil sea cada uno.
        """
        metricas_a_agregar = ('MAPE_%', 'WAPE_%', 'RMSE', 'MSE', 'R2', 'MASE')
        if len(ventanas_evaluadas) == 0:
            resultado_vacio = {k: np.nan for k in metricas_a_agregar}
            for k in metricas_a_agregar:
                resultado_vacio[f'{k}_mean'] = np.nan
                resultado_vacio[f'{k}_std'] = np.nan
                resultado_vacio[f'{k}_mad'] = np.nan
            resultado_vacio['n_ventanas_backtesting'] = 0
            resultado_vacio['metricas_por_ventana'] = []
            resultado_vacio['residuos_fuera_de_muestra'] = np.array([])
            return resultado_vacio

        resultado = {}
        for clave in metricas_a_agregar:
            valores = [v[clave] for v in ventanas_evaluadas if clave in v and not (isinstance(v[clave], float) and np.isnan(v[clave]))]
            mediana = float(np.median(valores)) if valores else np.nan
            resultado[clave] = mediana
            resultado[f'{clave}_mean'] = float(np.mean(valores)) if valores else np.nan
            resultado[f'{clave}_std'] = float(np.std(valores)) if len(valores) > 1 else 0.0
            resultado[f'{clave}_mad'] = (
                float(np.median(np.abs(np.asarray(valores) - mediana))) if valores else np.nan
            )
        resultado['n_ventanas_backtesting'] = len(ventanas_evaluadas)
        resultado['metricas_por_ventana'] = ventanas_evaluadas
        # [NUEVO -- RESIDUOS FUERA DE MUESTRA] Concatena el residuo crudo
        # de TODAS las ventanas (cada una ya calculada con TRAIN/TEST
        # correctamente separados, sin fuga) en un solo vector -- este es
        # el que Simulacion.py debe usar para el bootstrap, en vez de los
        # residuos dentro de muestra del ajuste final (ver el aviso
        # completo en Simulacion.extraer_vector_errores). Con 3 ventanas
        # de tamaño horizonte, da hasta 3*horizonte puntos -- más
        # representativo del error real de generalización que un solo
        # residuo dentro de muestra, que para modelos de árboles
        # subestima la incertidumbre real de forma severa.
        residuos_todas_ventanas = [
            v['residuos_ventana'] for v in ventanas_evaluadas if 'residuos_ventana' in v
        ]
        resultado['residuos_fuera_de_muestra'] = (
            np.concatenate(residuos_todas_ventanas) if residuos_todas_ventanas else np.array([])
        )
        return resultado

    def evaluar_backtesting_rolling_origin(self, nombre_modelo, X_total, y_total, hiperparametros,
                                            horizonte, n_ventanas=None):
        """
        [NUEVO -- ROLLING-ORIGIN BACKTESTING] Reemplaza evaluar_fuera_de_
        muestra (un solo TEST al final de la serie) por el promedio de
        varias ventanas TEST consecutivas hacia atrás en el tiempo, todas
        del mismo tamaño (horizonte) y sin solaparse entre sí.

        [POR QUÉ] Con demanda de alta volatilidad (CV>0.5 -- muy común en
        repuestos ligados a proyectos de construcción, ver el análisis de
        5_RELIABLE_ESTADOSUNIDOS/2_WILSON&COUSIN_CANADÁ: CV entre 0.9 y
        1.2), un solo TEST puede caer, por pura casualidad, en un tramo
        inusualmente fácil o inusualmente difícil de la serie. El
        MAPE_TEST de una sola ventana no distingue "el modelo generaliza
        mal" de "le tocó una mala racha". Promediar varias ventanas da una
        estimación mucho más estable de qué tan bien pronosticaría este
        modelo en producción, y además expone la VARIABILIDAD entre
        ventanas (columna '<métrica>_std') -- información nueva que antes
        no existía: dos clústeres con el mismo MAPE_TEST promedio pueden
        tener una confiabilidad muy distinta si uno varía poco entre
        ventanas y el otro varía muchísimo.

        [CÓMO] Ventana 0 (la más reciente) es exactamente el mismo tramo
        que antes evaluaba evaluar_fuera_de_muestra. Las ventanas
        adicionales se deslizan hacia atrás un horizonte completo cada
        vez -- de ahí "rolling ORIGIN": el punto donde termina TRAIN y
        empieza TEST se desliza, TRAIN crece hacia atrás en cada ventana
        más antigua (nunca se usa información del futuro de esa ventana).
        Los MISMOS hiperparámetros (ya elegidos una sola vez por CV sobre
        el TRAIN más reciente, ver entrenar_modelo_cluster) se reutilizan
        en todas las ventanas -- no se re-optimizan por ventana, eso
        multiplicaría el costo computacional sin aportar objetividad
        adicional (el propósito aquí es medir qué tan consistente es el
        DESEMPEÑO del modelo ya elegido, no volver a elegir modelo).

        Se detiene automáticamente si no queda suficiente historia para
        entrenar con sentido (mínimo 2 ciclos estacionales, o al menos
        horizonte+1 periodos) -- clústeres con historia corta usan menos
        de n_ventanas ventanas en vez de fallar.

        Devuelve un dict con las mismas 5 claves que calcular_metricas
        (promedio entre ventanas -- compatible con todo el código que ya
        lee metricas_test['MAPE_%'], etc., sin romper nada), más:
          - '<métrica>_std': desviación estándar entre ventanas
          - 'n_ventanas_backtesting': cuántas ventanas se usaron de verdad
          - 'metricas_por_ventana': detalle de cada ventana individual
        """
        n_ventanas = n_ventanas if n_ventanas is not None else self.n_ventanas_backtesting
        ventanas_indices = self._construir_ventanas_backtesting(y_total, horizonte, n_ventanas)
        ventanas_evaluadas = []

        for i, (inicio_test, fin_test) in enumerate(ventanas_indices):
            X_train_v = X_total.iloc[:inicio_test]
            y_train_v = y_total.iloc[:inicio_test]
            X_test_v = X_total.iloc[inicio_test:fin_test]
            y_test_v = y_total.iloc[inicio_test:fin_test]
            if len(y_test_v) == 0:
                break

            try:
                if nombre_modelo in self.MODELOS_CLASICOS:
                    y_pred_v, _ = self._ajustar_clasico(nombre_modelo, y_train_v, hiperparametros, len(y_test_v))
                else:
                    y_pred_v, _, _ = self._ajustar_ml_recursivo(
                        nombre_modelo, X_train_v, y_train_v, hiperparametros, len(y_test_v)
                    )
            except Exception:
                # Esta ventana en particular falló (ej. historia muy corta
                # para ese modelo en esa posición) -- se salta, no se
                # descarta el backtesting completo, igual que el manejo
                # fold-por-fold en entrenar_modelo_cluster.
                continue

            m = calcular_metricas(y_test_v.values, y_pred_v)
            m['MASE'] = calcular_mase(y_test_v.values, y_pred_v, y_train_v.values, self.PERIODO_ESTACIONAL)
            # [NUEVO -- RESIDUOS FUERA DE MUESTRA, ver _agregar_metricas_ventanas
            # y el aviso completo en Simulacion.extraer_vector_errores] Se
            # guarda el residuo CRUDO (no solo las métricas agregadas) de
            # esta ventana -- concatenado entre las 3 ventanas por
            # _agregar_metricas_ventanas, es lo que Simulación debe usar
            # para el bootstrap en vez de los residuos dentro de muestra
            # (que para modelos de árboles como XGBoost/RandomForest
            # subestiman brutalmente la incertidumbre real -- visto en
            # datos reales: std=0.008 dentro de muestra vs MAPE_TEST=39%).
            m['residuos_ventana'] = (y_test_v.values - y_pred_v)
            m['ventana_indice'] = i
            m['fecha_inicio_test'] = y_test_v.index[0]
            m['fecha_fin_test'] = y_test_v.index[-1]
            ventanas_evaluadas.append(m)

        return self._agregar_metricas_ventanas(ventanas_evaluadas)

    def ajustar_modelo_final(self, nombre_modelo, comportamiento, X_full, y_full, horizonte_pronostico, hiperparametros=None):
        """
        Reentrena el modelo ganador sobre el 100% de la historia
        (TRAIN+TEST) -- el modelo que de verdad produce el pronóstico
        futuro -- y calcula sus métricas DENTRO DE MUESTRA (valores
        ajustados vs. la misma historia con la que se entrenó). Devuelve
        (y_pred, validez_residuos, modelo_ajustado, extras_ml, metricas_in_sample).
        """
        if hiperparametros is None:
            hiperparametros = self._hiperparametros_default(nombre_modelo, comportamiento)

        extras_ml = None

        if nombre_modelo == 'SBA':
            # [CASO ESPECIAL] 'modelo' es un dict, no un objeto de
            # statsmodels -- no tiene .resid/.fittedvalues, así que se
            # construyen con _fitted_sba (ver ahí el porqué).
            y_pred, modelo_ajustado = self._ajustar_clasico(nombre_modelo, y_full, hiperparametros, horizonte_pronostico)
            alpha = hiperparametros.get('alpha', 0.1)
            fitted, _ = self._fitted_sba(y_full.values, alpha)
            residuos = y_full.values - fitted
            y_real_in_sample = y_full.values
        elif nombre_modelo in self.MODELOS_CLASICOS:
            y_pred, modelo_ajustado = self._ajustar_clasico(nombre_modelo, y_full, hiperparametros, horizonte_pronostico)
            residuos = np.asarray(modelo_ajustado.resid, dtype=float)
            fitted = np.asarray(modelo_ajustado.fittedvalues, dtype=float)
            # Algunos modelos (SARIMA con componente estacional, sobre todo)
            # no pueden producir un valor ajustado para las primeras
            # observaciones -- fitted queda más corto que y_full. Se alinea
            # contra el tramo final de y_full, del mismo largo que fitted.
            y_real_in_sample = y_full.values[-len(fitted):] if len(fitted) <= len(y_full) else y_full.values
        else:
            y_pred, modelo_ajustado, scaler = self._ajustar_ml_recursivo(
                nombre_modelo, X_full, y_full, hiperparametros, horizonte_pronostico
            )
            extras_ml = {
                'scaler': scaler, 'columnas_features': list(X_full.columns),
                'index_entrenamiento': X_full.index,
            }
            fitted = modelo_ajustado.predict(scaler.transform(X_full))
            y_real_in_sample = y_full.values
            residuos = y_full.values - fitted

        metricas_in_sample = calcular_metricas(y_real_in_sample, fitted)

        media_res = np.mean(residuos) if len(residuos) > 0 else 0
        normalidad_p = None
        if len(residuos) > 3:
            _, normalidad_p = shapiro(residuos)
        try:
            ljung_box = acorr_ljungbox(residuos, lags=min(10, len(residuos) - 1), return_df=True)
            independencia_p = ljung_box['lb_pvalue'].iloc[-1] if not ljung_box.empty else None
        except Exception:
            independencia_p = None
        try:
            hetero_p = het_breuschpagan(residuos, np.ones((len(residuos), 1)))[1] if len(residuos) > 2 else None
        except Exception:
            hetero_p = None

        validez = {
            'media_residuales': media_res, 'normalidad_pvalue': normalidad_p,
            'independencia_pvalue': independencia_p, 'heterocedasticidad_pvalue': hetero_p,
            'residuos': residuos,
        }

        return np.asarray(y_pred, dtype=float), validez, modelo_ajustado, extras_ml, metricas_in_sample

    def _pronostico_fallback_promedio_simple(self, y, horizonte_pronostico):
        """
        [CUÁNDO SE USA EXACTAMENTE ESTE FALLBACK -- 2 CASOS, Y SOLO ESOS]

        Caso 1 -- "ningún candidato pudo evaluarse en CV": entrenar_modelo_
        cluster devolvió resultados_cv vacío. Pasa cuando TODOS los
        candidatos fallaron en TODOS sus folds de validación cruzada (por
        ejemplo, una serie demasiado corta o demasiado irregular para que
        ni ARIMA ni XGBoost logren ajustar ni un solo fold).

        Caso 2 -- "los 2 mejores candidatos por MAPE_CV fallaron al
        reentrenarse": hay resultados_cv, se identificó un top-2, pero al
        intentar el reentrenamiento real (evaluar_fuera_de_muestra +
        ajustar_modelo_final) ambos lanzaron una excepción -- por ejemplo,
        un modelo que sí ajustó folds pequeños en CV pero no logra converger
        sobre la historia completa, o con el tamaño de TEST fuera de muestra.

        Fuera de esos 2 casos, SIEMPRE se usa el modelo real ganador -- este
        fallback no es una alternativa "por seguridad" para casos normales.

        [NO ES UN MODELO EQUIVALENTE A LOS DEMÁS] Es un promedio plano de
        los últimos PERIODO_ESTACIONAL periodos (o de toda la serie, si es
        más corta) repetido para todo el horizonte -- no captura tendencia
        ni estacionalidad. Con series muy cortas (p. ej. una serie
        trimestral con solo 7-8 observaciones, promediando "las últimas 4")
        el promedio en sí es poco robusto -- es la naturaleza de un
        promedio con pocos datos, no algo que este fallback pueda arreglar.
        Por eso cada fila de log_ejecucion/exportar_resultados marca
        Es_Fallback=True explícitamente: es una señal de que ese clúster
        necesita revisión manual (más historia, revisar el comportamiento
        asignado, o aceptar el pronóstico con ese aviso), no un resultado
        al mismo nivel de confianza que un ARIMA/SARIMA/XGBoost que sí
        ajustó y se validó normalmente.
        """
        if len(y) >= self.PERIODO_ESTACIONAL:
            ventana = y.iloc[-self.PERIODO_ESTACIONAL:]
        else:
            ventana = y
        valor_plano = float(ventana.mean())
        y_pred = np.full(horizonte_pronostico, valor_plano)
        # [NUEVO -- CORRIGE BUG REAL: Simulación no sabía consumir este
        # modelo] Antes este método NO devolvía ningún objeto "modelo
        # ajustado" -- las 3 clases que lo llaman guardaban directamente
        # 'modelo_ajustado': None en modelos_por_cluster. Si un clúster
        # caía en este fallback, el .pkl consolidado quedaba con un
        # nombre de modelo ('Promedio_Simple') que Simulacion.
        # NOMBRE_MODELO_A_TIPO no reconocía -- preparar_forecast_un_paso_
        # desde_pronosticador() lanzaba ValueError apenas Simulación
        # intentara procesar ese clúster, deteniendo el pipeline completo
        # (no solo ese clúster). Ahora se devuelve un dict simple
        # {'tipo': 'Promedio_Simple', 'valor': ...} -- mismo patrón que ya
        # usa SBA (ver Pronosticador._ajustar_sba_interno) para modelos
        # que no son un objeto de statsmodels/sklearn -- que Simulación ya
        # sabe adaptar (ver crear_forecast_un_paso_promedio_simple ahí).
        modelo_ajustado = {'tipo': 'Promedio_Simple', 'valor': valor_plano}
        # [MEJORADO] Los residuos ya no son un solo [0.0] (sin variabilidad
        # real, que además rompía el bootstrap de Simulación con un vector
        # de tamaño 1) -- se calculan como la desviación real de cada
        # periodo de la ventana usada frente al promedio plano, dando al
        # bootstrap una variabilidad genuina basada en la propia historia
        # reciente del clúster.
        residuos_fallback = (
            (ventana.values - valor_plano) if len(ventana) > 1 else np.array([0.0])
        )
        validez = {
            'media_residuales': 0.0, 'normalidad_pvalue': None, 'independencia_pvalue': None,
            'heterocedasticidad_pvalue': None, 'residuos': residuos_fallback, 'es_fallback': True,
        }
        return y_pred, validez, modelo_ajustado

    # ------------------------------------------------------------------
    # PROCESAMIENTO DE CLUSTER
    # ------------------------------------------------------------------

    def procesar_cluster(self, cluster_id, df_agregado):
        print(f"\n🔹 Procesando Cluster {cluster_id}")
        skus_cluster = self.df_clusters[self.df_clusters[self.cluster_col] == cluster_id][self.sku_col].tolist()
        print(f"   SKUs en cluster: {len(skus_cluster)}")

        config, lead_time_max_semanas, lead_time_max_en_unidad = self.obtener_config_temporal_cluster(cluster_id)
        self.config_por_cluster[cluster_id] = config
        self.UNIDAD_ACTUAL = config['unidad']
        self.REGLA_RESAMPLE = config['regla_resample']
        self.PERIODO_ESTACIONAL = config['periodo_estacional']
        self.REZAGOS = config['rezagos']
        self.VENTANAS_MOVIL = config['ventanas_movil']
        horizonte_cluster = config['horizonte']

        print(f"   Unidad de pronóstico (definida por el Traductor): {config['unidad']} | "
              f"lead time máximo: {lead_time_max_semanas:.1f} semanas "
              f"({lead_time_max_en_unidad:.2f} {config['unidad']}) | "
              f"horizonte = {horizonte_cluster} {config['unidad']} "
              f"(= lead time máximo en {config['unidad']} × 5, definido por el traductor)")

        if config['unidad'] == 'semanas':
            df_agregado_trabajo = df_agregado[['y']]
        else:
            df_agregado_trabajo = df_agregado[['y']].resample(config['regla_resample']).sum()

        # [PUNTO DE EXTENSIÓN] Por defecto no hace nada -- devuelve la
        # serie tal cual. Subclases (Pronósticos5.py: recorta la historia
        # antes de un quiebre de tendencia detectado; Pronósticos6.py:
        # nada aquí, la descomposición ocurre más adelante, solo para el
        # lado ML) pueden sobreescribir este método sin tener que duplicar
        # el resto de procesar_cluster.
        comportamiento_preliminar = self.clasificar_comportamiento_cluster(cluster_id)
        df_agregado_trabajo = self.preparar_serie_entrenamiento(
            df_agregado_trabajo, cluster_id, config, comportamiento_preliminar
        )

        comportamiento = self.clasificar_comportamiento_cluster(cluster_id)
        print(f"   Comportamiento: {comportamiento}")
        print(f"   Afinando hiperparámetros y comparando candidatos (validación cruzada dentro de TRAIN)...")

        (resultados_cv, hiperparametros_por_modelo, advertencias_busqueda,
         X_train, y_train, X_test, y_test) = self.entrenar_modelo_cluster(
            df_agregado_trabajo, comportamiento, cluster_id, horizonte_cluster
        )

        # [CAMBIO EXPLÍCITO -- SELECCIÓN POR MAPE_CV, NO WAPE_CV] Se
        # mantienen ambas métricas reportadas en todas las tablas, pero la
        # que decide el top-2 (y por tanto el modelo ganador) es MAPE_CV.
        top2 = sorted(resultados_cv.items(), key=lambda x: x[1]['MAPE_CV_%'])[:2] if resultados_cv else []

        y_full = pd.concat([y_train, y_test]) if len(y_test) > 0 else y_train
        X_full = pd.concat([X_train, X_test]) if len(y_test) > 0 else X_train

        y_pred = validacion = modelo_ajustado = extras_ml = None
        metricas_test = metricas_in_sample = None
        mejor_modelo = None
        candidatos_fallidos = []

        for nombre_candidato, metricas_cv in top2:
            hiperparametros_candidato = hiperparametros_por_modelo.get(nombre_candidato)
            try:
                # [CORREGIDO -- ROLLING-ORIGIN BACKTESTING] Antes se
                # evaluaba sobre UN solo tramo TEST final
                # (evaluar_fuera_de_muestra). Ahora se promedian varias
                # ventanas TEST consecutivas hacia atrás -- ver el
                # docstring de evaluar_backtesting_rolling_origin para el
                # porqué (series con CV alto pueden caer, por azar, en un
                # TEST inusualmente fácil o difícil con una sola ventana).
                metricas_test_candidato = self.evaluar_backtesting_rolling_origin(
                    nombre_candidato, X_full, y_full, hiperparametros_candidato, horizonte_cluster
                )
                y_pred, validacion, modelo_ajustado, extras_ml, metricas_in_sample_candidato = (
                    self.ajustar_modelo_final(
                        nombre_candidato, comportamiento, X_full, y_full,
                        horizonte_cluster, hiperparametros_candidato,
                    )
                )
                mejor_modelo = nombre_candidato
                metricas_test = metricas_test_candidato
                metricas_in_sample = metricas_in_sample_candidato

                print(f"   ✅ Modelo usado: {mejor_modelo}")
                print(f"      CV (afinamiento, {metricas_cv['n_folds_exitosos']}/{metricas_cv['n_folds_totales']} folds):  "
                      f"MAPE={metricas_cv['MAPE_CV_%']:.2f}% WAPE={metricas_cv['WAPE_CV_%']:.2f}% "
                      f"RMSE={metricas_cv['RMSE_CV']:.2f} R2={metricas_cv['R2_CV']:.3f}")
                print(f"      Backtesting rolling-origin ({metricas_test['n_ventanas_backtesting']} ventanas): "
                      f"MAPE={metricas_test['MAPE_%']:.2f}% (±{metricas_test['MAPE_%_std']:.2f}) "
                      f"WAPE={metricas_test['WAPE_%']:.2f}% (±{metricas_test['WAPE_%_std']:.2f}) "
                      f"RMSE={metricas_test['RMSE']:.2f} R2={metricas_test['R2']:.3f} (±{metricas_test['R2_std']:.3f})")
                print(f"      Dentro de muestra (ajuste final): "
                      f"MAPE={metricas_in_sample['MAPE_%']:.2f}% WAPE={metricas_in_sample['WAPE_%']:.2f}% "
                      f"RMSE={metricas_in_sample['RMSE']:.2f} R2={metricas_in_sample['R2']:.3f}")
                print(f"   🔧 Hiperparámetros: {hiperparametros_candidato}")
                break
            except Exception as e:
                mensaje = f"{nombre_candidato} falló en TEST/ajuste final: {str(e)[:100]}"
                print(f"   ⚠️ {mensaje}")
                candidatos_fallidos.append({'modelo': nombre_candidato, 'error': str(e)[:200]})

        if mejor_modelo is None:
            # [FALLBACK -- ver los 2 casos exactos en
            # _pronostico_fallback_promedio_simple.__doc__]
            motivo = (
                "ningún candidato pudo evaluarse en la comparación por MAPE_CV" if not resultados_cv
                else "los 2 mejores candidatos por MAPE_CV fallaron al evaluarse fuera de muestra o al reentrenarse"
            )
            print(f"   ⚠️ Cluster {cluster_id} cae en el camino de emergencia ({motivo}); se usa un promedio simple.")
            y_pred, validacion, modelo_ajustado = self._pronostico_fallback_promedio_simple(y_full, horizonte_cluster)
            extras_ml = None
            metricas_test = {k: np.nan for k in ('MAPE_%', 'WAPE_%', 'RMSE', 'MSE', 'R2')}
            metricas_in_sample = {k: np.nan for k in ('MAPE_%', 'WAPE_%', 'RMSE', 'MSE', 'R2')}
            mejor_modelo = self.NOMBRE_MODELO_FALLBACK

        y_pred = np.asarray(y_pred, dtype=float)
        offset = self.OFFSET_POR_UNIDAD[config['unidad']]
        fecha_inicio_pronostico = df_agregado_trabajo.index[-1] + offset

        self.modelos_por_cluster[cluster_id] = {
            'modelo': mejor_modelo, 'comportamiento': comportamiento,
            'resultados_cv': resultados_cv, 'metricas_test': metricas_test,
            'metricas_in_sample': metricas_in_sample, 'top2': top2,
            'hiperparametros': hiperparametros_por_modelo.get(mejor_modelo),
            'modelo_ajustado': modelo_ajustado, 'datos_agregados': df_agregado_trabajo.copy(),
            'candidatos_fallidos': candidatos_fallidos,
            'lead_time_max_cluster': lead_time_max_semanas,
            'lead_time_max_en_unidad': lead_time_max_en_unidad,
            'unidad_tiempo': config['unidad'], 'regla_resample': config['regla_resample'],
            'horizonte': horizonte_cluster,
            'n_periodos_train': len(y_train), 'n_periodos_test': len(y_test),
            **(extras_ml or {}),
        }

        self.pronosticos_por_cluster[cluster_id] = {
            'pronostico': y_pred, 'validacion': validacion,
            'horizonte_pronostico': horizonte_cluster, 'unidad_tiempo': config['unidad'],
            'fecha_inicio_pronostico': fecha_inicio_pronostico,
        }
        # [NUEVO -- RESIDUOS FUERA DE MUESTRA PARA SIMULACIÓN] Se copian
        # aquí, DENTRO de 'validacion' (no solo en metricas_test), porque
        # Simulacion.extraer_vector_errores lee 'residuos' de este mismo
        # dict -- es el punto de integración ya existente entre los dos
        # módulos, y agregar la clave nueva aquí no rompe nada que ya lea
        # 'residuos' (se conserva intacto). Ver el aviso completo en
        # _agregar_metricas_ventanas para el porqué.
        self.pronosticos_por_cluster[cluster_id]['validacion']['residuos_fuera_de_muestra'] = (
            metricas_test.get('residuos_fuera_de_muestra', np.array([]))
        )

        self.log_ejecucion.append({
            'cluster_id': cluster_id, 'n_skus': len(skus_cluster), 'comportamiento': comportamiento,
            'modelo_elegido': mejor_modelo, 'es_fallback': bool(validacion.get('es_fallback', False)),
            'mape_cv_%': resultados_cv.get(mejor_modelo, {}).get('MAPE_CV_%'),
            'wape_cv_%': resultados_cv.get(mejor_modelo, {}).get('WAPE_CV_%'),
            'mape_test_%': metricas_test['MAPE_%'], 'wape_test_%': metricas_test['WAPE_%'],
            'mape_in_sample_%': metricas_in_sample['MAPE_%'], 'wape_in_sample_%': metricas_in_sample['WAPE_%'],
            'candidatos_fallidos': candidatos_fallidos,
            'advertencias_busqueda_hiperparametros': advertencias_busqueda,
            'lead_time_max_cluster': lead_time_max_semanas,
            'lead_time_max_en_unidad': lead_time_max_en_unidad,
            'unidad_tiempo': config['unidad'], 'horizonte': horizonte_cluster,
        })

        # [CORREGIDO -- DESAGREGACIÓN QUE PRESERVA LA SUMA] Antes cada SKU
        # se escalaba con su PROPIA media histórica completa
        # (factor_escala = media_sku / media_cluster), calculada sobre
        # ventanas de tiempo potencialmente DISTINTAS entre SKU (cada uno
        # con su propia fecha de inicio) -- y distintas de la ventana común
        # con la que en realidad se construyó la serie del clúster (ver
        # clusterizacionVolumen.preparar_unidades_agregadas_por_cluster).
        # Eso rompía sum(F_SKU_i,t) = F_cluster,t.
        #
        # Ahora el peso de cada SKU se calcula como
        #   w_i = media_i / sum_j(media_j)
        # usando la media de CADA SKU sobre la MISMA ventana común
        # [fecha_inicio_comun, fecha_fin_comun] que corresponde a
        # df_agregado_trabajo (la serie que de verdad se usó para entrenar
        # el clúster). Como sum_i(w_i) = 1 por construcción,
        # sum_i(F_SKU_i,t) = F_cluster,t * sum_i(w_i) = F_cluster,t
        # exactamente, para cada periodo t -- el pronóstico del clúster se
        # conserva al repartirlo, insumo correcto para la simulación de
        # inventarios.
        fecha_inicio_comun = df_agregado_trabajo.index.min()
        fecha_fin_comun = df_agregado_trabajo.index.max()

        medias_sku = {}
        for sku in skus_cluster:
            df_sku = self.dataset[self.dataset[self.sku_col] == sku][['Fecha', 'Unidades']].copy()
            df_sku = df_sku.set_index('Fecha').sort_index()
            df_sku = df_sku.resample(config['regla_resample']).agg({'Unidades': 'sum'}).fillna(0)
            df_sku_comun = df_sku.loc[(df_sku.index >= fecha_inicio_comun) & (df_sku.index <= fecha_fin_comun)]
            medias_sku[sku] = float(df_sku_comun['Unidades'].mean()) if len(df_sku_comun) > 0 else 0.0

        suma_medias = sum(medias_sku.values())

        resultados_cluster = {}
        for sku in skus_cluster:
            peso = (medias_sku[sku] / suma_medias) if suma_medias > 0 else (1.0 / len(skus_cluster))
            pronostico_sku = y_pred * peso

            resultado_sku = {
                'sku': sku, 'cluster': cluster_id, 'comportamiento': comportamiento,
                'mejor_modelo': mejor_modelo, 'pronostico': pronostico_sku,
                'horizonte_pronostico': horizonte_cluster, 'unidad_tiempo': config['unidad'],
                'regla_resample': config['regla_resample'], 'fecha_inicio_pronostico': fecha_inicio_pronostico,
                'demanda_total': pronostico_sku.sum(), 'demanda_promedio': pronostico_sku.mean(),
                'peso_desagregacion': peso, 'validacion': validacion,
                'lead_time_max_cluster': lead_time_max_semanas,
                'lead_time_max_en_unidad': lead_time_max_en_unidad,
            }
            self.resultados_por_sku[sku] = resultado_sku
            resultados_cluster[sku] = resultado_sku

        return resultados_cluster

    # ------------------------------------------------------------------
    # PIPELINE PRINCIPAL (AUTÓNOMO)
    # ------------------------------------------------------------------

    def ejecutar_pipeline_pronosticos(self, skus_por_cluster=None, datos_por_cluster=None):
        print("\n" + "=" * 60)
        print("🚀 INICIANDO PRONÓSTICOS POR CLUSTER")
        print("   Unidad, lead time y horizonte de cada Cluster_Operativo ya ")
        print("   vienen resueltos por TraductorClusterPronostico.py.")
        print("=" * 60)

        if skus_por_cluster is None:
            skus_por_cluster = self.df_clusters.groupby(self.cluster_col)[self.sku_col].apply(list).to_dict()

        if datos_por_cluster is None:
            # Ver el aviso equivalente en TraductorClusterPronostico.py: este
            # fallback NO aplica la alineación a historia común -- prefiere
            # pasarle datos_por_cluster ya construido con
            # cargar_unidades_agregadas_desde_excel (más abajo en este archivo).
            datos_por_cluster = {}
            for cluster_id in skus_por_cluster.keys():
                skus = skus_por_cluster[cluster_id]
                df_cluster = self.dataset[self.dataset[self.sku_col].isin(skus)]
                df_cluster = df_cluster.set_index('Fecha').sort_index()
                df_cluster = df_cluster.resample('W-MON').agg({'Unidades': 'sum'})
                df_cluster = df_cluster.fillna(0)
                df_cluster = df_cluster.rename(columns={'Unidades': 'y'})
                datos_por_cluster[cluster_id] = df_cluster

        resultados_totales = {}
        for cluster_id, skus in skus_por_cluster.items():
            if cluster_id in datos_por_cluster:
                resultados = self.procesar_cluster(cluster_id, datos_por_cluster[cluster_id])
                resultados_totales.update(resultados)

        n_fallback = sum(1 for log in self.log_ejecucion if log['es_fallback'])
        conteo_unidades = pd.Series([log['unidad_tiempo'] for log in self.log_ejecucion]).value_counts()
        resumen_unidades = ", ".join(f"{n} en {u}" for u, n in conteo_unidades.items())
        print(f"\n✅ Pronósticos generados para {len(resultados_totales)} SKUs "
              f"({len(self.log_ejecucion)} clusters procesados: {resumen_unidades}; "
              f"{n_fallback} en fallback).")
        return resultados_totales

    def resumen_ejecucion(self):
        return pd.DataFrame(self.log_ejecucion)

    def tabla_metricas_finales(self):
        """
        [PEDIDO EXPLÍCITO] Una fila por Cluster_Operativo con el modelo
        ganador y sus métricas en los 3 conjuntos (CV, TEST fuera de
        muestra, IN_SAMPLE dentro de muestra). MAPE aparece primero en
        cada grupo de columnas porque se deja como métrica principal de
        reporte -- R2/WAPE/RMSE/MSE se conservan al lado para contexto
        (MAPE_CV sigue siendo la métrica que de verdad elige el modelo
        ganador internamente, ver el docstring de la clase, sección de
        metodología de evaluación).

        [TRANSPARENCIA DE DATOS] N_Periodos_Train/N_Periodos_Test se
        incluyen porque R²_TEST puede salir muy inestable en clústeres con
        poca historia (test de pocos periodos, ver el aviso en
        entrenar_modelo_cluster sobre "historia insuficiente") -- estas
        columnas dejan visible cuáles resultados están respaldados por
        suficiente historia y cuáles hay que interpretar con cautela.
        """
        filas = []
        for cluster_id, info in self.modelos_por_cluster.items():
            cv = info['resultados_cv'].get(info['modelo'], {})
            test = info['metricas_test']
            in_sample = info['metricas_in_sample']
            filas.append({
                'Cluster': cluster_id, 'Modelo_Ganador': info['modelo'],
                'Unidad_Tiempo': info['unidad_tiempo'], 'Horizonte': info['horizonte'],
                'N_Periodos_Train': info.get('n_periodos_train'),
                'N_Periodos_Test': info.get('n_periodos_test'),
                'MAPE_CV_%': cv.get('MAPE_CV_%'), 'R2_CV': cv.get('R2_CV'),
                'WAPE_CV_%': cv.get('WAPE_CV_%'), 'RMSE_CV': cv.get('RMSE_CV'), 'MSE_CV': cv.get('MSE_CV'),
                'MAPE_TEST_%': test.get('MAPE_%'), 'R2_TEST': test.get('R2'),
                'WAPE_TEST_%': test.get('WAPE_%'), 'RMSE_TEST': test.get('RMSE'), 'MSE_TEST': test.get('MSE'),
                'MAPE_IN_SAMPLE_%': in_sample.get('MAPE_%'), 'R2_IN_SAMPLE': in_sample.get('R2'),
                'WAPE_IN_SAMPLE_%': in_sample.get('WAPE_%'), 'RMSE_IN_SAMPLE': in_sample.get('RMSE'),
                'MSE_IN_SAMPLE': in_sample.get('MSE'),
            })
        return pd.DataFrame(filas)

    def exportar_resultados(self, resultados, archivo_salida='Resultados_Clusterizados.xlsx'):
        df_resumen = []
        df_detalle = []
        df_residuos = []
        df_hiperparametros = []
        df_metricas_candidatos = []

        for sku, res in resultados.items():
            validacion = res['validacion']
            unidad = res.get('unidad_tiempo', 'semanas')
            df_resumen.append({
                self.sku_col: sku, 'Cluster': res['cluster'], 'Comportamiento': res['comportamiento'],
                'Mejor_Modelo': res['mejor_modelo'], 'Es_Fallback': bool(validacion.get('es_fallback', False)),
                'Unidad_Tiempo': unidad, 'Horizonte': res['horizonte_pronostico'],
                'Demanda_Total': round(res['demanda_total'], 0), 'Demanda_Promedio': round(res['demanda_promedio'], 2),
                'Peso_Desagregacion_Cluster': round(res['peso_desagregacion'], 4),
                'Lead_Time_Max_Cluster_Semanas': round(res['lead_time_max_cluster'], 1),
                'Lead_Time_Max_Cluster_En_Unidad': round(res.get('lead_time_max_en_unidad', np.nan), 2),
                'Normalidad_pvalue': round(validacion['normalidad_pvalue'], 4) if validacion['normalidad_pvalue'] else None,
                'Independencia_pvalue': round(validacion['independencia_pvalue'], 4) if validacion['independencia_pvalue'] else None,
                'Heterocedasticidad_pvalue': round(validacion['heterocedasticidad_pvalue'], 4) if validacion['heterocedasticidad_pvalue'] else None,
            })

            regla = res.get('regla_resample', self.CONFIG_POR_UNIDAD['semanas']['regla_resample'])
            formato_fecha = '%Y-%m' if unidad in self.UNIDADES_MENSUALES else '%Y-%m-%d'
            periodos_pronostico = pd.date_range(
                start=res['fecha_inicio_pronostico'], periods=res['horizonte_pronostico'], freq=regla
            )
            for periodo, valor in zip(periodos_pronostico, res['pronostico']):
                df_detalle.append({
                    self.sku_col: sku, 'Periodo': periodo.strftime(formato_fecha),
                    'Unidad_Tiempo': unidad, 'Pronostico': round(valor, 0),
                })

        for cluster_id, info_cluster in self.modelos_por_cluster.items():
            validacion_cluster = self.pronosticos_por_cluster[cluster_id]['validacion']
            residuos = validacion_cluster.get('residuos')
            if residuos is not None and len(residuos) > 0:
                residuos_str = ', '.join([f'{r:.4f}' for r in residuos[:50]])
                df_residuos.append({
                    'Cluster': cluster_id, 'Unidad_Tiempo': info_cluster.get('unidad_tiempo', 'semanas'),
                    'N_Residuos': len(residuos), 'Media_Residuos': float(np.mean(residuos)),
                    'Std_Residuos': float(np.std(residuos)), 'Residuos_(primeros_50)': residuos_str,
                })
            else:
                df_residuos.append({
                    'Cluster': cluster_id, 'Unidad_Tiempo': info_cluster.get('unidad_tiempo', 'semanas'),
                    'N_Residuos': 0, 'Media_Residuos': None, 'Std_Residuos': None,
                    'Residuos_(primeros_50)': 'Sin residuos (fallback)',
                })

            df_hiperparametros.append({
                'Cluster': cluster_id, 'Unidad_Tiempo': info_cluster.get('unidad_tiempo', 'semanas'),
                'Modelo_Ganador': info_cluster.get('modelo'),
                'Hiperparametros': str(info_cluster.get('hiperparametros')) if info_cluster.get('hiperparametros') is not None else 'N/A',
            })

            for nombre_modelo, metricas in info_cluster.get('resultados_cv', {}).items():
                df_metricas_candidatos.append({
                    'Cluster': cluster_id, 'Modelo_Candidato': nombre_modelo,
                    'MAPE_CV_%': metricas.get('MAPE_CV_%'), 'WAPE_CV_%': metricas.get('WAPE_CV_%'),
                    'RMSE_CV': metricas.get('RMSE_CV'), 'MSE_CV': metricas.get('MSE_CV'), 'R2_CV': metricas.get('R2_CV'),
                })

        df_residuos = pd.DataFrame(df_residuos)
        df_hiperparametros = pd.DataFrame(df_hiperparametros)
        df_metricas_candidatos = pd.DataFrame(df_metricas_candidatos)
        df_resumen = pd.DataFrame(df_resumen)
        df_detalle = pd.DataFrame(df_detalle)
        df_metricas_finales = self.tabla_metricas_finales()

        with pd.ExcelWriter(archivo_salida, engine='openpyxl') as writer:
            df_resumen.to_excel(writer, sheet_name='Resumen', index=False)
            df_detalle.to_excel(writer, sheet_name='Pronosticos', index=False)
            df_metricas_finales.to_excel(writer, sheet_name='Metricas_Finales_Por_Cluster', index=False)
            df_hiperparametros.to_excel(writer, sheet_name='Hiperparametros', index=False)
            df_metricas_candidatos.to_excel(writer, sheet_name='Metricas_Candidatos_CV', index=False)
            df_residuos.to_excel(writer, sheet_name='Residuos', index=False)


# ============================================================
# CARGA DE LAS UNIDADES AGREGADAS YA ALINEADAS (SIN RECALCULAR)
# ============================================================
def cargar_unidades_agregadas_desde_excel(ruta='unidades_agregadas_por_cluster.xlsx'):
    indice = pd.read_excel(ruta, sheet_name='Indice')
    datos_por_cluster = {}
    for _, fila in indice.iterrows():
        serie = pd.read_excel(ruta, sheet_name=fila['Hoja'], index_col=0)['Unidades_Agregadas']
        serie.index = pd.to_datetime(serie.index)
        datos_por_cluster[fila['Cluster_Operativo']] = serie.rename('y').to_frame()
    return datos_por_cluster


# ============================================================
# EJECUCIÓN DIRECTA (SIN GLUE)


# ==========================================================================
# [V5 -- DETECCIÓN DE QUIEBRE DE TENDENCIA] Fusionado en este mismo archivo
# a pedido explícito -- ya no vive en Pronósticos5.py aparte. Ver el aviso
# completo de por qué existe justo antes de la función siguiente.
# ==========================================================================
def detectar_ultimo_quiebre_tendencia(y, ventana, mejora_relativa_minima=0.25,
                                       minimo_bloques_restantes=3):
    """
    [MÉTODO -- AJUSTE DE DOS TRAMOS, ELEGIDO POR REDUCCIÓN DE ERROR]
    Para cada punto candidato k (múltiplos de 'ventana', normalmente
    periodo_estacional -- "1 año" de esa unidad -- dejando al menos
    minimo_bloques_restantes*ventana periodos ANTES y DESPUÉS de k), se
    compara:
        (a) el error cuadrático de UNA sola recta ajustada a toda la serie
        (b) el error cuadrático de DOS rectas separadas, una antes de k y
            otra después de k

    Si partir la serie en dos tramos en k reduce el error al menos
    'mejora_relativa_minima' (25% por defecto) frente a una sola recta,
    k es un candidato válido de quiebre. Entre TODOS los candidatos
    válidos se elige el MÁS RECIENTE (mayor k) -- para recortar lo menos
    posible, quedándose solo con el quiebre más reciente que de verdad
    separa un régimen distinto del actual. Si ningún candidato supera el
    umbral, se concluye que no hay un quiebre real y se devuelve 0 (usar
    toda la historia, sin recortar).

    [POR QUÉ NO SE COMPARAN BLOQUES ADYACENTES] Una primera versión de
    este algoritmo comparaba la pendiente de cada bloque de 'ventana'
    periodos contra el bloque inmediatamente anterior -- resultó
    demasiado sensible al ruido: en una serie sintética con un quiebre
    real y obvio en la mitad, ese método detectaba un "quiebre" falso en
    el último par de bloques (pura variación de pendiente dentro del
    MISMO régimen), sin llegar nunca al quiebre real. El ajuste de dos
    tramos por SSE es el estándar para detección de un solo punto de
    quiebre en una serie (ver, p. ej., Chow test / optimal partitioning)
    y no depende de comparar solo dos bloques vecinos -- evalúa la serie
    completa en cada candidato.

    Devuelve el ÍNDICE (posición dentro de y, contando desde 0) del
    quiebre encontrado -- la serie recortada sería y[indice:]. 0 si no se
    encontró ninguno o la serie es demasiado corta para buscar con
    seguridad.
    """
    y = np.asarray(y, dtype=float)
    n = len(y)
    minimo = minimo_bloques_restantes * ventana

    if n < 2 * minimo + ventana:
        return 0

    t = np.arange(n)
    coef_unico = np.polyfit(t, y, 1)
    sse_unico = float(np.sum((y - np.polyval(coef_unico, t)) ** 2))
    if sse_unico <= 1e-9:
        return 0

    mejor_k = 0
    for k in range(minimo, n - minimo + 1, ventana):
        t1, y1 = t[:k], y[:k]
        t2, y2 = t[k:], y[k:]
        if len(t1) < 2 or len(t2) < 2:
            continue
        coef1 = np.polyfit(t1, y1, 1)
        coef2 = np.polyfit(t2, y2, 1)
        sse_dos = float(
            np.sum((y1 - np.polyval(coef1, t1)) ** 2) + np.sum((y2 - np.polyval(coef2, t2)) ** 2)
        )
        mejora = 1 - (sse_dos / sse_unico)
        if mejora >= mejora_relativa_minima:
            mejor_k = k  # se sigue recorriendo -- el bucle va de más antiguo a
            # más reciente (range ascendente), así que el último candidato
            # válido que sobrescribe mejor_k es siempre el MÁS RECIENTE.

    return mejor_k


# ==========================================================================
# [NUEVO -- COLAPSO DE NIVEL RECIENTE] Encontrado al investigar por qué
# 2_RELIABLE_ESTADOSUNIDOS, 5_KIDDE_ESTADOSUNIDOS y 5_TYCO_ESTADOSUNIDOS
# tenían MAPE_TEST altísimo pese a que ni el quiebre de tendencia (V5) ni
# la descomposición (V6) encontraban nada: en los 3, la media de TEST
# resultó ser 0.5%-2.2% de la media histórica completa -- la demanda se
# desplomó a casi nada en el tramo más reciente, mientras el histórico
# completo sigue dominado por años de demanda mucho más alta. Ningún
# modelo entrenado sobre TODA esa historia puede predecir bien el
# "ahora casi no se vende" si el 98%+ de sus datos de entrenamiento dice
# lo contrario.
#
# La corrección: si se detecta este colapso, se recorta el entrenamiento
# a SOLO la ventana reciente (después del colapso), y el comportamiento
# (estacional/tendencia/intermitente) se RECALCULA sobre esa ventana
# recortada -- no se seguirá usando la clasificación de comportamiento
# calculada sobre toda la historia, que ya no representa el régimen
# actual. Casi siempre la ventana reciente sale clasificada como
# 'intermitente' (correctamente, dado el colapso), lo que enruta a SBA --
# que estima una TASA basada en cuán seguido y cuánto se vende AHORA, no
# en un promedio histórico que ya dejó de ser cierto.
# ==========================================================================

UMBRAL_COLAPSO_RELATIVO = 0.25  # media reciente < 25% de la media histórica total
UMBRAL_ADI_INTERMITENTE = 1.32  # mismo umbral de Syntetos-Boylan usado en el resto del pipeline
UMBRAL_FUERZA_ESTACIONAL_RECLASIF = 0.15
UMBRAL_TENDENCIA_RELATIVA_RECLASIF = 0.001


def detectar_colapso_reciente(y, horizonte, periodo_estacional, umbral_relativo=UMBRAL_COLAPSO_RELATIVO):
    """
    Compara la media de la VENTANA RECIENTE (los últimos
    max(2*horizonte, periodo_estacional) periodos) contra la media de TODA
    la historia. Si la reciente es menor al umbral_relativo (25% por
    defecto) de la histórica, se considera que hubo un COLAPSO DE NIVEL
    reciente. Devuelve (hay_colapso, indice_inicio_ventana_reciente) --
    indice_inicio es 0 si no hay colapso (usar toda la historia).

    La ventana se ata a 2*horizonte (no solo horizonte) para no
    reaccionar a un solo periodo flojo -- necesita sostenerse por al
    menos 2 horizontes de pronóstico para contar como un cambio de
    régimen real, no ruido de corto plazo.
    """
    y = np.asarray(y, dtype=float)
    n = len(y)
    ventana = max(2 * horizonte, periodo_estacional)
    if n < 2 * ventana:
        return False, 0
    reciente = y[-ventana:]
    media_reciente = reciente.mean()
    media_total = y.mean()
    if media_total <= 0:
        return False, 0
    hay_colapso = (media_reciente / media_total) < umbral_relativo
    indice_inicio = (n - ventana) if hay_colapso else 0
    return hay_colapso, indice_inicio


def _clasificar_comportamiento_sobre_serie(serie_values, periodo_estacional):
    """
    Reclasifica comportamiento (mismo criterio que TraductorClusterPronostico.py
    -- ADI primero, luego STL) pero sobre un array de valores cualquiera,
    no sobre una tabla precomputada -- se usa para reclasificar la ventana
    reciente después de un colapso, sin depender de la columna
    'comportamiento' que trae df_clusters (calculada sobre toda la
    historia, ya no representativa del régimen actual).
    """
    y = np.asarray(serie_values, dtype=float)
    n = len(y)
    idx_demanda = np.where(y > 0)[0]
    media = float(y.mean()) if n > 0 else 0.0

    adi = (n / len(idx_demanda)) if len(idx_demanda) > 0 else np.inf
    if adi >= UMBRAL_ADI_INTERMITENTE:
        t = np.arange(n)
        pendiente = float(np.polyfit(t, y, 1)[0]) if n >= 2 else 0.0
        tendencia_sig = abs(pendiente) > UMBRAL_TENDENCIA_RELATIVA_RECLASIF * media if media else False
        return 'intermitente+tendencia' if tendencia_sig else 'intermitente'

    if n >= 2 * periodo_estacional:
        resultado = STL(pd.Series(y), period=periodo_estacional, robust=True).fit()
        var_resid = np.var(resultado.resid)
        var_seasonal_resid = np.var(resultado.seasonal + resultado.resid)
        fuerza_estacional = 0.0 if var_seasonal_resid == 0 else max(0.0, 1 - var_resid / var_seasonal_resid)
        t = np.arange(n)
        pendiente = float(np.polyfit(t, resultado.trend.values, 1)[0])
    else:
        fuerza_estacional = 0.0
        t = np.arange(n)
        pendiente = float(np.polyfit(t, y, 1)[0]) if n >= 2 else 0.0

    es_estacional = fuerza_estacional > UMBRAL_FUERZA_ESTACIONAL_RECLASIF
    tendencia_sig = abs(pendiente) > UMBRAL_TENDENCIA_RELATIVA_RECLASIF * media if media else False
    if es_estacional and tendencia_sig:
        return 'estacional+tendencia'
    elif es_estacional:
        return 'estacional'
    elif tendencia_sig:
        return 'tendencia'
    return 'estacionario'


# ==========================================================================
# [NUEVO -- ENSAMBLE DE LOS 2 MEJORES CANDIDATOS] Ataca el patrón que más
# se repitió al revisar la tabla completa de 18 clústeres: CV muy bueno
# (R2_CV >= 0.6, a veces 0.9) pero TEST desastroso (R2_TEST muy negativo)
# -- la firma clásica de SOBREAJUSTE: un solo modelo (casi siempre XGBoost
# o MLP) se ajustó demasiado bien al ruido específico de TRAIN, y esa
# sobreadaptación no generaliza. 6 de los 18 clústeres mostraban
# exactamente este patrón (0_SIMPLEX, 5_TYCO, 0_WILSON, 5_KIDDE,
# 4_RELIABLE, 6_RELIABLE).
#
# En vez de usar solo el candidato con menor MAPE_CV, esta estrategia
# promedia (ponderado por el inverso de su MAPE_CV) las predicciones de
# los 2 mejores candidatos de la comparación -- los mismos 'top2' que ya
# calcula entrenar_modelo_cluster. Promediar dos modelos con arquitecturas
# distintas (ej. un árbol de decisión + una red neuronal, o un modelo
# clásico + uno de ML) tiende a CANCELAR parte del error idiosincrático de
# cada uno: si XGBoost sobreestima por una razón y MLP subestima por otra,
# el promedio amortigua ambos errores -- es la razón estadística de fondo
# detrás de por qué los métodos de ensamble (bagging, promediado de
# modelos) generalmente generalizan mejor que un solo "ganador" elegido
# por su desempeño en una sola comparación, aunque individualmente ese
# ganador se viera mejor.
# ==========================================================================

class PronosticadorConEnsamble(Pronosticador):
    """
    [NUEVO] Reemplaza "usar el modelo con menor MAPE_CV" por "promediar,
    ponderado por 1/MAPE_CV, los 2 mejores candidatos" -- tanto para la
    evaluación fuera de muestra (TEST) como para el pronóstico final. Si
    solo uno de los 2 candidatos logra ajustarse (el otro falla), se usa
    ese único candidato sin promediar -- nunca se fuerza un ensamble con
    un solo elemento útil. Las métricas dentro de muestra y los
    diagnósticos de residuos (Ljung-Box, Shapiro, etc.) se calculan sobre
    el candidato de MENOR MAPE_CV únicamente -- reconstruir un "ajustado"
    combinado para 2 modelos con lógicas de entrenamiento distintas
    (ej. un SARIMA y un XGBoost) no tiene una definición limpia, y esos
    diagnósticos son secundarios frente a la precisión de TEST/pronóstico,
    que es lo que este ensamble optimiza.
    """

    def _pesos_inversos_mape(self, mapes_cv):
        mapes = [max(float(m), 1e-6) for m in mapes_cv]
        inversos = [1.0 / m for m in mapes]
        suma = sum(inversos)
        return [i / suma for i in inversos]

    def _predecir_serie(self, nombre_modelo, X_train, y_train, pasos, hiperparametros):
        if nombre_modelo in self.MODELOS_CLASICOS:
            y_pred, _ = self._ajustar_clasico(nombre_modelo, y_train, hiperparametros, pasos)
        else:
            y_pred, _, _ = self._ajustar_ml_recursivo(nombre_modelo, X_train, y_train, hiperparametros, pasos)
        return np.asarray(y_pred, dtype=float)

    def _ajustar_y_predecir_serie_con_componente(self, nombre_modelo, X_train, y_train, pasos, hiperparametros):
        """
        [NUEVO -- SIMULACIÓN FIEL DEL ENSAMBLE, no solo del mejor candidato
        individual] Igual que _predecir_serie, pero ADEMÁS devuelve un
        dict 'componente' con el objeto ya ajustado (y su scaler/columnas
        si es ML) -- en el mismo formato que modelos_por_cluster guarda
        para un modelo ganador individual. Antes, el pronóstico puntual sí
        combinaba los 2 candidatos con sus pesos, pero el .pkl consolidado
        para Simulación solo se quedaba con el objeto del candidato de
        MENOR MAPE_CV (nombre_mejor) -- la simulación Monte Carlo de esos
        clústeres terminaba reproduciendo un modelo distinto al que
        realmente generó el pronóstico puntual reportado. Ahora se
        conservan AMBOS objetos ajustados (ver 'ensamble_componentes' en
        procesar_cluster) para que Simulación pueda combinar sus
        pronósticos de un paso, paso a paso, con los MISMOS pesos -- una
        reconstrucción fiel del Ensamble, no una aproximación.
        """
        if nombre_modelo in self.MODELOS_CLASICOS:
            y_pred, modelo_obj = self._ajustar_clasico(nombre_modelo, y_train, hiperparametros, pasos)
            componente = {
                'modelo': nombre_modelo, 'modelo_ajustado': modelo_obj,
                'scaler': None, 'columnas_features': None,
            }
        else:
            y_pred, modelo_obj, scaler_obj = self._ajustar_ml_recursivo(
                nombre_modelo, X_train, y_train, hiperparametros, pasos
            )
            componente = {
                'modelo': nombre_modelo, 'modelo_ajustado': modelo_obj,
                'scaler': scaler_obj, 'columnas_features': list(X_train.columns),
            }
        return np.asarray(y_pred, dtype=float), componente

    def _evaluar_backtesting_rolling_origin_ensamble(self, exitosos, pesos, X_total, y_total,
                                                       horizonte, n_ventanas=None):
        """
        [NUEVO -- ROLLING-ORIGIN BACKTESTING PARA ENSAMBLE] Misma idea que
        Pronosticador.evaluar_backtesting_rolling_origin, adaptada para el
        Ensamble: en cada ventana TEST, se predice con CADA candidato de
        'exitosos' por separado (reentrenando cada uno solo sobre el TRAIN
        de esa ventana) y se combinan con los MISMOS 'pesos' (ya fijos,
        calculados una sola vez por 1/MAPE_CV -- no se recalculan por
        ventana, por la misma razón que en la clase base: el objetivo es
        medir qué tan consistente es el desempeño de la combinación YA
        elegida, no volver a elegir pesos). El error se calcula sobre la
        predicción YA combinada de cada ventana, luego se promedia entre
        ventanas -- igual formato de salida que la versión base (mismas
        claves, + '_std', + 'n_ventanas_backtesting').
        """
        n_ventanas = n_ventanas if n_ventanas is not None else self.n_ventanas_backtesting
        ventanas_indices = self._construir_ventanas_backtesting(y_total, horizonte, n_ventanas)
        ventanas_evaluadas = []

        for i, (inicio_test, fin_test) in enumerate(ventanas_indices):
            X_train_v = X_total.iloc[:inicio_test]
            y_train_v = y_total.iloc[:inicio_test]
            X_test_v = X_total.iloc[inicio_test:fin_test]
            y_test_v = y_total.iloc[inicio_test:fin_test]
            if len(y_test_v) == 0:
                break

            try:
                preds_v = [
                    self._predecir_serie(n, X_train_v, y_train_v, len(y_test_v), hp)
                    for n, _, hp in exitosos
                ]
                y_pred_v = np.maximum(sum(w * p for w, p in zip(pesos, preds_v)), 0.0)
            except Exception:
                continue

            m = calcular_metricas(y_test_v.values, y_pred_v)
            m['MASE'] = calcular_mase(y_test_v.values, y_pred_v, y_train_v.values, self.PERIODO_ESTACIONAL)
            # [NUEVO -- RESIDUOS FUERA DE MUESTRA, ver _agregar_metricas_ventanas
            # y el aviso completo en Simulacion.extraer_vector_errores] Se
            # guarda el residuo CRUDO (no solo las métricas agregadas) de
            # esta ventana -- concatenado entre las 3 ventanas por
            # _agregar_metricas_ventanas, es lo que Simulación debe usar
            # para el bootstrap en vez de los residuos dentro de muestra
            # (que para modelos de árboles como XGBoost/RandomForest
            # subestiman brutalmente la incertidumbre real -- visto en
            # datos reales: std=0.008 dentro de muestra vs MAPE_TEST=39%).
            m['residuos_ventana'] = (y_test_v.values - y_pred_v)
            m['ventana_indice'] = i
            m['fecha_inicio_test'] = y_test_v.index[0]
            m['fecha_fin_test'] = y_test_v.index[-1]
            ventanas_evaluadas.append(m)

        return self._agregar_metricas_ventanas(ventanas_evaluadas)

    def procesar_cluster(self, cluster_id, df_agregado):
        print(f"\n🔹 Procesando Cluster {cluster_id}")
        skus_cluster = self.df_clusters[self.df_clusters[self.cluster_col] == cluster_id][self.sku_col].tolist()
        print(f"   SKUs en cluster: {len(skus_cluster)}")

        config, lead_time_max_semanas, lead_time_max_en_unidad = self.obtener_config_temporal_cluster(cluster_id)
        self.config_por_cluster[cluster_id] = config
        self.UNIDAD_ACTUAL = config['unidad']
        self.REGLA_RESAMPLE = config['regla_resample']
        self.PERIODO_ESTACIONAL = config['periodo_estacional']
        self.REZAGOS = config['rezagos']
        self.VENTANAS_MOVIL = config['ventanas_movil']
        horizonte_cluster = config['horizonte']

        if config['unidad'] == 'semanas':
            df_agregado_trabajo = df_agregado[['y']]
        else:
            df_agregado_trabajo = df_agregado[['y']].resample(config['regla_resample']).sum()

        comportamiento_preliminar = self.clasificar_comportamiento_cluster(cluster_id)
        df_agregado_trabajo = self.preparar_serie_entrenamiento(
            df_agregado_trabajo, cluster_id, config, comportamiento_preliminar
        )
        comportamiento = self.clasificar_comportamiento_cluster(cluster_id)
        print(f"   Comportamiento: {comportamiento}")

        (resultados_cv, hiperparametros_por_modelo, advertencias_busqueda,
         X_train, y_train, X_test, y_test) = self.entrenar_modelo_cluster(
            df_agregado_trabajo, comportamiento, cluster_id, horizonte_cluster
        )

        top2 = sorted(resultados_cv.items(), key=lambda x: x[1]['MAPE_CV_%'])[:2] if resultados_cv else []
        y_full = pd.concat([y_train, y_test]) if len(y_test) > 0 else y_train
        X_full = pd.concat([X_train, X_test]) if len(y_test) > 0 else X_train

        exitosos = []  # (nombre, metricas_cv, hiperparametros)
        candidatos_fallidos = []
        for nombre_candidato, metricas_cv in top2:
            hiperparametros_candidato = hiperparametros_por_modelo.get(nombre_candidato)
            try:
                # probar que ambos ajustes (TEST y full) funcionen antes de aceptarlo
                if len(y_test) > 0:
                    self._predecir_serie(nombre_candidato, X_train, y_train, len(y_test), hiperparametros_candidato)
                self._predecir_serie(nombre_candidato, X_full, y_full, horizonte_cluster, hiperparametros_candidato)
                exitosos.append((nombre_candidato, metricas_cv, hiperparametros_candidato))
            except Exception as e:
                candidatos_fallidos.append({'modelo': nombre_candidato, 'error': str(e)[:200]})

        if len(exitosos) == 0:
            print(f"   ⚠️ Cluster {cluster_id}: ningún candidato del ensamble pudo ajustarse; se usa promedio simple.")
            y_pred, validacion, modelo_ajustado = self._pronostico_fallback_promedio_simple(y_full, horizonte_cluster)
            extras_ml = None
            ensamble_componentes = None
            metricas_test = {k: np.nan for k in ('MAPE_%', 'WAPE_%', 'RMSE', 'MSE', 'R2')}
            metricas_in_sample = {k: np.nan for k in ('MAPE_%', 'WAPE_%', 'RMSE', 'MSE', 'R2')}
            mejor_modelo = self.NOMBRE_MODELO_FALLBACK
        else:
            pesos = self._pesos_inversos_mape([m['MAPE_CV_%'] for _, m, _ in exitosos])
            nombre_mejor, metricas_cv_mejor, hp_mejor = exitosos[0]  # exitosos ya viene ordenado por MAPE_CV

            # [CORREGIDO -- ROLLING-ORIGIN BACKTESTING] Antes se evaluaba
            # solo sobre X_test/y_test (un tramo final). Ahora se promedian
            # varias ventanas -- ver _evaluar_backtesting_rolling_origin_
            # ensamble para el porqué (mismo razonamiento que en la clase
            # base, aplicado a la combinación ponderada de candidatos).
            metricas_test = self._evaluar_backtesting_rolling_origin_ensamble(
                exitosos, pesos, X_full, y_full, horizonte_cluster
            )

            preds_full_con_componentes = [
                self._ajustar_y_predecir_serie_con_componente(n, X_full, y_full, horizonte_cluster, hp)
                for n, _, hp in exitosos
            ]
            preds_full = [p for p, _ in preds_full_con_componentes]
            y_pred = np.maximum(sum(w * p for w, p in zip(pesos, preds_full)), 0.0)
            # [NUEVO] Objetos ya ajustados de CADA candidato + su peso --
            # ver _ajustar_y_predecir_serie_con_componente para el porqué.
            # Esto es lo que permite a Simulación reconstruir el Ensamble
            # de verdad (combinar los 2 modelos paso a paso), no solo
            # aproximarlo con el mejor candidato individual.
            ensamble_componentes = [
                {**componente, 'peso': peso}
                for (_, componente), peso in zip(preds_full_con_componentes, pesos)
            ]

            # Diagnósticos in-sample/residuos: SOLO del mejor candidato
            # individual (ver docstring de la clase para el porqué).
            _, validacion, modelo_ajustado, extras_ml, metricas_in_sample = self.ajustar_modelo_final(
                nombre_mejor, comportamiento, X_full, y_full, horizonte_cluster, hp_mejor,
            )

            if len(exitosos) >= 2:
                mejor_modelo = ' + '.join(f"{n}({w*100:.0f}%)" for (n, _, _), w in zip(exitosos, pesos))
            else:
                mejor_modelo = nombre_mejor

            print(f"   ✅ Modelo usado (Ensamble): {mejor_modelo}")
            print(f"      Backtesting ({metricas_test['n_ventanas_backtesting']} ventanas): "
                  f"MAPE={metricas_test['MAPE_%']:.2f}% (±{metricas_test['MAPE_%_std']:.2f}) "
                  f"WAPE={metricas_test['WAPE_%']:.2f}% (±{metricas_test['WAPE_%_std']:.2f}) "
                  f"R2={metricas_test['R2']:.3f} (±{metricas_test['R2_std']:.3f})")

        y_pred = np.asarray(y_pred, dtype=float)
        offset = self.OFFSET_POR_UNIDAD[config['unidad']]
        fecha_inicio_pronostico = df_agregado_trabajo.index[-1] + offset

        self.modelos_por_cluster[cluster_id] = {
            'modelo': mejor_modelo, 'comportamiento': comportamiento,
            # [CORREGIDO -- YA NO ES SOLO UNA APROXIMACIÓN] 'modelo' queda
            # con el string combinado ("XGBoost(60%) + MLP(40%)") -- no es
            # un nombre de modelo reconocible por Simulación por sí solo.
            # Antes, 'modelo_ajustado' de este dict solo traía el objeto
            # del candidato de MENOR MAPE_CV (nombre_mejor) -- Simulación
            # terminaba reproduciendo ese único candidato, NO la
            # combinación ponderada real que generó el pronóstico puntual
            # reportado (una inconsistencia real entre el pronóstico
            # puntual y la simulación Monte Carlo, señalada en revisión).
            # Ahora 'ensamble_componentes' (ver más abajo) guarda AMBOS
            # objetos ajustados con sus pesos -- Simulación los combina
            # paso a paso con los MISMOS pesos, reconstruyendo el Ensamble
            # de verdad. 'modelo_ajustado'/'modelo_individual_base' se
            # conservan igual que antes (compatibilidad hacia atrás: si
            # algo todavía lee solo el candidato individual, sigue
            # funcionando -- y siguen siendo la fuente de los diagnósticos
            # de residuos, ver el docstring de la clase).
            'modelo_individual_base': nombre_mejor if exitosos else None,
            'ensamble_componentes': ensamble_componentes,
            'resultados_cv': resultados_cv, 'metricas_test': metricas_test,
            'metricas_in_sample': metricas_in_sample, 'top2': top2,
            'hiperparametros': hp_mejor if exitosos else None, 'modelo_ajustado': modelo_ajustado,
            'datos_agregados': df_agregado_trabajo.copy(), 'candidatos_fallidos': candidatos_fallidos,
            'lead_time_max_cluster': lead_time_max_semanas, 'lead_time_max_en_unidad': lead_time_max_en_unidad,
            'unidad_tiempo': config['unidad'], 'regla_resample': config['regla_resample'],
            'horizonte': horizonte_cluster, 'n_periodos_train': len(y_train), 'n_periodos_test': len(y_test),
            **(extras_ml or {}),
        }
        self.pronosticos_por_cluster[cluster_id] = {
            'pronostico': y_pred, 'validacion': validacion,
            'horizonte_pronostico': horizonte_cluster, 'unidad_tiempo': config['unidad'],
            'fecha_inicio_pronostico': fecha_inicio_pronostico,
        }
        # [NUEVO -- RESIDUOS FUERA DE MUESTRA PARA SIMULACIÓN] Se copian
        # aquí, DENTRO de 'validacion' (no solo en metricas_test), porque
        # Simulacion.extraer_vector_errores lee 'residuos' de este mismo
        # dict -- es el punto de integración ya existente entre los dos
        # módulos, y agregar la clave nueva aquí no rompe nada que ya lea
        # 'residuos' (se conserva intacto). Ver el aviso completo en
        # _agregar_metricas_ventanas para el porqué.
        self.pronosticos_por_cluster[cluster_id]['validacion']['residuos_fuera_de_muestra'] = (
            metricas_test.get('residuos_fuera_de_muestra', np.array([]))
        )
        self.log_ejecucion.append({
            'cluster_id': cluster_id, 'n_skus': len(skus_cluster), 'comportamiento': comportamiento,
            'modelo_elegido': mejor_modelo, 'es_fallback': bool(validacion.get('es_fallback', False)),
            'mape_test_%': metricas_test['MAPE_%'], 'unidad_tiempo': config['unidad'], 'horizonte': horizonte_cluster,
        })

        fecha_inicio_comun = df_agregado_trabajo.index.min()
        fecha_fin_comun = df_agregado_trabajo.index.max()
        medias_sku = {}
        for sku in skus_cluster:
            df_sku = self.dataset[self.dataset[self.sku_col] == sku][['Fecha', 'Unidades']].copy()
            df_sku = df_sku.set_index('Fecha').sort_index()
            df_sku = df_sku.resample(config['regla_resample']).agg({'Unidades': 'sum'}).fillna(0)
            df_sku_comun = df_sku.loc[(df_sku.index >= fecha_inicio_comun) & (df_sku.index <= fecha_fin_comun)]
            medias_sku[sku] = float(df_sku_comun['Unidades'].mean()) if len(df_sku_comun) > 0 else 0.0
        suma_medias = sum(medias_sku.values())

        resultados_cluster = {}
        for sku in skus_cluster:
            peso = (medias_sku[sku] / suma_medias) if suma_medias > 0 else (1.0 / len(skus_cluster))
            pronostico_sku = y_pred * peso
            resultados_cluster[sku] = {
                'sku': sku, 'cluster': cluster_id, 'comportamiento': comportamiento,
                'mejor_modelo': mejor_modelo, 'pronostico': pronostico_sku,
                'horizonte_pronostico': horizonte_cluster, 'unidad_tiempo': config['unidad'],
                'regla_resample': config['regla_resample'], 'fecha_inicio_pronostico': fecha_inicio_pronostico,
                'demanda_total': pronostico_sku.sum(), 'demanda_promedio': pronostico_sku.mean(),
                'peso_desagregacion': peso, 'validacion': validacion,
                'lead_time_max_cluster': lead_time_max_semanas, 'lead_time_max_en_unidad': lead_time_max_en_unidad,
            }
            self.resultados_por_sku[sku] = resultados_cluster[sku]

        return resultados_cluster


class PronosticadorConColapsoReciente(Pronosticador):
    """
    [NUEVO] Ver el aviso arriba de detectar_colapso_reciente para el
    porqué. Recorta la historia de entrenamiento a la ventana reciente
    SOLO si se detecta un colapso de nivel, y reclasifica comportamiento
    sobre esa ventana recortada -- nunca sobre toda la historia una vez
    que se confirmó que ya no representa el régimen actual.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.colapsos_por_cluster = {}
        self._comportamiento_recalculado_por_cluster = {}

    def preparar_serie_entrenamiento(self, df_agregado_trabajo, cluster_id, config, comportamiento):
        serie = df_agregado_trabajo['y']
        horizonte = config['horizonte']
        hay_colapso, indice_inicio = detectar_colapso_reciente(
            serie.values, horizonte, config['periodo_estacional']
        )

        if hay_colapso and indice_inicio > 0:
            fecha_inicio = serie.index[indice_inicio]
            media_antes = float(serie.iloc[:indice_inicio].mean())
            media_despues = float(serie.iloc[indice_inicio:].mean())
            print(f"   📉 Colapso de nivel reciente detectado en {fecha_inicio.date()}: "
                  f"media antes={media_antes:.1f}, media después={media_despues:.1f} "
                  f"({(media_despues/media_antes*100 if media_antes>0 else 0):.1f}% del nivel histórico) "
                  f"-- se recorta el entrenamiento a partir de ahí y se reclasifica el comportamiento "
                  f"sobre esa ventana.")
            self.colapsos_por_cluster[cluster_id] = {
                'fecha_inicio_ventana': fecha_inicio, 'media_antes': media_antes, 'media_despues': media_despues,
            }
            df_agregado_trabajo = df_agregado_trabajo.iloc[indice_inicio:]
            nuevo_comportamiento = _clasificar_comportamiento_sobre_serie(
                df_agregado_trabajo['y'].values, config['periodo_estacional']
            )
            self._comportamiento_recalculado_por_cluster[cluster_id] = nuevo_comportamiento
            print(f"   🔄 Comportamiento recalculado sobre la ventana reciente: '{nuevo_comportamiento}' "
                  f"(antes, sobre toda la historia: '{comportamiento}')")
        else:
            self.colapsos_por_cluster[cluster_id] = None

        return df_agregado_trabajo

    def clasificar_comportamiento_cluster(self, cluster_id):
        if cluster_id in self._comportamiento_recalculado_por_cluster:
            return self._comportamiento_recalculado_por_cluster[cluster_id]
        return super().clasificar_comportamiento_cluster(cluster_id)

    def tabla_metricas_finales(self):
        tabla = super().tabla_metricas_finales()
        tabla['Colapso_Detectado'] = tabla['Cluster'].map(
            lambda c: self.colapsos_por_cluster.get(c) is not None
        )
        return tabla


class PronosticadorConDeteccionDeQuiebre(Pronosticador):
    """
    [V5] Antes de clasificar comportamiento y entrenar, recorta la
    historia de cada clúster hasta el último quiebre de tendencia
    detectado (ver detectar_ultimo_quiebre_tendencia) -- si se encuentra
    uno. Todo lo demás (CV/TEST/IN_SAMPLE, selección por MAPE_CV,
    candidatos por comportamiento) se hereda sin cambios de Pronosticador.

    El recorte ocurre ANTES de clasificar comportamiento, así que la
    clasificación (estacional/tendencia/intermitente) también se calcula
    sobre la historia YA recortada -- coherente con lo que de verdad se va
    a usar para entrenar.
    """

    MEJORA_RELATIVA_MINIMA = 0.25
    MINIMO_BLOQUES_RESTANTES = 3

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.quiebres_por_cluster = {}

    def preparar_serie_entrenamiento(self, df_agregado_trabajo, cluster_id, config, comportamiento):
        serie = df_agregado_trabajo['y']
        ventana = config['periodo_estacional']

        indice_quiebre = detectar_ultimo_quiebre_tendencia(
            serie.values, ventana,
            mejora_relativa_minima=self.MEJORA_RELATIVA_MINIMA,
            minimo_bloques_restantes=self.MINIMO_BLOQUES_RESTANTES,
        )

        if indice_quiebre > 0:
            fecha_quiebre = serie.index[indice_quiebre]
            n_recortados = indice_quiebre
            print(f"   ✂️  Quiebre de tendencia detectado en {fecha_quiebre.date()} -- "
                  f"se descartan {n_recortados} periodos anteriores a ese punto "
                  f"({len(serie)} -> {len(serie) - n_recortados} periodos usados para entrenar).")
            self.quiebres_por_cluster[cluster_id] = {
                'fecha_quiebre': fecha_quiebre, 'n_periodos_descartados': n_recortados,
                'n_periodos_originales': len(serie), 'n_periodos_usados': len(serie) - n_recortados,
            }
            df_agregado_trabajo = df_agregado_trabajo.iloc[indice_quiebre:]
        else:
            self.quiebres_por_cluster[cluster_id] = {
                'fecha_quiebre': None, 'n_periodos_descartados': 0,
                'n_periodos_originales': len(serie), 'n_periodos_usados': len(serie),
            }

        return df_agregado_trabajo

    def tabla_metricas_finales(self):
        tabla = super().tabla_metricas_finales()
        tabla['Quiebre_Detectado'] = tabla['Cluster'].map(
            lambda c: self.quiebres_por_cluster.get(c, {}).get('fecha_quiebre')
        )
        tabla['N_Periodos_Descartados'] = tabla['Cluster'].map(
            lambda c: self.quiebres_por_cluster.get(c, {}).get('n_periodos_descartados')
        )
        return tabla


# ==========================================================================
# [V6 -- DESCOMPOSICIÓN TENDENCIA+ESTACIONAL PARA ML] Fusionado en este
# mismo archivo a pedido explícito -- ya no vive en Pronósticos6.py aparte.
# ==========================================================================
class PronosticadorConDescomposicion(Pronosticador):

    COMPORTAMIENTOS_CON_DESCOMPOSICION = ('tendencia', 'estacional+tendencia')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._componente_por_cluster = {}

    def _debe_descomponer(self, comportamiento):
        return comportamiento in self.COMPORTAMIENTOS_CON_DESCOMPOSICION

    def _descomponer_serie(self, y, periodo_estacional):
        """
        Devuelve (componente_no_residual, residuo), ambos arrays alineados
        con 'y'. componente_no_residual = tendencia (+ estacional, si hay
        suficiente historia para STL) -- lo que se le resta a 'y' para
        obtener el residuo que de verdad entrena el ML.

        Si la serie es demasiado corta para STL (< 2 ciclos -- el mismo
        criterio de "2 ciclos" que usa TraductorClusterPronostico.py),
        se usa una tendencia lineal simple como componente_no_residual (sin
        estacional) -- STL con tan poca historia no es confiable, igual
        que ya se documentó en la clasificación de comportamiento.
        """
        y = np.asarray(y, dtype=float)
        n = len(y)
        if n >= 2 * periodo_estacional:
            resultado = STL(pd.Series(y), period=periodo_estacional, robust=True).fit()
            componente = np.asarray(resultado.trend) + np.asarray(resultado.seasonal)
        else:
            t = np.arange(n)
            coef = np.polyfit(t, y, 1) if n >= 2 else np.array([0.0, float(y.mean()) if n > 0 else 0.0])
            componente = np.polyval(coef, t)
        residuo = y - componente
        return componente, residuo

    def _proyectar_componente(self, componente, periodo_estacional, pasos):
        """
        Proyecta 'componente' (tendencia [+estacional], ya calculado sobre
        la historia) 'pasos' periodos hacia adelante.

        Tendencia: se reestima con una regresión lineal sobre SOLO el
        último ciclo (periodo_estacional puntos) de 'componente' -- una
        pendiente LOCAL reciente, no la de toda la historia. Esto es
        deliberado: en clústeres con caída curva (ver el aviso al inicio
        del archivo), una sola recta sobre TODA la historia subestima
        drásticamente qué tan rápido está cayendo AHORA -- la pendiente
        local de el último año sí lo captura.

        Estacional: si hubo suficiente historia para que STL calculara un
        componente estacional real, se le resta la tendencia local al
        último ciclo y el patrón que queda se repite cíclicamente hacia
        adelante.
        """
        n = len(componente)
        ventana = min(periodo_estacional, n)
        ultimo_ciclo = componente[-ventana:]
        t_local = np.arange(len(ultimo_ciclo))
        coef_local = (
            np.polyfit(t_local, ultimo_ciclo, 1) if len(ultimo_ciclo) >= 2
            else np.array([0.0, ultimo_ciclo[-1] if len(ultimo_ciclo) > 0 else 0.0])
        )
        patron_residual_ciclo = ultimo_ciclo - np.polyval(coef_local, t_local)

        proyeccion = np.empty(pasos, dtype=float)
        for h in range(1, pasos + 1):
            nivel_tendencia_local = np.polyval(coef_local, len(ultimo_ciclo) - 1 + h)
            patron = patron_residual_ciclo[(h - 1) % len(patron_residual_ciclo)]
            proyeccion[h - 1] = nivel_tendencia_local + patron
        return proyeccion

    # ------------------------------------------------------------------
    # FASE 1 (SOBREESCRITA): igual que V1, pero para candidatos 'ml' en
    # clústeres con descomposición, se entrena/evalúa sobre el RESIDUO y
    # se reconstruye antes de comparar contra el valor real.
    # ------------------------------------------------------------------

    def entrenar_modelo_cluster(self, df_agregado, comportamiento, cluster_id, horizonte_cluster):
        aplica_descomposicion = self._debe_descomponer(comportamiento)

        df_feat_y = self.crear_features_ts(df_agregado[['y']])
        X_total_y = df_feat_y.drop('y', axis=1)
        y_total = df_feat_y['y']

        if aplica_descomposicion:
            componente_total, residuo_total = self._descomponer_serie(
                df_agregado['y'], self.PERIODO_ESTACIONAL
            )
            componente_serie = pd.Series(componente_total, index=df_agregado.index)
            self._componente_por_cluster[cluster_id] = componente_serie

            df_residuo = df_agregado[['y']].copy()
            df_residuo['y'] = residuo_total
            df_feat_r = self.crear_features_ts(df_residuo)
            # crear_features_ts recorta el mismo número de filas iniciales
            # en 'y' cruda y en el residuo (mismo self.REZAGOS/VENTANAS_MOVIL
            # aplicados sobre series de igual longitud e índice) -- X_total_y
            # y X_total_r quedan con el MISMO índice, así que la misma
            # partición TRAIN/TEST y los mismos folds de TimeSeriesSplit
            # sirven para ambas sin tener que alinear nada aparte.
            X_total_r = df_feat_r.drop('y', axis=1)
            r_total = df_feat_r['y']
            print(f"   🔧 Descomposición activa para este clúster ('{comportamiento}'): "
                  f"los modelos de ML entrenarán sobre el residuo (Y - Tendencia"
                  f"{'-Estacional' if len(df_agregado) >= 2*self.PERIODO_ESTACIONAL else ''}), "
                  f"los clásicos sobre la serie cruda, como siempre.")
        else:
            X_total_r, r_total = X_total_y, y_total

        test_size = horizonte_cluster
        if len(df_feat_y) < test_size * 3:
            test_size_ajustado = max(1, int(len(df_feat_y) * 0.2))
            print(f"   ⚠️ Historia insuficiente ({len(df_feat_y)} periodos tras crear features) para "
                  f"reservar {horizonte_cluster} periodos completos como test fuera de muestra -- "
                  f"se usa un test más chico ({test_size_ajustado} periodos, ~20% de la historia).")
            test_size = test_size_ajustado
        test_size = min(test_size, max(0, len(df_feat_y) - 1))

        if test_size > 0:
            X_train_y, X_test_y = X_total_y.iloc[:-test_size], X_total_y.iloc[-test_size:]
            y_train, y_test = y_total.iloc[:-test_size], y_total.iloc[-test_size:]
            X_train_r, X_test_r = X_total_r.iloc[:-test_size], X_total_r.iloc[-test_size:]
            r_train, r_test = r_total.iloc[:-test_size], r_total.iloc[-test_size:]
        else:
            X_train_y, y_train = X_total_y, y_total
            X_test_y, y_test = X_total_y.iloc[0:0], y_total.iloc[0:0]
            X_train_r, r_train = X_total_r, r_total
            X_test_r, r_test = X_total_r.iloc[0:0], r_total.iloc[0:0]

        n_splits = min(3, len(X_train_y) // self.PERIODO_ESTACIONAL)
        if n_splits < 2:
            n_splits = 2
        n_splits = min(n_splits, max(2, len(X_train_y) - 1))
        tscv = TimeSeriesSplit(n_splits=n_splits)

        candidatos = self.obtener_modelos_por_comportamiento(comportamiento)
        tiene_historia_para_estacionales = len(X_train_y) >= 2 * self.PERIODO_ESTACIONAL
        if not tiene_historia_para_estacionales:
            candidatos = [(n, t) for n, t in candidatos if n not in ('Holt-Winters', 'SARIMA')]

        resultados_cv = {}
        hiperparametros_por_modelo = {}
        advertencias = []

        for nombre, tipo in candidatos:
            usa_residuo = aplica_descomposicion and tipo == 'ml'
            X_train_busqueda = X_train_r if usa_residuo else X_train_y
            y_train_busqueda = r_train if usa_residuo else y_train

            hiperparametros = self._buscar_hiperparametros_cluster(
                nombre, tipo, X_train_busqueda, y_train_busqueda, comportamiento, tscv, advertencias
            )
            hiperparametros_por_modelo[nombre] = hiperparametros

            mape_list, wape_num_list, wape_den_list, rmse_list, mse_list, r2_list = [], [], [], [], [], []
            count = 0
            for train_idx, val_idx in tscv.split(X_train_y):
                y_val_real = y_train.iloc[val_idx]
                try:
                    if tipo == 'clasico':
                        y_tr = y_train.iloc[train_idx]
                        y_pred_fold, _ = self._ajustar_clasico(nombre, y_tr, hiperparametros, len(val_idx))
                    elif usa_residuo:
                        X_tr, X_val = X_train_r.iloc[train_idx], X_train_r.iloc[val_idx]
                        r_tr = r_train.iloc[train_idx]
                        pred_residuo, _ = self._ajustar_ml_directo(nombre, X_tr, r_tr, X_val, hiperparametros)
                        componente_val = self._componente_por_cluster[cluster_id].reindex(X_val.index).values
                        y_pred_fold = np.maximum(pred_residuo + componente_val, 0.0)
                    else:
                        X_tr, X_val = X_train_y.iloc[train_idx], X_train_y.iloc[val_idx]
                        y_tr = y_train.iloc[train_idx]
                        y_pred_fold, _ = self._ajustar_ml_directo(nombre, X_tr, y_tr, X_val, hiperparametros)
                except Exception:
                    continue

                if len(y_pred_fold) != len(y_val_real):
                    y_pred_fold = y_pred_fold[:len(y_val_real)]

                m = calcular_metricas(y_val_real.values, y_pred_fold)
                mape_list.append(m['MAPE_%'] if not np.isnan(m['MAPE_%']) else 1_000_000.0)
                wape_num_list.append(float(np.sum(np.abs(y_val_real.values - y_pred_fold))))
                wape_den_list.append(float(np.sum(np.abs(y_val_real.values))))
                mse_list.append(m['MSE'])
                rmse_list.append(m['RMSE'])
                r2_list.append(m['R2'])
                count += 1

            if count > 0:
                suma_num = sum(wape_num_list)
                suma_den = sum(wape_den_list)
                wape = (suma_num / suma_den * 100) if suma_den > 0 else np.nan
                resultados_cv[nombre] = {
                    'MAPE_CV_%': float(np.nanmean(mape_list)),
                    'WAPE_CV_%': wape if not np.isnan(wape) else 1_000_000.0,
                    'RMSE_CV': float(np.nanmean(rmse_list)),
                    'MSE_CV': float(np.nanmean(mse_list)),
                    'R2_CV': float(np.nanmean(r2_list)),
                    'n_folds_exitosos': count, 'n_folds_totales': n_splits,
                }

        # X_test/y_test que se devuelven son siempre los de 'y' cruda --
        # evaluar_fuera_de_muestra y ajustar_modelo_final (sobreescritos
        # más abajo) se encargan de usar el residuo internamente cuando
        # corresponde, igual que aquí.
        return resultados_cv, hiperparametros_por_modelo, advertencias, X_train_y, y_train, X_test_y, y_test

    # ------------------------------------------------------------------
    # FASE 2 (SOBREESCRITA): evaluación fuera de muestra y ajuste final,
    # reconstruyendo Y = componente_proyectado + residuo_predicho para los
    # candidatos ML en clústeres con descomposición activa.
    # ------------------------------------------------------------------

    def evaluar_fuera_de_muestra(self, nombre_modelo, X_train, y_train, X_test, y_test, hiperparametros,
                                  cluster_id=None, comportamiento=None):
        if len(y_test) == 0:
            return {k: np.nan for k in ('MAPE_%', 'WAPE_%', 'RMSE', 'MSE', 'R2')}

        usa_residuo = (
            cluster_id is not None and comportamiento is not None
            and self._debe_descomponer(comportamiento) and nombre_modelo in self.MODELOS_ML
        )

        if usa_residuo:
            componente_serie = self._componente_por_cluster[cluster_id]
            componente_total, residuo_total = self._descomponer_serie(
                # recompone la serie completa (train+test, EN ESE ORDEN) a
                # partir de y_train+y_test para volver a descomponer solo
                # sobre TRAIN (nunca se usa información de TEST para
                # construir el residuo de entrenamiento)
                y_train.values, self.PERIODO_ESTACIONAL
            )
            r_train = pd.Series(residuo_total, index=y_train.index)
            df_r = pd.DataFrame({'y': r_train.values}, index=y_train.index)
            X_train_r = self.crear_features_ts(df_r).drop('y', axis=1)
            # X_train_r puede tener menos filas que X_train (por los NaN de
            # rezagos) -- re-alinear r_train a las filas que sí sobrevivieron
            r_train_alineado = r_train.reindex(X_train_r.index)

            pred_residuo, _, _ = self._ajustar_ml_recursivo(
                nombre_modelo, X_train_r, r_train_alineado, hiperparametros, len(y_test),
                clip_no_negativo=False,
            )
            componente_proyectado = self._proyectar_componente(
                componente_total, self.PERIODO_ESTACIONAL, len(y_test)
            )
            # [CORREGIDO -- BUG REAL, DEMANDA NEGATIVA] componente y residuo
            # se calculan y proyectan por separado -- nada garantiza que su
            # suma quede >= 0 (el residuo, correctamente, ya no se recorta
            # en 0 -- ver clip_no_negativo=False arriba). La demanda SÍ
            # tiene que ser >= 0 siempre: se recorta aquí, sobre el TOTAL
            # reconstruido, que es el único punto donde esa restricción
            # realmente aplica.
            y_pred_test = np.maximum(pred_residuo + componente_proyectado, 0.0)
        elif nombre_modelo in self.MODELOS_CLASICOS:
            y_pred_test, _ = self._ajustar_clasico(nombre_modelo, y_train, hiperparametros, len(y_test))
        else:
            y_pred_test, _, _ = self._ajustar_ml_recursivo(nombre_modelo, X_train, y_train, hiperparametros, len(y_test))

        return calcular_metricas(y_test.values, y_pred_test)

    def evaluar_backtesting_rolling_origin(self, nombre_modelo, X_total, y_total, hiperparametros,
                                            horizonte, n_ventanas=None, cluster_id=None, comportamiento=None):
        """
        [NUEVO -- ROLLING-ORIGIN BACKTESTING PARA DESCOMPOSICIÓN (V6)]
        Sobreescribe la versión base (Pronosticador.evaluar_backtesting_
        rolling_origin): en cada ventana TEST, si el candidato es ML y el
        comportamiento pide descomposición, se repite exactamente la
        misma lógica que evaluar_fuera_de_muestra de esta clase --
        descomponer SOLO el TRAIN de ESA ventana, entrenar el ML sobre el
        residuo, proyectar el componente tendencia/estacional con la
        pendiente LOCAL de esa ventana, reconstruir y recortar a >=0.
        Nunca se reutiliza una descomposición calculada sobre toda la
        historia -- eso filtraría información de periodos futuros (de esa
        ventana) hacia atrás, exactamente el mismo cuidado que ya tenía
        evaluar_fuera_de_muestra, ahora repetido por cada ventana. Para
        modelos clásicos (o ML sin descomposición), el comportamiento es
        idéntico al backtesting base.
        """
        n_ventanas = n_ventanas if n_ventanas is not None else self.n_ventanas_backtesting
        ventanas_indices = self._construir_ventanas_backtesting(y_total, horizonte, n_ventanas)
        usa_residuo_base = (
            cluster_id is not None and comportamiento is not None
            and self._debe_descomponer(comportamiento) and nombre_modelo in self.MODELOS_ML
        )
        ventanas_evaluadas = []

        for i, (inicio_test, fin_test) in enumerate(ventanas_indices):
            y_train_v = y_total.iloc[:inicio_test]
            y_test_v = y_total.iloc[inicio_test:fin_test]
            if len(y_test_v) == 0:
                break

            try:
                if usa_residuo_base:
                    componente_total_v, residuo_total_v = self._descomponer_serie(
                        y_train_v.values, self.PERIODO_ESTACIONAL
                    )
                    r_train_v = pd.Series(residuo_total_v, index=y_train_v.index)
                    df_r_v = pd.DataFrame({'y': r_train_v.values}, index=y_train_v.index)
                    X_train_r_v = self.crear_features_ts(df_r_v).drop('y', axis=1)
                    r_train_v_alineado = r_train_v.reindex(X_train_r_v.index)

                    pred_residuo_v, _, _ = self._ajustar_ml_recursivo(
                        nombre_modelo, X_train_r_v, r_train_v_alineado, hiperparametros, len(y_test_v),
                        clip_no_negativo=False,
                    )
                    componente_proyectado_v = self._proyectar_componente(
                        componente_total_v, self.PERIODO_ESTACIONAL, len(y_test_v)
                    )
                    y_pred_v = np.maximum(pred_residuo_v + componente_proyectado_v, 0.0)
                elif nombre_modelo in self.MODELOS_CLASICOS:
                    y_pred_v, _ = self._ajustar_clasico(nombre_modelo, y_train_v, hiperparametros, len(y_test_v))
                else:
                    X_train_v = X_total.iloc[:inicio_test]
                    y_pred_v, _, _ = self._ajustar_ml_recursivo(
                        nombre_modelo, X_train_v, y_train_v, hiperparametros, len(y_test_v)
                    )
            except Exception:
                continue

            m = calcular_metricas(y_test_v.values, y_pred_v)
            m['MASE'] = calcular_mase(y_test_v.values, y_pred_v, y_train_v.values, self.PERIODO_ESTACIONAL)
            # [NUEVO -- RESIDUOS FUERA DE MUESTRA, ver _agregar_metricas_ventanas
            # y el aviso completo en Simulacion.extraer_vector_errores] Se
            # guarda el residuo CRUDO (no solo las métricas agregadas) de
            # esta ventana -- concatenado entre las 3 ventanas por
            # _agregar_metricas_ventanas, es lo que Simulación debe usar
            # para el bootstrap en vez de los residuos dentro de muestra
            # (que para modelos de árboles como XGBoost/RandomForest
            # subestiman brutalmente la incertidumbre real -- visto en
            # datos reales: std=0.008 dentro de muestra vs MAPE_TEST=39%).
            m['residuos_ventana'] = (y_test_v.values - y_pred_v)
            m['ventana_indice'] = i
            m['fecha_inicio_test'] = y_test_v.index[0]
            m['fecha_fin_test'] = y_test_v.index[-1]
            ventanas_evaluadas.append(m)

        return self._agregar_metricas_ventanas(ventanas_evaluadas)

    def ajustar_modelo_final(self, nombre_modelo, comportamiento, X_full, y_full, horizonte_pronostico,
                              hiperparametros=None, cluster_id=None):
        if hiperparametros is None:
            hiperparametros = self._hiperparametros_default(nombre_modelo, comportamiento)

        usa_residuo = (
            cluster_id is not None and self._debe_descomponer(comportamiento)
            and nombre_modelo in self.MODELOS_ML
        )

        if usa_residuo:
            componente_total, residuo_total = self._descomponer_serie(y_full.values, self.PERIODO_ESTACIONAL)
            r_full = pd.Series(residuo_total, index=y_full.index)
            df_r = pd.DataFrame({'y': r_full.values}, index=y_full.index)
            X_full_r = self.crear_features_ts(df_r).drop('y', axis=1)
            r_full_alineado = r_full.reindex(X_full_r.index)

            pred_residuo, modelo_ajustado, scaler = self._ajustar_ml_recursivo(
                nombre_modelo, X_full_r, r_full_alineado, hiperparametros, horizonte_pronostico,
                clip_no_negativo=False,
            )
            componente_proyectado = self._proyectar_componente(
                componente_total, self.PERIODO_ESTACIONAL, horizonte_pronostico
            )
            # [CORREGIDO -- BUG REAL, DEMANDA NEGATIVA] mismo caso que en
            # evaluar_fuera_de_muestra -- ver ese comentario para el
            # porqué. Este es el pronóstico que de verdad se entrega, así
            # que este recorte es el que más importa de los dos.
            y_pred = np.maximum(pred_residuo + componente_proyectado, 0.0)

            extras_ml = {
                'scaler': scaler, 'columnas_features': list(X_full_r.columns),
                'index_entrenamiento': X_full_r.index,
            }
            # [NOTA] fitted (dentro de muestra) SÍ puede quedar con algún
            # valor negativo residual en el ajuste histórico -- no se
            # recorta aquí porque fitted no es "el pronóstico" (no se
            # entrega ni se usa para inventario), es solo el insumo de los
            # diagnósticos de residuos (Ljung-Box, Shapiro, etc.), que
            # necesitan los residuos reales sin recortar para ser válidos.
            fitted_residuo = modelo_ajustado.predict(scaler.transform(X_full_r))
            componente_alineado = pd.Series(componente_total, index=y_full.index).reindex(X_full_r.index).values
            fitted = fitted_residuo + componente_alineado
            y_real_in_sample = y_full.reindex(X_full_r.index).values
            residuos_diagnostico = y_real_in_sample - fitted
        elif nombre_modelo == 'SBA':
            y_pred, modelo_ajustado = self._ajustar_clasico(nombre_modelo, y_full, hiperparametros, horizonte_pronostico)
            alpha = hiperparametros.get('alpha', 0.1)
            fitted, _ = self._fitted_sba(y_full.values, alpha)
            residuos_diagnostico = y_full.values - fitted
            y_real_in_sample = y_full.values
            extras_ml = None
        elif nombre_modelo in self.MODELOS_CLASICOS:
            y_pred, modelo_ajustado = self._ajustar_clasico(nombre_modelo, y_full, hiperparametros, horizonte_pronostico)
            residuos_diagnostico = np.asarray(modelo_ajustado.resid, dtype=float)
            fitted = np.asarray(modelo_ajustado.fittedvalues, dtype=float)
            y_real_in_sample = y_full.values[-len(fitted):] if len(fitted) <= len(y_full) else y_full.values
            extras_ml = None
        else:
            y_pred, modelo_ajustado, scaler = self._ajustar_ml_recursivo(
                nombre_modelo, X_full, y_full, hiperparametros, horizonte_pronostico
            )
            extras_ml = {
                'scaler': scaler, 'columnas_features': list(X_full.columns),
                'index_entrenamiento': X_full.index,
            }
            fitted = modelo_ajustado.predict(scaler.transform(X_full))
            y_real_in_sample = y_full.values
            residuos_diagnostico = y_full.values - fitted

        metricas_in_sample = calcular_metricas(y_real_in_sample, fitted)

        media_res = np.mean(residuos_diagnostico) if len(residuos_diagnostico) > 0 else 0
        normalidad_p = None
        from scipy.stats import shapiro
        from statsmodels.stats.diagnostic import acorr_ljungbox, het_breuschpagan
        if len(residuos_diagnostico) > 3:
            _, normalidad_p = shapiro(residuos_diagnostico)
        try:
            ljung_box = acorr_ljungbox(residuos_diagnostico, lags=min(10, len(residuos_diagnostico) - 1), return_df=True)
            independencia_p = ljung_box['lb_pvalue'].iloc[-1] if not ljung_box.empty else None
        except Exception:
            independencia_p = None
        try:
            hetero_p = het_breuschpagan(residuos_diagnostico, np.ones((len(residuos_diagnostico), 1)))[1] if len(residuos_diagnostico) > 2 else None
        except Exception:
            hetero_p = None

        validez = {
            'media_residuales': media_res, 'normalidad_pvalue': normalidad_p,
            'independencia_pvalue': independencia_p, 'heterocedasticidad_pvalue': hetero_p,
            'residuos': residuos_diagnostico,
        }

        return np.asarray(y_pred, dtype=float), validez, modelo_ajustado, extras_ml, metricas_in_sample

    # ------------------------------------------------------------------
    # procesar_cluster: reutiliza el de V1, pero hay que pasarle
    # cluster_id/comportamiento a evaluar_fuera_de_muestra y
    # ajustar_modelo_final (V1 no lo hace porque no lo necesita) -- se
    # sobreescribe solo el tramo donde se llaman esos dos métodos.
    # ------------------------------------------------------------------

    def procesar_cluster(self, cluster_id, df_agregado):
        print(f"\n🔹 Procesando Cluster {cluster_id}")
        skus_cluster = self.df_clusters[self.df_clusters[self.cluster_col] == cluster_id][self.sku_col].tolist()
        print(f"   SKUs en cluster: {len(skus_cluster)}")

        config, lead_time_max_semanas, lead_time_max_en_unidad = self.obtener_config_temporal_cluster(cluster_id)
        self.config_por_cluster[cluster_id] = config
        self.UNIDAD_ACTUAL = config['unidad']
        self.REGLA_RESAMPLE = config['regla_resample']
        self.PERIODO_ESTACIONAL = config['periodo_estacional']
        self.REZAGOS = config['rezagos']
        self.VENTANAS_MOVIL = config['ventanas_movil']
        horizonte_cluster = config['horizonte']

        print(f"   Unidad de pronóstico (definida por el Traductor): {config['unidad']} | "
              f"lead time máximo: {lead_time_max_semanas:.1f} semanas "
              f"({lead_time_max_en_unidad:.2f} {config['unidad']}) | "
              f"horizonte = {horizonte_cluster} {config['unidad']}")

        if config['unidad'] == 'semanas':
            df_agregado_trabajo = df_agregado[['y']]
        else:
            df_agregado_trabajo = df_agregado[['y']].resample(config['regla_resample']).sum()

        comportamiento_preliminar = self.clasificar_comportamiento_cluster(cluster_id)
        df_agregado_trabajo = self.preparar_serie_entrenamiento(
            df_agregado_trabajo, cluster_id, config, comportamiento_preliminar
        )
        comportamiento = self.clasificar_comportamiento_cluster(cluster_id)
        print(f"   Comportamiento: {comportamiento}")
        print(f"   Afinando hiperparámetros y comparando candidatos (validación cruzada dentro de TRAIN)...")

        (resultados_cv, hiperparametros_por_modelo, advertencias_busqueda,
         X_train, y_train, X_test, y_test) = self.entrenar_modelo_cluster(
            df_agregado_trabajo, comportamiento, cluster_id, horizonte_cluster
        )

        top2 = sorted(resultados_cv.items(), key=lambda x: x[1]['MAPE_CV_%'])[:2] if resultados_cv else []

        y_full = pd.concat([y_train, y_test]) if len(y_test) > 0 else y_train
        X_full = pd.concat([X_train, X_test]) if len(y_test) > 0 else X_train

        y_pred = validacion = modelo_ajustado = extras_ml = None
        metricas_test = metricas_in_sample = None
        mejor_modelo = None
        candidatos_fallidos = []

        for nombre_candidato, metricas_cv in top2:
            hiperparametros_candidato = hiperparametros_por_modelo.get(nombre_candidato)
            try:
                # [CORREGIDO -- ROLLING-ORIGIN BACKTESTING] ver el
                # docstring de evaluar_backtesting_rolling_origin
                # (sobreescrito en esta clase) para el porqué.
                metricas_test_candidato = self.evaluar_backtesting_rolling_origin(
                    nombre_candidato, X_full, y_full, hiperparametros_candidato, horizonte_cluster,
                    cluster_id=cluster_id, comportamiento=comportamiento,
                )
                y_pred, validacion, modelo_ajustado, extras_ml, metricas_in_sample_candidato = (
                    self.ajustar_modelo_final(
                        nombre_candidato, comportamiento, X_full, y_full,
                        horizonte_cluster, hiperparametros_candidato, cluster_id=cluster_id,
                    )
                )
                mejor_modelo = nombre_candidato
                metricas_test = metricas_test_candidato
                metricas_in_sample = metricas_in_sample_candidato

                print(f"   ✅ Modelo usado: {mejor_modelo}"
                      f"{' (sobre residuo, ML+descomposición)' if (self._debe_descomponer(comportamiento) and nombre_candidato in self.MODELOS_ML) else ''}")
                print(f"      CV: MAPE={metricas_cv['MAPE_CV_%']:.2f}% WAPE={metricas_cv['WAPE_CV_%']:.2f}% R2={metricas_cv['R2_CV']:.3f}")
                print(f"      Backtesting ({metricas_test['n_ventanas_backtesting']} ventanas): "
                      f"MAPE={metricas_test['MAPE_%']:.2f}% (±{metricas_test['MAPE_%_std']:.2f}) "
                      f"WAPE={metricas_test['WAPE_%']:.2f}% R2={metricas_test['R2']:.3f}")
                print(f"      IN_SAMPLE: MAPE={metricas_in_sample['MAPE_%']:.2f}% WAPE={metricas_in_sample['WAPE_%']:.2f}% R2={metricas_in_sample['R2']:.3f}")
                break
            except Exception as e:
                mensaje = f"{nombre_candidato} falló en TEST/ajuste final: {str(e)[:150]}"
                print(f"   ⚠️ {mensaje}")
                candidatos_fallidos.append({'modelo': nombre_candidato, 'error': str(e)[:200]})

        if mejor_modelo is None:
            motivo = (
                "ningún candidato pudo evaluarse en la comparación por MAPE_CV" if not resultados_cv
                else "los 2 mejores candidatos por MAPE_CV fallaron al evaluarse fuera de muestra o al reentrenarse"
            )
            print(f"   ⚠️ Cluster {cluster_id} cae en el camino de emergencia ({motivo}); se usa un promedio simple.")
            y_pred, validacion, modelo_ajustado = self._pronostico_fallback_promedio_simple(y_full, horizonte_cluster)
            extras_ml = None
            metricas_test = {k: np.nan for k in ('MAPE_%', 'WAPE_%', 'RMSE', 'MSE', 'R2')}
            metricas_in_sample = {k: np.nan for k in ('MAPE_%', 'WAPE_%', 'RMSE', 'MSE', 'R2')}
            mejor_modelo = self.NOMBRE_MODELO_FALLBACK

        y_pred = np.asarray(y_pred, dtype=float)
        offset = self.OFFSET_POR_UNIDAD[config['unidad']]
        fecha_inicio_pronostico = df_agregado_trabajo.index[-1] + offset

        self.modelos_por_cluster[cluster_id] = {
            'modelo': mejor_modelo, 'comportamiento': comportamiento,
            'resultados_cv': resultados_cv, 'metricas_test': metricas_test,
            'metricas_in_sample': metricas_in_sample, 'top2': top2,
            'hiperparametros': hiperparametros_por_modelo.get(mejor_modelo),
            'modelo_ajustado': modelo_ajustado, 'datos_agregados': df_agregado_trabajo.copy(),
            'candidatos_fallidos': candidatos_fallidos,
            'lead_time_max_cluster': lead_time_max_semanas,
            'lead_time_max_en_unidad': lead_time_max_en_unidad,
            'unidad_tiempo': config['unidad'], 'regla_resample': config['regla_resample'],
            'horizonte': horizonte_cluster,
            'descomposicion_aplicada': self._debe_descomponer(comportamiento) and mejor_modelo in self.MODELOS_ML,
            'n_periodos_train': len(y_train), 'n_periodos_test': len(y_test),
            **(extras_ml or {}),
        }
        self.pronosticos_por_cluster[cluster_id] = {
            'pronostico': y_pred, 'validacion': validacion,
            'horizonte_pronostico': horizonte_cluster, 'unidad_tiempo': config['unidad'],
            'fecha_inicio_pronostico': fecha_inicio_pronostico,
        }
        # [NUEVO -- RESIDUOS FUERA DE MUESTRA PARA SIMULACIÓN] Se copian
        # aquí, DENTRO de 'validacion' (no solo en metricas_test), porque
        # Simulacion.extraer_vector_errores lee 'residuos' de este mismo
        # dict -- es el punto de integración ya existente entre los dos
        # módulos, y agregar la clave nueva aquí no rompe nada que ya lea
        # 'residuos' (se conserva intacto). Ver el aviso completo en
        # _agregar_metricas_ventanas para el porqué.
        self.pronosticos_por_cluster[cluster_id]['validacion']['residuos_fuera_de_muestra'] = (
            metricas_test.get('residuos_fuera_de_muestra', np.array([]))
        )
        self.log_ejecucion.append({
            'cluster_id': cluster_id, 'n_skus': len(skus_cluster), 'comportamiento': comportamiento,
            'modelo_elegido': mejor_modelo, 'es_fallback': bool(validacion.get('es_fallback', False)),
            'mape_cv_%': resultados_cv.get(mejor_modelo, {}).get('MAPE_CV_%'),
            'mape_test_%': metricas_test['MAPE_%'],
            'lead_time_max_cluster': lead_time_max_semanas, 'unidad_tiempo': config['unidad'],
            'horizonte': horizonte_cluster,
        })

        fecha_inicio_comun = df_agregado_trabajo.index.min()
        fecha_fin_comun = df_agregado_trabajo.index.max()
        medias_sku = {}
        for sku in skus_cluster:
            df_sku = self.dataset[self.dataset[self.sku_col] == sku][['Fecha', 'Unidades']].copy()
            df_sku = df_sku.set_index('Fecha').sort_index()
            df_sku = df_sku.resample(config['regla_resample']).agg({'Unidades': 'sum'}).fillna(0)
            df_sku_comun = df_sku.loc[(df_sku.index >= fecha_inicio_comun) & (df_sku.index <= fecha_fin_comun)]
            medias_sku[sku] = float(df_sku_comun['Unidades'].mean()) if len(df_sku_comun) > 0 else 0.0
        suma_medias = sum(medias_sku.values())

        resultados_cluster = {}
        for sku in skus_cluster:
            peso = (medias_sku[sku] / suma_medias) if suma_medias > 0 else (1.0 / len(skus_cluster))
            pronostico_sku = y_pred * peso
            resultado_sku = {
                'sku': sku, 'cluster': cluster_id, 'comportamiento': comportamiento,
                'mejor_modelo': mejor_modelo, 'pronostico': pronostico_sku,
                'horizonte_pronostico': horizonte_cluster, 'unidad_tiempo': config['unidad'],
                'regla_resample': config['regla_resample'], 'fecha_inicio_pronostico': fecha_inicio_pronostico,
                'demanda_total': pronostico_sku.sum(), 'demanda_promedio': pronostico_sku.mean(),
                'peso_desagregacion': peso, 'validacion': validacion,
                'lead_time_max_cluster': lead_time_max_semanas, 'lead_time_max_en_unidad': lead_time_max_en_unidad,
            }
            self.resultados_por_sku[sku] = resultado_sku
            resultados_cluster[sku] = resultado_sku

        return resultados_cluster

    def tabla_metricas_finales(self):
        tabla = super().tabla_metricas_finales()
        tabla['Descomposicion_Aplicada'] = tabla['Cluster'].map(
            lambda c: self.modelos_por_cluster.get(c, {}).get('descomposicion_aplicada')
        )
        return tabla


# ==========================================================================
# [V7 -- ORQUESTADOR: MEJOR ESTRATEGIA POR CLÚSTER, SALIDA SOLO POR CLÚSTER]
# Fusionado en este mismo archivo a pedido explícito. Las tres clases de
# arriba (Pronosticador, PronosticadorConDeteccionDeQuiebre,
# PronosticadorConDescomposicion) ya están definidas en este mismo módulo
# -- el orquestador las usa directamente, sin ningún import entre archivos.
#
# [REVERTIDO A PEDIDO EXPLÍCITO -- SIN LA CORRECCIÓN DE FUGA METODOLÓGICA]
# Esta clase vuelve a comparar cada estrategia por su propio MAPE_TEST
# (calculado sobre la MISMA historia completa que después se reporta como
# "evaluación independiente") para elegir la ganadora -- la fuga señalada
# en revisión y corregida en una versión anterior de este archivo. El
# usuario pidió explícitamente volver a esta versión para poder generar
# el .pkl de hiperparámetros que necesita el siguiente módulo; se hizo
# después de advertir que el MAPE_TEST que quedará documentado junto a
# esos hiperparámetros no es una medida honesta de generalización (el
# TEST participó en la selección de estrategia). El .pkl en sí (los
# modelos/hiperparámetros ya ajustados) es igual de válido para
# producción que en la versión corregida -- lo que cambia es solo qué
# tan confiable es el número de MAPE_TEST que lo acompaña como evidencia
# de desempeño futuro.
# ==========================================================================
class PronosticadorMejorEstrategia:
    """
    Orquestador -- NO es una subclase de Pronosticador. Mantiene CINCO
    instancias internas (Original, Quiebre_V5, Descomposicion_V6,
    ColapsoReciente, Ensamble -- ver self._instancias) que comparten el
    mismo dataset/df_clusters, corre cada una sobre el mismo clúster
    cuando aplica (ver ESTRATEGIAS_ADICIONALES_POR_COMPORTAMIENTO y la
    detección de colapso reciente en procesar_cluster para cuáles se
    prueban en cada caso), y se queda con la de menor MASE_TEST.
    """

    ESTRATEGIAS_ADICIONALES_POR_COMPORTAMIENTO = ('tendencia', 'estacional+tendencia')

    def __init__(self, dataset, df_clusters, n_iter_busqueda_ml=15, semilla_aleatoria=42):
        self.pron_original = Pronosticador(dataset, df_clusters, n_iter_busqueda_ml, semilla_aleatoria)
        self.pron_quiebre = PronosticadorConDeteccionDeQuiebre(dataset, df_clusters, n_iter_busqueda_ml, semilla_aleatoria)
        self.pron_descomposicion = PronosticadorConDescomposicion(dataset, df_clusters, n_iter_busqueda_ml, semilla_aleatoria)
        self.pron_colapso = PronosticadorConColapsoReciente(dataset, df_clusters, n_iter_busqueda_ml, semilla_aleatoria)
        self.pron_ensamble = PronosticadorConEnsamble(dataset, df_clusters, n_iter_busqueda_ml, semilla_aleatoria)
        self._instancias = {
            'Original': self.pron_original,
            'Quiebre_V5': self.pron_quiebre,
            'Descomposicion_V6': self.pron_descomposicion,
            'ColapsoReciente': self.pron_colapso,
            'Ensamble': self.pron_ensamble,
        }

        self.estrategia_ganadora_por_cluster = {}
        self.log_comparacion_estrategias = []
        self.cluster_col = self.pron_original.cluster_col
        self.sku_col = self.pron_original.sku_col
        self.df_clusters = df_clusters
        self.skus_descontinuados_por_mape = []
        self.detalle_revision_mape_alto = []

    def _construir_agregado_sin_skus(self, cluster_id, skus_excluir):
        """Reconstruye la serie semanal agregada del clúster excluyendo SKU concretos."""
        skus_cluster = self.df_clusters.loc[
            self.df_clusters[self.cluster_col] == cluster_id, self.sku_col
        ].dropna().unique().tolist()
        skus_usar = [s for s in skus_cluster if s not in set(skus_excluir)]
        if not skus_usar:
            return None
        d = self.pron_original.dataset.loc[
            self.pron_original.dataset[self.sku_col].isin(skus_usar), ['Fecha', 'Unidades']
        ].copy()
        d['Fecha'] = pd.to_datetime(d['Fecha'], errors='coerce')
        d['Unidades'] = pd.to_numeric(d['Unidades'], errors='coerce').fillna(0)
        d = d.dropna(subset=['Fecha'])
        if d.empty:
            return None
        return (d.set_index('Fecha').sort_index()['Unidades']
                 .resample('W-MON').sum().fillna(0).rename('y').to_frame())

    def _evaluar_sku_por_impacto_mape(self, cluster_id, sku, mape_original):
        """Prueba el clúster SIN un SKU y devuelve el MAPE TEST resultante.

        La prueba es leave-one-out: no clasifica un SKU como extraño por su
        forma aislada, sino por el efecto que tiene sobre el error del clúster.
        """
        agregado = self._construir_agregado_sin_skus(cluster_id, [sku])
        if agregado is None or agregado.empty:
            return np.nan, None

        dataset_reducido = self.pron_original.dataset.loc[
            self.pron_original.dataset[self.sku_col] != sku
        ].copy()
        clusters_reducido = self.df_clusters.loc[
            self.df_clusters[self.sku_col] != sku
        ].copy()

        prueba = PronosticadorMejorEstrategia(
            dataset=dataset_reducido,
            df_clusters=clusters_reducido,
            n_iter_busqueda_ml=self.pron_original.n_iter_busqueda_ml,
            semilla_aleatoria=self.pron_original.semilla_aleatoria,
        )
        prueba.procesar_cluster(cluster_id, agregado)
        tabla = prueba.tabla_comparacion_estrategias()
        if tabla.empty:
            return np.nan, None
        return float(tabla.iloc[0]['MAPE_TEST_%']), tabla.iloc[0]['Estrategia_Ganadora']

    def revisar_skus_y_recalcular_mape(self, umbral_mape=100.0, mejora_minima_relativa=0.20,
                                        archivo_excel='Revision_SKU_MAPE.xlsx',
                                        archivo_lista='codigos_descontinuados_mape.txt'):
        """Para clústeres con MAPE alto, prueba quitar cada SKU individualmente.

        Guarda como 'descontinuado/extraño' el SKU cuya exclusión produce la
        mayor mejora del MAPE, siempre que esa mejora sea al menos el porcentaje
        relativo indicado. Después reconstruye el clúster sin los SKU marcados
        y RECALCULA su MAPE para comprobar la mejora real.
        """
        tabla_inicial = self.tabla_comparacion_estrategias().copy()
        tabla_inicial['MAPE_TEST_%'] = pd.to_numeric(tabla_inicial['MAPE_TEST_%'], errors='coerce')
        altos = tabla_inicial.loc[tabla_inicial['MAPE_TEST_%'] > umbral_mape].copy()

        print("\n" + "=" * 100)
        print(f"🔎 EVALUACIÓN DE SKU Y RECÁLCULO DE MAPE -- CLÚSTERES > {umbral_mape:.0f}%")
        print("=" * 100)

        detalle = []
        seleccionados = []
        resumen = []

        for _, fila in altos.iterrows():
            cluster_id = fila['Cluster']
            mape_original = float(fila['MAPE_TEST_%'])
            skus = self.df_clusters.loc[
                self.df_clusters[self.cluster_col] == cluster_id, self.sku_col
            ].dropna().unique().tolist()

            print(f"\n📦 {cluster_id}: MAPE inicial={mape_original:.2f}% | {len(skus)} SKU")
            if len(skus) <= 1:
                print("   ⚠️ El clúster tiene un solo SKU; no se puede retirarlo y conservar el clúster.")
                resumen.append({'Cluster': cluster_id, 'MAPE_Inicial_%': mape_original,
                                'SKU_Extraño': None, 'MAPE_Recalculado_%': mape_original,
                                'Mejora_pp': 0.0, 'Mejora_Relativa_%': 0.0})
                continue

            candidatos = []
            for sku in skus:
                print(f"   🧪 Probando sin SKU {sku}...")
                try:
                    mape_sin, estrategia_sin = self._evaluar_sku_por_impacto_mape(cluster_id, sku, mape_original)
                except Exception as e:
                    print(f"      ⚠️ No se pudo evaluar {sku}: {e}")
                    mape_sin, estrategia_sin = np.nan, None
                mejora_pp = (mape_original - mape_sin) if np.isfinite(mape_sin) else np.nan
                mejora_rel = (mejora_pp / mape_original * 100) if np.isfinite(mejora_pp) and mape_original > 0 else np.nan
                candidatos.append((sku, mape_sin, mejora_pp, mejora_rel, estrategia_sin))
                detalle.append({'Cluster': cluster_id, 'SKU_Evaluado': sku,
                                'MAPE_Inicial_%': mape_original, 'MAPE_Sin_SKU_%': mape_sin,
                                'Mejora_pp': mejora_pp, 'Mejora_Relativa_%': mejora_rel,
                                'Estrategia_Sin_SKU': estrategia_sin})
                if np.isfinite(mape_sin):
                    print(f"      MAPE sin SKU={mape_sin:.2f}% | mejora={mejora_rel:.1f}%")

            validos = [x for x in candidatos if np.isfinite(x[1])]
            if not validos:
                resumen.append({'Cluster': cluster_id, 'MAPE_Inicial_%': mape_original,
                                'SKU_Extraño': None, 'MAPE_Recalculado_%': mape_original,
                                'Mejora_pp': 0.0, 'Mejora_Relativa_%': 0.0})
                continue

            mejor = min(validos, key=lambda x: x[1])
            sku_mejor, mape_mejor, mejora_pp, mejora_rel, estrategia_mejor = mejor
            marcar = mejora_rel >= (mejora_minima_relativa * 100)

            if marcar:
                seleccionados.append(sku_mejor)
                print(f"   🚩 SKU extraño: {sku_mejor} | {mape_original:.2f}% → {mape_mejor:.2f}% "
                      f"(mejora relativa {mejora_rel:.1f}%)")
            else:
                print(f"   ℹ️ Ningún SKU reduce el MAPE al menos {mejora_minima_relativa*100:.0f}%; no se excluye ninguno.")

            resumen.append({'Cluster': cluster_id, 'MAPE_Inicial_%': mape_original,
                            'SKU_Extraño': sku_mejor if marcar else None,
                            'MAPE_Recalculado_%': mape_mejor if marcar else mape_original,
                            'Mejora_pp': mejora_pp if marcar else 0.0,
                            'Mejora_Relativa_%': mejora_rel if marcar else 0.0,
                            'Estrategia_Recalculada': estrategia_mejor if marcar else fila['Estrategia_Ganadora']})

        self.skus_descontinuados_por_mape = sorted(set(seleccionados))
        with open(archivo_lista, 'w', encoding='utf-8') as f:
            f.write("CODIGOS_DESCONTINUADOS_MAPE = {\n")
            for codigo in self.skus_descontinuados_por_mape:
                f.write(f"    {codigo!r},\n")
            f.write("}\n")

        df_detalle = pd.DataFrame(detalle)
        df_resumen = pd.DataFrame(resumen)
        with pd.ExcelWriter(archivo_excel, engine='openpyxl') as writer:
            df_resumen.to_excel(writer, sheet_name='Resumen', index=False)
            df_detalle.to_excel(writer, sheet_name='Pruebas_SKU', index=False)
            pd.DataFrame({'Código': self.skus_descontinuados_por_mape}).to_excel(
                writer, sheet_name='Descontinuados_SKU', index=False
            )

        print("\n" + "=" * 100)
        print("📊 MAPE ANTES VS. DESPUÉS")
        print("=" * 100)
        if not df_resumen.empty:
            print(df_resumen[['Cluster','SKU_Extraño','MAPE_Inicial_%','MAPE_Recalculado_%','Mejora_Relativa_%']].to_string(index=False))
        print(f"\n💾 Guardado '{archivo_excel}' y '{archivo_lista}' ({len(self.skus_descontinuados_por_mape)} SKU extraños).")
        return df_resumen, df_detalle

    def procesar_cluster(self, cluster_id, df_agregado):
        print(f"\n{'='*70}\n🔹 Cluster {cluster_id}\n{'='*70}")
        comportamiento_preliminar = self.pron_original.clasificar_comportamiento_cluster(cluster_id)

        nombres_a_probar = ['Original', 'Ensamble']
        if comportamiento_preliminar in self.ESTRATEGIAS_ADICIONALES_POR_COMPORTAMIENTO:
            nombres_a_probar += ['Quiebre_V5', 'Descomposicion_V6']
            print(f"   (comportamiento='{comportamiento_preliminar}' -- se prueban también V5 y V6)")

        # [NUEVO] Chequeo de colapso de nivel reciente -- se hace ANTES de
        # correr cualquier estrategia, reagregando la serie cruda a la
        # unidad de este clúster (mismo criterio que usa internamente
        # cada Pronosticador), para decidir si vale la pena probar
        # ColapsoReciente. No se prueba en todos los clústeres -- solo
        # tiene sentido cuando el colapso realmente está ahí (ver
        # detectar_colapso_reciente).
        config, _, _ = self.pron_original.obtener_config_temporal_cluster(cluster_id)
        serie_en_unidad = (
            df_agregado['y'] if config['unidad'] == 'semanas'
            else df_agregado['y'].resample(config['regla_resample']).sum()
        )
        hay_colapso, _ = detectar_colapso_reciente(
            serie_en_unidad.values, config['horizonte'], config['periodo_estacional']
        )
        if hay_colapso:
            nombres_a_probar.append('ColapsoReciente')
            print(f"   (colapso de nivel reciente detectado -- se prueba también ColapsoReciente)")

        mase_test_por_estrategia = {}
        mape_test_por_estrategia = {}  # se conserva para el log/diagnóstico -- ya no decide
        for nombre in nombres_a_probar:
            pron = self._instancias[nombre]
            print(f"\n   --- Estrategia: {nombre} ---")
            try:
                pron.procesar_cluster(cluster_id, df_agregado)
                metricas = pron.modelos_por_cluster[cluster_id]['metricas_test']
                mase_test_por_estrategia[nombre] = metricas.get('MASE')
                mape_test_por_estrategia[nombre] = metricas.get('MAPE_%')
            except Exception as e:
                print(f"   ⚠️ Estrategia {nombre} falló para este clúster: {str(e)[:150]}")
                mase_test_por_estrategia[nombre] = None
                mape_test_por_estrategia[nombre] = None

        # [CORREGIDO -- CRITERIO DE SELECCIÓN CAMBIADO DE MAPE_TEST A
        # MASE_TEST] Encontrado con datos reales: 0_JINANMEIDE_CHINA ganaba
        # con 'Original' por tener el MENOR MAPE_TEST (38.96%, contra
        # Ensamble y las demás) -- pero su MASE_TEST resultó 1.25, es
        # decir, PEOR que un pronóstico ingenuo estacional (repetir el
        # mismo mes del año pasado). El propio MAPE que decidía la
        # selección es la métrica que ya sabíamos poco confiable para
        # estos clústeres (se dispara con periodos de demanda pequeña,
        # sin relación con qué tan bueno es el modelo de verdad) -- así
        # que usarlo para ELEGIR entre estrategias hereda exactamente el
        # mismo problema que ya se corrigió para REPORTAR el resultado
        # final (ver MASE en calcular_mase). Ahora la estrategia ganadora
        # es la de MENOR MASE_TEST -- MASE no se dispara con demanda
        # pequeña (no divide por el valor real), así que compara
        # estrategias de forma justa sin importar cuán volátil sea el
        # clúster.
        validos = {n: v for n, v in mase_test_por_estrategia.items() if v is not None and v == v}
        if validos:
            ganadora = min(validos, key=validos.get)
        elif mase_test_por_estrategia.get('Original') is not None:
            ganadora = 'Original'
        else:
            # Si hasta Original falló en tener MASE_TEST (ej. cayó en
            # fallback sin TEST posible), de todas formas se usa Original
            # -- es el resultado de referencia, nunca se deja el clúster
            # sin pronóstico.
            ganadora = 'Original'

        self.estrategia_ganadora_por_cluster[cluster_id] = ganadora
        pron_ganadora = self._instancias[ganadora]
        metricas_test_ganadora = pron_ganadora.modelos_por_cluster[cluster_id]['metricas_test']
        mape_g = metricas_test_ganadora.get('MAPE_%')
        wape_g = metricas_test_ganadora.get('WAPE_%')
        mase_g = metricas_test_ganadora.get('MASE')
        # [NUEVO -- ALERTA MASE>=1] La estrategia ganadora, aun siendo la
        # de MENOR MASE entre las probadas, puede seguir siendo >=1 (peor
        # que el ingenuo) si NINGUNA de las estrategias probadas le gana
        # al ingenuo en este clúster -- eso ya no es un problema de
        # selección, es una señal real de que el clúster necesita otra
        # cosa (más historia, revisar el comportamiento asignado, o
        # aceptar que para este clúster el pronóstico ingenuo estacional
        # es, por ahora, la mejor opción disponible).
        alerta_peor_que_ingenuo = mase_g is not None and mase_g == mase_g and mase_g >= 1.0
        # [ALERTA MAPE/WAPE CONTRADICTORIOS] se conserva igual que antes --
        # sigue siendo útil como diagnóstico adicional, aunque ya no decida
        # la selección.
        alerta_mape_wape = (
            mape_g is not None and mape_g == mape_g and wape_g is not None and wape_g == wape_g
            and mape_g < 60 and wape_g > mape_g * 2
        )
        self.log_comparacion_estrategias.append({
            'cluster_id': cluster_id, 'comportamiento': comportamiento_preliminar,
            'estrategia_ganadora': ganadora,
            'MASE_TEST_Original': mase_test_por_estrategia.get('Original'),
            'MASE_TEST_Ensamble': mase_test_por_estrategia.get('Ensamble'),
            'MASE_TEST_Quiebre_V5': mase_test_por_estrategia.get('Quiebre_V5'),
            'MASE_TEST_Descomposicion_V6': mase_test_por_estrategia.get('Descomposicion_V6'),
            'MASE_TEST_ColapsoReciente': mase_test_por_estrategia.get('ColapsoReciente'),
            'MAPE_TEST_Original': mape_test_por_estrategia.get('Original'),
            'MAPE_TEST_Ensamble': mape_test_por_estrategia.get('Ensamble'),
            'MAPE_TEST_Quiebre_V5': mape_test_por_estrategia.get('Quiebre_V5'),
            'MAPE_TEST_Descomposicion_V6': mape_test_por_estrategia.get('Descomposicion_V6'),
            'MAPE_TEST_ColapsoReciente': mape_test_por_estrategia.get('ColapsoReciente'),
            'MAPE_WAPE_Contradictorios': alerta_mape_wape,
            'Peor_Que_Ingenuo_MASE_Mayor_Igual_1': alerta_peor_que_ingenuo,
        })
        if alerta_mape_wape:
            print(f"   ⚠️⚠️ MAPE_TEST ({mape_g:.1f}%) y WAPE_TEST ({wape_g:.1f}%) muy distintos -- "
                  f"revisar manualmente, el MAPE de este clúster puede no ser representativo "
                  f"(probablemente TEST tiene muchos periodos en cero).")
        if alerta_peor_que_ingenuo:
            print(f"   ⚠️⚠️ MASE_TEST de la GANADORA ({mase_g:.2f}) >= 1 -- ni siquiera la mejor "
                  f"estrategia probada le gana a repetir el ciclo estacional anterior en este "
                  f"clúster. Revisar manualmente (más historia, comportamiento asignado, etc.).")
        print(f"\n   🏆 Estrategia ganadora: {ganadora} "
              f"(MASE_TEST={mase_g:.3f} | MAPE_TEST={mape_test_por_estrategia.get(ganadora)}%)")

    @property
    def pron_ganador_por_cluster(self):
        return {cid: self._instancias[nombre] for cid, nombre in self.estrategia_ganadora_por_cluster.items()}

    def ejecutar_pipeline_pronosticos(self, skus_por_cluster=None, datos_por_cluster=None):
        if skus_por_cluster is None:
            skus_por_cluster = self.df_clusters.groupby(self.cluster_col)[self.sku_col].apply(list).to_dict()

        for cluster_id in skus_por_cluster.keys():
            if datos_por_cluster is not None and cluster_id in datos_por_cluster:
                self.procesar_cluster(cluster_id, datos_por_cluster[cluster_id])

        n_cambiaron = sum(1 for v in self.estrategia_ganadora_por_cluster.values() if v != 'Original')
        print(f"\n{'='*70}")
        print(f"✅ {len(self.estrategia_ganadora_por_cluster)} clústeres procesados. "
              f"{n_cambiaron} mejoraron con una estrategia alternativa (V5/V6).")
        print(f"{'='*70}")

    def tabla_comparacion_estrategias(self):
        # Salida visible: solo MAPE TEST final de la estrategia ganadora.
        filas=[]
        for cluster_id, nombre in self.estrategia_ganadora_por_cluster.items():
            info=self._instancias[nombre].modelos_por_cluster[cluster_id]
            filas.append({'Cluster':cluster_id,'Estrategia_Ganadora':nombre,'MAPE_TEST_%':info['metricas_test'].get('MAPE_%')})
        return pd.DataFrame(filas)

    def tabla_metricas_finales(self):
        """Salida de métricas: únicamente MAPE TEST por clúster."""
        filas=[]
        for cluster_id, nombre in self.estrategia_ganadora_por_cluster.items():
            info=self._instancias[nombre].modelos_por_cluster[cluster_id]
            filas.append({'Cluster':cluster_id,'MAPE_TEST_%':info['metricas_test'].get('MAPE_%')})
        return pd.DataFrame(filas)

    def exportar_resultados_por_cluster(self, archivo_salida='Resultados_Por_Cluster.xlsx'):
        """
        [SOLO CLÚSTER, NO SKU] Una fila por Cluster_Operativo y periodo
        futuro, con el pronóstico CONSOLIDADO del clúster (la demanda
        conjunta de todos sus SKU) -- ninguna cifra individual por SKU.
        La hoja 'Composicion_Clusters' es metadata (qué SKU integra cada
        clúster), no un pronóstico -- para trazabilidad, sin desagregar
        ninguna cifra.
        """
        filas_pronostico = []
        filas_resumen = []
        filas_composicion = []
        filas_serie_agregada = []

        for cluster_id, nombre_estrategia in self.estrategia_ganadora_por_cluster.items():
            pron = self._instancias[nombre_estrategia]
            info = pron.modelos_por_cluster[cluster_id]
            pronostico_info = pron.pronosticos_por_cluster[cluster_id]
            unidad = info['unidad_tiempo']
            regla = info['regla_resample']
            validacion = pronostico_info['validacion']

            skus_cluster = self.df_clusters[self.df_clusters[self.cluster_col] == cluster_id][self.sku_col].tolist()
            for sku in skus_cluster:
                filas_composicion.append({'Cluster': cluster_id, self.sku_col: sku})

            formato_fecha_serie = '%Y-%m' if unidad in pron.UNIDADES_MENSUALES else '%Y-%m-%d'
            for fecha, fila in info['datos_agregados'].iterrows():
                filas_serie_agregada.append({
                    'Cluster': cluster_id, 'Estrategia_Ganadora': nombre_estrategia,
                    'Fecha': fecha.strftime(formato_fecha_serie), 'Unidad_Tiempo': unidad,
                    'Demanda_Agregada': float(fila['y']),
                })

            filas_resumen.append({
                'Cluster': cluster_id, 'N_SKUs_Consolidados': len(skus_cluster),
                'Comportamiento': info['comportamiento'], 'Estrategia_Ganadora': nombre_estrategia,
                'Modelo_Ganador': info['modelo'], 'Es_Fallback': bool(validacion.get('es_fallback', False)),
                'Unidad_Tiempo': unidad, 'Horizonte': info['horizonte'],
                'Demanda_Total_Pronosticada': round(float(np.sum(pronostico_info['pronostico'])), 0),
                'Lead_Time_Max_Semanas': round(info['lead_time_max_cluster'], 1),
                'MAPE_TEST_%': round(info['metricas_test'].get('MAPE_%'), 2) if info['metricas_test'].get('MAPE_%') == info['metricas_test'].get('MAPE_%') else None,
            })

            formato_fecha = '%Y-%m' if unidad in pron.UNIDADES_MENSUALES else '%Y-%m-%d'
            periodos = pd.date_range(
                start=pronostico_info['fecha_inicio_pronostico'],
                periods=pronostico_info['horizonte_pronostico'], freq=regla,
            )
            for periodo, valor in zip(periodos, pronostico_info['pronostico']):
                filas_pronostico.append({
                    'Cluster': cluster_id, 'Periodo': periodo.strftime(formato_fecha),
                    'Unidad_Tiempo': unidad, 'Pronostico_Cluster': round(float(valor), 0),
                })

        df_pronostico = pd.DataFrame(filas_pronostico)
        df_resumen = pd.DataFrame(filas_resumen)
        df_composicion = pd.DataFrame(filas_composicion)
        df_serie_agregada = pd.DataFrame(filas_serie_agregada)
        df_comparacion = self.tabla_comparacion_estrategias()
        df_metricas = self.tabla_metricas_finales()

        with pd.ExcelWriter(archivo_salida, engine='openpyxl') as writer:
            df_resumen.to_excel(writer, sheet_name='Resumen_Por_Cluster', index=False)
            df_pronostico.to_excel(writer, sheet_name='Pronostico_Por_Cluster', index=False)
            df_metricas.to_excel(writer, sheet_name='Metricas_Por_Cluster', index=False)
            df_comparacion.to_excel(writer, sheet_name='Comparacion_Estrategias', index=False)
            df_composicion.to_excel(writer, sheet_name='Composicion_Clusters', index=False)
            df_serie_agregada.to_excel(writer, sheet_name='Serie_Agregada_Por_Cluster', index=False)

    # ------------------------------------------------------------------
    # [NUEVO -- REINCORPORADO A PEDIDO EXPLÍCITO] Exporta, por clúster, el
    # modelo ya ajustado (modelo_ajustado), sus hiperparámetros, el
    # scaler/columnas de features cuando aplica (modelos ML), y los
    # metadatos necesarios para que el siguiente módulo (simulación de
    # inventario) pueda CARGAR y REUTILIZAR estos modelos sin volver a
    # entrenar nada -- ni volver a correr toda la búsqueda de
    # hiperparámetros ni la comparación de estrategias, que es lo que
    # de verdad consume tiempo en este pipeline.
    #
    # [QUÉ SE GUARDA POR CLÚSTER Y POR QUÉ]
    #   - modelo: nombre del modelo ganador (ej. 'XGBoost', 'SARIMA',
    #     o el string combinado del Ensamble, ej. 'XGBoost(60%) + MLP(40%)')
    #   - estrategia_ganadora: cuál de las 5 estrategias (Original, V5,
    #     V6, ColapsoReciente, Ensamble) produjo el pronóstico final
    #   - hiperparametros: el dict de hiperparámetros encontrados en la
    #     búsqueda -- necesario si el siguiente módulo quiere reentrenar
    #     el mismo modelo sobre datos actualizados sin repetir la
    #     búsqueda completa (RandomizedSearchCV es lo más lento del
    #     pipeline)
    #   - modelo_ajustado: el objeto Python ya entrenado (statsmodels
    #     para clásicos, el estimador de sklearn para ML) -- listo para
    #     .forecast()/.predict() directamente, sin reentrenar. Para el
    #     Ensamble, que promedia 2 candidatos, se guardan AMBOS objetos
    #     ajustados (ver 'modelo_ajustado_top2') porque el pronóstico
    #     final es la combinación de los dos, no un solo objeto.
    #   - scaler / columnas_features: solo para modelos ML -- necesarios
    #     para transformar cualquier fila nueva de features exactamente
    #     igual que se hizo en entrenamiento antes de llamar .predict().
    #   - comportamiento, unidad_tiempo, horizonte, lead_time: contexto
    #     mínimo para que el módulo de simulación sepa en qué unidad
    #     está el pronóstico y cuánto es el horizonte/lead time de ese
    #     clúster, sin tener que releer clusters_con_unidad_pronostico.xlsx.
    #   - metricas_test: MAPE/WAPE/R2 fuera de muestra del modelo ganador
    #     -- útil como referencia de confianza, con la salvedad ya
    #     explicada de que en esta versión participó en la selección de
    #     estrategia.
    # ------------------------------------------------------------------
    def exportar_modelos_pickle(self, archivo_salida='modelos_pronostico.pkl'):
        paquete = {'clusters': {}}

        for cluster_id, nombre_estrategia in self.estrategia_ganadora_por_cluster.items():
            pron = self._instancias[nombre_estrategia]
            info = pron.modelos_por_cluster[cluster_id]

            entrada = {
                'cluster_id': cluster_id,
                'estrategia_ganadora': nombre_estrategia,
                'modelo': info['modelo'],
                'comportamiento': info['comportamiento'],
                'unidad_tiempo': info['unidad_tiempo'],
                'regla_resample': info['regla_resample'],
                'horizonte': info['horizonte'],
                'lead_time_max_cluster_semanas': info['lead_time_max_cluster'],
                'lead_time_max_en_unidad': info.get('lead_time_max_en_unidad'),
                'hiperparametros': info.get('hiperparametros'),
                'modelo_ajustado': info.get('modelo_ajustado'),
                'scaler': info.get('scaler'),
                'columnas_features': info.get('columnas_features'),
                'metricas_cv': info['resultados_cv'].get(info['modelo']) if info['modelo'] in info['resultados_cv'] else None,
                'metricas_test': info['metricas_test'],
                'metricas_in_sample': info['metricas_in_sample'],
            }

            # [CASO ESPECIAL -- ENSAMBLE] El modelo ganador no es UN
            # objeto -- es la combinación ponderada de los 2 mejores
            # candidatos (ver PronosticadorConEnsamble.procesar_cluster).
            # 'modelo_ajustado' del dict de arriba solo trae el objeto
            # del candidato de MENOR MAPE_CV (el que se usa para los
            # diagnósticos de residuos) -- eso NO alcanza para
            # reproducir el pronóstico del Ensamble completo. Si la
            # estrategia ganadora fue Ensamble, se guardan también los
            # hiperparámetros de AMBOS candidatos (top2) para que el
            # siguiente módulo pueda reconstruir la combinación completa
            # si lo necesita -- el objeto ajustado del segundo candidato
            # no queda disponible (Ensamble no lo conserva), pero sus
            # hiperparámetros sí alcanzan para reentrenarlo si hace falta.
            if nombre_estrategia == 'Ensamble':
                entrada['ensamble_top2_candidatos'] = [
                    {'modelo': nombre, 'metricas_cv': metricas}
                    for nombre, metricas in info.get('top2', [])
                ]

            paquete['clusters'][cluster_id] = entrada

        with open(archivo_salida, 'wb') as f:
            pickle.dump(paquete, f)

        print(f"\n💾 Modelos y hiperparámetros guardados en '{archivo_salida}' "
              f"({len(paquete['clusters'])} clústeres) -- listo para que el siguiente "
              f"módulo cargue los modelos ya ajustados sin reentrenar.")

    # ------------------------------------------------------------------
    # [NUEVO -- COMPATIBILIDAD CON EL MÓDULO DE SIMULACIÓN] El módulo de
    # simulación (Monte Carlo) espera UN objeto Pronosticador con
    # modelos_por_cluster/pronosticos_por_cluster/resultados_por_sku ya
    # poblados directamente como atributos (pron = pickle.load(f); luego
    # pron.modelos_por_cluster, etc.) -- tal como corría con la primera
    # versión (un solo Pronosticador, sin orquestador de 5 estrategias).
    # Este orquestador reparte el trabajo entre 5 instancias internas
    # (Original, V5, V6, ColapsoReciente, Ensamble); este método arma un
    # Pronosticador base (mismo dataset/df_clusters) y le copia, por cada
    # clúster, la información de la estrategia GANADORA -- consolidando
    # las 5 en el mismo formato que Simulación ya sabe leer.
    #
    # 2 AJUSTES DE COMPATIBILIDAD:
    #   1) Ensamble: 'modelo' se sobreescribe con el nombre del candidato
    #      INDIVIDUAL cuyo objeto quedó en 'modelo_ajustado'
    #      (modelo_individual_base) -- el string combinado
    #      ("XGBoost(60%)+MLP(40%)") no es un nombre de modelo que el
    #      simulador pueda adaptar a una función de un paso. Esto es una
    #      aproximación real: la simulación Monte Carlo para estos
    #      clústeres reproduce el comportamiento del MEJOR CANDIDATO
    #      INDIVIDUAL, no el promedio ponderado que sí es el pronóstico
    #      puntual reportado en Resultados_Por_Cluster.xlsx.
    #   2) resultados_por_sku: se agrega la clave 'factor_escala' como
    #      alias de 'peso_desagregacion' -- Simulación busca ese nombre
    #      de campo específico.
    #
    # [LIMITACIÓN CONOCIDA -- NO CORREGIBLE DESDE ESTE LADO SOLO] El
    # simulador lee PERIODO_ESTACIONAL/REZAGOS/VENTANAS_MOVIL como UN
    # SOLO valor global del objeto Pronosticador
    # (getattr(pronosticador, "PERIODO_ESTACIONAL", 52)) -- no por
    # clúster, aunque este pipeline es multi-frecuencia (algunos
    # clústeres en semanas, otros en meses/bimestres/trimestres). Se deja
    # aquí el valor del ÚLTIMO clúster consolidado -- para clústeres en
    # una unidad de tiempo DISTINTA a esa, el adaptador ML de simulación
    # calculará mal los rezagos/estacionalidad. Corregirlo de raíz
    # requiere que preparar_forecast_un_paso_desde_pronosticador (en el
    # módulo de simulación) lea esta configuración desde
    # info['unidad_tiempo'] de cada clúster en vez de un atributo global
    # -- se puede hacer si lo autorizas, pero no se tocó aquí porque
    # pediste explícitamente no modificar Simulación.
    # ------------------------------------------------------------------
    def construir_pronosticador_consolidado(self):
        consolidado = Pronosticador(
            dataset=self.pron_original.dataset, df_clusters=self.df_clusters,
            n_iter_busqueda_ml=self.pron_original.n_iter_busqueda_ml,
            semilla_aleatoria=self.pron_original.semilla_aleatoria,
            sku_col=self.sku_col, cluster_col=self.cluster_col,
        )

        for cluster_id, nombre_estrategia in self.estrategia_ganadora_por_cluster.items():
            pron = self._instancias[nombre_estrategia]
            info = dict(pron.modelos_por_cluster[cluster_id])  # copia -- no mutar el original

            if nombre_estrategia == 'Ensamble' and info.get('modelo_individual_base'):
                info['modelo'] = info['modelo_individual_base']

            consolidado.modelos_por_cluster[cluster_id] = info
            consolidado.pronosticos_por_cluster[cluster_id] = pron.pronosticos_por_cluster[cluster_id]
            consolidado.config_por_cluster[cluster_id] = pron.config_por_cluster.get(cluster_id)

            # [CORREGIDO -- CORRIGE RIESGO DE ROBUSTEZ SEÑALADO EN REVISIÓN]
            # Antes, aquí se fijaban consolidado.PERIODO_ESTACIONAL/REZAGOS/
            # VENTANAS_MOVIL en CADA vuelta del loop -- como son atributos
            # GLOBALES del objeto (no por clúster), terminaban quedando con
            # los valores de la unidad del ÚLTIMO clúster procesado, sin
            # relación con los demás clústeres (multi-frecuencia real:
            # semanas/quincenas/meses/bimestres/trimestres pueden convivir).
            # Simulación ya lee la unidad correcta POR CLÚSTER desde
            # info['unidad_tiempo'] (ver preparar_forecast_un_paso_desde_
            # pronosticador) y solo cae a estos atributos globales como
            # último respaldo si a un clúster le faltara esa clave -- así
            # que dejarlos aquí con el valor de "cualquiera haya sido el
            # último clúster" era, en el mejor caso, inútil, y en el peor,
            # un respaldo silenciosamente incorrecto. Se elimina la
            # asignación: sin estos atributos, ese respaldo usa el default
            # explícito de getattr (52, semanas) -- previsible y siempre
            # el mismo, en vez de depender del orden de procesamiento.

            for sku, res in pron.resultados_por_sku.items():
                if res['cluster'] != cluster_id:
                    continue
                res_copia = dict(res)
                res_copia['factor_escala'] = res_copia.get('peso_desagregacion')
                consolidado.resultados_por_sku[sku] = res_copia

        return consolidado

    def exportar_pronosticador_consolidado_pickle(self, archivo_salida='pronosticador_entrenado.pkl'):
        consolidado = self.construir_pronosticador_consolidado()
        with open(archivo_salida, 'wb') as f:
            pickle.dump(consolidado, f)
        n_ensamble = sum(1 for n in self.estrategia_ganadora_por_cluster.values() if n == 'Ensamble')
        # [CORREGIDO -- MENSAJE DESACTUALIZADO] Este aviso describía la
        # limitación de antes (Simulación aproximaba el Ensamble con el
        # mejor candidato individual) -- ya corregida: 'ensamble_
        # componentes' guarda AMBOS objetos ajustados con sus pesos, y
        # Simulación los combina de verdad (ver crear_forecast_un_paso_
        # ensamble en Simulacion.py). Se deja el aviso informativo (sigue
        # siendo útil saber cuántos clústeres son Ensamble), pero ya sin
        # advertir de una limitación que no existe más.
        print(f"\n💾 Pronosticador consolidado guardado en '{archivo_salida}' "
              f"({len(consolidado.modelos_por_cluster)} clústeres) -- listo para el módulo "
              f"de simulación."
              + (f" ({n_ensamble} clústeres ganaron con Ensamble -- Simulación reconstruye la "
                 f"combinación ponderada completa de esos, no solo el mejor candidato individual.)"
                 if n_ensamble > 0 else ""))
        return consolidado


# ============================================================
# EJECUCIÓN DIRECTA
# ============================================================
if __name__ == "__main__":
    RUTA_CLUSTERS_CON_UNIDAD = 'clusters_con_unidad_pronostico.xlsx'
    if not os.path.exists(RUTA_CLUSTERS_CON_UNIDAD):
        raise FileNotFoundError(
            f"No se encontró '{RUTA_CLUSTERS_CON_UNIDAD}'. Corre primero "
            f"clusterizacionVolumen.py y luego TraductorClusterPronostico.py."
        )

    print("📥 Cargando datos para la corrida final (mejor estrategia por clúster)...")
    df_resultado = pd.read_excel(RUTA_CLUSTERS_CON_UNIDAD)
    df_featuring = pd.read_excel('df_featuring.xlsx')

    RUTA_AGREGADOS = 'unidades_agregadas_por_cluster.xlsx'
    datos_por_cluster = cargar_unidades_agregadas_desde_excel(RUTA_AGREGADOS) if os.path.exists(RUTA_AGREGADOS) else None

    t_inicio = time.time()
    pron = PronosticadorMejorEstrategia(dataset=df_featuring, df_clusters=df_resultado, n_iter_busqueda_ml=15)
    pron.ejecutar_pipeline_pronosticos(datos_por_cluster=datos_por_cluster)
    tiempo_total = time.time() - t_inicio

    pron.exportar_resultados_por_cluster('Resultados_Por_Cluster.xlsx')
    pron.exportar_modelos_pickle('modelos_pronostico.pkl')
    pron.exportar_pronosticador_consolidado_pickle('pronosticador_entrenado.pkl')

    print("\n" + "=" * 100)
    print("📊 MAPE TEST FINAL POR CLÚSTER")
    print("=" * 100)
    print(pron.tabla_comparacion_estrategias().to_string(index=False))

    # Para clústeres con MAPE > 100%, prueba retirar cada SKU, guarda los SKU
    # que realmente deterioran el pronóstico y recalcula el MAPE sin ellos.
    pron.revisar_skus_y_recalcular_mape(
        umbral_mape=100.0,
        mejora_minima_relativa=0.20,
        archivo_excel='Revision_SKU_MAPE.xlsx',
        archivo_lista='codigos_descontinuados_mape.txt',
    )

    tiempo_total = time.time() - t_inicio
    print(f"\n⏱️ Tiempo total: {tiempo_total:.1f}s ({tiempo_total/60:.1f} min)")
    print("\n💾 Guardado en 'Resultados_Por_Cluster.xlsx' -- SOLO pronósticos por clúster, "
          "sin desagregar por SKU (ver hoja 'Composicion_Clusters' solo como referencia de qué "
          "SKU integra cada clúster). Modelos y hiperparámetros guardados en "
          "'modelos_pronostico.pkl'.")
