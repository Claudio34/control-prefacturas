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
# 6) SIDEBAR FILTERS
# =========================
st.sidebar.header("🎯 Filtros de Gestión")

lista_sectores = ["Todos"] + sorted(df['sector'].dropna().unique().tolist())
filtro_sector = st.sidebar.selectbox("Seleccionar Sector:", lista_sectores)

# Periodos presentes en los datos, ordenados cronológicamente (no alfabético)
periodos_en_datos = df['periodo'].dropna().unique().tolist() if 'periodo' in df.columns else []
lista_periodos = ["Todos"] + [p for p in PERIODOS if p in periodos_en_datos]
filtro_periodo = st.sidebar.selectbox("Seleccionar Periodo:", lista_periodos)

lista_areas = ["Todos"] + sorted(df['area'].dropna().unique().tolist()) if 'area' in df.columns else ["Todos"]
filtro_area = st.sidebar.selectbox("Seleccionar Área:", lista_areas)

lista_subareas = ["Todos"] + sorted([s for s in df['sub_area'].dropna().unique().tolist() if s != ""]) if 'sub_area' in df.columns else ["Todos"]
filtro_subarea = st.sidebar.selectbox("Seleccionar Sub Área:", lista_subareas)

filtro_estado = st.sidebar.radio(
    "Mostrar solo:",
    ["Ver Todo", "1. Pendientes de Elaborar", "2. Pendientes de Conciliar", "3. Pendientes de Pedido", "4. Pedidos Recibidos"]
)

# =========================
# 7) DATASETS (IMPORTANT!)
# =========================
# df_sector: filtro de sector + periodo + área + subárea
df_sector = df.copy()
if filtro_sector != "Todos":
    df_sector = df_sector[df_sector["sector"] == filtro_sector]
if filtro_periodo != "Todos" and 'periodo' in df_sector.columns:
    df_sector = df_sector[df_sector["periodo"] == filtro_periodo]
if filtro_area != "Todos" and 'area' in df_sector.columns:
    df_sector = df_sector[df_sector["area"] == filtro_area]
if filtro_subarea != "Todos" and 'sub_area' in df_sector.columns:
    df_sector = df_sector[df_sector["sub_area"] == filtro_subarea]

# df_vista: sector + periodo + área + subárea + estado (lo que seleccionó el usuario)
df_vista = aplicar_filtro_estado(df_sector, filtro_estado)

# df_tablero: lo que usan KPIs + gráfico (aquí SÍ cambian con el radio)
df_tablero = df_vista

# df_filtrado: lo que usa la tabla (igual df_vista)
df_filtrado = df_vista

# =========================
# 8) KPIs / PIPELINE (df_tablero)
# =========================
titulo_tablero = f"Tablero de Control: {filtro_sector}"
if filtro_periodo != "Todos":
    titulo_tablero += f" — {filtro_periodo}"
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

total_importe_real = df_tablero['importe_real'].sum() if 'importe_real' in df_tablero.columns else 0

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

def pct(n, d):
    return (n / d) if d else 0

p1, p2, p3, p4 = (
    pct(por_elaborar, kpi_total),
    pct(por_conciliar, kpi_total),
    pct(pendiente_pedido, kpi_total),
    pct(pedido_recibido, kpi_total),
)

st.markdown(f"""
<div class="pipe-wrap">
  <div class="pipe-card">
    <div class="pipe-title">📦 Total Prefacturas
      <span class="badge" style="background:rgba(37,99,235,0.12); color:rgb(37,99,235);">Base</span>
    </div>
    <div class="pipe-value">{kpi_total}</div>
    <div class="pipe-sub">Registros (según filtros)</div>
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

# Cuando hay sector seleccionado => SIEMPRE por subsector (para visualizar Managua DN/DS)
if filtro_sector != "Todos" and 'subsector' in df_g.columns:
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

    # Misma lógica de categoría que el gráfico anterior (subsector si hay sector elegido)
    if filtro_sector != "Todos" and 'subsector' in df_imp.columns:
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
        # tramo de la barra apilada. Se ocultan si el segmento es demasiado angosto (<8% de
        # la barra) para que el texto no se salga ni se amontone; el valor completo sigue
        # visible al pasar el mouse (tooltip).
        UMBRAL_PCT_ETIQUETA = 0.08
        label_real_imp = base_imp.mark_text(
            align='center', baseline='middle', fontSize=11, fontWeight='bold', color='#065F46'
        ).encode(
            text=alt.Text('Monto:Q', format=',.2f')
        ).transform_filter(
            (alt.datum.Tipo == REAL_LBL) & (alt.datum.MontoPct >= UMBRAL_PCT_ETIQUETA)
        )
        label_prev_imp = base_imp.mark_text(
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

        registros_actualizar = []
        registros_crear = []

        for reg in registros:
            nuevo_reg = {}

            # Limpiar campo por campo para asegurar que no quede ningún nan
            for key, value in reg.items():
                # Si es nan (float), convertir a None
                if isinstance(value, float) and np.isnan(value):
                    nuevo_reg[key] = None
                # Si es lista o dict, verificar recursivamente (por si acaso)
                else:
                    nuevo_reg[key] = value

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
