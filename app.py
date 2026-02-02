import streamlit as st
import pandas as pd
from supabase import create_client
from datetime import datetime
import altair as alt
import numpy as np

# 1. Configuración de la página (Debe ser lo primero)
st.set_page_config(page_title="PREFACTURAS", layout="wide")

# 2. Conexión a Supabase (Usa st.secrets en producción)
URL = st.secrets["SUPABASE_URL"]
KEY = st.secrets["SUPABASE_KEY"]

@st.cache_resource
def init_connection():
    return create_client(URL, KEY)

supabase = init_connection()

# 3. Título
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

# Función para cargar datos
def cargar_datos():
    response = supabase.table('prefacturas_pedidos').select("*").order('id').execute()
    df_local = pd.DataFrame(response.data)
    return df_local

df = cargar_datos()

# VERIFICACIÓN DE SEGURIDAD
if df.empty:
    st.warning("⚠️ No se han cargado datos. Revisa tu conexión a Supabase.")
    st.stop()

# --- Normalización de nombres de columnas (por si vienen con mayúsculas) ---
# Esto evita inconsistencias y te simplifica todo el código.
rename_map = {}
if 'Sector' in df.columns and 'sector' not in df.columns:
    rename_map['Sector'] = 'sector'
if 'Subsector' in df.columns and 'subsector' not in df.columns:
    rename_map['Subsector'] = 'subsector'
if rename_map:
    df = df.rename(columns=rename_map)

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

# --- Sidebar de filtros ---
st.sidebar.header("🎯 Filtros de Gestión")

# Validar columna sector ya normalizada
if 'sector' not in df.columns:
    st.error("❌ No encuentro la columna 'sector' en los datos. Columnas detectadas: " + str(df.columns.tolist()))
    st.stop()

lista_sectores = ["Todos"] + sorted(df['sector'].dropna().unique().tolist())
filtro_sector = st.sidebar.selectbox("Seleccionar Sector:", lista_sectores)

#filtro_estado = st.sidebar.radio(
#    "Mostrar solo:",
#    ["Ver Todo", "Pendientes de Elaborar", "Pendientes de Conciliar", "Pendientes de Pedido", "Pedidos Recibidos"]
#)

# --- Helpers de ciclo (pedido lleno / vacío robusto) ---
def serie_pedido_lleno(df_in: pd.DataFrame) -> pd.Series:
    if 'pedido' not in df_in.columns:
        return pd.Series([False] * len(df_in), index=df_in.index)
    return df_in['pedido'].fillna('').astype(str).str.strip().ne('')

def etapa_excluyente(df_in: pd.DataFrame) -> pd.Series:
    """Devuelve una etapa por fila (excluyente) según tu ciclo."""
    pedido_lleno = serie_pedido_lleno(df_in)

    conds = [
        df_in['fecha_elaboracion'].isnull(),
        df_in['fecha_elaboracion'].notnull() & df_in['fecha_conciliacion'].isnull(),
        df_in['fecha_conciliacion'].notnull() & (~pedido_lleno),
        df_in['fecha_conciliacion'].notnull() & (pedido_lleno),
    ]
    etapas = [
        "1. Por Elaborar",
        "2. Por Conciliar",
        "3. Pendiente de Pedido",
        "4. Pedido Recibido",
    ]
    return pd.Series(np.select(conds, etapas, default="Sin clasificar"), index=df_in.index)

# --- 1) df_base: solo filtro de sector (KPIs + gráficos) ---
df_base = df.copy()
if filtro_sector != "Todos":
    df_base = df_base[df_base['sector'] == filtro_sector]

# --- 2) df_filtrado: df_base + filtro de estado (tabla) ---
df_filtrado = df_base.copy()

pedido_lleno_base = serie_pedido_lleno(df_filtrado)

if filtro_estado == "Pendientes de Elaborar":
    df_filtrado = df_filtrado[df_filtrado['fecha_elaboracion'].isnull()]

elif filtro_estado == "Pendientes de Conciliar":
    df_filtrado = df_filtrado[
        df_filtrado['fecha_elaboracion'].notnull() &
        df_filtrado['fecha_conciliacion'].isnull()
    ]

elif filtro_estado == "Pendientes de Pedido":
    df_filtrado = df_filtrado[
        df_filtrado['fecha_conciliacion'].notnull() &
        (~pedido_lleno_base)
    ]

elif filtro_estado == "Pedidos Recibidos":
    df_filtrado = df_filtrado[
        df_filtrado['fecha_conciliacion'].notnull() &
        (pedido_lleno_base)
    ]

# --- KPIs / Pipeline (calculados sobre df_base para que siempre tengan sentido) ---
st.header(f"Tablero de Control: {filtro_sector}")

kpi_total = len(df_base)

pedido_lleno = serie_pedido_lleno(df_base)

por_elaborar = df_base['fecha_elaboracion'].isnull().sum()
por_conciliar = (
    df_base['fecha_elaboracion'].notnull() &
    df_base['fecha_conciliacion'].isnull()
).sum()
pendiente_pedido = (
    df_base['fecha_conciliacion'].notnull() &
    (~pedido_lleno)
).sum()
pedido_recibido = (
    df_base['fecha_conciliacion'].notnull() &
    (pedido_lleno)
).sum()

sin_clasificar = max(0, kpi_total - (por_elaborar + por_conciliar + pendiente_pedido + pedido_recibido))

def pct(n, d): 
    return (n / d) if d else 0

p1, p2, p3, p4 = pct(por_elaborar, kpi_total), pct(por_conciliar, kpi_total), pct(pendiente_pedido, kpi_total), pct(pedido_recibido, kpi_total)

st.markdown(f"""
<div class="pipe-wrap">

  <div class="pipe-card">
    <div class="pipe-title">📦 Total Prefacturas
      <span class="badge" style="background:rgba(37,99,235,0.12); color:rgb(37,99,235);">Base</span>
    </div>
    <div class="pipe-value">{kpi_total}</div>
    <div class="pipe-sub">Registros (solo filtro de sector)</div>
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
    <div class="pipe-title">🧩 Etapa 3 · Conciliada y sin Pedido
      <span class="badge" style="background:rgba(168,85,247,0.14); color:rgb(126,34,206);">{p3:.0%}</span>
    </div>
    <div class="pipe-value">{pendiente_pedido}</div>
    <div class="pipe-sub">Conciliada y sin <b>pedido</b> </div>
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

# --- Gráfico apilado por etapa (usa df_base para no distorsionar por filtro de estado) ---
st.subheader("📊 Distribución de la Carga (por etapa)")
import altair as alt
import numpy as np

# IMPORTANTE: usar df_base (solo filtro de sector), NO df_filtrado
df_g = df_base.copy()

# 1) Si hay sector seleccionado => SIEMPRE por subsector
col_categoria = 'subsector' if (filtro_sector != "Todos" and 'subsector' in df_g.columns) else 'sector'
etiqueta = 'Subsector' if col_categoria == 'subsector' else 'Sector'

# 2) Pedido lleno/vacío robusto
if 'pedido' in df_g.columns:
    pedido_lleno = df_g['pedido'].fillna('').astype(str).str.strip().ne('')
else:
    pedido_lleno = pd.Series([False] * len(df_g), index=df_g.index)

# 3) Etapas excluyentes (con nombres claros)
etapas = ["1. Por elaborar", "2. Por conciliar", "3. Pendiente de pedido", "4. Pedido recibido"]
conds = [
    df_g['fecha_elaboracion'].isnull(),
    df_g['fecha_elaboracion'].notnull() & df_g['fecha_conciliacion'].isnull(),
    df_g['fecha_conciliacion'].notnull() & (~pedido_lleno),
    df_g['fecha_conciliacion'].notnull() & (pedido_lleno),
]
df_g['Etapa'] = np.select(conds, etapas, default="Sin clasificar")

# 4) Categoría limpia (y fallback: si subsector vacío, usa sector)
cat = df_g[col_categoria].fillna('').astype(str).str.strip() if col_categoria in df_g.columns else pd.Series(['']*len(df_g))
if col_categoria == 'subsector':
    cat_sector = df_g['sector'].fillna('Sin dato').astype(str).str.strip()
    df_g['Categoria'] = np.where(cat.ne(''), cat, cat_sector)
else:
    df_g['Categoria'] = np.where(cat.ne(''), cat, 'Sin dato')

# 5) Resumen agregado
resumen = (
    df_g.groupby(['Categoria', 'Etapa'], as_index=False)
        .size()
        .rename(columns={'size': 'Cantidad'})
)

# Total por categoría para ordenar
tot_cat = resumen.groupby('Categoria', as_index=False)['Cantidad'].sum().rename(columns={'Cantidad': 'TotalCategoria'})
resumen = resumen.merge(tot_cat, on='Categoria', how='left')

orden_etapas = etapas + (["Sin clasificar"] if (resumen['Etapa'] == "Sin clasificar").any() else [])

# 6) Altura mínima + barras gruesas + etiquetas
h = max(260, min(520, 60 + 30 * resumen['Categoria'].nunique()))

base = alt.Chart(resumen).encode(
    y=alt.Y('Categoria:N', sort=alt.SortField(field='TotalCategoria', order='descending'), title=etiqueta),
    x=alt.X('Cantidad:Q', stack='zero', title='Nº Prefacturas'),
    color=alt.Color('Etapa:N', sort=orden_etapas, title='Etapa'),
    tooltip=['Categoria:N', 'Etapa:N', 'Cantidad:Q', 'TotalCategoria:Q']
)

barras = base.mark_bar(size=26, cornerRadius=6, stroke='rgba(0,0,0,0.25)', strokeWidth=1)

labels = base.transform_filter(
    alt.datum.Cantidad > 0
).mark_text(
    align='left', baseline='middle', dx=6, fontSize=12
).encode(
    text='Cantidad:Q'
)

st.altair_chart((barras + labels).properties(height=h), use_container_width=True)

# --- Tabla ---
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

# --- Guardar Cambios ---
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

            if pd.isna(nuevo_reg.get('created_at')):
                if 'created_at' in nuevo_reg:
                    del nuevo_reg['created_at']

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

# --- EXPORTAR DATOS ---
st.divider()
csv = df_editado.to_csv(index=False).encode('utf-8')
st.download_button(
    label="📥 Descargar Tabla (CSV)",
    data=csv,
    file_name='control_entregas_ingenica.csv',
    mime='text/csv',
)


























































