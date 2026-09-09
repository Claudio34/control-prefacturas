import streamlit as st
import pandas as pd
from supabase import create_client
from datetime import datetime
import altair as alt
import numpy as np
import re

# =========================
# 1) PAGE CONFIG
# =========================
st.set_page_config(page_title="PREFACTURAS", layout="wide")

# =========================
# 2) SUPABASE CONNECTION
# =========================
URL = st.secrets["SUPABASE_URL"]
KEY = st.secrets["SUPABASE_KEY"]

@st.cache_resource
def init_connection():
    return create_client(URL, KEY)

supabase = init_connection()

# =========================
# 3) UI HEADER
# =========================
st.title("⚡ PREFACTURAS")
from datetime import datetime, timezone, timedelta
tz_nic = timezone(timedelta(hours=-6))
st.caption(f"Última actualización: {datetime.now(tz_nic).strftime('%d/%m/%Y %H:%M')}")

# --- CSS para KPIs tipo pipeline ---
st.markdown("""
<style>
.pipe-wrap{display:flex; gap:14px; align-items:stretch; margin:12px 0 8px 0; flex-wrap:wrap;}
.pipe-card{
  flex:1; min-width:210px;
  padding:16px 18px; border-radius:16px;
  border:1px solid rgba(49,51,63,0.15);
  background: rgba(255,255,255,0.70);
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
.pipe-title{font-size:.85rem; color:#6b7280; font-weight:800; display:flex; gap:8px; align-items:center; flex-wrap:wrap;}
.pipe-value{font-size:2.0rem; font-weight:900; color:#111827; line-height:1.05; margin-top:6px;}
.pipe-sub{font-size:.82rem; color:#6b7280; margin-top:6px;}
.pipe-money{font-size:1.0rem; font-weight:800; margin-top:2px;}
.pipe-money .tag{font-weight:600; font-size:.72rem; opacity:.75; margin-left:4px;}
.pipe-bar{height:8px; background:rgba(15,23,42,0.08); border-radius:999px; overflow:hidden; margin-top:10px;}
.pipe-bar span{display:block; height:100%; border-radius:999px;}
.badge{display:inline-block; padding:2px 10px; border-radius:999px; font-size:.75rem; font-weight:900;}
.small-muted{color:#6b7280; font-size:.82rem; margin-top:4px;}
/* Tarjeta destacada (Importe Real): colores fijos para que se lea igual en tema claro u oscuro */
.pipe-card.pipe-highlight{
  background:#ecfdf5 !important;
  border:1px solid rgba(16,185,129,0.45) !important;
}
.pipe-card.pipe-highlight .pipe-title{ color:#047857 !important; }
.pipe-card.pipe-highlight .pipe-value{ color:#065f46 !important; }
.pipe-card.pipe-highlight .pipe-sub{ color:#059669 !important; }
</style>
""", unsafe_allow_html=True)

# =========================
# 4) LOAD DATA
# =========================
def cargar_datos():
    response = supabase.table('prefacturas_pedidos').select("*").order('id').execute()
    return pd.DataFrame(response.data)

df = cargar_datos()

if df.empty:
    st.warning("⚠️ No se han cargado datos. Revisa tu conexión a Supabase.")
    st.stop()

# --- Normalizar nombres de columnas ---
rename_map = {}
if 'Sector' in df.columns and 'sector' not in df.columns:
    rename_map['Sector'] = 'sector'
if 'Subsector' in df.columns and 'subsector' not in df.columns:
    rename_map['Subsector'] = 'subsector'

# Buscar columnas de importes sin importar mayúsculas/espacios/guiones bajos
# (en Supabase pueden estar como "Importe Real", "importe_real", "IMPORTE REAL", etc.)
# Guardamos el nombre ORIGINAL de cada una para poder revertir el rename al guardar en Supabase.
def _detectar_columna_importe(df_in, nombre_interno, alias_normalizado):
    """Busca en df_in una columna que normalice a `alias_normalizado` (sin espacios/guiones/mayúsculas)
    y devuelve (nombre_original_o_None, entrada_para_rename_map_o_None)."""
    if nombre_interno in df_in.columns:
        return nombre_interno, None
    for c in df_in.columns:
        c_norm = c.strip().lower().replace(' ', '').replace('_', '')
        if c_norm == alias_normalizado:
            return c, (c, nombre_interno)
    return None, None

IMPORTE_REAL_COL_ORIGINAL, _entrada = _detectar_columna_importe(df, 'importe_real', 'importereal')
if _entrada:
    rename_map[_entrada[0]] = _entrada[1]

IMPORTE_PREVISTO_COL_ORIGINAL, _entrada = _detectar_columna_importe(df, 'importe_previsto', 'importeprevisto')
if _entrada:
    rename_map[_entrada[0]] = _entrada[1]

IMPORTE_PENDIENTE_COL_ORIGINAL, _entrada = _detectar_columna_importe(df, 'importe_pendiente', 'importependiente')
if _entrada:
    rename_map[_entrada[0]] = _entrada[1]

if rename_map:
    df = df.rename(columns=rename_map)

# --- Validaciones mínimas ---
if 'sector' not in df.columns:
    st.error("❌ No encuentro la columna 'sector'. Columnas detectadas: " + str(df.columns.tolist()))
    st.stop()

# --- Convertir texto a fechas reales ---
columnas_fechas = [
    "fecha_elaboracion",
    "fecha_formato",
    "fecha_solicitud_modificacion",
    "fecha_entrega_post_modificacion",
    "fecha_conciliacion",
    "fecha_firma_ingenica",
    "fecha_entrega_final_ingenica_central",
    "fecha_firma_dnds",
    "fecha_edicion_pedido"
]
for col in columnas_fechas:
    if col in df.columns:
        df[col] = pd.to_datetime(df[col], errors='coerce').dt.date

# --- Normalizar columnas tipo catálogo para que calcen con los combobox ---
for col in ["sector", "subsector", "periodo", "area", "sub_area"]:
    if col in df.columns:
        df[col] = (
            df[col]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.upper()
        )

# --- Convertir importe_real a numérico (el importe real a facturar) ---
def parse_importe(valor):
    """Convierte a float aceptando formatos como 198474.04, 198,474.04, 198.474,04, 'C$198474.04', None, etc."""
    if valor is None:
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor) if not pd.isna(valor) else 0.0
    s = str(valor).strip()
    if s == '' or s.lower() in ('none', 'nan', 'nat'):
        return 0.0
    s = re.sub(r'[^0-9,.\-]', '', s)  # quita símbolos de moneda, espacios, letras
    if ',' in s and '.' in s:
        if s.rfind(',') > s.rfind('.'):
            # coma es el separador decimal (formato latino: 198.474,04)
            s = s.replace('.', '').replace(',', '.')
        else:
            # punto es el separador decimal (formato US: 198,474.04)
            s = s.replace(',', '')
    elif ',' in s:
        # solo coma: decide si es decimal o miles según cantidad de dígitos tras la última coma
        partes = s.split(',')
        s = s.replace(',', '.') if len(partes[-1]) in (1, 2) else s.replace(',', '')
    try:
        return float(s)
    except ValueError:
        return 0.0

for _col_importe in ['importe_real', 'importe_previsto', 'importe_pendiente']:
    if _col_importe in df.columns:
        df[_col_importe] = df[_col_importe].apply(parse_importe)

# =========================
# 5) HELPERS (CYCLE LOGIC)
# =========================
def serie_pedido_lleno(df_in: pd.DataFrame) -> pd.Series:
    """True si pedido NO está vacío (maneja None, '', '   ')."""
    if 'pedido' not in df_in.columns:
        return pd.Series([False] * len(df_in), index=df_in.index)
    return df_in['pedido'].fillna('').astype(str).str.strip().ne('')

def aplicar_filtro_estado(df_in: pd.DataFrame, estado: str) -> pd.DataFrame:
    """Filtra el dataframe según el estado seleccionado del ciclo."""
    if estado == "Ver Todo":
        return df_in

    # Si faltan columnas críticas, no filtre y avise
    for c in ["fecha_elaboracion", "fecha_conciliacion"]:
        if c not in df_in.columns:
            st.warning(f"⚠️ Falta la columna '{c}'. No se aplicó el filtro de estado.")
            return df_in

    pedido_lleno = serie_pedido_lleno(df_in)

    if estado == "Pendientes de Elaborar":
        return df_in[df_in['fecha_elaboracion'].isnull()]

    if estado == "Pendientes de Conciliar":
        return df_in[
            df_in['fecha_elaboracion'].notnull() &
            df_in['fecha_conciliacion'].isnull()
        ]

    if estado == "Pendientes de Pedido":
        return df_in[
            df_in['fecha_conciliacion'].notnull() &
            (~pedido_lleno)
        ]

    if estado == "Pedidos Recibidos":
        return df_in[
            df_in['fecha_conciliacion'].notnull() &
            (pedido_lleno)
        ]

    return df_in

def etapa_excluyente(df_in: pd.DataFrame) -> pd.Series:
    """Devuelve etapa por fila (excluyente) según ciclo."""
    pedido_lleno = serie_pedido_lleno(df_in)

    # Si faltan columnas, no romper
    if 'fecha_elaboracion' not in df_in.columns or 'fecha_conciliacion' not in df_in.columns:
        return pd.Series(["Sin clasificar"] * len(df_in), index=df_in.index)

    conds = [
        df_in['fecha_elaboracion'].isnull(),
        df_in['fecha_elaboracion'].notnull() & df_in['fecha_conciliacion'].isnull(),
        df_in['fecha_conciliacion'].notnull() & (~pedido_lleno),
        df_in['fecha_conciliacion'].notnull() & (pedido_lleno),
    ]
    etapas = [
        "Por Elaborar",
        "Por Conciliar",
        "Pendiente de Pedido",
        "Pedido Recibido",
    ]
    return pd.Series(np.select(conds, etapas, default="Sin clasificar"), index=df_in.index)

# =========================
# LISTAS PARA COMBOBOX
# =========================
SECTORES = ["MANAGUA", "NORTE", "OCCIDENTE", "ORIENTE", "SUR"]
SUBSECTORES = ["MANAGUA DN", "MANAGUA DS", "NORTE", "OCCIDENTE", "ORIENTE", "SUR"]
MESES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
         "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]
PERIODOS = [f"{m} 1Q" for m in MESES] + [f"{m} 2Q" for m in MESES]
AREAS = ["MANTENIMIENTO", "DESARROLLO", "PROYECTOS", "PNESER", "CAMPAÑA", "PSSEN"]

# =========================
# 5b) RECALCULAR IMPORTE PREVISTO / IMPORTE PENDIENTE
# =========================
# Diccionario de normalización de sub_area (variantes de escritura → forma única), para que el
# promedio histórico no separe en grupos distintos algo que en realidad es la misma sub-área.
# Mismo criterio usado en el cálculo original del 08/09/2026 (ver hoja "Normalización aplicada").
# Casos con código realmente distinto (EA vs KV, ESTELI vs MATAGALPA, etc.) NO se unifican.
ALIAS_SUB_AREA = {
    ('MANAGUA', 'CAMPAÑA', 'INGENIEROS Y TENICOS'): 'INGENIEROS/TECNICOS',
    ('MANAGUA', 'CAMPAÑA', 'INGENIEROS/ TECNICOS'): 'INGENIEROS/TECNICOS',
    ('MANAGUA', 'CAMPAÑA', 'TÉCNICOS'): 'TECNICOS',
    ('MANAGUA', 'CAMPAÑA', 'VEHÍCULO'): 'VEHICULO',
    ('MANAGUA', 'DESARROLLO', 'PPSSE TERCERO'): 'PPSS TERCERO',
    ('MANAGUA', 'MANTENIMIENTO', 'CAMIONES DE PODA'): 'CAMIONES PODA',
    ('MANAGUA', 'MANTENIMIENTO', 'VEHICULOS GERENCIA'): 'VEHICULO GERENCIA',
    ('MANAGUA', 'PROYECTOS', 'TERCERO'): 'PPSS TERCERO',
    ('NORTE', 'DESARROLLO', 'ADMINISTRATIVA'): 'ADMINISTRATIVO',
    ('NORTE', 'DESARROLLO', 'PPSS PROPIAS'): 'PPSS PROPIA',
    ('NORTE', 'DESARROLLO', 'PPSS TERCEROS'): 'PPSS TERCERO',
    ('NORTE', 'MANTENIMIENTO', 'ADMINISTRATIVA'): 'ADMINISTRATIVO',
    ('NORTE', 'MANTENIMIENTO', 'CAMIONES DE PODA'): 'CAMIONES PODA',
    ('NORTE', 'MANTENIMIENTO', 'DIGITADORAS'): 'DIGITADORES',
    ('NORTE', 'PNESER', 'ADMINISTRATIVA'): 'ADMINISTRATIVO',
    ('NORTE', 'PNESER', 'PNESER C1 DNDS'): 'PNESER C1 (DNDS)',
    ('NORTE', 'PNESER', 'PNESERC2'): 'PNESER C2',
    ('OCCIDENTE', 'MANTENIMIENTO', 'MTTO- PODA'): 'MTTO-PODA',
    ('ORIENTE', 'CAMPAÑA', 'CAMPAÑAS'): 'CAMPAÑA',
    ('ORIENTE', 'DESARROLLO', 'PPSS PROPIAS'): 'PPSS PROPIA',
    ('ORIENTE', 'DESARROLLO', 'PPSS TERCEROS'): 'PPSS TERCERO',
    ('ORIENTE', 'DESARROLLO', 'PROPIA'): 'PPSS PROPIA',
    ('ORIENTE', 'DESARROLLO', 'PROPIAS'): 'PPSS PROPIA',
    ('ORIENTE', 'DESARROLLO', 'TERCEROS'): 'PPSS TERCERO',
    ('ORIENTE', 'MANTENIMIENTO', 'DIGITADORES - TECNICOS'): 'DIGITADORES-TECNICOS',
    ('ORIENTE', 'MANTENIMIENTO', 'DIGITADORES/TECNICOS'): 'DIGITADORES-TECNICOS',
    ('SUR', 'DESARROLLO', 'PPSS PROPIAS'): 'PPSS PROPIA',
    ('SUR', 'DESARROLLO', 'PPSS TERCEROS'): 'PPSS TERCERO',
    ('SUR', 'DESARROLLO', 'PROPIA'): 'PPSS PROPIA',
    ('SUR', 'DESARROLLO', 'TERCERO'): 'PPSS TERCERO',
    ('SUR', 'MANTENIMIENTO', 'ADMINISTRADOR'): 'ADMINISTRATIVO',
    ('SUR', 'MANTENIMIENTO', 'CAMION DE PODA'): 'CAMIONES PODA',
    ('SUR', 'MANTENIMIENTO', 'CAMION PODA'): 'CAMIONES PODA',
    ('SUR', 'MANTENIMIENTO', 'CAMIONES DE PODA'): 'CAMIONES PODA',
    ('SUR', 'MANTENIMIENTO', 'PODA - CAMIONES'): 'CAMIONES PODA',
    ('SUR', 'MANTENIMIENTO', 'DIGITADOR  EA'): 'DIGITADOR EA',
    ('SUR', 'MANTENIMIENTO', 'DIGITADOR- EA'): 'DIGITADOR EA',
    ('SUR', 'MANTENIMIENTO', 'DIGITADORES EA'): 'DIGITADOR EA',
    ('SUR', 'MANTENIMIENTO', 'DIGITADORES E'): 'DIGITADOR EA',
    ('SUR', 'MANTENIMIENTO', 'DIGITADORES EA -EP'): 'DIGITADOR EA-EP',
    ('SUR', 'MANTENIMIENTO', 'DIGITADORES EA-EP'): 'DIGITADOR EA-EP',
    ('SUR', 'MANTENIMIENTO', 'DIGITADORES K'): 'DIGITADOR KV',
    ('SUR', 'MANTENIMIENTO', 'DIGITADORES KV'): 'DIGITADOR KV',
    ('SUR', 'PNESER', 'ADMIN'): 'ADMINISTRATIVO',
    ('SUR', 'PNESER', 'ADMINISTRATIVA'): 'ADMINISTRATIVO',
}


def recalcular_previsto_pendiente():
    """
    Vuelve a calcular Importe Previsto / Importe Pendiente / Previsto Confianza / Previsto N Datos
    para TODAS las prefacturas, usando siempre la información más reciente de Supabase (no la
    tabla ya cargada en pantalla, por si hay filtros aplicados).

    Metodología (igual a la del cálculo original del 08/09/2026):
    - Si la prefactura YA tiene Importe Real (> 0): Previsto = Real, Pendiente = 0,
      Confianza = "Real", N Datos = None.
    - Si NO tiene Real todavía: Previsto = promedio de Importe Real de otras prefacturas del
      mismo Sector + Área + Sub-área (normalizada), sin incluir nunca el propio valor de la fila
      (leave-one-out). Si ese grupo no tiene suficiente historial, se usa como respaldo el
      promedio de Sector + Área. Si tampoco hay datos, queda "Sin datos" (Previsto = None).
      Pendiente = Previsto (porque el Real todavía es 0).
    - Confianza según cantidad de datos usados: Alta (≥5), Media (3-4), Baja (1-2),
      "Estimado (nivel Sector+Área)" cuando se usó el respaldo.
    """
    resp = supabase.table('prefacturas_pedidos').select(
        'id, sector, area, sub_area, "Importe Real"'
    ).execute()
    dfr = pd.DataFrame(resp.data)
    if dfr.empty:
        return {"total": 0, "con_real": 0, "alta": 0, "media": 0, "baja": 0,
                "estimado": 0, "sin_datos": 0}

    dfr['Importe Real'] = pd.to_numeric(dfr['Importe Real'], errors='coerce')
    dfr['sector_n'] = dfr['sector'].fillna('').astype(str).str.strip().str.upper()
    dfr['area_n'] = dfr['area'].fillna('').astype(str).str.strip().str.upper()
    dfr['sub_area_n'] = dfr['sub_area'].fillna('').astype(str).str.strip().str.upper()
    dfr['sub_area_canon'] = [
        ALIAS_SUB_AREA.get((sec, ar, sa), sa) if sa else ''
        for sec, ar, sa in zip(dfr['sector_n'], dfr['area_n'], dfr['sub_area_n'])
    ]
    dfr['tiene_real'] = dfr['Importe Real'].fillna(0) > 0
    dfr['real_val'] = dfr['Importe Real'].fillna(0)

    # --- Nivel 1: Sector + Área + Sub-área (canon), con leave-one-out ---
    dfr['grupo1'] = np.where(
        (dfr['sector_n'] != '') & (dfr['area_n'] != '') & (dfr['sub_area_canon'] != ''),
        dfr['sector_n'] + '||' + dfr['area_n'] + '||' + dfr['sub_area_canon'],
        None
    )
    g1 = dfr[dfr['tiene_real']].groupby('grupo1')['real_val'].agg(['sum', 'count'])
    dfr = dfr.merge(g1.rename(columns={'sum': 'g1_sum', 'count': 'g1_n'}), on='grupo1', how='left')
    dfr['g1_sum'] = dfr['g1_sum'].fillna(0.0)
    dfr['g1_n'] = dfr['g1_n'].fillna(0).astype(int)
    dfr['g1_sum_loo'] = dfr['g1_sum'] - np.where(dfr['tiene_real'], dfr['real_val'], 0.0)
    dfr['g1_n_loo'] = dfr['g1_n'] - np.where(dfr['tiene_real'], 1, 0)

    # --- Nivel 2 (respaldo): Sector + Área, con leave-one-out ---
    dfr['grupo2'] = np.where(
        (dfr['sector_n'] != '') & (dfr['area_n'] != ''),
        dfr['sector_n'] + '||' + dfr['area_n'],
        None
    )
    g2 = dfr[dfr['tiene_real']].groupby('grupo2')['real_val'].agg(['sum', 'count'])
    dfr = dfr.merge(g2.rename(columns={'sum': 'g2_sum', 'count': 'g2_n'}), on='grupo2', how='left')
    dfr['g2_sum'] = dfr['g2_sum'].fillna(0.0)
    dfr['g2_n'] = dfr['g2_n'].fillna(0).astype(int)
    dfr['g2_sum_loo'] = dfr['g2_sum'] - np.where(dfr['tiene_real'], dfr['real_val'], 0.0)
    dfr['g2_n_loo'] = dfr['g2_n'] - np.where(dfr['tiene_real'], 1, 0)

    previsto_calc, confianza_calc, n_datos_calc = [], [], []
    for _, row in dfr.iterrows():
        if row['g1_n_loo'] > 0:
            p = row['g1_sum_loo'] / row['g1_n_loo']
            n = int(row['g1_n_loo'])
            c = 'Alta' if n >= 5 else ('Media' if n >= 3 else 'Baja')
        elif row['g2_n_loo'] > 0:
            p = row['g2_sum_loo'] / row['g2_n_loo']
            n = int(row['g2_n_loo'])
            c = 'Estimado (nivel Sector+Área)'
        else:
            p, n, c = None, 0, 'Sin datos'
        previsto_calc.append(p)
        confianza_calc.append(c)
        n_datos_calc.append(n if p is not None else 0)

    dfr['previsto_calc'] = previsto_calc
    dfr['confianza_calc'] = confianza_calc
    dfr['n_datos_calc'] = n_datos_calc

    # --- Regla: filas que YA tienen Real → Previsto = Real, Pendiente = 0 ---
    dfr['previsto_final'] = np.where(dfr['tiene_real'], dfr['real_val'], dfr['previsto_calc'])
    dfr['confianza_final'] = np.where(dfr['tiene_real'], 'Real', dfr['confianza_calc'])
    dfr['n_datos_final'] = np.where(dfr['tiene_real'], np.nan, dfr['n_datos_calc'])
    dfr['pendiente_final'] = np.where(
        dfr['tiene_real'], 0.0,
        np.where(pd.notna(dfr['previsto_calc']), dfr['previsto_calc'], np.nan)
    )

    # --- Armar registros y guardar en Supabase, en lotes ---
    registros = []
    for _, row in dfr.iterrows():
        prev = row['previsto_final']
        pend = row['pendiente_final']
        ndat = row['n_datos_final']
        registros.append({
            'id': int(row['id']),
            'Importe Previsto': None if pd.isna(prev) else float(round(prev, 2)),
            'Importe Pendiente': None if pd.isna(pend) else float(round(pend, 2)),
            'Previsto Confianza': row['confianza_final'],
            # Entero real (no "10.0"), igual que la corrección aplicada al guardado normal.
            'Previsto N Datos': None if pd.isna(ndat) else int(ndat),
        })

    LOTE = 200
    for i in range(0, len(registros), LOTE):
        supabase.table('prefacturas_pedidos').upsert(registros[i:i + LOTE]).execute()

    return {
        "total": len(dfr),
        "con_real": int(dfr['tiene_real'].sum()),
        "alta": int((dfr['confianza_final'] == 'Alta').sum()),
        "media": int((dfr['confianza_final'] == 'Media').sum()),
        "baja": int((dfr['confianza_final'] == 'Baja').sum()),
        "estimado": int((dfr['confianza_final'] == 'Estimado (nivel Sector+Área)').sum()),
        "sin_datos": int((dfr['confianza_final'] == 'Sin datos').sum()),
    }


# =========================
# 6) SIDEBAR FILTERS
# =========================
st.sidebar.header("🎯 Filtros de Gestión")
st.sidebar.caption("Puedes elegir varias opciones en cada filtro. Vacío = todas.")

lista_sectores = sorted(df['sector'].dropna().unique().tolist())
filtro_sector = st.sidebar.multiselect("Seleccionar Sector:", lista_sectores, default=[])

# Periodos presentes en los datos, ordenados cronológicamente (no alfabético)
periodos_en_datos = df['periodo'].dropna().unique().tolist() if 'periodo' in df.columns else []
lista_periodos = [p for p in PERIODOS if p in periodos_en_datos]
filtro_periodo = st.sidebar.multiselect("Seleccionar Periodo:", lista_periodos, default=[])

lista_areas = sorted(df['area'].dropna().unique().tolist()) if 'area' in df.columns else []
filtro_area = st.sidebar.multiselect("Seleccionar Área:", lista_areas, default=[])

lista_subareas = sorted([s for s in df['sub_area'].dropna().unique().tolist() if s != ""]) if 'sub_area' in df.columns else []
filtro_subarea = st.sidebar.multiselect("Seleccionar Sub Área:", lista_subareas, default=[])

filtro_estado = st.sidebar.radio(
    "Mostrar solo:",
    ["Ver Todo", "1. Pendientes de Elaborar", "2. Pendientes de Conciliar", "3. Pendientes de Pedido", "4. Pedidos Recibidos"]
)

# Sector "único" seleccionado (solo cuando el usuario eligió exactamente uno): se usa más abajo
# para decidir si los gráficos se desglosan por Subsector (MANAGUA DN/DS) — con varios sectores
# elegidos, o ninguno, el desglose vuelve a ser por Sector.
sector_unico = filtro_sector[0] if len(filtro_sector) == 1 else None

# =========================
# 7) DATASETS (IMPORTANT!)
# =========================
# df_sector: filtro de sector + periodo + área + subárea
df_sector = df.copy()
if filtro_sector:
    df_sector = df_sector[df_sector["sector"].isin(filtro_sector)]
if filtro_periodo and 'periodo' in df_sector.columns:
    df_sector = df_sector[df_sector["periodo"].isin(filtro_periodo)]
if filtro_area and 'area' in df_sector.columns:
    df_sector = df_sector[df_sector["area"].isin(filtro_area)]
if filtro_subarea and 'sub_area' in df_sector.columns:
    df_sector = df_sector[df_sector["sub_area"].isin(filtro_subarea)]

# df_vista: sector + periodo + área + subárea + estado (lo que seleccionó el usuario)
df_vista = aplicar_filtro_estado(df_sector, filtro_estado)

# df_tablero: lo que usan KPIs + gráfico (aquí SÍ cambian con el radio)
df_tablero = df_vista

# df_filtrado: lo que usa la tabla (igual df_vista)
df_filtrado = df_vista

# =========================
# 8) KPIs / PIPELINE (df_tablero)
# =========================
if filtro_sector:
    titulo_sector = ", ".join(filtro_sector) if len(filtro_sector) <= 3 else f"{len(filtro_sector)} sectores"
else:
    titulo_sector = "Todos"
titulo_tablero = f"Tablero de Control: {titulo_sector}"
if filtro_periodo:
    titulo_periodo = ", ".join(filtro_periodo) if len(filtro_periodo) <= 2 else f"{len(filtro_periodo)} periodos"
    titulo_tablero += f" — {titulo_periodo}"
st.header(titulo_tablero)
st.caption(f"Vista: {filtro_estado} | Registros: {len(df_tablero)}")

kpi_total = len(df_tablero)
pedido_lleno = serie_pedido_lleno(df_tablero)

por_elaborar = df_tablero['fecha_elaboracion'].isnull().sum() if 'fecha_elaboracion' in df_tablero.columns else 0
por_conciliar = (
    df_tablero['fecha_elaboracion'].notnull() &
    df_tablero['fecha_conciliacion'].isnull()
).sum() if ('fecha_elaboracion' in df_tablero.columns and 'fecha_conciliacion' in df_tablero.columns) else 0
pendiente_pedido = (
    df_tablero['fecha_conciliacion'].notnull() &
    (~pedido_lleno)
).sum() if 'fecha_conciliacion' in df_tablero.columns else 0
pedido_recibido = (
    df_tablero['fecha_conciliacion'].notnull() &
    (pedido_lleno)
).sum() if 'fecha_conciliacion' in df_tablero.columns else 0

sin_clasificar = max(0, kpi_total - (por_elaborar + por_conciliar + pendiente_pedido + pedido_recibido))

# --- Monto por etapa ---
# En las primeras 3 etapas todavía no existe Importe Real (solo se sabe al recibir el pedido),
# así que se muestra el Importe Previsto (promedio histórico). En "Pedido Recibido" ya se
# conoce el Importe Real, así que se muestra ese.
etapa_tablero = etapa_excluyente(df_tablero)
tiene_previsto = 'importe_previsto' in df_tablero.columns
tiene_real = 'importe_real' in df_tablero.columns

def _monto_etapa(nombre_etapa, columna):
    if columna not in df_tablero.columns:
        return 0.0
    return df_tablero.loc[etapa_tablero == nombre_etapa, columna].sum()

monto_por_elaborar = _monto_etapa("Por Elaborar", 'importe_previsto') if tiene_previsto else 0.0
monto_por_conciliar = _monto_etapa("Por Conciliar", 'importe_previsto') if tiene_previsto else 0.0
monto_pendiente_pedido = _monto_etapa("Pendiente de Pedido", 'importe_previsto') if tiene_previsto else 0.0
monto_pedido_recibido = _monto_etapa("Pedido Recibido", 'importe_real') if tiene_real else 0.0
monto_previsto_pipeline = monto_por_elaborar + monto_por_conciliar + monto_pendiente_pedido

# "Importe Real a Facturar" = el Real de las prefacturas que YA llegaron a "Pedido Recibido"
# (misma cifra que la tarjeta de Etapa 4). Antes se sumaba el Importe Real de TODAS las filas
# sin importar la etapa, lo que podía dar un total mayor al de "Pedido Recibido" cuando una
# prefactura ya tenía Importe Real cargado pero todavía le faltaba la fecha de conciliación
# (por eso el sistema aún no la clasificaba como recibida). Se deja el mismo número en ambas
# tarjetas para que no parezcan cifras contradictorias.
total_importe_real = monto_pedido_recibido

# Aviso de datos: filas con Importe Real ya cargado pero que, por falta de fecha de
# conciliación (o de número de pedido), todavía no cuentan como "Pedido Recibido". Ese monto
# NO se ve reflejado en ninguna tarjeta hasta que se complete esa fecha en la fila.
if tiene_real:
    mask_real_sin_etapa4 = (df_tablero['importe_real'].fillna(0) > 0) & (etapa_tablero != "Pedido Recibido")
    monto_real_sin_etapa4 = df_tablero.loc[mask_real_sin_etapa4, 'importe_real'].sum()
    filas_real_sin_etapa4 = int(mask_real_sin_etapa4.sum())
else:
    monto_real_sin_etapa4 = 0.0
    filas_real_sin_etapa4 = 0

def pct(n, d):
    return (n / d) if d else 0

p1, p2, p3, p4 = (
    pct(por_elaborar, kpi_total),
    pct(por_conciliar, kpi_total),
    pct(pendiente_pedido, kpi_total),
    pct(pedido_recibido, kpi_total),
)

# Gran total del pipeline: Real (ya facturable, Etapa 4) + Previsto (estimado, Etapas 1-3).
monto_gran_total = total_importe_real + monto_previsto_pipeline

st.markdown(f"""
<div class="pipe-wrap">
  <div class="pipe-card">
    <div class="pipe-title">📦 Total Prefacturas
      <span class="badge" style="background:rgba(37,99,235,0.12); color:rgb(37,99,235);">Base</span>
    </div>
    <div class="pipe-value">{kpi_total}</div>
    <div class="pipe-sub">Registros (según filtros)</div>
    <div class="pipe-money" style="color:rgb(37,99,235);">C$ {monto_gran_total:,.2f}<span class="tag">real + previsto</span></div>
    <div class="pipe-bar"><span style="width:100%; background:rgb(37,99,235)"></span></div>
  </div>
  <div class="pipe-card pipe-highlight">
    <div class="pipe-title">💰 Importe Real a Facturar
      <span class="badge" style="background:rgba(16,185,129,0.14); color:rgb(4,120,87);">Total</span>
    </div>
    <div class="pipe-value">C$ {total_importe_real:,.2f}</div>
    <div class="pipe-sub">Suma según filtros aplicados</div>
    <div class="pipe-money" style="color:rgb(4,120,87);">+ C$ {monto_previsto_pipeline:,.2f}<span class="tag">previsto en las etapas 1-3</span></div>
    <div class="pipe-bar"><span style="width:100%; background:rgb(16,185,129)"></span></div>
  </div>
  <div class="pipe-card">
    <div class="pipe-title">🧾 Etapa 1 · Por Elaborar
      <span class="badge" style="background:rgba(245,158,11,0.14); color:rgb(161,98,7);">{p1:.0%}</span>
    </div>
    <div class="pipe-value">{por_elaborar}</div>
    <div class="pipe-sub">Sin Elaborar</div>
    <div class="pipe-money" style="color:rgb(161,98,7);">C$ {monto_por_elaborar:,.2f}<span class="tag">previsto</span></div>
    <div class="pipe-bar"><span style="width:{p1*100:.0f}%; background:rgb(245,158,11)"></span></div>
  </div>
  <div class="pipe-card">
    <div class="pipe-title">✅ Etapa 2 · Por Conciliar
      <span class="badge" style="background:rgba(59,130,246,0.14); color:rgb(29,78,216);">{p2:.0%}</span>
    </div>
    <div class="pipe-value">{por_conciliar}</div>
    <div class="pipe-sub">Elaborada y sin Conciliar</div>
    <div class="pipe-money" style="color:rgb(29,78,216);">C$ {monto_por_conciliar:,.2f}<span class="tag">previsto</span></div>
    <div class="pipe-bar"><span style="width:{p2*100:.0f}%; background:rgb(59,130,246)"></span></div>
  </div>
  <div class="pipe-card">
    <div class="pipe-title">🧩 Etapa 3 · Pendiente de Pedido
      <span class="badge" style="background:rgba(168,85,247,0.14); color:rgb(126,34,206);">{p3:.0%}</span>
    </div>
    <div class="pipe-value">{pendiente_pedido}</div>
    <div class="pipe-sub">Conciliada y sin <b>pedido</b></div>
    <div class="pipe-money" style="color:rgb(126,34,206);">C$ {monto_pendiente_pedido:,.2f}<span class="tag">previsto</span></div>
    <div class="pipe-bar"><span style="width:{p3*100:.0f}%; background:rgb(168,85,247)"></span></div>
  </div>
  <div class="pipe-card">
    <div class="pipe-title">📩 Etapa 4 · Pedido Recibido (Final)
      <span class="badge" style="background:rgba(16,185,129,0.14); color:rgb(4,120,87);">{p4:.0%}</span>
    </div>
    <div class="pipe-value">{pedido_recibido}</div>
    <div class="pipe-sub">Conciliada y con <b>pedido</b></div>
    <div class="pipe-money" style="color:rgb(4,120,87);">C$ {monto_pedido_recibido:,.2f}<span class="tag">real</span></div>
    <div class="pipe-bar"><span style="width:{p4*100:.0f}%; background:rgb(16,185,129)"></span></div>
  </div>
</div>
""", unsafe_allow_html=True)

if not tiene_previsto:
    st.caption("ℹ️ No se encontró la columna de Importe Previsto — los montos por etapa 1-3 no se pueden mostrar.")

if sin_clasificar > 0:
    st.warning(f"⚠️ Hay {sin_clasificar} registros 'Sin clasificar' (revisa fechas/pedido).")

if filas_real_sin_etapa4 > 0:
    st.info(
        f"ℹ️ {filas_real_sin_etapa4} prefactura(s) ya tienen Importe Real cargado "
        f"(C$ {monto_real_sin_etapa4:,.2f}) pero todavía no cuentan como \"Pedido Recibido\" "
        f"porque les falta la fecha de conciliación (o el número de pedido). Ese monto no "
        f"aparece en ninguna tarjeta hasta que se complete esa fecha. Completa "
        f"\"fecha_conciliacion\" en esas filas para que se sumen a Etapa 4."
    )

st.divider()

# =========================
# 9) STACKED CHART (df_tablero)
# =========================
st.subheader("📊 Distribución de la Carga (por etapa)")

modo_carga = st.radio(
    "Ver por:",
    ["Nº de prefacturas", "Monto (C$)"],
    horizontal=True,
    key="modo_carga_etapa"
)

df_g = df_tablero.copy()
df_g['Etapa'] = etapa_excluyente(df_g)

# Cuando hay UN SOLO sector seleccionado => SIEMPRE por subsector (para visualizar Managua DN/DS)
if sector_unico and 'subsector' in df_g.columns:
    col_categoria = 'subsector'
    etiqueta = 'Subsector'
else:
    col_categoria = 'sector'
    etiqueta = 'Sector'

# Categoria limpia (fallback: si subsector vacío, usa sector)
cat = df_g[col_categoria].fillna('').astype(str).str.strip() if col_categoria in df_g.columns else pd.Series([''] * len(df_g))
if col_categoria == 'subsector':
    cat_sector = df_g['sector'].fillna('Sin dato').astype(str).str.strip()
    df_g['Categoria'] = np.where(cat != '', cat, cat_sector)
else:
    df_g['Categoria'] = np.where(cat != '', cat, 'Sin dato')

orden_etapas = ["Por Elaborar", "Por Conciliar", "Pendiente de Pedido", "Pedido Recibido"]

if modo_carga == "Nº de prefacturas":
    # --- Cantidad de prefacturas por etapa ---
    resumen = (
        df_g.groupby(['Categoria', 'Etapa'], as_index=False)
            .size()
            .rename(columns={'size': 'Valor'})
    )
    titulo_x = 'Nº Prefacturas'
    fmt_valor = ',.0f'
    fmt_tooltip = ',.0f'
else:
    # --- Monto por etapa: Importe Real donde ya se recibió el pedido, Importe Previsto en las demás ---
    df_g['importe_real'] = df_g['importe_real'] if 'importe_real' in df_g.columns else 0.0
    df_g['importe_previsto'] = df_g['importe_previsto'] if 'importe_previsto' in df_g.columns else 0.0
    df_g['Valor'] = np.where(df_g['Etapa'] == 'Pedido Recibido', df_g['importe_real'], df_g['importe_previsto'])
    resumen = df_g.groupby(['Categoria', 'Etapa'], as_index=False)['Valor'].sum()
    titulo_x = 'Monto — Real en "Pedido Recibido", Previsto en las demás (C$)'
    fmt_valor = ',.2f'
    fmt_tooltip = ',.2f'

if (resumen['Etapa'] == "Sin clasificar").any():
    orden_etapas = orden_etapas + ["Sin clasificar"]

tot_cat = resumen.groupby('Categoria', as_index=False)['Valor'].sum().rename(columns={'Valor': 'TotalCategoria'})
resumen = resumen.merge(tot_cat, on='Categoria', how='left')

h = max(260, min(520, 60 + 30 * resumen['Categoria'].nunique()))

base = alt.Chart(resumen).encode(
    y=alt.Y('Categoria:N', sort=alt.SortField(field='TotalCategoria', order='descending'), title=etiqueta),
    x=alt.X('Valor:Q', stack='zero', title=titulo_x),
    color=alt.Color(
    'Etapa:N',
    sort=orden_etapas,
    title='Etapas',
    scale=alt.Scale(
        domain=["Por Elaborar", "Por Conciliar", "Pendiente de Pedido", "Pedido Recibido", "Sin clasificar"],
        range=["#60A5FA", "#1D4ED8", "#EF4444", "#86EFAC", "#9CA3AF"]  # rojo pendiente, verde claro recibido
    )
),
    tooltip=[
        alt.Tooltip('Categoria:N', title=etiqueta),
        alt.Tooltip('Etapa:N', title='Etapa'),
        alt.Tooltip('Valor:Q', title='Valor', format=fmt_tooltip),
        alt.Tooltip('TotalCategoria:Q', title='Total categoría', format=fmt_tooltip),
    ]
)

barras = base.mark_bar(size=26, cornerRadius=6, stroke='rgba(0,0,0,0.25)', strokeWidth=1)
labels = base.transform_filter(alt.datum.Valor > 0).mark_text(
    align='left', baseline='middle', dx=6, fontSize=12
).encode(text=alt.Text('Valor:Q', format=fmt_valor))

st.altair_chart((barras + labels).properties(height=h), use_container_width=True)

if modo_carga == "Monto (C$)":
    st.caption("💡 El monto de \"Pedido Recibido\" es Importe Real (ya conocido); el de las demás etapas es Importe Previsto (estimado por promedio histórico).")

st.divider()

# =========================
# 9b) CHART: IMPORTE REAL + PREVISTO POR SECTOR/SUBSECTOR
# =========================
st.subheader("💰 Importe Real y Previsto por Sector")

tiene_algun_importe = ('importe_real' in df_tablero.columns) or ('importe_previsto' in df_tablero.columns)

if tiene_algun_importe:
    df_imp = df_tablero.copy()

    # Misma lógica de categoría que el gráfico anterior (subsector si hay un solo sector elegido)
    if sector_unico and 'subsector' in df_imp.columns:
        col_cat_imp = 'subsector'
        etiqueta_imp = 'Subsector'
    else:
        col_cat_imp = 'sector'
        etiqueta_imp = 'Sector'

    cat_imp = df_imp[col_cat_imp].fillna('').astype(str).str.strip() if col_cat_imp in df_imp.columns else pd.Series([''] * len(df_imp))
    if col_cat_imp == 'subsector':
        cat_sector_imp = df_imp['sector'].fillna('Sin dato').astype(str).str.strip()
        df_imp['Categoria'] = np.where(cat_imp != '', cat_imp, cat_sector_imp)
    else:
        df_imp['Categoria'] = np.where(cat_imp != '', cat_imp, 'Sin dato')

    df_imp['Real'] = df_imp['importe_real'].fillna(0) if 'importe_real' in df_imp.columns else 0.0
    # El "Previsto" que se grafica es solo el que TODAVÍA no se volvió Real (para no contar dos veces
    # lo mismo): si la prefactura ya tiene Importe Real, su previsto ya no aporta a la barra.
    if 'importe_previsto' in df_imp.columns:
        df_imp['Previsto_pendiente'] = np.where(df_imp['Real'] > 0, 0.0, df_imp['importe_previsto'].fillna(0))
    else:
        df_imp['Previsto_pendiente'] = 0.0

    resumen_imp = df_imp.groupby('Categoria', as_index=False)[['Real', 'Previsto_pendiente']].sum()
    resumen_imp['Total'] = resumen_imp['Real'] + resumen_imp['Previsto_pendiente']

    if resumen_imp.empty or resumen_imp['Total'].sum() == 0:
        st.info("No hay montos de importe real ni previsto para los filtros seleccionados.")
    else:
        REAL_LBL = 'Real (ya conocido)'
        PREV_LBL = 'Previsto (aún no es real)'
        long_imp = resumen_imp.melt(
            id_vars=['Categoria', 'Total'],
            value_vars=['Real', 'Previsto_pendiente'],
            var_name='Tipo', value_name='Monto'
        )
        long_imp['Tipo'] = long_imp['Tipo'].map({'Real': REAL_LBL, 'Previsto_pendiente': PREV_LBL})
        # Orden fijo del apilado: Real primero (desde x=0), Previsto después.
        long_imp['OrdenTipo'] = long_imp['Tipo'].map({REAL_LBL: 0, PREV_LBL: 1})
        # % que representa cada segmento sobre el total de su barra, para no poner etiqueta
        # encima de un segmento demasiado angosto (se ve igual en el tooltip al pasar el mouse).
        long_imp['MontoPct'] = np.where(long_imp['Total'] > 0, long_imp['Monto'] / long_imp['Total'], 0)
        # Punto medio real de cada tramo dentro de la barra apilada (Real: 0→Real,
        # Previsto: Real→Real+Previsto). Vega-Lite apila las BARRAS solo, pero un mark_text
        # que reutilice el mismo encoding de x se dibuja en el INICIO del tramo, no en su
        # centro — por eso el texto quedaba pegado a la frontera entre el verde y el celeste,
        # ilegible. Calculamos el centro a mano y lo usamos con stack=None en las etiquetas.
        long_imp = long_imp.sort_values(['Categoria', 'OrdenTipo'])
        long_imp['FinTramo'] = long_imp.groupby('Categoria')['Monto'].cumsum()
        long_imp['InicioTramo'] = long_imp['FinTramo'] - long_imp['Monto']
        long_imp['MedioTramo'] = long_imp['InicioTramo'] + long_imp['Monto'] / 2.0

        h_imp = max(220, min(480, 60 + 30 * resumen_imp['Categoria'].nunique()))

        base_imp = alt.Chart(long_imp).encode(
            y=alt.Y('Categoria:N', sort=alt.SortField(field='Total', order='descending'), title=etiqueta_imp),
            x=alt.X('Monto:Q', stack='zero', title='Importe Real + Previsto (C$)'),
            order=alt.Order('OrdenTipo:Q'),
            color=alt.Color(
                'Tipo:N', title='',
                scale=alt.Scale(domain=[REAL_LBL, PREV_LBL], range=['#10B981', '#BFDBFE'])
            ),
            tooltip=[
                alt.Tooltip('Categoria:N', title=etiqueta_imp),
                alt.Tooltip('Tipo:N', title=''),
                alt.Tooltip('Monto:Q', title='Monto', format=',.2f'),
                alt.Tooltip('Total:Q', title='Total (Real + Previsto)', format=',.2f'),
            ]
        )
        barras_imp = base_imp.mark_bar(cornerRadius=6, stroke='rgba(0,0,0,0.25)', strokeWidth=1)

        # Etiqueta del TOTAL de la barra (Real + Previsto), al final de la barra.
        label_imp = alt.Chart(resumen_imp).mark_text(
            align='left', baseline='middle', dx=6, fontSize=12, fontWeight='bold'
        ).encode(
            y=alt.Y('Categoria:N', sort=alt.SortField(field='Total', order='descending')),
            x=alt.X('Total:Q'),
            text=alt.Text('Total:Q', format=',.2f')
        )

        # Etiquetas POR SEGMENTO (Real y Previsto por separado), centradas dentro de cada
        # tramo de la barra apilada usando el punto medio calculado arriba (MedioTramo,
        # con stack=None: es un valor absoluto, no se vuelve a apilar). Se ocultan si el
        # segmento es demasiado angosto (<8% de la barra) para que el texto no se salga del
        # tramo ni se amontone; el valor completo sigue visible al pasar el mouse (tooltip).
        UMBRAL_PCT_ETIQUETA = 0.08
        base_label_imp = alt.Chart(long_imp).encode(
            y=alt.Y('Categoria:N', sort=alt.SortField(field='Total', order='descending')),
            x=alt.X('MedioTramo:Q', stack=None),
        )
        # Real: texto blanco sobre el verde (#10B981) para máximo contraste.
        label_real_imp = base_label_imp.mark_text(
            align='center', baseline='middle', fontSize=11, fontWeight='bold', color='#FFFFFF'
        ).encode(
            text=alt.Text('Monto:Q', format=',.2f')
        ).transform_filter(
            (alt.datum.Tipo == REAL_LBL) & (alt.datum.MontoPct >= UMBRAL_PCT_ETIQUETA)
        )
        # Previsto: texto azul oscuro sobre el celeste (#BFDBFE) para máximo contraste.
        label_prev_imp = base_label_imp.mark_text(
            align='center', baseline='middle', fontSize=11, fontWeight='bold', color='#1E3A8A'
        ).encode(
            text=alt.Text('Monto:Q', format=',.2f')
        ).transform_filter(
            (alt.datum.Tipo == PREV_LBL) & (alt.datum.MontoPct >= UMBRAL_PCT_ETIQUETA)
        )

        st.altair_chart(
            (barras_imp + label_real_imp + label_prev_imp + label_imp).properties(height=h_imp),
            use_container_width=True
        )
        st.caption("🟩 Real = Importe Real ya cargado · 🟦 Previsto = Importe Previsto de las prefacturas que aún no tienen Real (para no sumar dos veces lo mismo) · Los números dentro de cada tramo son el Real y el Previsto por separado; el número en negrita al final es la suma de ambos.")
else:
    st.info("No se encontraron las columnas de importe (Real/Previsto) para graficar.")

# =========================
# 9c) RECALCULAR IMPORTE PREVISTO / IMPORTE PENDIENTE
# =========================
with st.expander("🔄 Recalcular Importe Previsto e Importe Pendiente", expanded=False):
    st.caption(
        "El Importe Previsto y el Importe Pendiente NO se recalculan solos: quedan fijos desde "
        "la última vez que se calcularon. Usa este botón cuando agregues prefacturas nuevas o "
        "cargues importes reales, para que el pronóstico se actualice con toda la información "
        "más reciente de la base de datos (no solo con lo que ves filtrado en pantalla).\n\n"
        "Reglas: si una prefactura YA tiene Importe Real, su Previsto pasa a ser igual al Real y "
        "su Pendiente queda en 0. Si todavía NO tiene Real, su Previsto se calcula como el "
        "promedio histórico de otras prefacturas del mismo Sector + Área + Sub-área (sin contar "
        "la propia fila), y su Pendiente queda igual a ese Previsto."
    )
    if st.button("🔄 Recalcular Previsto y Pendiente", key="btn_recalcular_previsto"):
        with st.spinner("Recalculando Previsto y Pendiente para todas las prefacturas…"):
            try:
                resumen_recalc = recalcular_previsto_pendiente()
                st.success(
                    f"✅ Se recalcularon {resumen_recalc['total']} prefacturas: "
                    f"{resumen_recalc['con_real']} ya con Importe Real (Previsto = Real), "
                    f"{resumen_recalc['alta']} con confianza Alta, "
                    f"{resumen_recalc['media']} Media, {resumen_recalc['baja']} Baja, "
                    f"{resumen_recalc['estimado']} Estimadas (nivel Sector+Área) y "
                    f"{resumen_recalc['sin_datos']} sin datos suficientes."
                )
                st.rerun()
            except Exception as e:
                st.error(f"Error al recalcular: {e}")

# =========================
# 10) TABLE (df_filtrado)
# =========================
st.subheader("📝 Gestión de Datos")

configuracion_columnas = {
    "created_at": None,
    "id": None,
    "sector": st.column_config.SelectboxColumn(
        "Sector",
        options=[""] + SECTORES,
        help="Selecciona el sector"
    ),
    "subsector": st.column_config.SelectboxColumn(
        "Subsector",
        options=[""] + SUBSECTORES,
        help="Selecciona el subsector"
    ),
    "periodo": st.column_config.SelectboxColumn(
        "Periodo",
        options=[""] + PERIODOS,
        help="Selecciona el periodo (mes + quincena)"
    ),
    "sub_area": st.column_config.TextColumn("Sub Área"),
    "fecha_elaboracion": st.column_config.DateColumn("Fecha Elaboración", format="DD/MM/YYYY"),
    "fecha_formato": st.column_config.DateColumn("Fecha Formato", format="DD/MM/YYYY"),
    "fecha_solicitud_modificacion": st.column_config.DateColumn("Fecha Sol. Modif.", format="DD/MM/YYYY"),
    "fecha_entrega_post_modificacion": st.column_config.DateColumn("Fecha Entrega Post Modif.", format="DD/MM/YYYY"),
    "fecha_conciliacion": st.column_config.DateColumn("Fecha Conciliación", format="DD/MM/YYYY"),
    "fecha_firma_ingenica": st.column_config.DateColumn("Firma Ingenica", format="DD/MM/YYYY"),
    "fecha_entrega_final_ingenica_central": st.column_config.DateColumn("Entrega Final Central", format="DD/MM/YYYY"),
    "fecha_firma_dnds": st.column_config.DateColumn("Firma DNDS", format="DD/MM/YYYY", help="(Opcional)"),
    "fecha_edicion_pedido": st.column_config.DateColumn("Fecha Edición Pedido", format="DD/MM/YYYY"),
    "area": st.column_config.SelectboxColumn(
        "Área",
        options=[""] + AREAS
    ),
    # Columnas calculadas automáticamente (promedio histórico por Sector+Área+Sub-área):
    # se muestran de solo lectura para que no se sobrescriban a mano por error.
    "importe_previsto": st.column_config.NumberColumn(
        "Importe Previsto", format="%.2f", disabled=True,
        help="Calculado: promedio histórico del Importe Real en el mismo Sector+Área+Sub-área."
    ),
    "importe_pendiente": st.column_config.NumberColumn(
        "Importe Pendiente", format="%.2f", disabled=True,
        help="Previsto − Real. Se recalcula junto con el Previsto."
    ),
    "Previsto Confianza": st.column_config.TextColumn("Confianza Previsto", disabled=True),
    "Previsto N Datos": st.column_config.NumberColumn("N° datos usados", disabled=True),
}

# --- Dataframe para el editor (sin índice visible) ---
df_editor = df_filtrado.copy().reset_index(drop=True)

# Asegurar columnas existen y normalizar para que calcen con los combobox
for col in ["sector", "subsector", "periodo", "area"]:
    if col not in df_editor.columns:
        df_editor[col] = ""
    df_editor[col] = (
        df_editor[col]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.upper()
    )

df_editado = st.data_editor(
    df_editor,
    column_config=configuracion_columnas,
    hide_index=True,              # ✅ quita el índice (esa era tu "primera columna")
    use_container_width=True,
    num_rows="dynamic",
    key="editor_principal_v2"     # ✅ cambia el key para forzar refresh y que aparezcan combos
)

# =========================
# 11) SAVE CHANGES (CORREGIDO)
# =========================
if st.button("Guardar Cambios en Supabase"):
    try:
        datos_a_enviar = df_editado.copy()

        # --- 1) Limpiar fechas ---
        columnas_fechas_guardar = [
            "fecha_elaboracion", "fecha_formato", "fecha_solicitud_modificacion",
            "fecha_entrega_post_modificacion", "fecha_conciliacion",
            "fecha_firma_ingenica", "fecha_entrega_final_ingenica_central",
            "fecha_firma_dnds", "fecha_edicion_pedido"
        ]
        for col in columnas_fechas_guardar:
            if col in datos_a_enviar.columns:
                datos_a_enviar[col] = pd.to_datetime(datos_a_enviar[col], dayfirst=True, errors='coerce').dt.strftime('%Y-%m-%d')

        # --- 2) CORRECCIÓN PRINCIPAL: Limpiar TODOS los NaN/NaT/inf del DataFrame ---
        # Reemplazar NaN, NaT, inf, -inf por None en TODO el dataframe
        datos_a_enviar = datos_a_enviar.replace({
            np.nan: None,
            pd.NaT: None,
            float('inf'): None,
            float('-inf'): None
        })

        # También asegurar que cualquier string 'nan', 'NaT', 'None' quede como None
        datos_a_enviar = datos_a_enviar.replace(['nan', 'NaT', 'None', '<NA>', ''], None)

        # --- 2b) Revertir el nombre de las columnas de importe a su nombre REAL en Supabase ---
        # (internamente usamos importe_real/importe_previsto/importe_pendiente aunque en la
        # tabla tengan otro nombre/mayúsculas, p.ej. "Importe Real", "Importe Previsto")
        for _interno, _original in [
            ('importe_real', IMPORTE_REAL_COL_ORIGINAL),
            ('importe_previsto', IMPORTE_PREVISTO_COL_ORIGINAL),
            ('importe_pendiente', IMPORTE_PENDIENTE_COL_ORIGINAL),
        ]:
            if _original and _original != _interno and _interno in datos_a_enviar.columns:
                datos_a_enviar = datos_a_enviar.rename(columns={_interno: _original})

        # --- 3) Convertir a diccionario (ahora sin valores nan) ---
        registros = datos_a_enviar.to_dict('records')

        # Columnas que en Supabase son de tipo INTEGER de verdad. Si se envían como
        # float (p.ej. 10.0 en vez de 10), Postgres las rechaza con
        # "invalid input syntax for type integer: '10.0'" porque el valor viaja como
        # texto con decimal. pandas convierte estas columnas a float automáticamente
        # en cuanto tienen algún valor vacío/None mezclado, así que hay que forzarlas
        # de vuelta a int (o None) justo antes de enviarlas.
        COLUMNAS_ENTERAS_SUPABASE = {"Previsto N Datos"}

        registros_actualizar = []
        registros_crear = []

        for reg in registros:
            nuevo_reg = {}

            # Limpiar campo por campo para asegurar que no quede ningún nan
            for key, value in reg.items():
                # Si es nan (float), convertir a None
                if isinstance(value, float) and np.isnan(value):
                    nuevo_reg[key] = None
                # numpy usa sus propios tipos (numpy.float64, numpy.int64, etc.) que no
                # son "int"/"float" nativos de Python y algunos clientes los serializan
                # mal (terminan como texto, p.ej. "10.0"); los pasamos a tipo nativo.
                elif isinstance(value, np.generic):
                    nuevo_reg[key] = value.item()
                # Si es lista o dict, verificar recursivamente (por si acaso)
                else:
                    nuevo_reg[key] = value

            # Forzar a entero real las columnas que en Supabase son INTEGER, para que
            # nunca viaje un "10.0" donde la base espera "10".
            for _col_entera in COLUMNAS_ENTERAS_SUPABASE:
                if _col_entera in nuevo_reg and nuevo_reg[_col_entera] is not None:
                    try:
                        nuevo_reg[_col_entera] = int(round(float(nuevo_reg[_col_entera])))
                    except (TypeError, ValueError):
                        nuevo_reg[_col_entera] = None

            # Manejar el ID para distinguir insert vs update
            id_val = nuevo_reg.get('id')

            # Limpiar created_at si está vacío
            if 'created_at' in nuevo_reg and (nuevo_reg['created_at'] is None or nuevo_reg['created_at'] == ''):
                del nuevo_reg['created_at']

            # Clasificar
            if id_val is None or id_val == '' or (isinstance(id_val, float) and np.isnan(id_val)):
                if 'id' in nuevo_reg:
                    del nuevo_reg['id']
                registros_crear.append(nuevo_reg)
            else:
                # Asegurar que el ID sea entero (no float)
                if isinstance(id_val, float):
                    nuevo_reg['id'] = int(id_val)
                registros_actualizar.append(nuevo_reg)

        # --- 4) Ejecutar operaciones en Supabase ---
        if len(registros_actualizar) > 0:
            supabase.table('prefacturas_pedidos').upsert(registros_actualizar).execute()

        if len(registros_crear) > 0:
            supabase.table('prefacturas_pedidos').insert(registros_crear).execute()

        st.success("¡Cambios guardados correctamente!")
        st.balloons()
        import time
        time.sleep(2)  # Espera 2 segundos para que se vean los globos
        st.rerun()

    except Exception as e:
        st.error(f"Error al guardar: {e}")
        import traceback
        st.code(traceback.format_exc())  # Muestra el detalle completo del error para debug

# =========================
# 12) EXPORT CSV
# =========================
st.divider()
csv = df_editado.to_csv(index=False).encode('utf-8')
st.download_button(
    label="📥 Descargar Tabla (CSV)",
    data=csv,
    file_name='control_entregas_ingenica.csv',
    mime='text/csv',
)
