"""
==============================================================================
CLUSTERING HÍBRIDO DE INVENTARIOS
Une clusterizacionVolumen.py (método 1: por comportamiento) y
clusterizacionVolumenN.py (método 2: por periodo estacional N).
==============================================================================

IDEA
----
El periodo N solo tiene significado para los SKU que de verdad son
estacionales. En un SKU estacionario o con tendencia, el N detectado por la
ACF puede ser espurio, y separar esos SKU por un N arbitrario produce
clusters con MAPE disparado. Por eso, antes de clusterizar, cada SKU se
asigna a UNO de tres bloques:

  1. ESTACIONALES  -> método 2: se separan por Periodo_N (un segmento por
                      cada N) y se clusteriza dentro de cada segmento.
                      Condición: Periodo_N_estado == 'Detectada', N > 0 y,
                      si CONFIRMAR_CON_STL=True, Estacionalidad_STL >= UMBRAL_FS.
                      (La fuerza STL de featuring usa periodo 52; como 4, 13 y
                      26 dividen a 52, también captura esos ciclos.)
  2. NO ESTACIONALES -> método 1: todos juntos en un solo bloque,
                      clusterizados por patrón de demanda (sin usar N).
  3. INTERMITENTES -> Clase_Demanda en CLASES_INTERMITENTES. Por defecto van
                      a un bloque propio, clusterizado con las mismas
                      variables del método 1 pero sin mezclarse con los
                      SKU de demanda regular.

Input : df_featuring.xlsx (salida de featuring.py)
Output: mismo esquema que los dos métodos originales, con nombres NUEVOS:
          - clusters_asignados_hibrido.xlsx
          - unidades_agregadas_por_cluster_hibrido.xlsx
          - gráficos con prefijo 'hibrido_'
        Columnas añadidas (al final, no alteran las existentes):
          - Segmento_N      : bloque/segmento del SKU (EST_N_52, NO_ESTACIONAL,
                              INTERMITENTE...), mismo nombre de columna que el
                              método 2 para mantener compatibilidad.
          - Metodo_Aplicado : 'Método 2 (N)' / 'Método 1' / 'Método 1 (intermitentes)'
          - Motivo_Segmento : por qué el SKU quedó en ese bloque
        Hoja añadida: 'Segmentacion_Hibrida' (conteo de SKU por bloque).
"""

import time
import warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import MiniBatchKMeans
from sklearn.mixture import GaussianMixture
from sklearn.metrics import silhouette_score, davies_bouldin_score, calinski_harabasz_score
from scipy.cluster.hierarchy import dendrogram, linkage, fcluster
from scipy.stats import f_oneway

warnings.filterwarnings("ignore")

try:
    import hdbscan
    HDBSCAN_AVAILABLE = True
except ImportError:
    HDBSCAN_AVAILABLE = False
    print("⚠️ HDBSCAN no está instalado. Se omitirá este modelo.")


# ==========================================================================
# 0. CONFIGURACIÓN GLOBAL
# ==========================================================================

TAM_MUESTRA_SILHOUETTE = 8000
TAM_MICROCLUSTERS = 1500
RANDOM_STATE = 42

# ---- Parámetros de la segmentación híbrida (ajustables) -------------------
# Confirmar la estacionalidad con la fuerza STL además del N por ACF.
# True = un SKU solo entra al método 2 si su N fue detectado Y su fuerza
# estacional STL supera UMBRAL_FS. Recomendado: evita que un pico espurio
# de la ACF mande un SKU no estacional al método 2.
CONFIRMAR_CON_STL = True
UMBRAL_FS = 0.50          # mismo umbral de featuring.py (Wang et al., 2006)

# Clases de Syntetos-Boylan (columna Clase_Demanda de featuring) que se
# consideran intermitentes.
CLASES_INTERMITENTES = ['Intermitente', 'Irregular (lumpy)']

# 'segmento_propio': los intermitentes forman su propio bloque (método 1
#                    aplicado solo entre ellos).
# 'metodo1'        : los intermitentes se mezclan con los no estacionales.
TRATAMIENTO_INTERMITENTES = 'segmento_propio'

# True: un SKU intermitente NO entra al método 2 aunque se le haya detectado
# estacionalidad (con series casi todo ceros, la ACF y la fuerza STL son
# poco confiables; ver advertencia en featuring.py).
PRIORIDAD_INTERMITENCIA = True

# ---- Nombres de salida (nuevos, para comparar con los métodos 1 y 2) ------
RUTA_ENTRADA = 'df_featuring.xlsx'
RUTA_SALIDA_CLUSTERS = 'clusters_asignados_hibrido.xlsx'
RUTA_SALIDA_AGREGADOS = 'unidades_agregadas_por_cluster_hibrido.xlsx'
PREFIJO_GRAFICOS = 'hibrido_'

SEG_NO_EST = 'NO_ESTACIONAL'
SEG_INT = 'INTERMITENTE'
MET_1 = 'Método 1'
MET_1_INT = 'Método 1 (intermitentes)'
MET_2 = 'Método 2 (N)'


def _log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


def silhouette_muestreado(X, etiquetas, tam_muestra=TAM_MUESTRA_SILHOUETTE,
                          random_state=RANDOM_STATE):
    n = X.shape[0]
    if n <= tam_muestra:
        return silhouette_score(X, etiquetas)
    return silhouette_score(X, etiquetas, sample_size=tam_muestra,
                            random_state=random_state)


# ==========================================================================
# 1. CARGA Y PREPARACIÓN DE DATOS
# ==========================================================================

def cargar_datos_desde_featuring(ruta_excel=RUTA_ENTRADA):

    df = pd.read_excel(ruta_excel)
    _log(f"📥 Cargado df_featuring con {len(df):,} filas.")

    columnas_estaticas = [
        'Código', 'Lead Time (semanas)', 'Demanda_Promedio',
        'Tendencia_pendiente', 'CV_Normalizado', 'ADI',
        'Denominacion familia', 'Pais', 'Proveedor', 'Volumen',
        'Costo Unitario', 'Demanda_std_residuos', 'Comportamiento',
        'Periodo_N', 'Periodo_N_estado',
        # [HÍBRIDO] necesarias para decidir el bloque de cada SKU
        'Clase_Demanda', 'Es_Estacional', 'Estacionalidad_STL',
    ]
    columnas_necesarias = columnas_estaticas + ['Unidades', 'Subtotal']

    faltantes = [c for c in columnas_necesarias if c not in df.columns]
    if faltantes:
        raise ValueError(f"❌ Columnas no encontradas en df_featuring: {faltantes}")

    agg = df.groupby('Código').agg(
        Total_Unidades=('Unidades', 'sum'),
        Valor_Promedio=('Subtotal', 'mean'),
        # Suma real del Subtotal histórico de cada SKU (base correcta para
        # agregar dinero por clúster, ver calcular_granularidad).
        Valor_Total_Historico=('Subtotal', 'sum'),
        Zero_Pct=('Subtotal', lambda x: (x == 0).mean()),
    ).reset_index()

    df_productos = df.groupby('Código', as_index=False).first()[columnas_estaticas]
    df_productos = df_productos.merge(agg, on='Código', how='left')

    for col in ['Total_Unidades', 'Valor_Promedio', 'Valor_Total_Historico', 'Zero_Pct']:
        df_productos[col] = df_productos[col].fillna(0)

    # ADI NaN = nunca tuvo demanda real; 0 sería el valor más incorrecto.
    # Se imputa con la mediana del catálogo y se avisa (igual que el OG).
    if df_productos['ADI'].isna().any():
        skus_sin_adi = df_productos.loc[df_productos['ADI'].isna(), 'Código'].tolist()
        mediana_adi = df_productos['ADI'].median()
        _log(f"⚠️ {len(skus_sin_adi)} SKU sin ninguna semana de demanda real "
             f"(ADI indefinido): {skus_sin_adi} -- se imputan con la mediana "
             f"de ADI del catálogo ({mediana_adi:.2f}) para poder clusterizarlos.")
        df_productos['ADI'] = df_productos['ADI'].fillna(mediana_adi)

    _log(f"✅ Agregado a {len(df_productos):,} productos únicos.")
    _log(f"📊 Variables disponibles: {list(df_productos.columns)}")
    return df_productos


# ==========================================================================
# 1b. [HÍBRIDO] SEGMENTACIÓN PREVIA
# ==========================================================================

def asignar_segmento_hibrido(fila):
    """
    Retorna (Segmento_N, Metodo_Aplicado, Motivo_Segmento) para un SKU.
    """
    clase = str(fila['Clase_Demanda']).strip()
    es_intermitente = clase in CLASES_INTERMITENTES

    estado_n = str(fila['Periodo_N_estado']).strip()
    n = pd.to_numeric(fila['Periodo_N'], errors='coerce')
    fs = pd.to_numeric(fila['Estacionalidad_STL'], errors='coerce')

    n_detectado = estado_n == 'Detectada' and pd.notna(n) and n > 0
    if CONFIRMAR_CON_STL:
        stl_confirma = pd.notna(fs) and fs >= UMBRAL_FS
    else:
        stl_confirma = True
    estacional = n_detectado and stl_confirma

    # 1) Intermitentes
    if es_intermitente and (PRIORIDAD_INTERMITENCIA or not estacional):
        motivo = f"Clase_Demanda = {clase}"
        if estacional:
            motivo += f" (tenía N={int(n)} detectado, pero prima la intermitencia)"
        if TRATAMIENTO_INTERMITENTES == 'segmento_propio':
            return SEG_INT, MET_1_INT, motivo
        return SEG_NO_EST, MET_1, motivo + "; agrupado con no estacionales"

    # 2) Estacionales confirmados -> método 2
    if estacional:
        motivo = f"N={int(n)} detectado por ACF"
        if CONFIRMAR_CON_STL:
            motivo += f" y fuerza STL={fs:.2f} >= {UMBRAL_FS}"
        return f"EST_N_{int(n)}", MET_2, motivo

    # 3) Todo lo demás -> método 1
    if n_detectado and not stl_confirma:
        fs_txt = f"{fs:.2f}" if pd.notna(fs) else "no evaluable"
        motivo = (f"N={int(n)} detectado por ACF, pero la fuerza STL "
                  f"({fs_txt}) no confirma estacionalidad")
    elif estado_n == 'No detectada':
        motivo = "Sin periodo estacional detectado (N=0)"
    else:
        motivo = f"Periodo_N {estado_n.lower()}"
    return SEG_NO_EST, MET_1, motivo


# ==========================================================================
# 2. PREPROCESAMIENTO (idéntico a ambos métodos)
# ==========================================================================
# Vector de distancia = solo patrón de demanda (Demanda_Promedio, CV, ADI,
# Tendencia, Lead Time) + Comportamiento en one-hot. Pais y Proveedor NO
# entran a la distancia: se usan después en Cluster_Operativo.

def preparar_features_con_pesos(df_productos, pesos=None):

    columnas_numericas = ['Demanda_Promedio', 'CV_Normalizado', 'ADI',
                          'Tendencia_pendiente', 'Lead Time (semanas)']
    columnas_extra = ['Costo Unitario', 'Total_Unidades', 'Volumen', 'Pais', 'Proveedor']

    faltantes = [c for c in columnas_numericas + columnas_extra
                 if c not in df_productos.columns]
    if faltantes:
        raise ValueError(f"❌ Columnas no encontradas: {faltantes}")

    X_raw = df_productos[columnas_numericas].copy()

    # Recorte 5%/95% (ver comentario del OG sobre "solo 2 clústeres").
    lower = X_raw.quantile(0.05)
    upper = X_raw.quantile(0.95)
    X_raw = X_raw.clip(lower=lower, upper=upper, axis=1)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_raw).astype(np.float32)

    if pesos is None:
        pesos = np.ones(len(columnas_numericas), dtype=np.float32)
    else:
        assert len(pesos) == X_scaled.shape[1], \
            "Los pesos deben coincidir con el número total de features"

    categorias = df_productos['Comportamiento'].astype('string').fillna('No determinado').str.strip()
    categorias = categorias.mask(categorias.eq(''), 'No determinado')
    dummies = pd.get_dummies(categorias, prefix='Comportamiento', dtype=np.float32)
    columnas_comportamiento = dummies.columns.tolist()

    peso_comportamiento = 1.0
    X_categorico = dummies.to_numpy(dtype=np.float32) * (peso_comportamiento / np.sqrt(2))
    X_weighted = np.hstack((X_scaled * pesos, X_categorico)).astype(np.float32)

    for columna in columnas_comportamiento:
        df_productos[columna] = dummies[columna].to_numpy(dtype=np.float32)

    feature_names = columnas_numericas + columnas_comportamiento

    _log(f"🧬 Features para clustering: {feature_names}")
    _log(f"⚖️ Pesos aplicados (todos iguales): {pesos.tolist()}")
    _log(f"🧮 Matriz de features: {X_weighted.shape}, {X_weighted.nbytes/1e6:.1f} MB")

    return X_weighted, feature_names, scaler


# ==========================================================================
# 3. CLASES DE CLUSTERING
# ==========================================================================
# Misma lógica que los dos métodos. Se toma la versión robusta del método 2
# (omite k que no producen etiquetas evaluables) y los gráficos llevan el
# prefijo 'hibrido_' + el segmento, para no sobrescribir los de otros
# métodos ni los de otros segmentos.

def _ruta_grafico(nombre, etiqueta):
    sufijo = f"_{etiqueta}" if etiqueta else ""
    return f"{PREFIJO_GRAFICOS}{nombre}{sufijo}.png"


class ModeloClusterizacionBase:

    def __init__(self, X, k_min=2, k_max=25, etiqueta=''):
        self.X = X
        self.k_min = k_min
        self.k_max = min(k_max, X.shape[0] - 1)
        self.etiqueta = etiqueta
        self.k_optimo = None
        self.etiquetas = None
        self.modelo_final = None
        self.resultados = []

    def _entrenar_con_k(self, k):
        raise NotImplementedError

    def buscar_k_optimo(self, criterio='silhouette', graficar=True):

        mejor_score = -np.inf
        mejor_k = None
        mejores_etiquetas = None
        mejor_modelo = None

        if self.k_min > self.k_max:
            self.k_max = min(self.k_min + 1, self.X.shape[0] - 1)

        for k in range(self.k_min, self.k_max + 1):
            try:
                modelo, etiquetas = self._entrenar_con_k(k)
                if not (1 < len(np.unique(etiquetas)) < self.X.shape[0]):
                    _log(f"   k={k}: etiquetas insuficientes para silhouette; se omite")
                    continue
            except (ValueError, RuntimeError) as exc:
                _log(f"   k={k}: no evaluable ({exc})")
                continue

            sil = silhouette_muestreado(self.X, etiquetas)
            db = davies_bouldin_score(self.X, etiquetas)
            cal = calinski_harabasz_score(self.X, etiquetas)
            inertia = getattr(modelo, 'inertia_', None)

            self.resultados.append((k, sil, db, cal, inertia))
            _log(f"   k={k:2d} | silhouette={sil:.4f} | "
                 f"davies_bouldin={db:.4f} | calinski={cal:.1f}")

            score = {'silhouette': sil, 'calinski_harabasz': cal,
                     'davies_bouldin': -db}[criterio]

            if score > mejor_score:
                mejor_score = score
                mejor_k = k
                mejores_etiquetas = etiquetas
                mejor_modelo = modelo

        if mejor_k is None:
            raise ValueError("Ningún k produjo clústeres evaluables en este segmento.")

        self.k_optimo = mejor_k
        self.etiquetas = mejores_etiquetas
        self.modelo_final = mejor_modelo

        _log(f"✔ k óptimo ({self.__class__.__name__}): {self.k_optimo} "
             f"(score {criterio}: {mejor_score:.4f})")

        if graficar:
            self._graficar_busqueda(criterio)

        return self.k_optimo, mejor_score

    def _graficar_busqueda(self, criterio):

        ks = [r[0] for r in self.resultados]
        sil_scores = [r[1] for r in self.resultados]
        db_scores = [r[2] for r in self.resultados]

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))

        ax1.plot(ks, sil_scores, marker='o', color='blue')
        ax1.axvline(self.k_optimo, color='red', linestyle='--',
                    label=f'k óptimo = {self.k_optimo}')
        ax1.set_xlabel('k')
        ax1.set_ylabel('Silhouette (muestreado)')
        ax1.set_title(f'Silhouette - {self.__class__.__name__} {self.etiqueta}')
        ax1.legend()

        ax2.plot(ks, db_scores, marker='s', color='green')
        ax2.axvline(self.k_optimo, color='red', linestyle='--',
                    label=f'k óptimo = {self.k_optimo}')
        ax2.set_xlabel('k')
        ax2.set_ylabel('Davies-Bouldin (completo)')
        ax2.set_title(f'Davies-Bouldin - {self.__class__.__name__} {self.etiqueta}')
        ax2.legend()

        plt.tight_layout()
        plt.savefig(_ruta_grafico(f'evaluacion_{self.__class__.__name__}', self.etiqueta), dpi=150)
        plt.close()


class ModeloJerarquico(ModeloClusterizacionBase):

    def __init__(self, X, k_min=2, k_max=25, linkage_method='ward',
                 n_microclusters=TAM_MICROCLUSTERS, random_state=RANDOM_STATE,
                 etiqueta=''):
        super().__init__(X, k_min, k_max, etiqueta)
        self.linkage_method = linkage_method
        self.n_microclusters = min(n_microclusters, X.shape[0] - 1)
        self.random_state = random_state
        self._Z = None
        self._micro_labels_por_producto = None
        self._centroides = None

    def _preparar_microclusters(self):
        if self._centroides is not None:
            return
        mbk = MiniBatchKMeans(n_clusters=self.n_microclusters,
                              random_state=self.random_state,
                              batch_size=2048, n_init=3)
        self._micro_labels_por_producto = mbk.fit_predict(self.X)
        self._centroides = mbk.cluster_centers_
        _log(f"🧩 Micro-clustering: {self.X.shape[0]:,} filas -> "
             f"{self.n_microclusters} centroides")
        self._Z = linkage(self._centroides, method=self.linkage_method)
        _log("🌳 Linkage jerárquico sobre centroides calculado")

    def _entrenar_con_k(self, k):
        self._preparar_microclusters()
        etiquetas_micro = fcluster(self._Z, k, criterion='maxclust') - 1
        etiquetas_producto = etiquetas_micro[self._micro_labels_por_producto]

        class _ModeloFalso:
            pass

        return _ModeloFalso(), etiquetas_producto

    def graficar_dendrograma(self):
        self._preparar_microclusters()
        plt.figure(figsize=(12, 6))
        dendrogram(self._Z, truncate_mode='lastp', p=40, leaf_rotation=90,
                   leaf_font_size=8, show_contracted=True)
        plt.title(f'Dendrograma {self.etiqueta} (sobre {self.n_microclusters} '
                  f'micro-clusters, truncado a 40 fusiones)')
        plt.xlabel('Micro-clusters')
        plt.ylabel('Distancia')
        plt.tight_layout()
        plt.savefig(_ruta_grafico('dendrograma', self.etiqueta), dpi=150)
        plt.close()


class ModeloKMeans(ModeloClusterizacionBase):

    def __init__(self, X, k_min=2, k_max=25, random_state=RANDOM_STATE,
                 batch_size=2048, etiqueta=''):
        super().__init__(X, k_min, k_max, etiqueta)
        self.random_state = random_state
        self.batch_size = batch_size

    def _entrenar_con_k(self, k):
        modelo = MiniBatchKMeans(n_clusters=k, random_state=self.random_state,
                                 batch_size=self.batch_size, n_init=5)
        etiquetas = modelo.fit_predict(self.X)
        return modelo, etiquetas

    def graficar_codo(self):
        ks = [r[0] for r in self.resultados]
        inercias = [r[4] for r in self.resultados]
        plt.figure(figsize=(8, 5))
        plt.plot(ks, inercias, marker='o', color='purple')
        plt.axvline(self.k_optimo, color='red', linestyle='--',
                    label=f'k óptimo = {self.k_optimo}')
        plt.xlabel('k')
        plt.ylabel('Inercia')
        plt.title(f'Método del codo - MiniBatchKMeans {self.etiqueta}')
        plt.legend()
        plt.tight_layout()
        plt.savefig(_ruta_grafico('codo_kmeans', self.etiqueta), dpi=150)
        plt.close()


class ModeloGMM(ModeloClusterizacionBase):

    def __init__(self, X, k_min=2, k_max=25, random_state=RANDOM_STATE,
                 covariance_type='diag', n_init=3, reg_covar=1e-2, etiqueta=''):
        super().__init__(X, k_min, k_max, etiqueta)
        self.random_state = random_state
        self.covariance_type = covariance_type
        self.n_init = n_init
        self.reg_covar = reg_covar

    def _entrenar_con_k(self, k):
        X_float64 = self.X.astype(np.float64)
        modelo = GaussianMixture(n_components=k, random_state=self.random_state,
                                 covariance_type=self.covariance_type,
                                 n_init=self.n_init, max_iter=100,
                                 reg_covar=self.reg_covar)
        etiquetas = modelo.fit_predict(X_float64)
        return modelo, etiquetas


class ModeloHDBSCAN:

    def __init__(self, X, min_cluster_size_range=None, step=5,
                 random_state=RANDOM_STATE, etiqueta=''):
        self.X = X
        self.n = X.shape[0]
        self.etiqueta = etiqueta

        if min_cluster_size_range is None:
            if self.n <= 200:
                min_cluster_size_range = (5, min(30, self.n // 2))
            elif self.n <= 1000:
                min_cluster_size_range = (10, min(50, self.n // 2))
            else:
                min_cluster_size_range = (20, 200)

        self.min_cluster_size_range = min_cluster_size_range
        self.step = step
        self.random_state = random_state
        self.etiquetas = None
        self.modelo_final = None
        self.mejor_param = None
        self.resultados = []
        self.usar_muestra = self.n > 2000
        self.tam_muestra = min(15000, self.n) if self.usar_muestra else self.n

    def buscar_parametros_optimos(self, graficar=True):

        X_work = self.X if not self.usar_muestra else self._obtener_muestra()

        mejor_sil = -np.inf
        mejor_mcs = None
        mejor_modelo = None

        min_vals = range(self.min_cluster_size_range[0],
                         min(self.min_cluster_size_range[1], self.n - 1) + 1,
                         self.step)

        for mcs in min_vals:
            min_samples = min(mcs, self.n - 1)
            modelo = hdbscan.HDBSCAN(min_cluster_size=mcs, min_samples=min_samples,
                                     core_dist_n_jobs=-1,
                                     prediction_data=self.usar_muestra)
            etiquetas_m = modelo.fit_predict(X_work)

            n_clusters = len(set(etiquetas_m)) - (1 if -1 in etiquetas_m else 0)
            n_noise = int(np.sum(etiquetas_m == -1))

            if n_clusters < 2 or n_noise == len(etiquetas_m):
                sil = -1.0
            else:
                mask = etiquetas_m != -1
                sil = (silhouette_score(X_work[mask], etiquetas_m[mask])
                       if mask.sum() >= 2 else -1.0)

            self.resultados.append((mcs, sil, n_clusters, n_noise))
            _log(f"   min_cluster_size={mcs:4d} | silhouette={sil:.4f} | "
                 f"clusters={n_clusters} | ruido={n_noise:,}")

            if sil > mejor_sil:
                mejor_sil = sil
                mejor_mcs = mcs
                mejor_modelo = modelo

        if mejor_modelo is None:
            raise ValueError("HDBSCAN no evaluó ningún min_cluster_size.")

        self.mejor_param = mejor_mcs
        _log(f"✔ Mejor min_cluster_size: {mejor_mcs} (silhouette: {mejor_sil:.4f})")

        if self.usar_muestra:
            etiquetas_full, _ = hdbscan.approximate_predict(mejor_modelo, self.X)
            _log(f"🔗 approximate_predict sobre {self.n:,} filas")
            self.etiquetas = etiquetas_full
        else:
            self.etiquetas = mejor_modelo.labels_
        self.modelo_final = mejor_modelo

        if graficar:
            self._graficar_busqueda()

        return mejor_mcs, mejor_sil

    def _obtener_muestra(self):
        rng = np.random.default_rng(self.random_state)
        idx = rng.choice(self.n, size=self.tam_muestra, replace=False)
        return self.X[idx]

    def _graficar_busqueda(self):
        mcs_vals = [r[0] for r in self.resultados]
        sil_vals = [r[1] for r in self.resultados]
        n_clusters = [r[2] for r in self.resultados]
        n_noise = [r[3] for r in self.resultados]

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))
        ax1.plot(mcs_vals, sil_vals, marker='o', color='orange')
        ax1.axvline(self.mejor_param, color='red', linestyle='--',
                    label=f'mejor mcs = {self.mejor_param}')
        ax1.set_xlabel('min_cluster_size')
        ax1.set_ylabel('Silhouette')
        ax1.set_title(f'HDBSCAN - Silhouette {self.etiqueta}')
        ax1.legend()

        ax2.plot(mcs_vals, n_clusters, marker='s', color='green', label='#clusters')
        ax2.plot(mcs_vals, n_noise, marker='^', linestyle='--', color='red', label='#ruido')
        ax2.axvline(self.mejor_param, color='red', linestyle='--')
        ax2.set_xlabel('min_cluster_size')
        ax2.set_ylabel('Número')
        ax2.set_title(f'HDBSCAN - Clusters y ruido {self.etiqueta}')
        ax2.legend()

        plt.tight_layout()
        plt.savefig(_ruta_grafico('evaluacion_HDBSCAN', self.etiqueta), dpi=150)
        plt.close()


# ==========================================================================
# 4. VALIDACIÓN, GRANULARIDAD Y PERFILES (idénticos a ambos métodos)
# ==========================================================================

def validar_clusters(df_con_cluster, feature_names):

    clusters = sorted(df_con_cluster['Cluster'].unique())
    _log("--- VALIDACIÓN ESTADÍSTICA (ANOVA) ---")

    columnas_continuas = [c for c in feature_names if not c.startswith('Comportamiento_')]
    anova_results = []

    for col in columnas_continuas:
        grupos = [df_con_cluster.loc[df_con_cluster['Cluster'] == c, col].values
                  for c in clusters]
        grupos = [g for g in grupos if len(g) > 0]
        f_stat, p_val = f_oneway(*grupos)
        anova_results.append({'Feature': col, 'F_stat': f_stat, 'p_valor': p_val})
        _log(f"   {col}: F={f_stat:.3f}, p={p_val:.6f} "
             f"{'(SÍ discrimina)' if p_val < 0.01 else '(NO discrimina bien)'}")

    intra_cv = (
        df_con_cluster.groupby('Cluster')[columnas_continuas]
        .agg(lambda x: x.std() / x.mean() if x.mean() != 0 else np.nan)
        .round(4)
    )

    return pd.DataFrame(anova_results), intra_cv


def calcular_granularidad(df_con_cluster, columna_grupo='Cluster'):
    """
    Mismas fórmulas de agregación que los métodos originales:
    volumen ponderado por demanda, costo ponderado por unidades, suma de
    demandas promedio, suma de valores históricos totales, lead time máximo.
    """
    df_trabajo = df_con_cluster.copy()
    df_trabajo['_costo_x_unidades'] = df_trabajo['Costo Unitario'] * df_trabajo['Total_Unidades']
    df_trabajo['_volumen_x_demanda'] = df_trabajo['Volumen'] * df_trabajo['Demanda_Promedio']

    granularidad = (
        df_trabajo.groupby(columna_grupo).agg(
            N_Productos=('Código', 'count'),
            N_Familias_Distintas=('Denominacion familia', 'nunique'),
            N_Paises_Distintos=('Pais', 'nunique'),
            N_Proveedores_Distintos=('Proveedor', 'nunique'),
            Volumen_Fisico_Semanal_Cluster=('_volumen_x_demanda', 'sum'),
            _suma_costo_x_unidades=('_costo_x_unidades', 'sum'),
            Demanda_Promedio_Semanal_Cluster=('Demanda_Promedio', 'sum'),
            Lead_Time_Maximo=('Lead Time (semanas)', 'max'),
            Unidades_Total_Vendidas=('Total_Unidades', 'sum'),
            Valor_Total_Ventas_Historicas=('Valor_Total_Historico', 'sum'),
        ).reset_index()
    )

    granularidad['Costo_Unitario_Agregado_Cluster'] = (
        granularidad['_suma_costo_x_unidades']
        / granularidad['Unidades_Total_Vendidas'].replace(0, np.nan)
    ).fillna(0)
    granularidad = granularidad.drop(columns=['_suma_costo_x_unidades'])

    total = granularidad['N_Productos'].sum()
    granularidad['Porcentaje_Productos'] = (granularidad['N_Productos'] / total * 100).round(2)

    return granularidad.round(3)[[
        columna_grupo, 'N_Productos', 'Porcentaje_Productos',
        'N_Familias_Distintas', 'N_Paises_Distintos', 'N_Proveedores_Distintos',
        'Volumen_Fisico_Semanal_Cluster', 'Costo_Unitario_Agregado_Cluster',
        'Demanda_Promedio_Semanal_Cluster', 'Lead_Time_Maximo',
        'Unidades_Total_Vendidas', 'Valor_Total_Ventas_Historicas',
    ]]


def perfiles_cluster(df_con_cluster, feature_names):

    def _moda(x):
        m = x.mode()
        return m.iat[0] if not m.empty else 'NA'

    g = df_con_cluster.groupby('Cluster')
    perfil = g[feature_names].mean().round(3)
    perfil['Tamaño'] = g.size()
    perfil['Familia_Moda'] = g['Denominacion familia'].agg(_moda)
    perfil['Pais_Moda'] = g['Pais'].agg(_moda)
    perfil['Comportamiento_Moda'] = g['Comportamiento'].agg(_moda)
    return perfil.reset_index()


def evaluar_solucion_comparable(X, etiquetas):
    """
    Evalúa una solución sobre las mismas filas de X. El ruido de HDBSCAN (-1)
    se reasigna temporalmente al centroide más cercano para que todos los
    métodos se comparen sobre los mismos productos.
    """
    etiquetas = np.asarray(etiquetas).copy()
    n = len(etiquetas)
    ruido = etiquetas == -1
    proporcion_ruido = float(ruido.mean())
    etiquetas_eval = etiquetas.copy()

    if ruido.any():
        labels_validos = sorted(set(etiquetas[~ruido]))
        if len(labels_validos) < 2:
            return {'etiquetas_evaluacion': etiquetas_eval, 'silhouette': -1.0,
                    'davies_bouldin': np.inf, 'calinski_harabasz': -np.inf,
                    'n_clusters': len(labels_validos),
                    'proporcion_ruido': proporcion_ruido,
                    'tam_min_cluster': 0, 'porcentaje_min_cluster': 0.0}

        centroides = {c: X[etiquetas == c].mean(axis=0) for c in labels_validos}
        for idx in np.where(ruido)[0]:
            distancias = {c: np.linalg.norm(X[idx] - centroides[c]) for c in labels_validos}
            etiquetas_eval[idx] = min(distancias, key=distancias.get)

    labels_eval = np.unique(etiquetas_eval)
    if len(labels_eval) < 2:
        sil, db, cal = -1.0, np.inf, -np.inf
    else:
        sil = silhouette_muestreado(X, etiquetas_eval)
        db = davies_bouldin_score(X, etiquetas_eval)
        cal = calinski_harabasz_score(X, etiquetas_eval)

    tamanos = pd.Series(etiquetas_eval).value_counts()
    tam_min = int(tamanos.min()) if len(tamanos) else 0

    return {'etiquetas_evaluacion': etiquetas_eval, 'silhouette': float(sil),
            'davies_bouldin': float(db), 'calinski_harabasz': float(cal),
            'n_clusters': int(len(labels_eval)),
            'proporcion_ruido': proporcion_ruido, 'tam_min_cluster': tam_min,
            'porcentaje_min_cluster': float(tam_min / n) if n else 0.0}


def construir_ranking_modelos(modelos_resultados, X):
    """
    Ranking por suma de posiciones (Borda simple) en Silhouette (↑),
    Davies-Bouldin (↓) y Calinski-Harabasz (↑). Desempate: mayor
    silhouette, luego menor Davies-Bouldin.
    """
    filas = []
    for nombre, res in modelos_resultados.items():
        ev = evaluar_solucion_comparable(X, res['etiquetas'])
        res['evaluacion_comparable'] = ev
        filas.append({
            'Modelo': nombre,
            'k_configuracion': res.get('k'),
            'N_Clusters_Evaluados': ev['n_clusters'],
            'Silhouette_Comparable': ev['silhouette'],
            'Davies_Bouldin_Comparable': ev['davies_bouldin'],
            'Calinski_Harabasz_Comparable': ev['calinski_harabasz'],
            'Proporcion_Ruido_Original': ev['proporcion_ruido'],
            'Tamano_Min_Cluster': ev['tam_min_cluster'],
            'Porcentaje_Min_Cluster': ev['porcentaje_min_cluster'],
        })

    tabla = pd.DataFrame(filas)
    tabla['Rank_Silhouette'] = tabla['Silhouette_Comparable'].rank(ascending=False, method='min')
    tabla['Rank_Davies_Bouldin'] = tabla['Davies_Bouldin_Comparable'].rank(ascending=True, method='min')
    tabla['Rank_Calinski_Harabasz'] = tabla['Calinski_Harabasz_Comparable'].rank(ascending=False, method='min')
    tabla['Puntaje_Ranking'] = (tabla['Rank_Silhouette'] + tabla['Rank_Davies_Bouldin']
                                + tabla['Rank_Calinski_Harabasz'])

    tabla = tabla.sort_values(
        by=['Puntaje_Ranking', 'Silhouette_Comparable', 'Davies_Bouldin_Comparable'],
        ascending=[True, False, True]
    ).reset_index(drop=True)
    tabla['Posicion_Final'] = np.arange(1, len(tabla) + 1)
    return tabla


def _imprimir_resumen_narrativo(df_granularidad, etiqueta_nivel, columna_grupo):

    _log(f"\n📋 Resumen por clúster ({etiqueta_nivel}):")

    for _, fila in df_granularidad.iterrows():
        id_grupo = fila[columna_grupo]
        try:
            id_grupo_str = str(int(id_grupo))
        except (ValueError, TypeError):
            id_grupo_str = str(id_grupo)

        volumen_cm3 = fila['Volumen_Fisico_Semanal_Cluster']
        volumen_m3 = volumen_cm3 / 1_000_000

        _log(
            f"   El {etiqueta_nivel} {id_grupo_str} contiene {int(fila['N_Productos'])} SKU, "
            f"que representan el {fila['Porcentaje_Productos']:.2f}% del catálogo. "
            f"Esos SKU pertenecen a {int(fila['N_Familias_Distintas'])} familias diferentes, "
            f"provienen de {int(fila['N_Paises_Distintos'])} país(es) y tienen "
            f"{int(fila['N_Proveedores_Distintos'])} proveedor(es) distinto(s). "
            f"Su volumen físico agregado es {volumen_cm3:,.0f} cm³/semana "
            f"(≈ {volumen_m3:,.3f} m³/semana), ponderado por la demanda semanal de cada SKU, "
            f"su costo unitario agregado (ponderado por unidades históricas vendidas) es "
            f"${fila['Costo_Unitario_Agregado_Cluster']:,.2f}, su demanda promedio semanal "
            f"conjunta es de aproximadamente {fila['Demanda_Promedio_Semanal_Cluster']:.1f} "
            f"unidades/semana, el mayor lead time es {fila['Lead_Time_Maximo']:.0f} semanas, "
            f"históricamente vendieron {fila['Unidades_Total_Vendidas']:,.0f} unidades en "
            f"conjunto, y su valor total de ventas históricas asciende a "
            f"${fila['Valor_Total_Ventas_Historicas']:,.0f}."
        )


# ==========================================================================
# 5. PIPELINE PRINCIPAL HÍBRIDO
# ==========================================================================

def _clusterizar_segmento(X_seg, segmento, k_min, k_max, correr_hierarquico,
                          correr_hdbscan, scores_por_modelo):
    """
    Corre los 4 algoritmos sobre un segmento y devuelve
    (etiquetas_locales, ganador, tabla_ranking_o_None).
    Misma lógica para el método 1 y el método 2: lo que cambia entre ellos
    es QUÉ SKU entran al segmento, no cómo se clusteriza.
    """
    n_seg = X_seg.shape[0]
    resultados_seg = {}
    k_max_seg = min(k_max, n_seg - 1)
    k_min_seg = max(k_min, 2)
    etiqueta = segmento

    def _registrar(nombre, modelo, buscar, grafica_adicional=None):
        try:
            k_encontrado, score = buscar()
            if grafica_adicional is not None:
                grafica_adicional()
            resultados_seg[nombre] = {
                'modelo': modelo,
                'k': k_encontrado if nombre != 'HDBSCAN' else None,
                'silhouette_interno': score,
                'etiquetas': modelo.etiquetas,
            }
        except (ValueError, RuntimeError, IndexError, TypeError) as exc:
            _log(f"   ⚠️ {nombre}: sin solución evaluable para {segmento}: {exc}")
        scores_por_modelo[nombre].extend(
            [tuple(r) + (segmento,) for r in getattr(modelo, 'resultados', [])]
        )

    if n_seg >= 3 and k_min_seg <= k_max_seg:
        if correr_hierarquico:
            modelo_jer = ModeloJerarquico(X_seg, k_min=k_min_seg, k_max=k_max_seg,
                                          linkage_method='ward', etiqueta=etiqueta)
            _registrar('Jerárquico', modelo_jer,
                       lambda: modelo_jer.buscar_k_optimo(criterio='silhouette', graficar=True),
                       modelo_jer.graficar_dendrograma)

        modelo_kmeans = ModeloKMeans(X_seg, k_min=k_min_seg, k_max=k_max_seg, etiqueta=etiqueta)
        _registrar('K-Means', modelo_kmeans,
                   lambda: modelo_kmeans.buscar_k_optimo(criterio='silhouette', graficar=True),
                   modelo_kmeans.graficar_codo)

        modelo_gmm = ModeloGMM(X_seg, k_min=k_min_seg, k_max=k_max_seg,
                               reg_covar=1e-2, etiqueta=etiqueta)
        _registrar('GMM', modelo_gmm,
                   lambda: modelo_gmm.buscar_k_optimo(criterio='silhouette', graficar=True))

        if correr_hdbscan and HDBSCAN_AVAILABLE and n_seg >= 10:
            modelo_hdb = ModeloHDBSCAN(X_seg, etiqueta=etiqueta)
            _registrar('HDBSCAN', modelo_hdb,
                       lambda: modelo_hdb.buscar_parametros_optimos(graficar=True))

    if resultados_seg:
        tabla_seg = construir_ranking_modelos(resultados_seg, X_seg)
        tabla_seg['Segmento_N'] = segmento
        ganador = tabla_seg.iloc[0]['Modelo']
        etiquetas_locales = resultados_seg[ganador]['evaluacion_comparable']['etiquetas_evaluacion']
        for _, row in tabla_seg.iterrows():
            _log(f"   {row['Modelo']}: Sil={row['Silhouette_Comparable']:.4f} | "
                 f"DB={row['Davies_Bouldin_Comparable']:.4f} | "
                 f"CH={row['Calinski_Harabasz_Comparable']:.1f} | "
                 f"clusters={int(row['N_Clusters_Evaluados'])} | "
                 f"puntaje ranking={row['Puntaje_Ranking']:.0f}")
        return etiquetas_locales, ganador, tabla_seg

    # 1-2 SKU o ningún método evaluable: un solo grupo, nunca se descartan SKU.
    _log("   ⚠️ No es posible validar divisiones: se conserva un solo grupo.")
    return np.zeros(n_seg, dtype=int), 'Sin dividir', None


def ejecutar_clustering_completo(df_productos, k_min=2, k_max=25,
                                 ruta_salida=RUTA_SALIDA_CLUSTERS,
                                 correr_hierarquico=True, correr_hdbscan=True):

    df_productos = df_productos.copy().reset_index(drop=True)
    n_productos = len(df_productos)
    if n_productos == 0:
        raise ValueError("No hay productos para clusterizar.")

    _log("=" * 80)
    _log(f" CLUSTERING HÍBRIDO DE INVENTARIOS ({n_productos:,} SKUs)")
    _log("=" * 80)
    _log(f"⚙️ CONFIRMAR_CON_STL={CONFIRMAR_CON_STL} | UMBRAL_FS={UMBRAL_FS} | "
         f"TRATAMIENTO_INTERMITENTES='{TRATAMIENTO_INTERMITENTES}' | "
         f"PRIORIDAD_INTERMITENCIA={PRIORIDAD_INTERMITENCIA}")

    # Escalado global único (igual que el método 2): los SKU de todos los
    # bloques quedan en la misma escala.
    X_weighted, feature_names, scaler = preparar_features_con_pesos(df_productos)

    # ---- [HÍBRIDO] Segmentación previa -----------------------------------
    asignacion = df_productos.apply(asignar_segmento_hibrido, axis=1, result_type='expand')
    asignacion.columns = ['Segmento_N', 'Metodo_Aplicado', 'Motivo_Segmento']
    df_productos[['Segmento_N', 'Metodo_Aplicado', 'Motivo_Segmento']] = asignacion

    df_segmentacion = (
        df_productos.groupby(['Metodo_Aplicado', 'Segmento_N'])
        .size().reset_index(name='N_SKU')
    )
    df_segmentacion['Porcentaje_SKU'] = (df_segmentacion['N_SKU'] / n_productos * 100).round(2)

    _log("📐 Segmentación híbrida (SKU por bloque):")
    for _, fila in df_segmentacion.iterrows():
        _log(f"   {fila['Metodo_Aplicado']:<26} {fila['Segmento_N']:<16} "
             f"{fila['N_SKU']:>6} SKU ({fila['Porcentaje_SKU']:.1f}%)")

    etiquetas_globales = np.empty(n_productos, dtype=int)
    nombres_modelo = np.empty(n_productos, dtype=object)
    siguiente_cluster = 0
    comparaciones = []
    scores_por_modelo = {'Jerárquico': [], 'K-Means': [], 'GMM': [], 'HDBSCAN': []}

    # Orden: primero los estacionales (método 2), luego no estacionales e
    # intermitentes (método 1). Solo afecta la numeración de los clusters.
    def _orden(seg):
        if seg.startswith('EST_N_'):
            return (0, int(seg.replace('EST_N_', '')))
        return (1 if seg == SEG_NO_EST else 2, 0)

    for segmento in sorted(df_productos['Segmento_N'].unique(), key=_orden):
        indices = df_productos.index[df_productos['Segmento_N'] == segmento].to_numpy(dtype=int)
        metodo = df_productos.loc[indices[0], 'Metodo_Aplicado']
        _log(f"\n--- SEGMENTO {segmento} [{metodo}]: {len(indices)} SKU ---")

        etiquetas_locales, ganador, tabla_seg = _clusterizar_segmento(
            X_weighted[indices], segmento, k_min, k_max,
            correr_hierarquico, correr_hdbscan, scores_por_modelo)
        if tabla_seg is not None:
            comparaciones.append(tabla_seg)

        mapa = {orig: siguiente_cluster + j
                for j, orig in enumerate(sorted(np.unique(etiquetas_locales)))}
        etiquetas_globales[indices] = [mapa[x] for x in etiquetas_locales]
        nombres_modelo[indices] = ganador
        siguiente_cluster += len(mapa)
        _log(f"   ✅ {len(mapa)} clúster(es); modelo seleccionado: {ganador}")

    columnas_comparacion = [
        'Modelo', 'k_configuracion', 'N_Clusters_Evaluados',
        'Silhouette_Comparable', 'Davies_Bouldin_Comparable',
        'Calinski_Harabasz_Comparable', 'Proporcion_Ruido_Original',
        'Tamano_Min_Cluster', 'Porcentaje_Min_Cluster', 'Rank_Silhouette',
        'Rank_Davies_Bouldin', 'Rank_Calinski_Harabasz', 'Puntaje_Ranking',
        'Posicion_Final', 'Segmento_N',
    ]
    tabla_comparacion = (
        pd.concat(comparaciones, ignore_index=True)[columnas_comparacion]
        if comparaciones else pd.DataFrame(columns=columnas_comparacion)
    )

    # ---- Resultado con el mismo esquema que los métodos 1 y 2 ------------
    df_resultado = df_productos.copy()
    df_resultado['Cluster'] = etiquetas_globales
    df_resultado['Modelo_seleccionado'] = nombres_modelo
    if df_resultado.groupby('Cluster')['Segmento_N'].nunique().max() > 1:
        raise RuntimeError("Se mezclaron segmentos distintos en un mismo clúster.")

    # Cluster_Comportamiento = unidad para PRONOSTICAR (patrón de demanda).
    # Cluster_Operativo = Cluster + Proveedor + Pais: unidad para CONSOLIDAR
    # pedidos/contenedores (no se puede consolidar China con Canadá).
    df_resultado['Cluster_Comportamiento'] = df_resultado['Cluster']
    df_resultado['Cluster_Operativo'] = (
        df_resultado['Cluster'].astype(str)
        + '_' + df_resultado['Proveedor'].astype(str).str.strip().str.replace(' ', '', regex=False)
        + '_' + df_resultado['Pais'].astype(str).str.strip().str.replace(' ', '', regex=False)
    )

    # Las columnas híbridas se mueven al final para no alterar posiciones.
    columnas_hibridas = ['Segmento_N', 'Metodo_Aplicado', 'Motivo_Segmento']
    df_resultado = df_resultado[[c for c in df_resultado.columns if c not in columnas_hibridas]
                                + columnas_hibridas]

    df_anova, intra_cv = validar_clusters(df_resultado, feature_names)
    df_granularidad = calcular_granularidad(df_resultado, columna_grupo='Cluster')
    df_granularidad_operativo = calcular_granularidad(df_resultado, columna_grupo='Cluster_Operativo')

    _imprimir_resumen_narrativo(df_granularidad, 'Cluster_Comportamiento', 'Cluster')
    _imprimir_resumen_narrativo(df_granularidad_operativo, 'Cluster_Operativo', 'Cluster_Operativo')

    df_perfil = perfiles_cluster(df_resultado, feature_names)

    # Tabla de segmentación con los clusters que salieron de cada bloque.
    clusters_por_seg = (
        df_resultado.groupby('Segmento_N')['Cluster']
        .agg(N_Clusters='nunique',
             Clusters=lambda x: ', '.join(str(c) for c in sorted(x.unique())))
        .reset_index()
    )
    df_segmentacion = df_segmentacion.merge(clusters_por_seg, on='Segmento_N', how='left')

    _log(f"\n💾 Guardando resultados en Excel ({len(df_resultado):,} filas)...")

    columnas_scores = {
        'HDBSCAN': ['min_cluster_size', 'silhouette', 'n_clusters', 'n_noise', 'Segmento_N'],
        'otros': ['k', 'silhouette', 'davies_bouldin', 'calinski', 'inertia', 'Segmento_N'],
    }

    with pd.ExcelWriter(ruta_salida, engine='xlsxwriter') as writer:
        df_resultado.to_excel(writer, sheet_name='Productos_con_cluster', index=False)
        df_perfil.to_excel(writer, sheet_name='Perfiles_Cluster', index=False)
        df_granularidad.to_excel(writer, sheet_name='Granularidad', index=False)
        df_granularidad_operativo.to_excel(writer, sheet_name='Granularidad_Operativo', index=False)
        df_anova.to_excel(writer, sheet_name='ANOVA_Validacion', index=False)
        intra_cv.to_excel(writer, sheet_name='Intra_CV_Homogeneidad')
        tabla_comparacion.to_excel(writer, sheet_name='Comparacion_Modelos', index=False)

        for nombre in ['Jerárquico', 'K-Means', 'GMM', 'HDBSCAN']:
            if nombre == 'Jerárquico' and not correr_hierarquico:
                continue
            if nombre == 'HDBSCAN' and (not correr_hdbscan or not HDBSCAN_AVAILABLE):
                continue
            cols = columnas_scores['HDBSCAN' if nombre == 'HDBSCAN' else 'otros']
            df_scores = pd.DataFrame(scores_por_modelo[nombre], columns=cols)
            # Mismo orden de columnas que el OG; Segmento_N queda al final.
            df_scores.insert(len(cols) - 1, 'modelo', nombre)
            df_scores.to_excel(writer, sheet_name=f'Scores_{nombre}'[:31], index=False)

        df_segmentacion.to_excel(writer, sheet_name='Segmentacion_Hibrida', index=False)

    _log(f"✅ Excel guardado -> {ruta_salida}")
    _log(f"🏆 Modelo final: Híbrido por segmento | {siguiente_cluster} clústeres en total")

    return df_resultado, df_perfil, df_granularidad


# ==========================================================================
# 6. SERIES SEMANALES POR CLÚSTER -- ALINEADAS A HISTORIA COMÚN
# ==========================================================================

def preparar_unidades_agregadas_por_cluster(df_clusters, df_semanal, fecha_col='Fecha',
                                            sku_col='Código', cluster_col='Cluster',
                                            alinear_por_historia_comun=True):
    """
    Demanda semanal agregada (lunes a domingo) de cada clúster. Si
    alinear_por_historia_comun=True, cada serie arranca en la semana en que
    TODOS sus SKU ya tienen historia (evita tendencia artificial por SKU que
    entran al catálogo más tarde). Misma lógica que los métodos originales.
    """
    df = df_semanal.copy()
    df[fecha_col] = pd.to_datetime(df[fecha_col])

    asignacion = df_clusters[[sku_col, cluster_col]].drop_duplicates(subset=[sku_col])
    df_merged = df.merge(asignacion, on=sku_col, how='inner')

    if 'Unidades' not in df_merged.columns:
        raise ValueError("❌ La columna 'Unidades' no existe en el dataset histórico.")

    df_merged['Semana'] = df_merged[fecha_col].dt.to_period('W-SUN').dt.start_time

    if alinear_por_historia_comun:
        primera_semana_por_sku = df_merged.groupby(sku_col)['Semana'].min()
        cluster_por_sku = asignacion.set_index(sku_col)[cluster_col]
        primera_semana_con_cluster = pd.DataFrame({
            'primera_semana': primera_semana_por_sku,
            cluster_col: cluster_por_sku.reindex(primera_semana_por_sku.index),
        })
        fecha_alineada_por_cluster = (
            primera_semana_con_cluster.groupby(cluster_col)['primera_semana'].max()
        )

        _log("🧭 Alineando cada clúster a su historia común "
             "(el SKU incorporado más tarde marca el punto de partida):")
        for cluster_id, fecha_corte in fecha_alineada_por_cluster.sort_index().items():
            n_semanas_descartadas = df_merged.loc[
                (df_merged[cluster_col] == cluster_id) & (df_merged['Semana'] < fecha_corte),
                'Semana'
            ].nunique()
            _log(f"   Cluster {cluster_id}: inicio común = {fecha_corte.date()} "
                 f"({n_semanas_descartadas} semanas previas descartadas, "
                 f"donde no todos los SKU del clúster ya existían)")

        df_merged['_fecha_alineada_cluster'] = df_merged[cluster_col].map(fecha_alineada_por_cluster)
        df_merged = (df_merged[df_merged['Semana'] >= df_merged['_fecha_alineada_cluster']]
                     .drop(columns=['_fecha_alineada_cluster']).copy())

    serie_semanal = (
        df_merged.groupby([cluster_col, 'Semana'], as_index=False)['Unidades'].sum()
        .rename(columns={'Unidades': 'Unidades_Agregadas'})
        .sort_values([cluster_col, 'Semana'])
    )

    datos_por_cluster = {
        cluster_id: (
            serie_semanal.loc[serie_semanal[cluster_col] == cluster_id,
                              ['Semana', 'Unidades_Agregadas']]
            .set_index('Semana')['Unidades_Agregadas'].sort_index()
        )
        for cluster_id in sorted(serie_semanal[cluster_col].unique())
    }

    for cluster_id, serie in datos_por_cluster.items():
        if len(serie) < 52:
            _log(f"   ⚠️ Cluster {cluster_id}: tras alinear, solo quedan "
                 f"{len(serie)} semanas de historia común -- puede ser "
                 f"insuficiente para un pronóstico confiable.")

    _log(f"✅ Unidades agregadas semanales generadas para {len(datos_por_cluster)} clústeres.")
    return datos_por_cluster


def exportar_unidades_agregadas(unidades_agregadas_por_cluster,
                                ruta_salida=RUTA_SALIDA_AGREGADOS):
    """
    Mismo formato que los métodos originales: una hoja por Cluster_Operativo
    (nombre truncado a 31 caracteres, sin colisiones) + hoja 'Indice'.
    """
    nombres_hoja_usados = {}

    def _nombre_hoja_seguro(cluster_id):
        base = f'Cluster_{cluster_id}'[:31]
        if base not in nombres_hoja_usados:
            nombres_hoja_usados[base] = 0
            return base
        nombres_hoja_usados[base] += 1
        sufijo = f'_{nombres_hoja_usados[base]}'
        return base[:31 - len(sufijo)] + sufijo

    with pd.ExcelWriter(ruta_salida, engine='xlsxwriter') as writer:
        indice_hojas = []
        for cluster_id, serie in unidades_agregadas_por_cluster.items():
            nombre_hoja = _nombre_hoja_seguro(cluster_id)
            indice_hojas.append({'Cluster_Operativo': cluster_id, 'Hoja': nombre_hoja})
            serie.to_frame(name='Unidades_Agregadas').to_excel(writer, sheet_name=nombre_hoja)
        pd.DataFrame(indice_hojas).to_excel(writer, sheet_name='Indice', index=False)

    _log(f"✅ Unidades agregadas guardadas en '{ruta_salida}' "
         f"({len(unidades_agregadas_por_cluster)} hojas).")


# ==========================================================================
# 7. FUNCIÓN LLAMABLE (para la interfaz) Y EJECUCIÓN DIRECTA
# ==========================================================================

def ejecutar_clusterizacion_hibrida(ruta_featuring=RUTA_ENTRADA,
                                    ruta_salida_clusters=RUTA_SALIDA_CLUSTERS,
                                    ruta_salida_agregados=RUTA_SALIDA_AGREGADOS,
                                    k_min=2, k_max=25):
    """Corre todo el módulo de punta a punta. Retorna df_resultado."""
    df_productos = cargar_datos_desde_featuring(ruta_featuring)

    df_resultado, df_perfil, df_granularidad = ejecutar_clustering_completo(
        df_productos, k_min=k_min, k_max=k_max, ruta_salida=ruta_salida_clusters)

    _log("🔍 Muestra de la asignación de clusters:")
    print(df_resultado[['Código', 'Cluster', 'Segmento_N', 'Metodo_Aplicado',
                        'Modelo_seleccionado']].head(10))

    _log("\n📦 Generando unidades agregadas semanales por Cluster_Operativo "
         "(alineadas a historia común)...")
    df_featuring_raw = pd.read_excel(ruta_featuring)
    unidades = preparar_unidades_agregadas_por_cluster(
        df_clusters=df_resultado, df_semanal=df_featuring_raw, fecha_col='Fecha',
        sku_col='Código', cluster_col='Cluster_Operativo',
        alinear_por_historia_comun=True)
    exportar_unidades_agregadas(unidades, ruta_salida_agregados)

    _log("🎯 Proceso completado exitosamente.")
    return df_resultado


if __name__ == "__main__":
    ejecutar_clusterizacion_hibrida()
