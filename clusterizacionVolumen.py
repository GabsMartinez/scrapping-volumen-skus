"""
==============================================================================
CLUSTERING DE INVENTARIOS - VERSIÓN ESCALABLE (109,900+ referencias)
Incluye variables categóricas: Denominacion familia, Pais, Proveedor
Generación de series semanales por clúster, alineadas a historia común
==============================================================================
"""

# [NUEVO N] Segmentación previa por Periodo_N. Se conserva el código OG y sus outputs.
import time
import warnings
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import AgglomerativeClustering, MiniBatchKMeans
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


def _log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


def silhouette_muestreado(
    X,
    etiquetas,
    tam_muestra=TAM_MUESTRA_SILHOUETTE,
    random_state=RANDOM_STATE
):
    n = X.shape[0]

    if n <= tam_muestra:
        return silhouette_score(X, etiquetas)

    return silhouette_score(
        X,
        etiquetas,
        sample_size=tam_muestra,
        random_state=random_state
    )


# ==========================================================================
# 1. CARGA Y PREPARACIÓN DE DATOS
# ==========================================================================

def cargar_datos_desde_featuring(ruta_excel='df_featuring.xlsx'):

    df = pd.read_excel(ruta_excel)

    _log(f"📥 Cargado df_featuring con {len(df):,} filas.")

    columnas_necesarias = [
        'Código',
        'Lead Time (semanas)',
        'Demanda_Promedio',
        'Tendencia_pendiente',
        'CV_Normalizado',
        'ADI',
        'Denominacion familia',
        'Pais',
        'Proveedor',
        'Volumen',
        'Costo Unitario',
        'Unidades',
        'Subtotal',
        'Demanda_std_residuos',
        'Comportamiento',
        'Periodo_N',
        'Periodo_N_estado'
    ]

    faltantes = [
        c for c in columnas_necesarias
        if c not in df.columns
    ]

    if faltantes:
        raise ValueError(
            f"❌ Columnas no encontradas en df_featuring: {faltantes}"
        )

    agg = df.groupby('Código').agg(

        Total_Unidades=(
            'Unidades',
            'sum'
        ),

        Valor_Promedio=(
            'Subtotal',
            'mean'
        ),

        # [NUEVO] Suma real del Subtotal histórico de cada SKU (no el
        # promedio -- ver la corrección en calcular_granularidad para por
        # qué sumar promedios por SKU no da el valor histórico real del
        # clúster). Esta es la base correcta para agregar dinero: sumar
        # SUMAS por SKU sí da la suma total real sobre todas las
        # transacciones de todos los SKU del clúster.
        Valor_Total_Historico=(
            'Subtotal',
            'sum'
        ),

        Zero_Pct=(
            'Subtotal',
            lambda x: (x == 0).mean()
        ),

    ).reset_index()

    columnas_estaticas = [

        'Código',
        'Lead Time (semanas)',
        'Demanda_Promedio',
        'Tendencia_pendiente',
        'CV_Normalizado',
        'ADI',
        'Denominacion familia',
        'Pais',
        'Proveedor',
        'Volumen',
        'Costo Unitario',
        'Demanda_std_residuos',
        'Comportamiento',
        'Periodo_N',
        'Periodo_N_estado'

    ]

    df_productos = (
        df
        .groupby(
            'Código',
            as_index=False
        )
        .first()[columnas_estaticas]
    )

    df_productos = df_productos.merge(
        agg,
        on='Código',
        how='left'
    )

    for col in [
        'Total_Unidades',
        'Valor_Promedio',
        'Valor_Total_Historico',
        'Zero_Pct'
    ]:

        df_productos[col] = (
            df_productos[col]
            .fillna(0)
        )

    # [ADI] A diferencia de Total_Unidades/Valor_Promedio/Zero_Pct, un NaN en
    # ADI NO significa "sin actividad" -- significa "nunca tuvo ninguna
    # semana con demanda real", así que 0 sería el valor MÁS incorrecto
    # posible (0 implicaría demanda todas las semanas, justo lo opuesto).
    # Si aparece (debería ser rarísimo, dado que el pipeline ya exige un
    # mínimo de registros reales por SKU), se imputa con la MEDIANA de ADI
    # del resto del catálogo -- una intermitencia "típica", no un extremo
    # inventado -- y se avisa explícitamente cuál SKU quedó así.
    if df_productos['ADI'].isna().any():
        skus_sin_adi = df_productos.loc[df_productos['ADI'].isna(), 'Código'].tolist()
        mediana_adi = df_productos['ADI'].median()
        _log(
            f"⚠️ {len(skus_sin_adi)} SKU sin ninguna semana de demanda real "
            f"(ADI indefinido): {skus_sin_adi} -- se imputan con la mediana "
            f"de ADI del catálogo ({mediana_adi:.2f}) para poder clusterizarlos."
        )
        df_productos['ADI'] = df_productos['ADI'].fillna(mediana_adi)

    _log(
        f"✅ Agregado a {len(df_productos):,} productos únicos."
    )

    _log(
        f"📊 Variables disponibles: "
        f"{list(df_productos.columns)}"
    )

    return df_productos


# ==========================================================================
# 2. PREPROCESAMIENTO
# ==========================================================================
#
# [ELIMINADO] Existía aquí una función codificar_categoricas() que
# convertía Pais/Proveedor en columnas numéricas (por frecuencia) para
# meterlas en el vector de clustering. Se retiró por completo: para una
# variable NOMINAL como Proveedor, "qué tan común es" no es una medida de
# similitud -- dos proveedores distintos con la misma cuota de mercado
# terminaban siendo matemáticamente idénticos en esa dimensión, y dos con
# cuotas distintas quedaban "lejos" aunque operaran igual. Pais y
# Proveedor siguen en el pipeline, pero como lo que realmente son:
# restricciones operativas a revisar DESPUÉS de clusterizar por patrón de
# demanda (ver N_Paises_Distintos / N_Proveedores_Distintos en
# calcular_granularidad, y Pais_Moda en perfiles_cluster), no como
# ingrediente de la distancia. Ver preparar_features_con_pesos.


def preparar_features_con_pesos(
    df_productos,
    pesos=None
):

    # [CORREGIDO -- SEGUNDA RONDA] Pais y Proveedor SE SACAN por completo
    # del vector de distancia. La codificación por frecuencia que se usó
    # en la ronda anterior (un número = "qué tan común es esa categoría")
    # sigue siendo conceptualmente inválida para una variable NOMINAL: dos
    # proveedores completamente distintos con la misma cuota de mercado
    # quedan matemáticamente idénticos en esa dimensión, y dos con cuotas
    # distintas quedan "lejos" entre sí aunque operen exactamente igual
    # (mismo país, mismas condiciones comerciales). El clustering no debe
    # decidir "estos SKU se parecen" basado en eso.
    #
    # País y Proveedor pasan a ser exactamente lo que son operativamente:
    # una RESTRICCIÓN A REVISAR DESPUÉS de agrupar por patrón de demanda,
    # no un ingrediente de la distancia. Por eso siguen apareciendo en
    # calcular_granularidad (N_Paises_Distintos, N_Proveedores_Distintos)
    # y en perfiles_cluster (Familia_Moda, Pais_Moda) -- para que puedas
    # ver, clúster por clúster, qué tan mezclado quedó en país/proveedor y
    # decidir manualmente si conviene partir alguno por razones operativas
    # (condiciones comerciales, aduanas, moneda, etc.), sin que esa
    # decisión se la haya inventado la distancia euclidiana por su cuenta.
    #
    # El vector de clustering queda así, solo con PATRÓN DE DEMANDA puro:
    # Demanda_Promedio (demanda media), CV_Normalizado, ADI (intermitencia),
    # Tendencia_pendiente y Lead Time (semanas) -- exactamente lo que debe
    # decidir si dos SKU pueden compartir una misma política de inventario.
    # 'Volumen' NO entra aquí (a pedido explícito): sigue disponible más
    # adelante como agregado por clúster en calcular_granularidad
    # ('Volumen_Total_Fisico'), no como criterio de agrupación.
    columnas_numericas = [

        'Demanda_Promedio',
        'CV_Normalizado',
        'ADI',
        'Tendencia_pendiente',
        'Lead Time (semanas)'

    ]

    columnas_extra = [

        'Costo Unitario',
        'Total_Unidades',
        'Volumen',
        'Pais',
        'Proveedor'

    ]

    faltantes = [

        c
        for c in columnas_numericas + columnas_extra
        if c not in df_productos.columns

    ]

    if faltantes:

        raise ValueError(
            f"❌ Columnas no encontradas: {faltantes}"
        )

    X_raw = (
        df_productos[
            columnas_numericas
        ]
        .copy()
    )

    lower = X_raw.quantile(0.05)
    upper = X_raw.quantile(0.95)

    X_raw = X_raw.clip(
        lower=lower,
        upper=upper,
        axis=1
    )

    # [CORREGIDO -- LA VERDADERA CAUSA DE "SOLO 2 CLÚSTERES"] Se verificó
    # con datos reales: el "clúster 0" de k=2 resultó ser, literalmente,
    # los 6 únicos SKU con una caída de tendencia muy pronunciada (entre
    # -0.46 y -1.37, cuando el resto del catálogo se mueve entre -0.02 y
    # +0.02) -- un 4% del catálogo. El recorte de percentiles de arriba
    # antes era 1%/99%, que con solo 151 SKU apenas afecta ~1-2 filas --
    # no alcanzaba a atenuar un grupo de 6. Ahora es 5%/95%, que sí cubre
    # ese grupo completo.
    #
    # Con StandardScaler, esos 6 valores extremos inflaban la desviación
    # estándar de la columna, así que aislarlos del resto separaba casi
    # perfectamente y el silhouette (que es un promedio GLOBAL) quedaba
    # tan alto con esa única separación que ya no "compensaba" seguir
    # dividiendo los otros 145 SKU -- quedaban todos amontonados en un
    # solo clúster sin diferenciación interna, aunque tuvieran Lead Time,
    # CV, ADI y demanda muy distintos entre sí.
    #
    # Se probó también cambiar a RobustScaler (mediana/IQR, pensado para
    # ser menos sensible a outliers) pero resultó CONTRAPRODUCENTE aquí: el
    # rango intercuartílico de Tendencia_pendiente es tan angosto (la
    # mayoría del catálogo vive entre -0.02 y +0.02) que dividir por un
    # IQR tan pequeño deja a los outliers relativamente MÁS lejos, no
    # menos -- el silhouette de k=2 subió de 0.605 a 0.885 en vez de
    # bajar. Se mantiene StandardScaler; el recorte de percentiles más
    # ancho es lo que realmente resuelve el problema.
    scaler = StandardScaler()

    X_scaled = (
        scaler
        .fit_transform(X_raw)
        .astype(np.float32)
    )

    if pesos is None:

        pesos = np.ones(
            len(columnas_numericas),
            dtype=np.float32
        )

    else:

        assert (
            len(pesos)
            == X_scaled.shape[1]
        ), (
            "Los pesos deben coincidir "
            "con el número total de features"
        )

    # Comportamiento es nominal: codificación one-hot sin orden artificial.
    # Cada categoría se incorpora como indicador binario, sin recortar
    # ni estandarizar sus columnas como si fueran magnitudes continuas.
    categorias = df_productos['Comportamiento'].astype('string').fillna('No determinado').str.strip()
    categorias = categorias.mask(categorias.eq(''), 'No determinado')
    dummies = pd.get_dummies(categorias, prefix='Comportamiento', dtype=np.float32)
    columnas_comportamiento = dummies.columns.tolist()

    # Normalizar el bloque: dos categorías diferentes tienen distancia 1.
    # Su peso puede ajustarse por separado, sin cambiar los pesos numéricos.
    peso_comportamiento = 1.0
    X_categorico = dummies.to_numpy(dtype=np.float32) * (peso_comportamiento / np.sqrt(2))
    X_weighted = np.hstack((X_scaled * pesos, X_categorico)).astype(np.float32)

    # Mantener indicadores en el DataFrame para perfiles y validaciones.
    for columna in columnas_comportamiento:
        df_productos[columna] = dummies[columna].to_numpy(dtype=np.float32)

    feature_names = columnas_numericas + columnas_comportamiento

    _log(
        f"🧬 Features para clustering (solo patrón de demanda -- "
        f"Pais/Proveedor quedan fuera de la distancia, ver "
        f"calcular_granularidad para revisarlos después): "
        f"{feature_names}"
    )

    _log(
        f"⚖️ Pesos aplicados "
        f"(todos iguales): "
        f"{pesos.tolist()}"
    )

    _log(
        f"🧮 Matriz de features: "
        f"{X_weighted.shape}, "
        f"{X_weighted.nbytes/1e6:.1f} MB"
    )

    return (
        X_weighted,
        feature_names,
        scaler
    )


# ==========================================================================
# 3. CLASES DE CLUSTERING
# ==========================================================================

class ModeloClusterizacionBase:

    def __init__(
        self,
        X,
        k_min=2,
        k_max=25,
    ):

        self.X = X
        self.k_min = k_min

        self.k_max = min(
            k_max,
            X.shape[0] - 1
        )

        self.k_optimo = None
        self.etiquetas = None
        self.modelo_final = None
        self.resultados = []

    def _entrenar_con_k(
        self,
        k
    ):

        raise NotImplementedError

    def buscar_k_optimo(
        self,
        criterio='silhouette',
        graficar=True
    ):

        mejor_score = -np.inf
        mejor_k = None
        mejores_etiquetas = None
        mejor_modelo = None

        if (
            self.k_min
            > self.k_max
        ):

            self.k_max = min(
                self.k_min + 1,
                self.X.shape[0] - 1
            )

        for k in range(
            self.k_min,
            self.k_max + 1
        ):

            try:
                modelo, etiquetas = self._entrenar_con_k(k)
                if not (1 < len(np.unique(etiquetas)) < self.X.shape[0]):
                    _log(f"   k={k}: etiquetas insuficientes para silhouette; se omite")
                    continue
            except (ValueError, RuntimeError) as exc:
                _log(f"   k={k}: no evaluable ({exc})")
                continue

            sil = silhouette_muestreado(
                self.X,
                etiquetas
            )

            db = davies_bouldin_score(
                self.X,
                etiquetas
            )

            cal = calinski_harabasz_score(
                self.X,
                etiquetas
            )

            inertia = getattr(
                modelo,
                'inertia_',
                None
            )

            self.resultados.append(
                (
                    k,
                    sil,
                    db,
                    cal,
                    inertia
                )
            )

            _log(
                f"   k={k:2d} | "
                f"silhouette={sil:.4f} | "
                f"davies_bouldin={db:.4f} | "
                f"calinski={cal:.1f}"
            )

            score = {

                'silhouette':
                    sil,

                'calinski_harabasz':
                    cal,

                'davies_bouldin':
                    -db

            }[criterio]

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

        _log(
            f"✔ k óptimo "
            f"({self.__class__.__name__}): "
            f"{self.k_optimo} "
            f"(score {criterio}: "
            f"{mejor_score:.4f})"
        )

        if graficar:

            self._graficar_busqueda(
                criterio
            )

        return (
            self.k_optimo,
            mejor_score
        )

    def _graficar_busqueda(
        self,
        criterio
    ):

        ks = [
            r[0]
            for r in self.resultados
        ]

        sil_scores = [
            r[1]
            for r in self.resultados
        ]

        db_scores = [
            r[2]
            for r in self.resultados
        ]

        fig, (
            ax1,
            ax2
        ) = plt.subplots(
            1,
            2,
            figsize=(12, 4)
        )

        ax1.plot(
            ks,
            sil_scores,
            marker='o',
            color='blue'
        )

        ax1.axvline(
            self.k_optimo,
            color='red',
            linestyle='--',
            label=f'k óptimo = {self.k_optimo}'
        )

        ax1.set_xlabel('k')

        ax1.set_ylabel(
            'Silhouette (muestreado)'
        )

        ax1.set_title(
            f'Silhouette - '
            f'{self.__class__.__name__}'
        )

        ax1.legend()

        ax2.plot(
            ks,
            db_scores,
            marker='s',
            color='green'
        )

        ax2.axvline(
            self.k_optimo,
            color='red',
            linestyle='--',
            label=f'k óptimo = {self.k_optimo}'
        )

        ax2.set_xlabel('k')

        ax2.set_ylabel(
            'Davies-Bouldin (completo)'
        )

        ax2.set_title(
            f'Davies-Bouldin - '
            f'{self.__class__.__name__}'
        )

        ax2.legend()

        plt.tight_layout()

        plt.savefig(
            f'evaluacion_'
            f'{self.__class__.__name__}.png',
            dpi=150
        )

        plt.close()


class ModeloJerarquico(
    ModeloClusterizacionBase
):

    def __init__(
        self,
        X,
        k_min=2,
        k_max=25,
        linkage_method='ward',
        n_microclusters=TAM_MICROCLUSTERS,
        random_state=RANDOM_STATE
    ):

        super().__init__(
            X,
            k_min,
            k_max
        )

        self.linkage_method = (
            linkage_method
        )

        self.n_microclusters = min(
            n_microclusters,
            X.shape[0] - 1
        )

        self.random_state = (
            random_state
        )

        self._Z = None

        self._micro_labels_por_producto = (
            None
        )

        self._centroides = None

    def _preparar_microclusters(
        self
    ):

        if self._centroides is not None:
            return

        mbk = MiniBatchKMeans(

            n_clusters=
                self.n_microclusters,

            random_state=
                self.random_state,

            batch_size=2048,

            n_init=3

        )

        self._micro_labels_por_producto = (
            mbk.fit_predict(self.X)
        )

        self._centroides = (
            mbk.cluster_centers_
        )

        _log(
            f"🧩 Micro-clustering: "
            f"{self.X.shape[0]:,} filas -> "
            f"{self.n_microclusters} centroides"
        )

        self._Z = linkage(
            self._centroides,
            method=self.linkage_method
        )

        _log(
            f"🌳 Linkage jerárquico "
            f"sobre centroides calculado"
        )

    def _entrenar_con_k(
        self,
        k
    ):

        self._preparar_microclusters()

        etiquetas_micro = (
            fcluster(
                self._Z,
                k,
                criterion='maxclust'
            )
            - 1
        )

        etiquetas_producto = (
            etiquetas_micro[
                self._micro_labels_por_producto
            ]
        )

        class _ModeloFalso:
            pass

        return (
            _ModeloFalso(),
            etiquetas_producto
        )

    def graficar_dendrograma(
        self
    ):

        self._preparar_microclusters()

        plt.figure(
            figsize=(12, 6)
        )

        dendrogram(

            self._Z,

            truncate_mode=
                'lastp',

            p=40,

            leaf_rotation=90,

            leaf_font_size=8,

            show_contracted=True

        )

        plt.title(
            f'Dendrograma '
            f'(sobre {self.n_microclusters} '
            f'micro-clusters, '
            f'truncado a 40 fusiones)'
        )

        plt.xlabel(
            'Micro-clusters'
        )

        plt.ylabel(
            'Distancia'
        )

        plt.tight_layout()

        plt.savefig(
            'dendrograma.png',
            dpi=150
        )

        plt.close()


class ModeloKMeans(
    ModeloClusterizacionBase
):

    def __init__(
        self,
        X,
        k_min=2,
        k_max=25,
        random_state=RANDOM_STATE,
        batch_size=2048
    ):

        super().__init__(
            X,
            k_min,
            k_max
        )

        self.random_state = (
            random_state
        )

        self.batch_size = (
            batch_size
        )

    def _entrenar_con_k(
        self,
        k
    ):

        modelo = MiniBatchKMeans(

            n_clusters=k,

            random_state=
                self.random_state,

            batch_size=
                self.batch_size,

            n_init=5

        )

        etiquetas = (
            modelo.fit_predict(
                self.X
            )
        )

        return (
            modelo,
            etiquetas
        )

    def graficar_codo(
        self
    ):

        ks = [
            r[0]
            for r in self.resultados
        ]

        inercias = [
            r[4]
            for r in self.resultados
        ]

        plt.figure(
            figsize=(8, 5)
        )

        plt.plot(
            ks,
            inercias,
            marker='o',
            color='purple'
        )

        plt.axvline(
            self.k_optimo,
            color='red',
            linestyle='--',
            label=f'k óptimo = {self.k_optimo}'
        )

        plt.xlabel('k')

        plt.ylabel(
            'Inercia'
        )

        plt.title(
            'Método del codo - '
            'MiniBatchKMeans'
        )

        plt.legend()

        plt.tight_layout()

        plt.savefig(
            'codo_kmeans.png',
            dpi=150
        )

        plt.close()


class ModeloGMM(
    ModeloClusterizacionBase
):

    def __init__(
        self,
        X,
        k_min=2,
        k_max=25,
        random_state=RANDOM_STATE,
        covariance_type='diag',
        n_init=3,
        reg_covar=1e-2
    ):

        super().__init__(
            X,
            k_min,
            k_max
        )

        self.random_state = (
            random_state
        )

        self.covariance_type = (
            covariance_type
        )

        self.n_init = (
            n_init
        )

        self.reg_covar = (
            reg_covar
        )

    def _entrenar_con_k(
        self,
        k
    ):

        X_float64 = (
            self.X.astype(
                np.float64
            )
        )

        modelo = GaussianMixture(

            n_components=k,

            random_state=
                self.random_state,

            covariance_type=
                self.covariance_type,

            n_init=
                self.n_init,

            max_iter=100,

            reg_covar=
                self.reg_covar

        )

        etiquetas = (
            modelo.fit_predict(
                X_float64
            )
        )

        return (
            modelo,
            etiquetas
        )


class ModeloHDBSCAN:

    def __init__(
        self,
        X,
        min_cluster_size_range=None,
        step=5,
        random_state=RANDOM_STATE
    ):

        self.X = X
        self.n = X.shape[0]

        if min_cluster_size_range is None:

            if self.n <= 200:

                min_cluster_size_range = (
                    5,
                    min(
                        30,
                        self.n // 2
                    )
                )

            elif self.n <= 1000:

                min_cluster_size_range = (
                    10,
                    min(
                        50,
                        self.n // 2
                    )
                )

            else:

                min_cluster_size_range = (
                    20,
                    200
                )

        self.min_cluster_size_range = (
            min_cluster_size_range
        )

        self.step = step

        self.random_state = (
            random_state
        )

        self.etiquetas = None
        self.modelo_final = None
        self.mejor_param = None
        self.resultados = []

        self.usar_muestra = (
            self.n > 2000
        )

        self.tam_muestra = (
            min(
                15000,
                self.n
            )
            if self.usar_muestra
            else self.n
        )

    def buscar_parametros_optimos(
        self,
        graficar=True
    ):

        X_work = (
            self.X
            if not self.usar_muestra
            else self._obtener_muestra()
        )

        mejor_sil = -np.inf
        mejor_mcs = None
        mejor_modelo = None

        min_vals = range(

            self.min_cluster_size_range[0],

            min(
                self.min_cluster_size_range[1],
                self.n - 1
            ) + 1,

            self.step

        )

        for mcs in min_vals:

            min_samples = min(
                mcs,
                self.n - 1
            )

            modelo = hdbscan.HDBSCAN(

                min_cluster_size=
                    mcs,

                min_samples=
                    min_samples,

                core_dist_n_jobs=
                    -1,

                prediction_data=
                    self.usar_muestra

            )

            etiquetas_m = (
                modelo.fit_predict(
                    X_work
                )
            )

            n_clusters = (
                len(
                    set(
                        etiquetas_m
                    )
                )
                - (
                    1
                    if -1 in etiquetas_m
                    else 0
                )
            )

            n_noise = int(
                np.sum(
                    etiquetas_m == -1
                )
            )

            if (
                n_clusters < 2
                or
                n_noise == len(
                    etiquetas_m
                )
            ):

                sil = -1.0

            else:

                mask = (
                    etiquetas_m != -1
                )

                sil = (
                    silhouette_score(
                        X_work[mask],
                        etiquetas_m[mask]
                    )
                    if mask.sum() >= 2
                    else -1.0
                )

            self.resultados.append(
                (
                    mcs,
                    sil,
                    n_clusters,
                    n_noise
                )
            )

            _log(
                f"   min_cluster_size="
                f"{mcs:4d} | "
                f"silhouette={sil:.4f} | "
                f"clusters={n_clusters} | "
                f"ruido={n_noise:,}"
            )

            if sil > mejor_sil:

                mejor_sil = sil
                mejor_mcs = mcs
                mejor_modelo = modelo

        self.mejor_param = (
            mejor_mcs
        )

        _log(
            f"✔ Mejor min_cluster_size: "
            f"{mejor_mcs} "
            f"(silhouette: "
            f"{mejor_sil:.4f})"
        )

        if self.usar_muestra:

            etiquetas_full, _ = (
                hdbscan
                .approximate_predict(
                    mejor_modelo,
                    self.X
                )
            )

            _log(
                f"🔗 approximate_predict "
                f"sobre {self.n:,} filas"
            )

            self.etiquetas = (
                etiquetas_full
            )

            self.modelo_final = (
                mejor_modelo
            )

        else:

            self.etiquetas = (
                mejor_modelo.labels_
            )

            self.modelo_final = (
                mejor_modelo
            )

        if graficar:

            self._graficar_busqueda()

        return (
            mejor_mcs,
            mejor_sil
        )

    def _obtener_muestra(
        self
    ):

        rng = (
            np.random
            .default_rng(
                self.random_state
            )
        )

        idx = rng.choice(

            self.n,

            size=
                self.tam_muestra,

            replace=False

        )

        return self.X[idx]

    def _graficar_busqueda(
        self
    ):

        mcs_vals = [
            r[0]
            for r in self.resultados
        ]

        sil_vals = [
            r[1]
            for r in self.resultados
        ]

        n_clusters = [
            r[2]
            for r in self.resultados
        ]

        n_noise = [
            r[3]
            for r in self.resultados
        ]

        fig, (
            ax1,
            ax2
        ) = plt.subplots(
            1,
            2,
            figsize=(12, 4)
        )

        ax1.plot(
            mcs_vals,
            sil_vals,
            marker='o',
            color='orange'
        )

        ax1.axvline(
            self.mejor_param,
            color='red',
            linestyle='--',
            label=f'mejor mcs = '
                  f'{self.mejor_param}'
        )

        ax1.set_xlabel(
            'min_cluster_size'
        )

        ax1.set_ylabel(
            'Silhouette'
        )

        ax1.set_title(
            'HDBSCAN - Silhouette'
        )

        ax1.legend()

        ax2.plot(
            mcs_vals,
            n_clusters,
            marker='s',
            color='green',
            label='#clusters'
        )

        ax2.plot(
            mcs_vals,
            n_noise,
            marker='^',
            linestyle='--',
            color='red',
            label='#ruido'
        )

        ax2.axvline(
            self.mejor_param,
            color='red',
            linestyle='--'
        )

        ax2.set_xlabel(
            'min_cluster_size'
        )

        ax2.set_ylabel(
            'Número'
        )

        ax2.set_title(
            'HDBSCAN - '
            'Clusters y ruido'
        )

        ax2.legend()

        plt.tight_layout()

        plt.savefig(
            'evaluacion_HDBSCAN.png',
            dpi=150
        )

        plt.close()


# ==========================================================================
# 4. VALIDACIÓN, GRANULARIDAD, PERFILES Y POLÍTICAS
# ==========================================================================

def validar_clusters(
    df_con_cluster,
    feature_names
):

    clusters = sorted(
        df_con_cluster[
            'Cluster'
        ].unique()
    )

    _log(
        "--- VALIDACIÓN ESTADÍSTICA "
        "(ANOVA) ---"
    )

    anova_results = []

    for col in [c for c in feature_names if not c.startswith('Comportamiento_')]:

        grupos = [

            df_con_cluster.loc[
                df_con_cluster[
                    'Cluster'
                ] == c,
                col
            ].values

            for c in clusters

        ]

        grupos = [
            g
            for g in grupos
            if len(g) > 0
        ]

        f_stat, p_val = (
            f_oneway(
                *grupos
            )
        )

        anova_results.append(
            {
                'Feature':
                    col,

                'F_stat':
                    f_stat,

                'p_valor':
                    p_val
            }
        )

        _log(
            f"   {col}: "
            f"F={f_stat:.3f}, "
            f"p={p_val:.6f} "
            f"{'(SÍ discrimina)' if p_val < 0.01 else '(NO discrimina bien)'}"
        )

    columnas_continuas = [c for c in feature_names if not c.startswith('Comportamiento_')]
    intra_cv = (
        df_con_cluster
        .groupby(
            'Cluster'
        )[columnas_continuas]
        .agg(
            lambda x:
                x.std() / x.mean()
                if x.mean() != 0
                else np.nan
        )
        .round(4)
    )

    return (
        pd.DataFrame(
            anova_results
        ),
        intra_cv
    )


def calcular_granularidad(
    df_con_cluster,
    columna_grupo='Cluster'
):

    """
    [CORREGIDO -- FÓRMULAS DE AGREGACIÓN] Cada columna de esta tabla se
    agrega según lo que FÍSICA o ECONÓMICAMENTE representa -- no todo se
    puede sumar o promediar igual:

    - Volumen_Fisico_Semanal_Cluster: 'Volumen' es volumen POR UNIDAD, en
      cm³ (confirmado por el usuario), no un total. Sumar directamente el
      volumen-por-unidad de cada SKU (0.001 + 0.010 + 0.500 = 0.511) no
      significa nada físico. Lo que realmente se mueve cada semana es
      volumen-por-unidad × unidades/semana de CADA SKU, sumado entre
      todos: Σ(Volumen_i × Demanda_Promedio_i) -- así si un SKU chico se
      vende 1000/semana y uno grande 20/semana, el chico puede pesar más
      en el total físico aunque su volumen-por-unidad sea menor. Queda en
      cm³/semana (las mismas unidades que trae 'Volumen'), coherente con
      Demanda_Promedio. Ver _imprimir_resumen_narrativo, que además lo
      muestra convertido a m³/semana para lectura rápida.

    - Costo_Unitario_Agregado_Cluster: un promedio simple de costos
      unitarios (Σcosto_i / N) le da el mismo peso a un SKU que vendió
      10 unidades que a uno que vendió 100,000 -- no representa el costo
      real de lo que se movió. Se pondera por unidades históricas
      vendidas: Σ(Costo_i × Total_Unidades_i) / ΣTotal_Unidades_i -- el
      SKU que más se vendió pesa más en el costo "típico" del clúster.
      Es un promedio ponderado, no una suma: sumar costos no tiene
      ninguna interpretación económica.

    - Demanda_Promedio_Semanal_Cluster: Σ Demanda_Promedio de los SKU del
      clúster -- SÍ es correcto sumar aquí, porque Demanda_Promedio ya es
      una tasa (unidades/semana) y la demanda conjunta del clúster es
      literalmente la suma de las demandas individuales.

    - Valor_Total_Ventas_Historicas: 'Valor_Promedio' es el PROMEDIO
      histórico de Subtotal de cada SKU (ver FeaturingVol3.py) -- sumar
      promedios entre SKU (Σ Valor_Promedio) no da el valor económico
      histórico real del clúster, da una suma de promedios sin
      interpretación clara. Lo correcto es sumar el TOTAL histórico de
      cada SKU (Valor_Total_Historico, ya calculado en
      cargar_datos_desde_featuring como suma de Subtotal, no promedio) --
      así Σ Valor_Total_Historico sí es el dinero total real que
      representaron las ventas históricas de todos los SKU del clúster.

    - N_Paises_Distintos / N_Proveedores_Distintos: como Pais y Proveedor
      YA NO son variables de clustering (ver preparar_features_con_pesos),
      estas columnas son la forma de revisar, DESPUÉS de clusterizar por
      patrón de demanda, si un clúster quedó operativamente homogéneo en
      país/proveedor o si mezcla varios -- ver Cluster_Operativo más abajo
      en ejecutar_clustering_completo, que es la restricción logística que
      se construye a partir de esta información.

    - Lead_Time_Maximo: el mayor lead time entre los SKU del clúster --
      el mismo criterio que después usa Pronosticador para decidir si el
      clúster se pronostica en semanas o en meses.

    El parámetro columna_grupo permite reutilizar esta misma función tanto
    a nivel de Cluster_Comportamiento (el clúster estadístico original)
    como de Cluster_Operativo (Cluster_Comportamiento + Proveedor + Pais,
    la unidad que sí puede usarse para consolidar pedidos/contenedores).
    """

    df_trabajo = df_con_cluster.copy()

    df_trabajo['_costo_x_unidades'] = (
        df_trabajo['Costo Unitario'] * df_trabajo['Total_Unidades']
    )
    df_trabajo['_volumen_x_demanda'] = (
        df_trabajo['Volumen'] * df_trabajo['Demanda_Promedio']
    )

    granularidad = (
        df_trabajo
        .groupby(
            columna_grupo
        )
        .agg(

            N_Productos=(
                'Código',
                'count'
            ),

            N_Familias_Distintas=(
                'Denominacion familia',
                'nunique'
            ),

            N_Paises_Distintos=(
                'Pais',
                'nunique'
            ),

            N_Proveedores_Distintos=(
                'Proveedor',
                'nunique'
            ),

            Volumen_Fisico_Semanal_Cluster=(
                '_volumen_x_demanda',
                'sum'
            ),

            _suma_costo_x_unidades=(
                '_costo_x_unidades',
                'sum'
            ),

            Demanda_Promedio_Semanal_Cluster=(
                'Demanda_Promedio',
                'sum'
            ),

            Lead_Time_Maximo=(
                'Lead Time (semanas)',
                'max'
            ),

            Unidades_Total_Vendidas=(
                'Total_Unidades',
                'sum'
            ),

            Valor_Total_Ventas_Historicas=(
                'Valor_Total_Historico',
                'sum'
            )

        )
        .reset_index()
    )

    granularidad['Costo_Unitario_Agregado_Cluster'] = (
        granularidad['_suma_costo_x_unidades']
        / granularidad['Unidades_Total_Vendidas'].replace(0, np.nan)
    ).fillna(0)

    granularidad = granularidad.drop(columns=['_suma_costo_x_unidades'])

    total = (
        granularidad[
            'N_Productos'
        ].sum()
    )

    granularidad[
        'Porcentaje_Productos'
    ] = (
        granularidad[
            'N_Productos'
        ]
        / total
        * 100
    ).round(2)

    return (
        granularidad
        .round(3)
        [
            [
                columna_grupo,
                'N_Productos',
                'Porcentaje_Productos',
                'N_Familias_Distintas',
                'N_Paises_Distintos',
                'N_Proveedores_Distintos',
                'Volumen_Fisico_Semanal_Cluster',
                'Costo_Unitario_Agregado_Cluster',
                'Demanda_Promedio_Semanal_Cluster',
                'Lead_Time_Maximo',
                'Unidades_Total_Vendidas',
                'Valor_Total_Ventas_Historicas'
            ]
        ]
    )


def perfiles_cluster(
    df_con_cluster,
    feature_names
):

    perfil = (
        df_con_cluster
        .groupby(
            'Cluster'
        )[feature_names]
        .mean()
        .round(3)
    )

    perfil[
        'Tamaño'
    ] = (
        df_con_cluster
        .groupby(
            'Cluster'
        )
        .size()
    )

    perfil[
        'Familia_Moda'
    ] = (
        df_con_cluster
        .groupby(
            'Cluster'
        )[
            'Denominacion familia'
        ]
        .agg(
            lambda x:
                x.mode().iat[0]
                if not x.mode().empty
                else 'NA'
        )
    )

    perfil[
        'Pais_Moda'
    ] = (
        df_con_cluster
        .groupby(
            'Cluster'
        )[
            'Pais'
        ]
        .agg(
            lambda x:
                x.mode().iat[0]
                if not x.mode().empty
                else 'NA'
        )
    )

    perfil['Comportamiento_Moda'] = (
        df_con_cluster.groupby('Cluster')['Comportamiento']
        .agg(lambda x: x.mode().iat[0] if not x.mode().empty else 'NA')
    )

    return (
        perfil
        .reset_index()
    )


# [QUITADO] Existía aquí una función recomendar_politicas() que añadía una
# columna 'Politica_Recomendada' por clúster (JIT / EOQ / (s,S) / (Q,r)
# según Valor_Promedio, CV_Normalizado y Zero_Pct). Se retiró por completo
# a pedido explícito: este script responde únicamente "¿qué SKU son
# similares entre sí?" (clustering por patrón de demanda). Qué política de
# inventario conviene para cada perfil resultante es una pregunta distinta,
# de un paso posterior del pipeline -- no debe decidirse ni mezclarse aquí.


def evaluar_solucion_comparable(
    X,
    etiquetas
):

    """
    Evalúa una solución final usando SIEMPRE las mismas filas de X.
    Para HDBSCAN, el ruido (-1) se conserva como ruido para calcular su proporción,
    pero para las métricas comparables se asigna temporalmente al clúster más cercano
    por centroide. Así todos los métodos se evalúan sobre los mismos productos.
    """

    etiquetas = (
        np.asarray(
            etiquetas
        )
        .copy()
    )

    n = len(
        etiquetas
    )

    ruido = (
        etiquetas == -1
    )

    proporcion_ruido = float(
        ruido.mean()
    )

    etiquetas_eval = (
        etiquetas.copy()
    )

    if ruido.any():

        labels_validos = sorted(
            set(
                etiquetas[
                    ~ruido
                ]
            )
        )

        if len(
            labels_validos
        ) < 2:

            return {

                'etiquetas_evaluacion':
                    etiquetas_eval,

                'silhouette':
                    -1.0,

                'davies_bouldin':
                    np.inf,

                'calinski_harabasz':
                    -np.inf,

                'n_clusters':
                    len(
                        labels_validos
                    ),

                'proporcion_ruido':
                    proporcion_ruido,

                'tam_min_cluster':
                    0,

                'porcentaje_min_cluster':
                    0.0

            }

        centroides = {

            c:
                X[
                    etiquetas == c
                ]
                .mean(
                    axis=0
                )

            for c
            in labels_validos

        }

        for idx in np.where(
            ruido
        )[0]:

            distancias = {

                c:
                    np.linalg.norm(
                        X[idx]
                        - centroides[c]
                    )

                for c
                in labels_validos

            }

            etiquetas_eval[
                idx
            ] = min(
                distancias,
                key=distancias.get
            )

    labels_eval = (
        np.unique(
            etiquetas_eval
        )
    )

    if len(
        labels_eval
    ) < 2:

        sil = -1.0
        db = np.inf
        cal = -np.inf

    else:

        sil = (
            silhouette_muestreado(
                X,
                etiquetas_eval
            )
        )

        db = (
            davies_bouldin_score(
                X,
                etiquetas_eval
            )
        )

        cal = (
            calinski_harabasz_score(
                X,
                etiquetas_eval
            )
        )

    tamanos = (
        pd.Series(
            etiquetas_eval
        )
        .value_counts()
    )

    tam_min = (
        int(
            tamanos.min()
        )
        if len(tamanos)
        else 0
    )

    return {

        'etiquetas_evaluacion':
            etiquetas_eval,

        'silhouette':
            float(
                sil
            ),

        'davies_bouldin':
            float(
                db
            ),

        'calinski_harabasz':
            float(
                cal
            ),

        'n_clusters':
            int(
                len(
                    labels_eval
                )
            ),

        'proporcion_ruido':
            proporcion_ruido,

        'tam_min_cluster':
            tam_min,

        'porcentaje_min_cluster':
            float(
                tam_min / n
            )
            if n
            else 0.0

    }


def construir_ranking_modelos(
    modelos_resultados,
    X
):

    """
    Compara las soluciones finales con tres métricas internas:
      - Silhouette: mayor es mejor
      - Davies-Bouldin: menor es mejor
      - Calinski-Harabasz: mayor es mejor

    La selección se hace por suma de posiciones (Borda simple).
    Como desempate: mayor silhouette, luego menor Davies-Bouldin.
    """

    filas = []

    for nombre, res in (
        modelos_resultados
        .items()
    ):

        ev = (
            evaluar_solucion_comparable(
                X,
                res[
                    'etiquetas'
                ]
            )
        )

        res[
            'evaluacion_comparable'
        ] = ev

        filas.append({

            'Modelo':
                nombre,

            'k_configuracion':
                res.get(
                    'k'
                ),

            'N_Clusters_Evaluados':
                ev[
                    'n_clusters'
                ],

            'Silhouette_Comparable':
                ev[
                    'silhouette'
                ],

            'Davies_Bouldin_Comparable':
                ev[
                    'davies_bouldin'
                ],

            'Calinski_Harabasz_Comparable':
                ev[
                    'calinski_harabasz'
                ],

            'Proporcion_Ruido_Original':
                ev[
                    'proporcion_ruido'
                ],

            'Tamano_Min_Cluster':
                ev[
                    'tam_min_cluster'
                ],

            'Porcentaje_Min_Cluster':
                ev[
                    'porcentaje_min_cluster'
                ]

        })

    tabla = pd.DataFrame(
        filas
    )

    tabla[
        'Rank_Silhouette'
    ] = (
        tabla[
            'Silhouette_Comparable'
        ]
        .rank(
            ascending=False,
            method='min'
        )
    )

    tabla[
        'Rank_Davies_Bouldin'
    ] = (
        tabla[
            'Davies_Bouldin_Comparable'
        ]
        .rank(
            ascending=True,
            method='min'
        )
    )

    tabla[
        'Rank_Calinski_Harabasz'
    ] = (
        tabla[
            'Calinski_Harabasz_Comparable'
        ]
        .rank(
            ascending=False,
            method='min'
        )
    )

    tabla[
        'Puntaje_Ranking'
    ] = (

        tabla[
            'Rank_Silhouette'
        ]

        +

        tabla[
            'Rank_Davies_Bouldin'
        ]

        +

        tabla[
            'Rank_Calinski_Harabasz'
        ]

    )

    tabla = (
        tabla
        .sort_values(

            by=[
                'Puntaje_Ranking',
                'Silhouette_Comparable',
                'Davies_Bouldin_Comparable'
            ],

            ascending=[
                True,
                False,
                True
            ]

        )
        .reset_index(
            drop=True
        )
    )

    tabla[
        'Posicion_Final'
    ] = np.arange(
        1,
        len(tabla) + 1
    )

    return tabla


def _imprimir_resumen_narrativo(
    df_granularidad,
    etiqueta_nivel,
    columna_grupo
):

    """
    Imprime el párrafo narrativo de caracterización para cada fila de una
    tabla de granularidad -- reutilizable tanto para Cluster_Comportamiento
    como para Cluster_Operativo, pasándole la tabla correspondiente y el
    nombre de su columna de agrupación (el valor puede ser numérico, como
    en Cluster, o texto, como en Cluster_Operativo -- p.ej. '1_JINANMECH_CHINA').

    [CONFIRMADO POR EL USUARIO] La columna 'Volumen' original está en cm³
    por unidad, así que Volumen_Fisico_Semanal_Cluster (Volumen ponderado
    por demanda semanal, ver calcular_granularidad) también queda en
    cm³/semana. Como esos números salen en el orden de millones de cm³
    (ilegible en una frase), se muestra también convertido a m³/semana
    (÷ 1,000,000) para lectura rápida, sin perder el valor exacto en cm³.
    """

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
# 5. PIPELINE PRINCIPAL
# ==========================================================================

def ejecutar_clustering_completo(
    df_productos,
    k_min=2,
    k_max=25,
    ruta_salida='clusters_asignados_completo.xlsx',
    correr_hierarquico=True,
    correr_hdbscan=True
):

    # [NUEVO N] El DataFrame conserva el mismo esquema de salida del original.
    # Las variables y su escalado global se calculan exactamente una vez,
    # como en la versión original, antes de separar por Periodo_N.
    df_productos = df_productos.copy().reset_index(drop=True)
    n_productos = len(df_productos)
    if n_productos == 0:
        raise ValueError("No hay productos para clusterizar.")

    _log("=" * 80)
    _log(f" CLUSTERING DE INVENTARIOS POR N ({n_productos:,} SKUs)")
    _log("=" * 80)

    X_weighted, feature_names, scaler = preparar_features_con_pesos(df_productos)

    # [NUEVO N] Diferenciar N=0 (evaluado, sin periodo detectado)
    # de N no evaluable/inconcluso (ausencia de evidencia).
    def _identificar_segmento_n(fila):
        estado = str(fila['Periodo_N_estado']).strip()
        numero = pd.to_numeric(fila['Periodo_N'], errors='coerce')
        if estado == 'Detectada' and pd.notna(numero) and numero > 0:
            return f"N_{int(numero)}"
        if estado == 'No detectada' and pd.notna(numero) and numero == 0:
            return 'N_0'
        if estado == 'Inconcluso':
            return 'N_Inconcluso'
        return 'N_No_evaluable'

    df_productos['Segmento_N'] = df_productos.apply(_identificar_segmento_n, axis=1)
    _log("📐 Segmentos N (SKU por segmento):")
    for segmento, cantidad in df_productos['Segmento_N'].value_counts().sort_index().items():
        _log(f"   {segmento}: {cantidad}")

    # Los ID numéricos globales conservan el nombre y tipo de la columna Cluster.
    etiquetas_globales = np.empty(n_productos, dtype=int)
    nombres_modelo = np.empty(n_productos, dtype=object)
    siguiente_cluster = 0
    comparaciones = []

    # Los scores se acumulan por algoritmo y se exportan en las mismas hojas,
    # con las mismas columnas y el mismo nombre que en el código OG.
    columnas_scores = {
        'Jerárquico': ['k', 'silhouette', 'davies_bouldin', 'calinski', 'inertia'],
        'K-Means': ['k', 'silhouette', 'davies_bouldin', 'calinski', 'inertia'],
        'GMM': ['k', 'silhouette', 'davies_bouldin', 'calinski', 'inertia'],
        'HDBSCAN': ['min_cluster_size', 'silhouette', 'n_clusters', 'n_noise'],
    }
    scores_por_modelo = {nombre: [] for nombre in columnas_scores}

    for segmento, df_seg in df_productos.groupby('Segmento_N', sort=True):
        indices = df_seg.index.to_numpy(dtype=int)
        X_seg = X_weighted[indices]
        n_seg = len(indices)
        _log(f"\n--- SEGMENTO {segmento}: {n_seg} SKU ---")
        resultados_seg = {}

        # k debe permitir silhouette: 2 <= k <= n-1. Sin mínimos
        # arbitrarios de tamaño; segmentos no evaluables se mantienen unidos.
        k_max_seg = min(k_max, n_seg - 1)
        k_min_seg = max(k_min, 2)

        def _registrar(nombre, modelo, buscar, grafica_adicional=None):
            try:
                k_encontrado, score = buscar()
                if grafica_adicional is not None:
                    grafica_adicional()
                resultados_seg[nombre] = {
                    'modelo': modelo,
                    'k': k_encontrado,
                    'silhouette_interno': score,
                    'etiquetas': modelo.etiquetas,
                }
                scores_por_modelo[nombre].extend(modelo.resultados)
            except (ValueError, RuntimeError, IndexError, TypeError) as exc:
                _log(f"   ⚠️ {nombre}: sin solución evaluable para {segmento}: {exc}")
                # Conserva, si existen, las puntuaciones evaluadas hasta el fallo.
                scores_por_modelo[nombre].extend(getattr(modelo, 'resultados', []))

        if n_seg >= 3 and k_min_seg <= k_max_seg:
            if correr_hierarquico:
                modelo_jer = ModeloJerarquico(
                    X_seg, k_min=k_min_seg, k_max=k_max_seg, linkage_method='ward'
                )
                _registrar(
                    'Jerárquico', modelo_jer,
                    lambda: modelo_jer.buscar_k_optimo(criterio='silhouette', graficar=True),
                    modelo_jer.graficar_dendrograma,
                )

            modelo_kmeans = ModeloKMeans(X_seg, k_min=k_min_seg, k_max=k_max_seg)
            _registrar(
                'K-Means', modelo_kmeans,
                lambda: modelo_kmeans.buscar_k_optimo(criterio='silhouette', graficar=True),
                modelo_kmeans.graficar_codo,
            )

            modelo_gmm = ModeloGMM(
                X_seg, k_min=k_min_seg, k_max=k_max_seg, reg_covar=1e-2
            )
            _registrar(
                'GMM', modelo_gmm,
                lambda: modelo_gmm.buscar_k_optimo(criterio='silhouette', graficar=True),
            )

            if correr_hdbscan and HDBSCAN_AVAILABLE and n_seg >= 10:
                modelo_hdb = ModeloHDBSCAN(X_seg)
                _registrar(
                    'HDBSCAN', modelo_hdb,
                    lambda: modelo_hdb.buscar_parametros_optimos(graficar=True),
                )

        if resultados_seg:
            tabla_seg = construir_ranking_modelos(resultados_seg, X_seg)
            tabla_seg['Segmento_N'] = segmento
            comparaciones.append(tabla_seg)
            ganador = tabla_seg.iloc[0]['Modelo']
            etiquetas_locales = resultados_seg[ganador]['evaluacion_comparable']['etiquetas_evaluacion']
        else:
            # Necesario para 1-2 SKU o cuando ningún método produce
            # una solución estadísticamente evaluable; nunca se descartan SKU.
            ganador = 'Sin dividir'
            etiquetas_locales = np.zeros(n_seg, dtype=int)
            _log("   ⚠️ No es posible validar divisiones: se conserva un solo grupo.")

        # Asignación única de etiquetas entre segmentos, sin cambiar el tipo
        # numérico ni el nombre que consumen los módulos posteriores.
        mapa = {
            original: siguiente_cluster + j
            for j, original in enumerate(sorted(np.unique(etiquetas_locales)))
        }
        etiquetas_globales[indices] = [mapa[x] for x in etiquetas_locales]
        nombres_modelo[indices] = ganador
        siguiente_cluster += len(mapa)
        _log(f"   ✅ {len(mapa)} clúster(es); modelo seleccionado: {ganador}")

    # Mantener las columnas del ranking original; Segmento_N se añade al
    # final para no alterar las posiciones de las columnas preexistentes.
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

    # La exportación OG recorre modelos_resultados[nombre]['modelo'].resultados.
    # Esta estructura de adaptación preserva ese recorrido SIN modificar
    # ninguna de las hojas ni las columnas de scores existentes.
    class _RegistroResultados:
        def __init__(self, resultados):
            self.resultados = resultados

    modelos_resultados = {}
    for nombre in ['Jerárquico', 'K-Means', 'GMM', 'HDBSCAN']:
        if nombre == 'Jerárquico' and not correr_hierarquico:
            continue
        if nombre == 'HDBSCAN' and (not correr_hdbscan or not HDBSCAN_AVAILABLE):
            continue
        modelos_resultados[nombre] = {
            'modelo': _RegistroResultados(scores_por_modelo[nombre]),
        }

    # Salida OG: mismas columnas Cluster y Modelo_seleccionado.
    df_resultado = df_productos.copy()
    df_resultado['Cluster'] = etiquetas_globales
    df_resultado['Modelo_seleccionado'] = nombres_modelo
    if df_resultado.groupby('Cluster')['Segmento_N'].nunique().max() > 1:
        raise RuntimeError("La segmentación N se mezcló al asignar etiquetas finales.")

    # El resumen original al final también conserva su texto y formato.
    mejor_nombre = 'Por segmento N'
    mejor_k = None

    # [NUEVO] Cluster_Comportamiento vs Cluster_Operativo -- dos preguntas
    # distintas que no deben confundirse:
    #
    # 'Cluster' / 'Cluster_Comportamiento' (alias, mismo valor): SKU con
    # patrón de demanda similar (Demanda_Promedio, CV, ADI, Tendencia,
    # Lead Time) -- esto es lo que decide el algoritmo de clustering, y es
    # lo que sigue usando el resto del pipeline (traductor, Pronosticador)
    # como 'Cluster'. Sigue siendo la unidad correcta para PRONOSTICAR
    # demanda: SKU de comportamiento similar comparten un modelo de
    # pronóstico razonablemente.
    #
    # 'Cluster_Operativo' = Cluster_Comportamiento + Proveedor + Pais: la
    # unidad correcta para CONSOLIDAR PEDIDOS/CONTENEDORES. Dos SKU pueden
    # tener demanda casi idéntica y terminar en el mismo Cluster_Comportamiento,
    # pero si uno se compra a un proveedor en China y otro a un proveedor
    # en Canadá, no pueden consolidarse en el mismo pedido ni en el mismo
    # contenedor -- son flujos logísticos distintos (tránsito, aduana,
    # ruta). Partir cada Cluster_Comportamiento por Proveedor+Pais da la
    # unidad real sobre la que puede correr una política de inventario
    # conjunta con sentido operativo, SIN descartar la información de
    # similitud de demanda que ya encontró el clustering -- simplemente
    # se usa esa información en la etapa que le corresponde (logística),
    # no en la distancia del clustering (que sigue siendo solo patrón de
    # demanda, ver preparar_features_con_pesos).
    df_resultado[
        'Cluster_Comportamiento'
    ] = df_resultado['Cluster']

    df_resultado[
        'Cluster_Operativo'
    ] = (
        df_resultado['Cluster'].astype(str)
        + '_'
        + df_resultado['Proveedor'].astype(str).str.strip().str.replace(' ', '', regex=False)
        + '_'
        + df_resultado['Pais'].astype(str).str.strip().str.replace(' ', '', regex=False)
    )

    df_anova, intra_cv = (
        validar_clusters(
            df_resultado,
            feature_names
        )
    )

    df_granularidad = (
        calcular_granularidad(
            df_resultado,
            columna_grupo='Cluster'
        )
    )

    df_granularidad_operativo = (
        calcular_granularidad(
            df_resultado,
            columna_grupo='Cluster_Operativo'
        )
    )

    _imprimir_resumen_narrativo(df_granularidad, 'Cluster_Comportamiento', 'Cluster')
    _imprimir_resumen_narrativo(df_granularidad_operativo, 'Cluster_Operativo', 'Cluster_Operativo')

    df_perfil = (
        perfiles_cluster(
            df_resultado,
            feature_names
        )
    )

    # [QUITADO] Antes aquí se llamaba recomendar_politicas() y se añadía
    # una columna 'Politica_Recomendada' + una hoja 'Politicas_Recomendadas'
    # al Excel. Se saca por pedido explícito: este script responde a la
    # pregunta "¿qué SKU son similares entre sí?" (clustering), no a
    # "¿qué política de inventario conviene para ese perfil?" -- son dos
    # preguntas distintas y no deben mezclarse en el mismo archivo. La
    # función recomendar_politicas() se eliminó por completo de este
    # archivo (no solo se dejó de invocar).

    _log(
        f"\n💾 Guardando resultados "
        f"en Excel "
        f"({len(df_resultado):,} filas)..."
    )

    with pd.ExcelWriter(
        ruta_salida,
        engine='xlsxwriter'
    ) as writer:

        df_resultado.to_excel(
            writer,
            sheet_name='Productos_con_cluster',
            index=False
        )

        df_perfil.to_excel(
            writer,
            sheet_name='Perfiles_Cluster',
            index=False
        )

        df_granularidad.to_excel(
            writer,
            sheet_name='Granularidad',
            index=False
        )

        df_granularidad_operativo.to_excel(
            writer,
            sheet_name='Granularidad_Operativo',
            index=False
        )

        df_anova.to_excel(
            writer,
            sheet_name='ANOVA_Validacion',
            index=False
        )

        intra_cv.to_excel(
            writer,
            sheet_name='Intra_CV_Homogeneidad'
        )

        tabla_comparacion.to_excel(
            writer,
            sheet_name='Comparacion_Modelos',
            index=False
        )

        for nombre, res in (
            modelos_resultados
            .items()
        ):

            if nombre == 'HDBSCAN':

                cols = [

                    'min_cluster_size',
                    'silhouette',
                    'n_clusters',
                    'n_noise'

                ]

            else:

                cols = [

                    'k',
                    'silhouette',
                    'davies_bouldin',
                    'calinski',
                    'inertia'

                ]

            df_scores = (
                pd.DataFrame(

                    res[
                        'modelo'
                    ].resultados,

                    columns=
                        cols

                )
            )

            df_scores[
                'modelo'
            ] = nombre

            sheet_name = (
                f'Scores_{nombre}'[
                    :31
                ]
            )

            df_scores.to_excel(
                writer,
                sheet_name=sheet_name,
                index=False
            )

    _log(
        f"✅ Excel guardado -> {ruta_salida}"
    )

    _log(
        f"🏆 Modelo final: "
        f"{mejor_nombre}"
        +
        (
            f" | k={mejor_k}"
            if mejor_k
            else " | k automático"
        )
    )

    return (
        df_resultado,
        df_perfil,
        df_granularidad
    )


# ==========================================================================
# 6. SERIES SEMANALES POR CLÚSTER -- ALINEADAS A HISTORIA COMÚN
# ==========================================================================

def preparar_unidades_agregadas_por_cluster(
    df_clusters,
    df_semanal,
    fecha_col='Fecha',
    sku_col='Código',
    cluster_col='Cluster',
    alinear_por_historia_comun=True,
):

    """
    Construye la demanda semanal agregada de cada clúster.

    Para cada semana, suma las unidades vendidas de TODOS los SKU
    que pertenecen al mismo clúster.

    Cada semana corresponde al periodo:
        lunes -> domingo

    [ALINEACIÓN DE HISTORIA COMÚN] Los SKU de un mismo clúster no
    necesariamente empezaron a venderse en la misma fecha -- unos tienen
    historia desde 2009, otros desde 2015, otros desde 2021. Cada SKU, en
    df_semanal, solo tiene filas desde SU PROPIA primera semana con datos
    en adelante (la reindexación semanal en el script de lectura nunca
    rellena hacia atrás de esa fecha). Sumar directamente todas las
    semanas de todos los SKU de un clúster mezclaría, en las semanas más
    antiguas, la suma de solo los pocos SKU que ya existían entonces --
    creando una tendencia de crecimiento ARTIFICIAL en la serie agregada
    del clúster (parece que la demanda crece, pero en realidad solo se
    está incorporando un producto nuevo al catálogo). Eso es justamente el
    tipo de sesgo que después el traductor podría confundir con tendencia
    o estacionalidad real al hacer STL.

    Si alinear_por_historia_comun=True (por defecto), la serie de cada
    clúster se recorta para empezar solo en la semana a partir de la cual
    TODOS sus SKU ya tienen historia -- es decir, la fecha de inicio del
    SKU que se incorporó más tarde dentro de ese clúster ("todos tienen
    data en común desde esa fecha, se deja así"). Como cada SKU ya viene
    reindexado semana a semana sin huecos desde su propio inicio, una vez
    recortada al punto común la serie del clúster no tiene huecos: cada
    semana restante refleja la suma de exactamente el mismo conjunto de
    SKU durante todo el periodo.

    Pásale alinear_por_historia_comun=False si en algún caso prefieres la
    suma cruda sin este recorte (por ejemplo, para inspeccionar el efecto
    tú mismo comparando ambas versiones).

    Retorna:
        dict {
            cluster_id: Serie de pandas indexada por Semana
        }
    """

    df = df_semanal.copy()

    # Asegurar que Fecha sea tipo datetime
    df[fecha_col] = pd.to_datetime(
        df[fecha_col]
    )

    # Relación SKU -> Cluster obtenida del modelo ganador
    asignacion = (
        df_clusters[
            [
                sku_col,
                cluster_col
            ]
        ]
        .drop_duplicates(
            subset=[
                sku_col
            ]
        )
    )

    # Incorporar el cluster de cada SKU al histórico de ventas
    df_merged = df.merge(

        asignacion,

        on=
            sku_col,

        how=
            'inner'

    )

    if (
        'Unidades'
        not in df_merged.columns
    ):

        raise ValueError(
            "❌ La columna 'Unidades' "
            "no existe en el dataset histórico."
        )

    # ============================================================
    # CREAR PERIODO SEMANAL
    # Semana de lunes a domingo
    # ============================================================

    df_merged[
        'Semana'
    ] = (

        df_merged[
            fecha_col
        ]

        .dt.to_period(
            'W-SUN'
        )

        .dt.start_time

    )

    # ============================================================
    # ALINEAR CADA CLÚSTER A SU HISTORIA COMÚN
    # ============================================================

    if alinear_por_historia_comun:

        primera_semana_por_sku = (
            df_merged
            .groupby(sku_col)['Semana']
            .min()
        )

        cluster_por_sku = (
            asignacion
            .set_index(sku_col)[cluster_col]
        )

        primera_semana_con_cluster = pd.DataFrame({
            'primera_semana': primera_semana_por_sku,
            cluster_col: cluster_por_sku.reindex(primera_semana_por_sku.index),
        })

        fecha_alineada_por_cluster = (
            primera_semana_con_cluster
            .groupby(cluster_col)['primera_semana']
            .max()
        )

        _log(
            "🧭 Alineando cada clúster a su historia común "
            "(el SKU incorporado más tarde marca el punto de partida):"
        )

        for cluster_id, fecha_corte in fecha_alineada_por_cluster.sort_index().items():
            n_semanas_descartadas = (
                df_merged.loc[
                    (df_merged[cluster_col] == cluster_id)
                    & (df_merged['Semana'] < fecha_corte),
                    'Semana'
                ]
                .nunique()
            )
            _log(
                f"   Cluster {cluster_id}: inicio común = {fecha_corte.date()} "
                f"({n_semanas_descartadas} semanas previas descartadas, "
                f"donde no todos los SKU del clúster ya existían)"
            )

        df_merged['_fecha_alineada_cluster'] = (
            df_merged[cluster_col].map(fecha_alineada_por_cluster)
        )
        df_merged = (
            df_merged[df_merged['Semana'] >= df_merged['_fecha_alineada_cluster']]
            .drop(columns=['_fecha_alineada_cluster'])
            .copy()
        )

    # ============================================================
    # SUMAR TODAS LAS UNIDADES DE TODOS LOS SKU
    # DE CADA CLUSTER, SEMANA A SEMANA
    # ============================================================

    serie_semanal = (

        df_merged

        .groupby(
            [
                cluster_col,
                'Semana'
            ],
            as_index=False
        )[
            'Unidades'
        ]

        .sum()

        .rename(
            columns={
                'Unidades':
                    'Unidades_Agregadas'
            }
        )

        .sort_values(
            [
                cluster_col,
                'Semana'
            ]
        )

    )

    # ============================================================
    # CREAR UNA SERIE INDEPENDIENTE PARA CADA CLUSTER
    # ============================================================

    datos_por_cluster = {

        cluster_id: (

            serie_semanal.loc[

                serie_semanal[
                    cluster_col
                ] == cluster_id,

                [
                    'Semana',
                    'Unidades_Agregadas'
                ]

            ]

            .set_index(
                'Semana'
            )[
                'Unidades_Agregadas'
            ]

            .sort_index()

        )

        for cluster_id
        in sorted(
            serie_semanal[
                cluster_col
            ].unique()
        )

    }

    for cluster_id, serie in datos_por_cluster.items():
        if len(serie) < 52:
            _log(
                f"   ⚠️ Cluster {cluster_id}: tras alinear, solo quedan "
                f"{len(serie)} semanas de historia común -- puede ser "
                f"insuficiente para un pronóstico confiable (STL en el "
                f"traductor necesita al menos 104 semanas para estimar "
                f"estacionalidad de forma fiable)."
            )

    _log(
        f"✅ Unidades agregadas semanales "
        f"generadas para "
        f"{len(datos_por_cluster)} clústeres."
    )

    return datos_por_cluster


# ==========================================================================
# 7. EJECUCIÓN
# ==========================================================================

if __name__ == "__main__":

    df_productos = (
        cargar_datos_desde_featuring(
            'df_featuring.xlsx'
        )
    )

    (
        df_resultado,
        df_perfil,
        df_granularidad
    ) = ejecutar_clustering_completo(

        df_productos,

        k_min=2,

        k_max=25,

        ruta_salida=
            'clusters_asignados_completo.xlsx'

    )

    _log(
        "🔍 Muestra de la asignación "
        "de clusters:"
    )

    print(

        df_resultado[
            [
                'Código',
                'Cluster',
                'Modelo_seleccionado'
            ]
        ]
        .head(10)

    )

    # ============================================================
    # SERIES SEMANALES (ALINEADAS A HISTORIA COMÚN POR DEFECTO)
    # ============================================================
    #
    # [CORREGIDO] Esto se calcula por 'Cluster_Operativo', no por
    # 'Cluster' (Cluster_Comportamiento). Antes se calculaba por 'Cluster'
    # aquí Y se volvía a calcular por 'Cluster_Operativo' en
    # TraductorClusterPronostico.py -- trabajo caro (recorre todo
    # df_featuring para alinear historia común) repetido dos veces sobre
    # agrupaciones distintas, y la de 'Cluster' ya no la consume nadie
    # río abajo (el pronóstico trabaja sobre Cluster_Operativo). Ahora se
    # calcula una sola vez, aquí, por la agrupación que sí se usa después;
    # TraductorClusterPronostico.py reutiliza este mismo archivo en vez de
    # recalcularlo (ver FORZAR_RECALCULAR_AGREGADOS en su __main__).

    _log(
        "\n📦 Generando unidades "
        "agregadas semanales "
        "por Cluster_Operativo (alineadas a historia común)..."
    )

    df_featuring_raw = (
        pd.read_excel(
            'df_featuring.xlsx'
        )
    )

    unidades_agregadas_por_cluster = (
        preparar_unidades_agregadas_por_cluster(

            df_clusters=
                df_resultado,

            df_semanal=
                df_featuring_raw,

            fecha_col=
                'Fecha',

            sku_col=
                'Código',

            cluster_col=
                'Cluster_Operativo',

            alinear_por_historia_comun=True

        )
    )

    # [CORREGIDO] Nombres de hoja seguros para Excel (límite de 31
    # caracteres). Con 'Cluster_Operativo' (ej. '11_RELIABLE_ESTADOSUNIDOS')
    # el nombre f'Cluster_{cluster_id}' supera 31 caracteres en 6 de los 18
    # grupos reales de este catálogo -- xlsxwriter habría fallado al
    # escribir el archivo. Se trunca a 31 y, si dos nombres truncados
    # coinciden (no ocurre en este catálogo, pero podría con otro), se
    # numeran para no pisarse.
    nombres_hoja_usados = {}

    def _nombre_hoja_seguro(cluster_id):
        base = f'Cluster_{cluster_id}'[:31]
        if base not in nombres_hoja_usados:
            nombres_hoja_usados[base] = 0
            return base
        nombres_hoja_usados[base] += 1
        sufijo = f'_{nombres_hoja_usados[base]}'
        return base[:31 - len(sufijo)] + sufijo

    with pd.ExcelWriter(
        'unidades_agregadas_por_cluster.xlsx',
        engine='xlsxwriter'
    ) as writer:

        indice_hojas = []

        for (
            cluster_id,
            serie
        ) in (
            unidades_agregadas_por_cluster
            .items()
        ):

            nombre_hoja = _nombre_hoja_seguro(cluster_id)
            indice_hojas.append({'Cluster_Operativo': cluster_id, 'Hoja': nombre_hoja})

            serie.to_frame(
                name='Unidades_Agregadas'
            ).to_excel(

                writer,

                sheet_name=nombre_hoja

            )

        # [NUEVO] Hoja de índice: como el nombre de hoja puede quedar
        # truncado respecto al Cluster_Operativo real (límite de 31
        # caracteres de Excel), esta tabla es la única forma confiable de
        # reconstruir qué hoja corresponde a qué clúster al releer el
        # archivo -- TraductorClusterPronostico.py la usa para reutilizar
        # este archivo en vez de recalcular las series agregadas.
        pd.DataFrame(indice_hojas).to_excel(writer, sheet_name='Indice', index=False)

    _log(
        f"✅ Unidades agregadas guardadas en "
        f"'unidades_agregadas_por_cluster.xlsx' "
        f"({len(unidades_agregadas_por_cluster)} hojas)."
    )

    _log(
        "🎯 Proceso completado exitosamente."
    )
