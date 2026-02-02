import streamlit as st
import pandas as pd
from supabase import create_client
from datetime import datetime
import altair as alt
import numpy as np

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
st.caption(f"Última actualización: {datetime.now().strftime('%d/%m/%Y %H:%M')}")

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
.pipe-bar{height:8px; background:rgba(15,23,42,0.08); border-radius:999px; overflow:hidden; margin-top:10px;}
.pipe-bar span{display:block; height:100%; border-radius:999px;}
.badge{display:inline-block; padding:2px 10px; border-radius:999px; font-size:.75rem; font-weight:900;}
.small-muted{color:#6b7280; font-size:.82rem; margin-top:4px;}
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
# 6) SIDEBAR FILTERS
# =========================
st.sidebar.header("🎯 Filtros de Gestión")

lista_sectores = ["Todos"] + sorted(df['sector'].dropna().unique().tolist())
filtro_sector = st.sidebar.selectbox("Seleccionar Sector:", lista_sectores)

filtro_estado = st.sidebar.radio(
    "Mostrar solo:",
    ["Ver Todo", "Pendientes de Elaborar", "Pendientes de Conciliar", "Pendientes de Pedido", "Pedidos Recibidos"]
)

# =========================
# 7) DATASETS (IMPORTANT!)
# =========================
# df_sector: SOLO filtro de sector
df_sector = df.copy()
if filtro_sector != "Todos":
    df_sector = df_sector[df_sector["sector"] == filtro_sector]

# df_vista: sector + estado (lo que seleccionó el usuario)
df_vista = aplicar_filtro_estado(df_sector, filtro_estado)

# df_tablero: lo que usan KPIs + gráfico (aquí SÍ cambian con el radio)
df_tablero = df_vista

# df_filtrado: lo que usa la tabla (igual df_vista)
df_filtrado = df_vista

# =========================
# 8) KPIs / PIPELINE (df_tablero)
# =========================
st.header(f"Tablero de Control: {filtro_sector}")
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

  <div class="pipe-card">
    <div class="pipe-title">🧾 Etapa 1 · Por Elaborar
      <span class="badge" style="background:rgba(245,158,11,0.14); color:rgb(161,98,7);">{p1:.0%}</span>
    </div>
    <div class="pipe-value">{por_elaborar}</div>
    <div class="pipe-sub">Sin Elaborar</div>
    <div class="pipe-bar"><span style="width:{p1*100:.0f}%; background:rgb(245,158,11)"></span></div>
  </div>

  <div class="pipe-card">
    <div class="pipe-title">✅ Etapa 2 · Por Conciliar
      <span class="badge" style="background:rgba(59,130,246,0.14); color:rgb(29,78,216);">{p2:.0%}</span>
    </div>
    <div class="pipe-value">{por_conciliar}</div>
    <div class="pipe-sub">Elaborada y sin Conciliar</div>
    <div class="pipe-bar"><span style="width:{p2*100:.0f}%; background:rgb(59,130,246)"></span></div>
  </div>

  <div class="pipe-card">
    <div class="pipe-title">🧩 Etapa 3 · Pendiente de Pedido
      <span class="badge" style="background:rgba(168,85,247,0.14); color:rgb(126,34,206);">{p3:.0%}</span>
    </div>
    <div class="pipe-value">{pendiente_pedido}</div>
    <div class="pipe-sub">Conciliada y sin <b>pedido</b></div>
    <div class="pipe-bar"><span style="width:{p3*100:.0f}%; background:rgb(168,85,247)"></span></div>
  </div>

  <div class="pipe-card">
    <div class="pipe-title">📩 Etapa 4 · Pedido Recibido (Final)
      <span class="badge" style="background:rgba(16,185,129,0.14); color:rgb(4,120,87);">{p4:.0%}</span>
    </div>
    <div class="pipe-value">{pedido_recibido}</div>
    <div class="pipe-sub">Conciliada y con <b>pedido</b></div>
    <div class="pipe-bar"><span style="width:{p4*100:.0f}%; background:rgb(16,185,129)"></span></div>
  </div>

</div>
""", unsafe_allow_html=True)

if sin_clasificar > 0:
    st.warning(f"⚠️ Hay {sin_clasificar} registros 'Sin clasificar' (revisa fechas/pedido).")

st.divider()

# =========================
# 9) STACKED CHART (df_tablero)
# =========================
st.subheader("📊 Distribución de la Carga (por etapa)")

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

resumen = (
    df_g.groupby(['Categoria', 'Etapa'], as_index=False)
        .size()
        .rename(columns={'size': 'Cantidad'})
)

tot_cat = resumen.groupby('Categoria', as_index=False)['Cantidad'].sum().rename(columns={'Cantidad': 'TotalCategoria'})
resumen = resumen.merge(tot_cat, on='Categoria', how='left')

orden_etapas = ["1. Por Elaborar", "2. Por Conciliar", "3. Pendiente de Pedido", "4. Pedido Recibido"]

if (resumen['Etapa'] == "Sin clasificar").any():
    orden_etapas = orden_etapas + ["Sin clasificar"]

h = max(260, min(520, 60 + 30 * resumen['Categoria'].nunique()))

base = alt.Chart(resumen).encode(
    y=alt.Y('Categoria:N', sort=alt.SortField(field='TotalCategoria', order='descending'), title=etiqueta),
    x=alt.X('Cantidad:Q', stack='zero', title='Nº Prefacturas'),
    color=alt.Color('Etapa:N', sort=orden_etapas, title='Etapas'),
    tooltip=[
        alt.Tooltip('Categoria:N', title=etiqueta),
        alt.Tooltip('Etapa:N', title='Etapa'),
        alt.Tooltip('Cantidad:Q', title='Cantidad'),
        alt.Tooltip('TotalCategoria:Q', title='Total categoría'),
    ]
)

barras = base.mark_bar(size=26, cornerRadius=6, stroke='rgba(0,0,0,0.25)', strokeWidth=1)
labels = base.transform_filter(alt.datum.Cantidad > 0).mark_text(
    align='left', baseline='middle', dx=6, fontSize=12
).encode(text='Cantidad:Q')

st.altair_chart((barras + labels).properties(height=h), use_container_width=True)

# =========================
# 10) TABLE (df_filtrado)
# =========================
st.subheader("📝 Gestión de Datos")

configuracion_columnas = {
    "created_at": None,
    "id": None,

    "sector": st.column_config.TextColumn("Sector", disabled=True),
    "subsector": st.column_config.TextColumn("Subsector"),
    "periodo": st.column_config.TextColumn("Periodo"),
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
        options=["MANTENIMIENTO", "DESARROLLO", "PROYECTOS", "PNESER", "CAMPAÑA", "PSSEN"]
    )
}

df_editado = st.data_editor(
    df_filtrado,
    column_config=configuracion_columnas,
    use_container_width=True,
    num_rows="dynamic",
    key="editor_principal"
)

# =========================
# 11) SAVE CHANGES
# =========================
if st.button("Guardar Cambios en Supabase"):
    try:
        datos_a_enviar = df_editado.copy()

        columnas_fechas_guardar = [
            "fecha_elaboracion", "fecha_formato", "fecha_solicitud_modificacion",
            "fecha_entrega_post_modificacion", "fecha_conciliacion",
            "fecha_firma_ingenica", "fecha_entrega_final_ingenica_central",
            "fecha_firma_dnds", "fecha_edicion_pedido"
        ]

        for col in columnas_fechas_guardar:
            if col in datos_a_enviar.columns:
                datos_a_enviar[col] = pd.to_datetime(datos_a_enviar[col], dayfirst=True, errors='coerce').dt.strftime('%Y-%m-%d')
                datos_a_enviar[col] = datos_a_enviar[col].replace(['nan', 'NaT', 'None', '<NA>'], None)
                datos_a_enviar[col] = datos_a_enviar[col].where(pd.notnull(datos_a_enviar[col]), None)

        registros = datos_a_enviar.to_dict('records')

        registros_actualizar = []
        registros_crear = []

        for reg in registros:
            nuevo_reg = reg.copy()
            id_val = nuevo_reg.get('id')

            # limpiar created_at vacío
            if pd.isna(nuevo_reg.get('created_at')):
                if 'created_at' in nuevo_reg:
                    del nuevo_reg['created_at']

            # clasificar nuevo vs existente
            if id_val is None or pd.isna(id_val) or str(id_val).strip() == "":
                if 'id' in nuevo_reg:
                    del nuevo_reg['id']
                registros_crear.append(nuevo_reg)
            else:
                registros_actualizar.append(nuevo_reg)

        if len(registros_actualizar) > 0:
            supabase.table('prefacturas_pedidos').upsert(registros_actualizar).execute()

        if len(registros_crear) > 0:
            supabase.table('prefacturas_pedidos').insert(registros_crear).execute()

        st.success("¡Cambios guardados correctamente!")
        st.balloons()
        # st.rerun()

    except Exception as e:
        st.error(f"Error al guardar: {e}")

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






























































