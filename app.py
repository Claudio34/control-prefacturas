import streamlit as st
import pandas as pd
from supabase import create_client, Client
from datetime import datetime

# 1. Configuración de la página (Debe ser lo primero)
st.set_page_config(page_title="PREFACTURAS INGENICA", layout="wide")

# 2. Conexión a Supabase (Usa st.secrets en producción)
# Por ahora pon tus llaves aquí para probar, luego las movemos a un archivo seguro
URL = st.secrets["SUPABASE_URL"]
KEY = st.secrets["SUPABASE_KEY"]

@st.cache_resource
def init_connection():
    return create_client(URL, KEY)

supabase = init_connection()

# 3. Título y Métricas Rápidas
st.title("⚡ PREFACTURAS - INGENICA")

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
    "fecha_firma_dnds"  # <--- AGREGADA OTRA VEZ COMO FECHA
]

for col in columnas_fechas:
    if col in df.columns:
        # Convertir a datetime y quitar la hora
        df[col] = pd.to_datetime(df[col], errors='coerce').dt.date
# -------------------------------------------------------------

# --- SECCIÓN DE INDICADORES (Dashboard) ---
if not df.empty:
    col1, col2, col3 = st.columns(3)
    
    # KPI 1: Total de pedidos
    col1.metric("Total Registros", len(df))
    
    # KPI 2: Pendientes de Firma DNDS (donde la fecha es nula)
    # Asumiendo que 'fecha_firma_dnds' es el nombre exacto de la columna
    pendientes_dnds = df['fecha_firma_dnds'].isnull().sum()
    col2.metric("Pendientes Firma DNDS", pendientes_dnds, delta_color="inverse")
    
    # KPI 3: Entregados este mes (Ejemplo)
    # Convertir a datetime si no lo está
    if 'fecha_elaboracion' in df.columns:
        df['fecha_elaboracion'] = pd.to_datetime(df['fecha_elaboracion'])
        mes_actual = datetime.now().month
        entregas_mes = df[df['fecha_elaboracion'].dt.month == mes_actual].shape[0]
        col3.metric(f"Elaborados este Mes ({mes_actual})", entregas_mes)

st.divider()

# --- SECCIÓN DE EDICIÓN ---
st.subheader("📝 Edición de Datos")
st.info("Edita las celdas directamente y presiona 'Guardar Cambios' al final.")

# El editor de datos mágico de Streamlit
df_editado = st.data_editor(
    df,
    num_rows="dynamic",
    hide_index=True,
    column_config={
        # --- CONFIGURACIÓN DE FECHAS (Calendarios) ---
        "fecha_elaboracion": st.column_config.DateColumn("Fecha Elaboración", format="DD/MM/YYYY", required=False),
        "fecha_formato": st.column_config.DateColumn("Fecha Formato", format="DD/MM/YYYY", required=False),
        "fecha_solicitud_modificacion": st.column_config.DateColumn("Fecha Sol. Modif.", format="DD/MM/YYYY", required=False),
        "fecha_entrega_post_modificacion": st.column_config.DateColumn("Fecha Entrega Post Modif.", format="DD/MM/YYYY", required=False),
        "fecha_conciliacion": st.column_config.DateColumn("Fecha Conciliación", format="DD/MM/YYYY", required=False),
        "fecha_firma_ingenica": st.column_config.DateColumn("Firma Ingenica", format="DD/MM/YYYY", required=False),
        "fecha_entrega_final_ingenica_central": st.column_config.DateColumn("Entrega Final Central", format="DD/MM/YYYY", required=False),
        
        # --- FIRMA DNDS (VUELVE A SER FECHA) ---
        "fecha_firma_dnds": st.column_config.DateColumn(
            "Firma DNDS", 
            format="DD/MM/YYYY", 
            required=False,
            help="Si está vacía, se considera PENDIENTE"
        ),

        # --- OTRAS CONFIGURACIONES ---
        "area": st.column_config.SelectboxColumn(
            "Área", 
            options=["MANTENIMIENTO", "DESARROLLO", "PROYECTOS", "PNESER", "CAMPAÑA"]
        ),
        "id": st.column_config.Column(disabled=True),
        "created_at": st.column_config.Column(disabled=True),
    },
    use_container_width=True
)
# --- Botón de Guardar ---
if st.button("Guardar Cambios en Supabase"):
    try:
        # 1. Preparar los datos
        datos_a_enviar = df_editado.copy()

        # 2. CONVERSIÓN DE FECHAS A TEXTO (Incluyendo Firma DNDS)
        columnas_fechas_guardar = [
            "fecha_elaboracion", "fecha_formato", "fecha_solicitud_modificacion", 
            "fecha_entrega_post_modificacion", "fecha_conciliacion", 
            "fecha_firma_ingenica", "fecha_entrega_final_ingenica_central",
            "fecha_firma_dnds" # <--- Importante incluirla aquí
        ]

        for col in columnas_fechas_guardar:
            if col in datos_a_enviar.columns:
                datos_a_enviar[col] = datos_a_enviar[col].astype(str)
                datos_a_enviar[col] = datos_a_enviar[col].replace(['nan', 'NaT', 'None', '<NA>'], None)

        # 3. Convertir a lista de diccionarios
        registros = datos_a_enviar.to_dict('records')
        
        # 4. LIMPIEZA PARA FILAS NUEVAS (ESTO ARREGLA TU ERROR DE HOY)
        registros_limpios = []
        for reg in registros:
            nuevo_reg = reg.copy()
            
            # --- LA CURA PARA EL ERROR "NULL VALUE IN ID" ---
            # Si el ID está vacío, lo borramos del diccionario.
            # Así Supabase sabe que es nuevo y le inventa un ID solo.
            if pd.isna(nuevo_reg.get('id')):
                del nuevo_reg['id']
            
            # Limpiamos created_at si es nuevo
            if pd.isna(nuevo_reg.get('created_at')):
                if 'created_at' in nuevo_reg: del nuevo_reg['created_at']
            
            registros_limpios.append(nuevo_reg)

        # 5. Enviamos a Supabase
        response = supabase.table('prefacturas_pedidos').upsert(registros_limpios).execute()
        
        st.success("¡Cambios guardados correctamente!")
        st.balloons()

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













