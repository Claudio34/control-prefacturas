import streamlit as st
import pandas as pd
from supabase import create_client, Client
from datetime import datetime

# 1. Configuración de la página (Debe ser lo primero)
st.set_page_config(page_title="PREFACTURAS", layout="wide")

# 2. Conexión a Supabase (Usa st.secrets en producción)
# Por ahora pon tus llaves aquí para probar, luego las movemos a un archivo seguro
URL = st.secrets["SUPABASE_URL"]
KEY = st.secrets["SUPABASE_KEY"]

@st.cache_resource
def init_connection():
    return create_client(URL, KEY)

supabase = init_connection()

# 3. Título y Métricas Rápidas
st.title("⚡ PREFACTURAS")

# Función para cargar datos
def cargar_datos():
    response = supabase.table('prefacturas_pedidos').select("*").order('id').execute()
    df = pd.DataFrame(response.data)
    return df

# Cargar el dataframe
df = cargar_datos()

# --- BLOQUE 1: Convertir texto a fechas reales (Incluyendo Firma DNDS) ---
columnas_fechas = [
    "fecha_elaboracion", 
    "fecha_formato", 
    "fecha_solicitud_modificacion", 
    "fecha_entrega_post_modificacion", 
    "fecha_conciliacion", 
    "fecha_firma_ingenica",
    "fecha_entrega_final_ingenica_central",
    "fecha_firma_dnds",  # <--- AGREGADA OTRA VEZ COMO FECHA
    "fecha_edicion_pedido"  # <--- ¡NUEVA AGREGADA AQUÍ!
]

for col in columnas_fechas:
    if col in df.columns:
        # Convertir a datetime y quitar la hora
        df[col] = pd.to_datetime(df[col], errors='coerce').dt.date
# -------------------------------------------------------------

# --- 1. BARRA LATERAL DE FILTROS (SIDEBAR) ---
# Esto crea el menú a la izquierda
st.sidebar.header("🎯 Filtros de Gestión")

# A. Filtro por Sector
# Ordenamos los sectores y agregamos la opción "Todos"
# --- 1. BARRA LATERAL DE FILTROS (SIDEBAR) ---
#st.sidebar.header("🎯 Filtros de Gestión")

# VERIFICACIÓN DE SEGURIDAD
if df.empty:
    st.warning("⚠️ No se han cargado datos. Revisa tu conexión a Supabase.")
    st.stop() # Detiene la app aquí para que no de error

# A. Filtro por Sector (Intentamos buscar 'Sector' o 'sector')
if 'Sector' in df.columns:
    col_sector = 'Sector'
elif 'sector' in df.columns:
    col_sector = 'sector'
else:
    st.error("❌ No encuentro la columna de Sector. Tus columnas son: " + str(df.columns.tolist()))
    st.stop()

# Usamos la columna detectada (col_sector) en lugar del nombre fijo
lista_sectores = ["Todos"] + sorted(df[col_sector].unique().tolist())
filtro_sector = st.sidebar.selectbox("Seleccionar Sector:", lista_sectores)
# B. Filtro Rápido de Estado
filtro_estado = st.sidebar.radio(
    "Mostrar solo:",
    ["Ver Todo", "Pendientes de Elaborar", "Pendientes de Conciliar"]
)

# --- 2. APLICACIÓN DE FILTROS ---
# Creamos una copia de los datos para filtrar sin perder los originales
df_filtrado = df.copy()

# Filtro de Sector
if filtro_sector != "Todos":
    df_filtrado = df_filtrado[df_filtrado['sector'] == filtro_sector]

# Filtro de Estado (Lógica corregida según tus indicaciones)
if filtro_estado == "Pendientes de Elaborar":
    df_filtrado = df_filtrado[df_filtrado['fecha_elaboracion'].isnull()]
elif filtro_estado == "Pendientes de Conciliar":
    df_filtrado = df_filtrado[df_filtrado['fecha_conciliacion'].isnull()]

# --- 3. INDICADORES DINÁMICOS (KPIs) ---
st.header(f"Tablero de Control: {filtro_sector}")

# Cálculos (se mantienen igual)
kpi_total = len(df_filtrado)
kpi_elaborar = df_filtrado['fecha_elaboracion'].isnull().sum()
kpi_conciliar = df_filtrado['fecha_conciliacion'].isnull().sum()

if 'pedido' in df_filtrado.columns:
    kpi_pedidos = df_filtrado['pedido'].notnull().sum()
else:
    kpi_pedidos = 0

# Visualización (Textos actualizados según tu imagen)
col1, col2, col3, col4 = st.columns(4)

col1.metric("Total Prefacturas", kpi_total)          # Antes: Total Vista Actual
col2.metric("Prefacturas por Elaborar", kpi_elaborar)# Antes: Falta Elaborar
col3.metric("Prefacturas por Conciliar", kpi_conciliar) # Antes: Falta Conciliar
col4.metric("Pedidos Recibidos", kpi_pedidos)        # Antes: Pedidos Listos

st.divider()

# --- 4. GRÁFICO DE BARRAS PRO (CON BORDES) ---
st.subheader("📊 Distribución de la Carga")
import altair as alt

try:
    # 1. PREPARAR LOS DATOS
    columna_grafico = 'sector' # Por defecto
    etiqueta_eje = 'Sector'

    if filtro_sector != "Todos":
        if 'subsector' in df_filtrado.columns:
            columna_grafico = 'subsector'
            etiqueta_eje = 'Subsector'
        elif 'Subsector' in df_filtrado.columns:
            columna_grafico = 'Subsector'
            etiqueta_eje = 'Subsector'

    # Tabla resumen
    if columna_grafico in df_filtrado.columns:
        datos_grafico = df_filtrado[columna_grafico].value_counts().reset_index()
        datos_grafico.columns = ['Categoria', 'Cantidad']
    else:
        st.warning(f"No encuentro la columna '{columna_grafico}' para graficar.")
        datos_grafico = None

    # 2. DIBUJAR EL GRÁFICO
    if datos_grafico is not None and not datos_grafico.empty:
        
        base = alt.Chart(datos_grafico).encode(
            x=alt.X('Categoria', sort='-y', title=etiqueta_eje),
            y=alt.Y('Cantidad', title='Nº Prefacturas'),
            tooltip=['Categoria', 'Cantidad']
        )

        # CORRECCIÓN AQUÍ: Añadimos borde negro
        barras = base.mark_bar(
            size=60, 
            cornerRadiusTopLeft=5, 
            cornerRadiusTopRight=5,
            stroke='black',       # <--- Color del borde
            strokeWidth=1         # <--- Grosor del borde
        )

        textos = base.mark_text(
            align='center',
            baseline='bottom',
            dy=-5,
            fontSize=12,
            color='black'
        ).encode(
            text='Cantidad'
        )

        st.altair_chart(barras + textos, use_container_width=True)

    else:
        st.info("No hay datos para mostrar en el gráfico con los filtros actuales.")

except Exception as e:
    st.error(f"Error al generar el gráfico: {e}")
    
# --- 5. TABLA DE EDICIÓN LIMPIA Y CONFIGURADA ---
st.subheader("📝 Gestión de Datos")

# Configuración MAESTRA (Añadimos títulos bonitos a las minúsculas)
configuracion_columnas = {
    # A. Columnas Técnicas (Ocultas o Bloqueadas)
    "created_at": None,   
    "id": None,           
    
    # B. Renombrar encabezados (¡Nuevo!)
    "sector": st.column_config.TextColumn("Sector", disabled=True), # Bloqueado y con Mayúscula
    "subsector": st.column_config.TextColumn("Subsector"),
    "periodo": st.column_config.TextColumn("Periodo"),
    "sub_area": st.column_config.TextColumn("Sub Área"),

    # C. Configuración de Fechas
    "fecha_elaboracion": st.column_config.DateColumn("Fecha Elaboración", format="DD/MM/YYYY"),
    "fecha_formato": st.column_config.DateColumn("Fecha Formato", format="DD/MM/YYYY"),
    "fecha_solicitud_modificacion": st.column_config.DateColumn("Fecha Sol. Modif.", format="DD/MM/YYYY"),
    "fecha_entrega_post_modificacion": st.column_config.DateColumn("Fecha Entrega Post Modif.", format="DD/MM/YYYY"),
    "fecha_conciliacion": st.column_config.DateColumn("Fecha Conciliación", format="DD/MM/YYYY"),
    "fecha_firma_ingenica": st.column_config.DateColumn("Firma Ingenica", format="DD/MM/YYYY"),
    "fecha_entrega_final_ingenica_central": st.column_config.DateColumn("Entrega Final Central", format="DD/MM/YYYY"),
    "fecha_firma_dnds": st.column_config.DateColumn("Firma DNDS", format="DD/MM/YYYY", help="Si está vacía, se considera PENDIENTE"),
    "fecha_edicion_pedido": st.column_config.DateColumn("Fecha Edición Pedido", format="DD/MM/YYYY"),

    # D. Listas Desplegables
    "area": st.column_config.SelectboxColumn(
        "Área",
        options=["MANTENIMIENTO", "DESARROLLO", "PROYECTOS", "PNESER", "CAMPAÑA", "PSSEN"]
    )
}

# (El resto del código sigue igual...)

# Mostramos la tabla y guardamos el resultado en 'df_editado'
# IMPORTANTE: Usamos 'df_editado' para que coincida con tu botón de guardar de abajo
df_editado = st.data_editor(
    df_filtrado,
    column_config=configuracion_columnas,
    use_container_width=True,
    num_rows="dynamic",
    key="editor_principal"
)
# --- Botón de Guardar (Versión Divide y Vencerás) ---
if st.button("Guardar Cambios en Supabase"):
    try:
        # 1. Preparar los datos
        datos_a_enviar = df_editado.copy()

        # 2. CONVERSIÓN DE FECHAS (Tu traductor que ya funciona)
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

        # 3. Convertir a lista de diccionarios
        registros = datos_a_enviar.to_dict('records')
        
        # 4. LIMPIEZA Y SEPARACIÓN (Aquí está el truco nuevo)
        registros_actualizar = [] # Filas viejas (tienen ID)
        registros_crear = []      # Filas nuevas (no tienen ID)

        for reg in registros:
            nuevo_reg = reg.copy()
            id_val = nuevo_reg.get('id')
            
            # Limpiamos created_at si está vacío
            if pd.isna(nuevo_reg.get('created_at')):
                if 'created_at' in nuevo_reg: del nuevo_reg['created_at']

            # CLASIFICACIÓN: ¿Es nuevo o viejo?
            if id_val is None or pd.isna(id_val) or str(id_val).strip() == "":
                # ES NUEVO: Borramos el ID para que Supabase lo invente
                if 'id' in nuevo_reg: del nuevo_reg['id']
                registros_crear.append(nuevo_reg)
            else:
                # ES VIEJO: Lo dejamos tal cual para actualizar
                registros_actualizar.append(nuevo_reg)

        # 5. ENVIAR POR SEPARADO
        # A) Actualizamos los existentes (Upsert)
        if len(registros_actualizar) > 0:
            supabase.table('prefacturas_pedidos').upsert(registros_actualizar).execute()
            
        # B) Insertamos los nuevos (Insert)
        if len(registros_crear) > 0:
            supabase.table('prefacturas_pedidos').insert(registros_crear).execute()
        
        # 6. Éxito
        st.success("¡Cambios guardados correctamente!")
        st.balloons()
        
        # Recargar para ver los nuevos IDs asignados
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










































